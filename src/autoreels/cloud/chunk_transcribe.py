"""Whisper-чанкинг: длинное аудио → чанки → транскрипт → склейка таймкодов.

Порог чанкинга: >15 мин ИЛИ >20 МБ (see ChunkingConfig). До порога — один запрос.

Ключевой инвариант склейки:
    absolute_t = chunk_start_sec[i] + whisper_relative_t
Offset берётся из РЕАЛЬНОГО VAD-среза (не из target_sec) — иначе слова у границ
съезжают на разницу target vs actual (ловит test_overlap_zone_consistency).

Кэш: data/cache/<chunk_sha256>.chunk.json — идемпотентность при повторном прогоне.
Провал чанка (fail_fast=False): None в списке результатов + WARNING с временным диапазоном;
следующий run добьёт только упавшие чанки (остальные берутся из кэша).
"""
from __future__ import annotations

import hashlib
import math
import subprocess
from pathlib import Path

from autoreels.core.models import Reel, Transcript, Word


class ChunkTranscribeError(Exception):
    """Ошибка чанкинга: провал одного чанка при fail_fast=True или системная ошибка."""


# =========================================================== чистые функции

def apply_offset(transcript: Transcript, offset_sec: float) -> Transcript:
    """Сдвинуть все t0/t1 слов на offset_sec (relative → absolute time).

    Возвращает новый Transcript; оригинал не мутируется.
    Offset берётся из реального VAD-среза, а не из target — это предотвращает
    смещение слов у границ чанков (см. test_overlap_zone_consistency).
    """
    shifted = [
        Word(word=w.word, t0=w.t0 + offset_sec, t1=w.t1 + offset_sec)
        for w in transcript.words
    ]
    return Transcript(language=transcript.language, words=shifted)


def find_split_point(
    silences: list[tuple[float, float]],
    target_sec: float,
    window_sec: float,
) -> float:
    """Найти лучшую точку разреза вблизи target_sec по списку интервалов тишины.

    Ищет тишины в окне [target - window, target + window].
    Среди найденных выбирает ближайшую к target (по midpoint).
    Возвращает midpoint найденной тишины, иначе target_sec (hard-cut fallback).
    """
    lo = target_sec - window_sec
    hi = target_sec + window_sec

    best: tuple[float, float] | None = None
    best_dist = float("inf")

    for s_start, s_end in silences:
        mid = (s_start + s_end) / 2.0
        if lo <= mid <= hi:
            dist = abs(mid - target_sec)
            if dist < best_dist:
                best_dist = dist
                best = (s_start, s_end)

    if best is None:
        return target_sec
    return (best[0] + best[1]) / 2.0


def should_chunk(audio_size_bytes: int, audio_duration_sec: float, cfg) -> bool:
    """Нужен ли чанкинг? True если длительность > порога ИЛИ размер > порога."""
    if not cfg.enabled:
        return False
    over_duration = audio_duration_sec > cfg.whisper_threshold_minutes * 60
    over_bytes    = audio_size_bytes > cfg.whisper_threshold_bytes
    return over_duration or over_bytes


def merge_transcripts(
    chunks: list[Transcript | None],
    start_secs: list[float],
    *,
    warns: list[str] | None = None,
) -> Transcript:
    """Склеить чанки в единый Transcript, применив offset из start_secs.

    None-чанки (провалы транскрипции) пропускаются; в warns добавляется сообщение
    с временным интервалом пропущенного чанка (для диагностики потерь).

    Порядок слов: чанки конкатенируются в порядке start_secs.
    """
    if len(chunks) != len(start_secs):
        raise ValueError(f"chunks ({len(chunks)}) и start_secs ({len(start_secs)}) должны совпадать")

    all_words: list[Word] = []
    language = "ru"

    for i, (chunk, start) in enumerate(zip(chunks, start_secs)):
        if chunk is None:
            if warns is not None:
                # определяем конец чанка: start следующего или start + условный чанк
                end = start_secs[i + 1] if i + 1 < len(start_secs) else start + 600.0
                warns.append(
                    f"⚠ чанк {i} ({_fmt_sec(start)}-{_fmt_sec(end)}) не транскрибирован — "
                    f"моменты в этом диапазоне пропущены"
                )
            continue
        language = chunk.language or language
        shifted = apply_offset(chunk, start)
        all_words.extend(shifted.words)

    return Transcript(language=language, words=all_words)


