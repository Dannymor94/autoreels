"""Извлечение аудио: ffmpeg -vn → компактный формат под Whisper (mp3 64k mono 16kHz).

Сидит на границе тиров: ffmpeg локальный, но готовит вход облачному тиру (транскрипция),
поэтому модуль в cloud/. Видеоряд наружу не уходит — извлекается только аудио.

Почему mp3 64k, а не PCM:
- Groq Whisper лимит: 25 МБ/запрос. PCM 16kHz mono = 32 000 байт/с → 13 мин до лимита.
- mp3 64k = 8 000 байт/с → 52 мин до лимита. Разблокирует всё что < 52 мин без чанкинга.
- Качество для ASR: Whisper не выигрывает от битрейта выше 64k (не музыка).

Параметры извлечения берутся из render.yaml (`AudioExtract`), не хардкодятся.
Выход в data/cache по хэшу содержимого источника → идемпотентность шага 3.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

from autoreels.core import state
from autoreels.core.config import AudioExtract


class ExtractAudioError(Exception):
    """Извлечение аудио не удалось (нет файла, нет ffmpeg, ffmpeg вернул ошибку)."""


def _ffmpeg_not_found_msg(ffmpeg: str) -> str:
    """Внятное сообщение о ненайденном ffmpeg — ЧТО искали и КАК задать путь (вместо
    голого [WinError 2] «Не удаётся найти указанный файл», который ничего не объясняет)."""
    return (
        f"ffmpeg не найден (искали '{ffmpeg}' в PATH). Задай путь одним из способов:\n"
        f"  • файл:  config/render.local.yaml → ffmpeg: D:\\ffmpeg\\bin\\ffmpeg.exe\n"
        f"  • флаг:  --ffmpeg D:\\ffmpeg\\bin\\ffmpeg.exe\n"
        f"  • env:   RENDER_FFMPEG=D:\\ffmpeg\\bin\\ffmpeg.exe\n"
        f"или установи ffmpeg в PATH."
    )


def _probe_duration_sec(ffmpeg_bin: str, source: Path) -> float | None:
    """Длительность источника через ffprobe (для процента бара). None — если не удалось
    (нет ffprobe/битый вывод): тогда показываем живой спиннер без %, а не падаем."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        # ffprobe часто лежит рядом с ffmpeg — пробуем соседний бинарь.
        cand = Path(ffmpeg_bin).with_name("ffprobe" + Path(ffmpeg_bin).suffix)
        ffprobe = str(cand) if cand.is_file() else None
    if ffprobe is None:
        return None
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(source)],
            capture_output=True, text=True,
        )
        return float(proc.stdout.strip()) or None
    except (ValueError, OSError):
        return None


def _run_extract_with_progress(cmd: list[str], *, duration_sec: float | None) -> tuple[int, str]:
    """Запустить ffmpeg с `-progress pipe:1`, рисуя живой прогресс-бар по времени.

    Живой бар (при известной длительности) или спиннер (если длительность неизвестна) —
    видно, что этап идёт, а не завис. stderr сливается в поток (иначе Popen на большом
    stderr зависает). Возвращает (returncode, stderr_text) — как subprocess.run.
    """
    from autoreels.core.progress import is_tty, print_bar_line, print_spin_line

    prog_cmd = [cmd[0], "-progress", "pipe:1", "-nostats"] + cmd[1:]
    try:
        proc = subprocess.Popen(
            prog_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
        )
    except FileNotFoundError as e:
        # Бинарь не запустился (напр. путь мимо файла) — сырой [WinError 2] превращаем в внятное.
        raise ExtractAudioError(_ffmpeg_not_found_msg(cmd[0])) from e
    stderr_chunks: list[str] = []

    def _drain_stderr() -> None:
        for line in proc.stderr:
            stderr_chunks.append(line)

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()

    tick = 0
    last_bucket = -1
    for line in proc.stdout:
        key, _, val = line.strip().partition("=")
        if key != "out_time_ms":
            continue
        tick += 1
        try:
            elapsed = max(0.0, int(val) / 1_000_000)
        except ValueError:
            continue
        if duration_sec:
            pct = min(100.0, elapsed / duration_sec * 100)
            # На non-TTY (пайп/лог) печатаем не чаще, чем раз в 5% — иначе спам строк.
            bucket = int(pct) // 5
            if is_tty() or bucket != last_bucket:
                print_bar_line("извлекаю аудио", pct, tick=tick)
                last_bucket = bucket
        elif is_tty():
            print_spin_line("извлекаю аудио", tick=tick)

    proc.wait()
    t.join(timeout=2)
    if proc.returncode == 0:
        if duration_sec:
            print_bar_line("извлекаю аудио", 100, done=True)
        else:
            print_spin_line("извлекаю аудио", done=True)
    return proc.returncode, "".join(stderr_chunks)


def build_extract_cmd(
    ffmpeg: str,
    source: Path,
    out: Path,
    audio_cfg: AudioExtract,
) -> list[str]:
    """Собрать команду ffmpeg для извлечения аудио под Whisper. Чистая функция (без ФС)."""
    cmd = [
        str(ffmpeg), "-y", "-loglevel", "error",
        "-i", str(source),
        "-vn",
        "-ac", str(audio_cfg.channels),
        "-ar", str(audio_cfg.sample_rate),
        "-c:a", audio_cfg.codec,
    ]
    if audio_cfg.bitrate:
        cmd += ["-b:a", audio_cfg.bitrate]
    cmd += ["-f", audio_cfg.format, str(out)]
    return cmd


def extract_audio(
    source: str | Path,
    audio_cfg: AudioExtract,
    cache_dir: str | Path,
    *,
    ffmpeg: str = "ffmpeg",
    source_sha: str | None = None,
) -> Path:
    """Извлечь аудиодорожку из `source` в `cache_dir`/<sha256>.<format>.

    `source_sha` — уже вычисленный хэш источника (напр. из cmd_run). Если не передан,
    вычисляется полным sha256 аудио (аудио мало — это быстро). Имя выхода детерминировано.
    """
    source = Path(source)
    if not source.is_file():
        raise ExtractAudioError(f"исходный файл не найден: {source}")

    ffmpeg_bin = shutil.which(ffmpeg)
    if ffmpeg_bin is None:
        raise ExtractAudioError(_ffmpeg_not_found_msg(ffmpeg))

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    sha = source_sha if source_sha is not None else state.file_sha256(source)
    out = cache_dir / f"{sha}.{audio_cfg.format}"

    cmd = build_extract_cmd(ffmpeg_bin, source, out, audio_cfg)
    duration = _probe_duration_sec(ffmpeg_bin, source)
    returncode, stderr_text = _run_extract_with_progress(cmd, duration_sec=duration)
    if returncode != 0:
        out.unlink(missing_ok=True)
        stderr = stderr_text.strip() or "(пустой stderr)"
        raise ExtractAudioError(
            f"ffmpeg не смог извлечь аудио из {source} (код {returncode}): {stderr}"
        )
    return out