def dedup_reels(reels: list[Reel], threshold: float) -> list[Reel]:
    """Дедуп рилов из разных R0-чанков по пересечению (intersection / min_duration).

    Сортирует по t0 ПЕРЕД дедупом: «первый по t0» — хронологически ранний.
    При пересечении > threshold оставляет тот, кто раньше в хронологии (меньший start).
    """
    kept: list[Reel] = []
    for r in sorted(reels, key=lambda x: x.start):
        duplicate = False
        for k in kept:
            if _overlap_ratio(r, k) > threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(r)
    return kept


def renumber_reels(reels: list[Reel]) -> list[Reel]:
    """Сквозная нумерация рилов: r01, r02, … (не мутирует оригиналы)."""
    return [
        r.model_copy(update={"id": f"r{i:02d}"})
        for i, r in enumerate(reels, 1)
    ]


def _overlap_ratio(a: Reel, b: Reel) -> float:
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    shorter = min(a.end - a.start, b.end - b.start)
    return inter / shorter if shorter > 0 else 0.0


def _fmt_sec(sec: float) -> str:
    """Форматировать секунды в MM:SS для warning-сообщений."""
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


# =========================================================== I/O (mocked in tests)

def detect_silences(
    audio_path: Path,
    threshold_db: float,
    *,
    ffmpeg: str = "ffmpeg",
) -> list[tuple[float, float]]:
    """Запустить ffmpeg silencedetect, вернуть список (silence_start, silence_end) в сек."""
    cmd = [
        ffmpeg, "-i", str(audio_path),
        "-af", f"silencedetect=noise={threshold_db}dB:d=0.3",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    # silencedetect пишет в stderr
    return _parse_silencedetect(proc.stderr)


def _parse_silencedetect(stderr: str) -> list[tuple[float, float]]:
    """Парсинг вывода ffmpeg silencedetect из stderr."""
    import re
    starts = re.findall(r"silence_start: ([0-9.]+)", stderr)
    ends   = re.findall(r"silence_end: ([0-9.]+)", stderr)
    result = []
    for s, e in zip(starts, ends):
        result.append((float(s), float(e)))
    return result


def split_audio_chunk(
    audio_path: Path,
    start_sec: float,
    end_sec: float | None,
    out_path: Path,
    audio_cfg,
    *,
    ffmpeg: str = "ffmpeg",
) -> None:
    """Вырезать один чанк из audio_path [start_sec, end_sec) → out_path."""
    cmd = [ffmpeg, "-y", "-loglevel", "error",
           "-i", str(audio_path),
           "-ss", str(start_sec)]
    if end_sec is not None:
        cmd += ["-to", str(end_sec)]
    cmd += [
        "-vn",
        "-ac", str(audio_cfg.channels),
        "-ar", str(audio_cfg.sample_rate),
        "-c:a", audio_cfg.codec,
    ]
    if audio_cfg.bitrate:
        cmd += ["-b:a", audio_cfg.bitrate]
    cmd += ["-f", audio_cfg.format, str(out_path)]

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise ChunkTranscribeError(
            f"ffmpeg не смог нарезать чанк [{start_sec}-{end_sec}]: "
            f"{proc.stderr.strip() or '(пустой stderr)'}"
        )


def _chunk_cache_path(cache_dir: Path, chunk_path: Path) -> Path:
    """Путь кэша транскрипта чанка: <cache_dir>/<sha256(chunk_bytes)>.chunk.json."""
    sha = hashlib.sha256(chunk_path.read_bytes()).hexdigest()
    return cache_dir / f"{sha}.chunk.json"


def _probe_duration(audio_path: Path, ffmpeg: str = "ffmpeg") -> float:
    """Длительность аудиофайла через ffprobe (секунды)."""
    ffprobe = "ffprobe" if ffmpeg == "ffmpeg" else ffmpeg.replace("ffmpeg", "ffprobe")
    cmd = [ffprobe, "-v", "error",
           "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1",
           str(audio_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise ChunkTranscribeError(
            f"не удалось определить длительность {audio_path}: {result.stderr.strip()}"
        )


def transcribe_chunks(
    chunks_info: list[tuple[Path, float, float]],
    backend,
    cache_dir: Path,
    *,
    fail_fast: bool = False,
    language: str = "ru",
) -> tuple[list[Transcript | None], list[str]]:
    """Транскрибировать список чанков с кэшем и обработкой провалов.

    chunks_info: [(chunk_path, start_sec, end_sec), ...]
    Возвращает (results, warnings):
      results — list[Transcript|None] в том же порядке (None = провал)
      warnings — список строк для пользователя о пропущенных диапазонах
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    results: list[Transcript | None] = []
    warnings: list[str] = []

    for i, (chunk_path, start_sec, end_sec) in enumerate(chunks_info):
        cache_path = _chunk_cache_path(cache_dir, chunk_path)

        # Кэш-хит
        if cache_path.exists():
            tr = Transcript.model_validate_json(cache_path.read_text(encoding="utf-8"))
            results.append(tr)
            continue

        # Транскрипция
        try:
            tr = backend.transcribe(chunk_path, language=language)
            cache_path.write_text(tr.model_dump_json(), encoding="utf-8")
            results.append(tr)
        except Exception as exc:
            if fail_fast:
                raise ChunkTranscribeError(
                    f"чанк {i} ({_fmt_sec(start_sec)}-{_fmt_sec(end_sec)}) провалился: {exc}"
                ) from exc
            warnings.append(
                f"⚠ чанк {i} ({_fmt_sec(start_sec)}-{_fmt_sec(end_sec)}) "
                f"не транскрибирован — моменты пропущены ({exc})"
            )
            results.append(None)

    return results, warnings


def transcribe_chunked(
    audio_path: Path,
    cfg,
    audio_cfg,
    cache_dir: Path,
    backend,
    *,
    ffmpeg: str = "ffmpeg",
    language: str = "ru",
) -> tuple[Transcript, list[str]]:
    """Оркестратор Whisper-чанкинга end-to-end.

    1. Определяет длительность аудио через ffprobe.
    2. Вычисляет target-границы (i * chunk_duration_sec).
    3. Для каждой границы ищет ближайшую тишину через VAD → реальный срез.
    4. Нарезает аудио на чанки: start_secs[] берётся из РЕАЛЬНЫХ VAD-срезов, не i*duration.
    5. Транскрибирует каждый чанк с кэшем (transcribe_chunks).
    6. Склеивает с apply_offset(offset=real_start_sec) → absolute timestamps.

    Инвариант: offset чанка i = real_start_sec[i] (точка -ss, которую получил ffmpeg),
    а не target_sec[i] = i * chunk_duration. Разница target vs actual = смещение слов у границ.
    """
    audio_path = Path(audio_path)
    cache_dir  = Path(cache_dir)

    duration = _probe_duration(audio_path, ffmpeg)
    n_chunks = max(1, math.ceil(duration / cfg.whisper_chunk_duration_sec))

    # target-границы: точки, где хотим нарезать
    target_splits = [i * cfg.whisper_chunk_duration_sec for i in range(1, n_chunks)]

    # VAD: ищем тишину вблизи каждой target-границы
    silences = detect_silences(audio_path, cfg.silence_threshold_db, ffmpeg=ffmpeg)
    real_splits = [
        find_split_point(silences, t, cfg.silence_window_sec)
        for t in target_splits
    ]

    # Границы чанков: [0, real_split_0, real_split_1, ...] / [real_split_0, ..., None]
    starts: list[float] = [0.0] + real_splits
    ends:   list[float | None] = real_splits + [None]

    # Нарезка: chunk_i.mp3 в data/cache/chunks/<audio_sha>/
    audio_sha  = hashlib.sha256(audio_path.read_bytes()[:4096]).hexdigest()[:16]
    chunks_dir = cache_dir / "chunks" / audio_sha
    chunks_dir.mkdir(parents=True, exist_ok=True)

    chunks_info: list[tuple[Path, float, float]] = []
    for i, (start, end) in enumerate(zip(starts, ends)):
        chunk_path = chunks_dir / f"chunk_{i:02d}.{audio_cfg.format}"
        if not chunk_path.exists():
            split_audio_chunk(audio_path, start, end, chunk_path, audio_cfg, ffmpeg=ffmpeg)
        end_for_meta = end if end is not None else duration
        chunks_info.append((chunk_path, start, end_for_meta))

    # Транскрипция + кэш
    results, warnings = transcribe_chunks(
        chunks_info, backend, cache_dir,
        fail_fast=cfg.fail_fast, language=language,
    )

    # Склейка: offset = real start_sec из chunks_info (не i*duration!)
    real_start_secs = [info[1] for info in chunks_info]
    transcript = merge_transcripts(results, real_start_secs, warns=warnings)
    return transcript, warnings
