"""CLI-склейка тиров: две команды по границе ОБЛАКО/ЛОКАЛЬ (M0 шаг 8).

Убирает терминал-ритуал (ручная активация venv, многострочные `python -c`, ручные пути,
`source .env`, невидимый прогресс). Без субтитров — R3 встанет одним блоком между select
и render (этапы `run` оформлены как отдельные функции-блоки именно ради этого).

    autoreels run [video]            # без аргумента → batch: все inputs/*.mp4
    autoreels render                 # системник: manifests/*.json → reels-out/

Граница тиров: `run` живёт в облачном конвейере (аудио/текст), `render` — локальный ffmpeg.
Видео между тирами не ходит: манифест несёт source_sha256, render ищет файл в inputs/.

Манифест: manifests/<stem>.json (имя по видео, batch-совместимость).
Архив: inputs-archive/ — после успеха видео перемещается, идемпотентно.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from autoreels.cloud.compress import compress_transcript
from autoreels.cloud.extract_audio import ExtractAudioError, extract_audio
from autoreels.cloud.providers import GroqLLM, ProviderError
from autoreels.cloud.select import SelectError, select
from autoreels.cloud.snap import snap_segments
from autoreels.cloud.trim import trim_too_long
from autoreels.cloud.transcribe import TranscriptionError, get_backend, transcribe
from autoreels.core import state
from autoreels.core.calibration import (
    CalibrationError,
    _probe_frame_size_for_auto,
    auto_crop,
    calibration_path,
    load_calibration,
    load_or_auto_calibrate,
    save_calibration,
)
from autoreels.core.config import (
    ConfigError,
    load_r0_config,
    load_render_config,
    load_subtitles_config,
    load_transcribe_config,
)
from autoreels.core.models import Manifest
from autoreels.local.calibrate import CalibrateError, cmd_calibrate
from autoreels.local.render import RenderError, SourceNotFoundError, load_manifest, render_crop
from autoreels.local.subtitles import words_in_window

# Ошибки тиров, которые CLI превращает во внятное сообщение (а не голый traceback).
_KNOWN_ERRORS = (
    ExtractAudioError,
    TranscriptionError,
    ProviderError,
    SelectError,
    RenderError,
    ConfigError,
    CalibrationError,
    CalibrateError,
    FileNotFoundError,
)


# --------------------------------------------------------------------------- .env

def _load_env(dotenv_path: str | Path | None = None) -> None:
    """Подхватить .env в окружение (закрывает ручной `source .env`, долг 5a)."""
    from dotenv import load_dotenv

    load_dotenv(str(dotenv_path) if dotenv_path is not None else None)


def _run_key(source_sha256: str, duration_preset: str) -> str:
    """Детерминированный ключ прогона от source+preset (полноценная версия рубрики — M1)."""
    return hashlib.sha256(f"{source_sha256}:{duration_preset}".encode()).hexdigest()[:16]


# ----------------------------------------------------- архив (общий хелпер)

def _archive_video(video: Path, archive_dir: Path) -> None:
    """Переместить видео в inputs-archive/ после успеха. Идемпотентно: уже там → skip."""
    dest = archive_dir / video.name
    if dest.exists():
        return
    if video.exists():
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(video), str(dest))
        print(f"архивирован: {video.name} → {archive_dir}", flush=True)


# ----------------------------------------------------- этапы конвейера `run` (блоки)

def _stage_extract_audio(video, *, render_cfg, cache_dir, ffmpeg, source_sha=None):
    print("извлекаю аудио…", flush=True)
    return extract_audio(video, render_cfg.audio_extract, cache_dir,
                         ffmpeg=ffmpeg, source_sha=source_sha)


def _stage_transcribe(audio, *, transcribe_cfg, cache_dir, r0_cfg=None, audio_cfg=None, ffmpeg="ffmpeg"):
    print("транскрипция…", flush=True)
    backend = get_backend(transcribe_cfg)
    chunking_cfg = r0_cfg.chunking if r0_cfg is not None else None
    return transcribe(
        audio, cache_dir,
        backend=backend,
        language=transcribe_cfg.language,
        chunking_cfg=chunking_cfg,
        audio_cfg=audio_cfg,
        ffmpeg=ffmpeg,
    )


def _stage_compress(transcript, *, r0_cfg):
    print("сжатие транскрипта…", flush=True)
    return compress_transcript(
        transcript, pause_sec=r0_cfg.sentence_pause_sec, max_sentence_sec=r0_cfg.max_sentence_sec
    )


def _stage_select(compressed, *, r0_cfg, root):
    print("выбор моментов…", flush=True)
    root = Path(root)
    system_text = (root / r0_cfg.prompts.system).read_text(encoding="utf-8")
    fewshot = json.loads((root / r0_cfg.prompts.fewshot).read_text(encoding="utf-8"))
    return select(
        compressed, system_text=system_text, fewshot=fewshot,
        provider=GroqLLM(), r0_cfg=r0_cfg,
    )


def _stage_snap(reels, transcript, *, r0_cfg):
    """R4: подтянуть границы reel к словам/паузам транскрипта (код, не LLM)."""
    print("подтяжка границ к словам…", flush=True)
    snap_segments(
        reels, transcript.words,
        tail_sec=r0_cfg.tail_sec, window_sec=r0_cfg.snap_window_sec,
        pause_sec=r0_cfg.sentence_pause_sec, max_duration=r0_cfg.max_duration,
    )
    return reels


def _stage_trim(reels, transcript, *, r0_cfg):
    """Политика too_long: trim/drop/keep сегменты длиннее max_duration (код, не LLM)."""
    policy = getattr(r0_cfg, "too_long_policy", "keep")
    if policy == "keep":
        return reels
    n_before = len(reels)
    trim_too_long(
        reels, transcript.words,
        max_duration=r0_cfg.max_duration,
        pause_sec=r0_cfg.sentence_pause_sec,
        policy=policy,
    )
    n_after = len(reels)
    if policy == "drop" and n_after < n_before:
        print(f"too_long drop: убрано {n_before - n_after} сегментов", flush=True)
    elif policy == "trim":
        trimmed = sum(1 for r in reels if "too_long" not in r.flags)
        print(f"too_long trim: обрезано по паузе", flush=True)
    return reels


def _stage_subtitles(reels, transcript):
    """R3: привязать word-level транскрипта к каждому reel."""
    print("субтитры: привязка слов к сегментам…", flush=True)
    for reel in reels:
        reel.subtitles = words_in_window(transcript.words, reel.start, reel.end)
    return reels


def _assemble_manifest(video, reels, *, sha, setup, duration_preset):
    """Собрать манифест: кроп/setup_id — из калибровки (setup), source_sha256 — от файла."""
    return Manifest(
        source=Path(video).name,
        source_sha256=sha,
        source_hash_scheme="partial-p1",
        duration_preset=duration_preset,
        setup=setup,
        run_key=_run_key(sha, duration_preset),
        reels=reels,
    )


def _write_manifest(manifest, manifests_dir) -> Path:
    """Записать манифест как manifests/<stem>.json (имя по видео, batch-совместимость)."""
    manifests_dir = Path(manifests_dir)
    manifests_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(manifest.source).stem
    path = manifests_dir / f"{stem}.json"
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return path


# ------------------------------------------------------------------------- команды

def cmd_run(
    video,
    *,
    root=".",
    calibrations_dir=None,
    manifests_dir=None,
    cache_dir=None,
    archive_dir=None,
    ffmpeg: str = "ffmpeg",
) -> Path:
    """ОБЛАЧНЫЙ тир: одно видео → manifests/<stem>.json + архив источника.

    Кроп per-file: берётся из `calibrations/<sha256>.json` (пишет `autoreels calibrate`).
    Нет калибровки → авто-кроп по центру (9:16, полная высота) с сообщением.
    После записи манифеста видео перемещается в inputs-archive/.
    """
    root = Path(root)
    cfg = root / "config"
    render_cfg = load_render_config(cfg / "render.yaml")
    r0_cfg = load_r0_config(cfg / "r0.yaml")
    transcribe_cfg = load_transcribe_config(cfg / "transcribe.yaml")
    calibrations_dir = Path(calibrations_dir) if calibrations_dir else root / "calibrations"
    cache_dir = Path(cache_dir) if cache_dir else root / "data" / "cache"
    manifests_dir = Path(manifests_dir) if manifests_dir else root / "manifests"
    archive_dir = Path(archive_dir) if archive_dir else root / "inputs-archive"

    size_gb = Path(video).stat().st_size / (1 << 30)
    print(f"считаю хэш видео ({size_gb:.1f} ГБ)…", flush=True)
    sha = state.file_sha256_cached_fast(video, cache_dir)
    print("хэш готов.", flush=True)
    setup = load_or_auto_calibrate(
        calibrations_dir, sha, Path(video).name,
        get_frame_size=lambda: _probe_frame_size_for_auto(video),
    )

    print(f"=== run: {Path(video).name} (setup={setup.setup_id}) ===", flush=True)
    audio = _stage_extract_audio(video, render_cfg=render_cfg, cache_dir=cache_dir,
                                 ffmpeg=ffmpeg, source_sha=sha)
    transcript = _stage_transcribe(
        audio, transcribe_cfg=transcribe_cfg, cache_dir=cache_dir,
        r0_cfg=r0_cfg, audio_cfg=render_cfg.audio_extract, ffmpeg=ffmpeg,
    )
    compressed = _stage_compress(transcript, r0_cfg=r0_cfg)
    reels = _stage_select(compressed, r0_cfg=r0_cfg, root=root)
    reels = _stage_snap(reels, transcript, r0_cfg=r0_cfg)
    reels = _stage_trim(reels, transcript, r0_cfg=r0_cfg)
    reels = _stage_subtitles(reels, transcript)
    manifest = _assemble_manifest(
        video, reels, sha=sha, setup=setup, duration_preset=r0_cfg.duration_preset
    )
    path = _write_manifest(manifest, manifests_dir)
    print(f"манифест собран: {len(manifest.reels)} reels → {path}", flush=True)
    _archive_video(Path(video), archive_dir)
    return path


def cmd_run_batch(
    *,
    root=".",
    inputs_dir=None,
    calibrations_dir=None,
    manifests_dir=None,
    cache_dir=None,
    archive_dir=None,
    ffmpeg: str = "ffmpeg",
) -> tuple[list[str], list[tuple[str, Exception]]]:
    """Batch: обработать все *.mp4 в inputs/ по очереди. Один упал → остальные продолжают.

    Возвращает (ok_names, failed_list) где failed_list = [(name, exc), ...].
    """
    root = Path(root)
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"
    videos = sorted(inputs_dir.glob("*.mp4"))
    if not videos:
        print("inputs/ пуст — нечего обрабатывать", flush=True)
        return [], []

    ok: list[str] = []
    failed: list[tuple[str, Exception]] = []
    for v in videos:
        try:
            cmd_run(
                v, root=root, calibrations_dir=calibrations_dir, manifests_dir=manifests_dir,
                cache_dir=cache_dir, archive_dir=archive_dir, ffmpeg=ffmpeg,
            )
            ok.append(v.name)
        except Exception as e:  # noqa: BLE001
            print(f"\n[ОШИБКА] {v.name}: {e}", file=sys.stderr, flush=True)
            failed.append((v.name, e))

    print(f"\n=== batch run: {len(ok)} ok / {len(failed)} failed ===", flush=True)
    for name, err in failed:
        print(f"  ✗ {name}: {err}", file=sys.stderr)
    return ok, failed


def _missing_reels(manifest: Manifest, out_dir: Path) -> list:
    """Вернуть reel-объекты из манифеста, для которых ещё нет выходного mp4.

    Выходной файл: out_dir/<reel.id>.mp4  (render_crop без суффикса — вертикальный рез).
    """
    return [r for r in manifest.reels if not (out_dir / f"{r.id}.mp4").exists()]


def cmd_render(
    *,
    manifests_dir=None,
    inputs_dir=None,
    out_dir=None,
    archive_dir=None,
    root=".",
    ffmpeg: str = "ffmpeg",
    encoder=None,
) -> list[Path]:
    """ЛОКАЛЬНЫЙ тир: manifests/*.json → reels-out/ (batch по всем манифестам).

    Каждый манифест рендерится независимо. Три исхода:
    - все клипы уже есть в reels-out/<stem>/ → пропуск «✓ уже готово»;
    - исходник не найден в inputs/ → пропуск «⊘ нет видео»;
    - рендер упал → ошибка в сводке.

    Манифесты в manifests/ НЕ трогаются — git ими управляет (Mac→системник через pull).
    Идемпотентность обеспечивается проверкой выходных файлов, а не перемещением манифеста.
    """
    root = Path(root)
    render_cfg = load_render_config(root / "config" / "render.yaml")
    subtitles_cfg = load_subtitles_config(root / "config" / "subtitles.yaml")
    manifests_dir = Path(manifests_dir) if manifests_dir else root / "manifests"
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"
    out_dir = Path(out_dir) if out_dir else root / "reels-out"
    archive_dir = Path(archive_dir) if archive_dir else root / "inputs-archive"

    manifest_files = sorted(manifests_dir.glob("*.json"))
    if not manifest_files:
        print("manifests/ пуст — нечего рендерить", flush=True)
        return []

    enc = encoder or os.environ.get("RENDER_ENCODER") or render_cfg.encoder.codec
    all_outputs: list[Path] = []
    skipped_no_video: list[str] = []
    skipped_done: list[str] = []
    failed: list[tuple[str, Exception]] = []

    for mf in manifest_files:
        try:
            manifest = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
            stem = Path(manifest.source).stem
            out_dir_final = out_dir / stem

            # Идемпотентность: пропускаем манифесты, для которых все клипы уже есть
            missing = _missing_reels(manifest, out_dir_final)
            if not missing:
                print(f"✓ {stem}: все {len(manifest.reels)} клипов уже готовы — пропуск",
                      flush=True)
                skipped_done.append(mf.name)
                continue

            # Рендерим только недостающие клипы (при частичном завершении)
            render_manifest = manifest if len(missing) == len(manifest.reels) else (
                manifest.model_copy(update={"reels": missing})
            )
            n_missing = len(missing)
            n_total = len(manifest.reels)
            label = f"{n_missing}/{n_total} клипов" if n_missing < n_total else f"{n_total} клипов"
            print(f"=== render: {mf.name} ({label}, {enc}) → {out_dir_final} ===", flush=True)
            outputs = render_crop(
                render_manifest, inputs_dir=inputs_dir, out_dir=out_dir_final,
                render_cfg=render_cfg, ffmpeg=ffmpeg, encoder=encoder,
                subtitles_cfg=subtitles_cfg,
            )
            all_outputs.extend(outputs)
            print(f"готово: {len(outputs)} клипов → {out_dir_final}", flush=True)
            _archive_video(inputs_dir / Path(manifest.source).name, archive_dir)
        except SourceNotFoundError:
            print(f"⊘ пропущен {mf.stem}: исходник не найден в inputs/", flush=True)
            skipped_no_video.append(mf.name)
        except Exception as e:  # noqa: BLE001
            print(f"\n[ОШИБКА] {mf.name}: {e}", file=sys.stderr, flush=True)
            failed.append((mf.name, e))

    total = len(manifest_files)
    skipped = skipped_no_video + skipped_done
    if total > 1 or failed or skipped:
        ok = total - len(failed) - len(skipped)
        parts = [f"{ok} отрендерено"]
        if skipped_done:
            names = ", ".join(s.removesuffix(".json") for s in skipped_done)
            parts.append(f"{len(skipped_done)} уже готово ({names})")
        if skipped_no_video:
            names = ", ".join(s.removesuffix(".json") for s in skipped_no_video)
            parts.append(f"{len(skipped_no_video)} нет видео ({names})")
        if failed:
            parts.append(f"{len(failed)} ошибок")
        print(f"\n=== batch render: {' / '.join(parts)} ===", flush=True)
        for name, err in failed:
            print(f"  ✗ {name}: {err}", file=sys.stderr)
    return all_outputs


# ---------------------------------------------------------------------- калибровка (batch)

def _calibration_kind(calibrations_dir: Path, sha: str) -> str:
    """Вернуть 'manual', 'auto' или 'none' для видео по sha256."""
    path = calibration_path(calibrations_dir, sha)
    if not path.is_file():
        return "none"
    try:
        import json as _json
        rec = _json.loads(path.read_text(encoding="utf-8"))
        return "auto" if rec.get("auto") or rec.get("setup_label") == "auto" else "manual"
    except Exception:  # noqa: BLE001
        return "none"


def _ask_batch_action(name: str) -> str:
    """Интерактивный промпт для одного видео в calibrate --all. Точка подмены в тестах."""
    while True:
        ans = input(f"  {name}: кропа нет. [к]алибровать / [а]втокроп / [п]ропустить? ").strip().lower()
        if ans in ("к", "а", "п", "k", "a", "p"):
            # нормализовать латиницу → кириллица
            return {"k": "к", "a": "а", "p": "п"}.get(ans, ans)
        print("  введите к, а или п")


def cmd_calibrate_batch(
    *,
    root=".",
    inputs_dir=None,
    calibrations_dir=None,
    cache_dir=None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> None:
    """Интерактивная калибровка пачки: проходит по inputs/*.mp4, пропускает ручные.

    Для каждого видео без ручной калибровки спрашивает: к/а/п.
    к → браузер-калибратор; а → сохранить автокроп; п → пропустить.
    """
    root = Path(root)
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"
    calibrations_dir = Path(calibrations_dir) if calibrations_dir else root / "calibrations"
    cache_dir = Path(cache_dir) if cache_dir else root / "data" / "cache"

    videos = sorted(inputs_dir.glob("*.mp4")) if inputs_dir.is_dir() else []
    if not videos:
        print("inputs/ пуст — нечего калибровать")
        return

    for video in videos:
        sha = state.file_sha256_cached_fast(video, cache_dir)
        kind = _calibration_kind(calibrations_dir, sha)
        if kind == "manual":
            continue  # уже откалиброван вручную — пропуск молча

        action = _ask_batch_action(video.name)

        if action == "п":
            continue

        if action == "а":
            frame_size = _probe_frame_size_for_auto(video, ffprobe=ffprobe)
            crop = auto_crop(frame_size)
            import json as _json
            calibrations_dir.mkdir(parents=True, exist_ok=True)
            rec = {
                "source_name": video.name,
                "source_sha256": sha,
                "setup_label": "auto",
                "crop": crop.model_dump(),
                "scale": [1080, 1920],
                "frame": list(frame_size),
                "auto": True,
            }
            calibration_path(calibrations_dir, sha).write_text(
                _json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  ⚙ автокроп зафиксирован: {video.name}")

        elif action == "к":
            cmd_calibrate(video, setup_label=None, ffmpeg=ffmpeg, ffprobe=ffprobe)


# --------------------------------------------------------------------------- status

def cmd_status(*, root=".") -> int:
    """Сводка текущего состояния проекта: inputs / manifests / reels-out / archive + предупреждения."""
    root = Path(root)
    inputs_dir      = root / "inputs"
    manifests_dir   = root / "manifests"
    reels_out_dir   = root / "reels-out"
    archive_dir     = root / "inputs-archive"
    calibrations_dir = root / "calibrations"

    inputs    = sorted(inputs_dir.glob("*.mp4"))      if inputs_dir.is_dir()    else []
    manifests = sorted(manifests_dir.glob("*.json"))  if manifests_dir.is_dir() else []
    rendered  = [d for d in reels_out_dir.iterdir() if d.is_dir()] \
                if reels_out_dir.is_dir() else []
    archived  = sorted(archive_dir.glob("*.mp4"))     if archive_dir.is_dir()   else []

    print("─── autoreels status ───────────────────────────────")
    print(f"  inputs/          {len(inputs):>3} видео  (ждут run)")
    print(f"  manifests/       {len(manifests):>3} манифеста  (готовы к рендеру)")
    print(f"  reels-out/       {len(rendered):>3} папок  (отрендеренные видео)")
    print(f"  inputs-archive/  {len(archived):>3} архивных видео")

    cache_dir = root / "data" / "cache"

    # Per-file таблица кропа
    if inputs:
        print()
        print("  ┌─ inputs/ ────────────────────────────────────────")
        for v in inputs:
            try:
                sha = state.file_sha256_cached_fast(v, cache_dir)
                kind = _calibration_kind(calibrations_dir, sha)
            except Exception:  # noqa: BLE001
                kind = "none"
            if kind == "manual":
                mark = "✓ кроп откалиброван (ручной)"
            else:
                mark = "⚙ автокроп (калибровки нет)" if kind == "none" else "⚙ автокроп (зафиксирован)"
            print(f"  │ {v.name:<30}  {mark}")
        print("  └──────────────────────────────────────────────────")

    # Предупреждения: манифесты без видео
    warnings: list[str] = []
    input_stems = {v.stem for v in inputs}
    for mf in manifests:
        try:
            m = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
            stem = Path(m.source).stem
            if stem not in input_stems:
                warnings.append(f"  ⚠ манифест без видео: {mf.name} (нет inputs/{m.source})")
        except Exception:  # noqa: BLE001
            warnings.append(f"  ⚠ битый манифест: {mf.name}")

    if warnings:
        print()
        for w in warnings:
            print(w)

    print("────────────────────────────────────────────────────")
    return 0


# ----------------------------------------------------------------------------- main

_CHEATSHEET = """\
autoreels — длинное видео → вертикальные Reels 9:16

Команды:
  status              состояние: исходники, кроп, манифесты, готовые рилсы
  calibrate <видео>   визуальная калибровка кропа (браузер)
  calibrate --all     пройтись по всем некалиброванным (интерактивно)
  run <видео>         анализ → манифест (Mac, нужен Groq; длинное → чанкинг авто)
  render              рендер по манифесту → reels-out/ (системник, AMF)
  help                расширенная справка: цикл, папки, частые случаи

Рабочий цикл:
  1. autoreels status                         # что где, нужен ли кроп
  2. autoreels calibrate --all                # настроить кадры (или пропустить → автокроп)
  3. autoreels run inputs/видео.mp4           # → manifests/<имя>.json
  4. autoreels render --encoder h264_amf      # → reels-out/<имя>/

Папки: inputs/ · manifests/ · reels-out/ · inputs-archive/
autoreels <команда> --help — детали и флаги.\
"""

_HELP_EXTENDED = """\
autoreels — длинное talking-head видео → вертикальные Reels 9:16

━━━ КОМАНДЫ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  status [--root .]
    Сводка состояния проекта: inputs/ (ждут run), manifests/ (готовы к рендеру),
    reels-out/ (готовые рилсы), inputs-archive/ (заархивированные).
    Per-file таблица кропа для inputs/: ✓ ручной / ⚙ автокроп.

  calibrate <видео> [--setup МЕТКА] [--all] [--port 8765] [--ffmpeg] [--ffprobe]
    Визуальная калибровка кропа (9:16) конкретного видео — браузер с UI.
    --all / --pending: интерактивный обход inputs/*.mp4. Для каждого без ручной
    калибровки спрашивает: [к]алибровать / [а]втокроп / [п]ропустить.
    Откалиброванные вручную — пропускаются молча.
    Без калибровки run делает автокроп 9:16 по центру кадра (молча).

  run [видео] [--ffmpeg путь]
    Облачный тир (Mac): аудио → Groq Whisper → транскрипт → Groq LLM → манифест.
    Нужен: GROQ_API_KEY в .env. Видео за пределы машины не уходит.
    Длинное видео (>15 мин / >20 МБ аудио) → чанкинг включается автоматически.
    Без аргумента: batch по всем inputs/*.mp4.
    После успеха видео перемещается в inputs-archive/.

  render [--encoder КОДЕК] [--ffmpeg путь]
    Локальный тир (системник): manifests/*.json → reels-out/<стем>/<id>.mp4.
    Системник Windows: --encoder h264_amf (AMD) или h264_nvenc (NVIDIA).
    Идемпотентен: уже готовые mp4 пропускаются; нет видео — предупреждение ⊘.

━━━ РАБОЧИЙ ЦИКЛ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. autoreels status                         # проверить что где
  2. autoreels calibrate --all                # пройтись по кропам (к/а/п per-file)
  3. [Mac, нужен Groq]
     autoreels run inputs/видео.mp4           # → manifests/видео.json
     # git commit manifests/ + push → системник pull
  4. [Системник, после git pull]
     autoreels render --encoder h264_amf      # → reels-out/видео/r01.mp4, ...

━━━ ПАПКИ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  inputs/           исходные видео (mp4, gitignore — гигабайты)
  inputs-archive/   видео после обработки (перемещаются автоматически)
  manifests/        JSON-задания для рендера (git-tracked, Mac → системник)
  reels-out/        готовые вертикальные клипы (gitignore)
  calibrations/     профили кропа по sha256 (gitignore)
  data/cache/       кэш аудио и транскриптов (gitignore)
  config/           r0.yaml, render.yaml, subtitles.yaml — все настройки

━━━ ЧАСТЫЕ СЛУЧАИ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Нет калибровки → автокроп 9:16 по центру (run молча, calibrate --all явно спрашивает).
  Длинное видео → чанкинг Whisper автоматически (config: chunking.whisper_threshold_minutes).
  429/413 от Groq → пауза между чанками (config: chunking.r0_chunk_delay_sec).
  Сегменты >59 с → обрезаются по паузе (config: r0.yaml too_long_policy: trim).
  Groq недоступен на системнике → run на Mac, манифест через git push/pull.
\
"""


def _build_parser():
    import argparse

    p = argparse.ArgumentParser(
        prog="autoreels",
        description="Длинное talking-head видео → вертикальные Reels 9:16.",
        add_help=True,
    )
    sub = p.add_subparsers(dest="cmd", required=False)

    sub.add_parser("help", help="расширенная справка: полный цикл, папки, частые случаи")

    ps = sub.add_parser(
        "status",
        help="сводка состояния: inputs / manifests / reels-out / archive + предупреждения",
        description=(
            "Показывает текущее состояние проекта:\n"
            "  • сколько видео ждут run (inputs/)\n"
            "  • сколько манифестов готовы к рендеру (manifests/)\n"
            "  • сколько папок уже отрендерено (reels-out/)\n"
            "  • сколько видео заархивировано (inputs-archive/)\n"
            "  • предупреждения: манифесты без видео, видео без калибровки\n\n"
            "Пример: autoreels status"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ps.add_argument("--root", default=".", help="корень проекта (по умолчанию: .)")

    pc = sub.add_parser(
        "calibrate",
        help="визуальная калибровка кропа (per-file или --all для пачки)",
        description=(
            "Открывает UI в браузере для настройки кадра кропа (9:16) конкретного видео.\n"
            "Сохраняет профиль в calibrations/<sha256>.json.\n"
            "Без калибровки run делает автокроп 9:16 по центру кадра с предупреждением.\n\n"
            "--all / --pending: интерактивный обход inputs/*.mp4 — спрашивает только для\n"
            "видео без ручной калибровки (к=браузер / а=автокроп / п=пропустить).\n\n"
            "Пример: autoreels calibrate inputs/лекция.mp4 --setup tearoom_main\n"
            "Пачка:  autoreels calibrate --all"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pc.add_argument("video", nargs="?", default=None,
                    help="путь к видео для калибровки (не нужен с --all)")
    pc.add_argument("--all", dest="all", action="store_true", default=False,
                    help="интерактивный обход всех inputs/*.mp4 без ручной калибровки")
    pc.add_argument("--pending", dest="all", action="store_true",
                    help="псевдоним --all")
    pc.add_argument("--setup", default=None,
                    help="метка сетапа — имя позиции съёмки (→ setup_id в манифесте)")
    pc.add_argument("--ffmpeg", default="ffmpeg",
                    help="путь к ffmpeg (по умолчанию: ffmpeg из PATH)")
    pc.add_argument("--ffprobe", default="ffprobe",
                    help="путь к ffprobe (по умолчанию: ffprobe из PATH)")
    pc.add_argument("--port", type=int, default=8765,
                    help="порт localhost-сервера калибровки (по умолчанию: 8765)")

    pr = sub.add_parser(
        "run",
        help="транскрипция + выбор моментов → manifests/<стем>.json (облачный тир, нужен Groq)",
        description=(
            "Облачный тир: видео → аудио → Groq Whisper → транскрипт → Groq LLM → манифест.\n"
            "Нужен GROQ_API_KEY в .env. Видео за пределы машины не уходит.\n"
            "Без <видео>: batch-обработка всех inputs/*.mp4.\n"
            "После успеха видео перемещается в inputs-archive/.\n\n"
            "Пример: autoreels run inputs/лекция.mp4\n"
            "Batch:   autoreels run"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pr.add_argument("video", nargs="?", default=None,
                    help="путь к видео; без аргумента — batch: все *.mp4 из inputs/")
    pr.add_argument("--ffmpeg", default="ffmpeg",
                    help="путь к ffmpeg (по умолчанию: ffmpeg из PATH)")

    pd = sub.add_parser(
        "render",
        help="manifests/*.json → reels-out/ (локальный тир, ffmpeg)",
        description=(
            "Локальный тир: все манифесты в manifests/ → вертикальные mp4 в reels-out/.\n"
            "Идемпотентен: уже готовые клипы пропускаются; нет видео — предупреждение ⊘.\n"
            "На системнике Windows: --encoder h264_amf (AMD) или h264_nvenc (NVIDIA).\n\n"
            "Пример: autoreels render --encoder h264_amf\n"
            "Windows: autoreels render --encoder h264_amf --ffmpeg D:\\ffmpeg\\bin\\ffmpeg.exe"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pd.add_argument("--encoder", default=None,
                    help="видеокодек ffmpeg (h264_amf — AMD Windows, h264_nvenc — NVIDIA, libx264 — CPU)")
    pd.add_argument("--ffmpeg", default="ffmpeg",
                    help="путь к ffmpeg-бинарю (Windows: D:\\ffmpeg\\bin\\ffmpeg.exe)")

    return p


def main(argv=None) -> int:
    """Точка входа CLI. Автоподхват .env, диспетч по команде, ошибки тиров → код 1 + сообщение."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except AttributeError:
            pass

    _load_env()
    args = _build_parser().parse_args(argv)

    if args.cmd is None:
        print(_CHEATSHEET)
        return 0

    if args.cmd == "help":
        print(_HELP_EXTENDED)
        return 0

    if args.cmd == "status":
        return cmd_status(root=args.root)

    try:
        if args.cmd == "calibrate":
            if args.all:
                cmd_calibrate_batch(ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)
            elif args.video:
                cmd_calibrate(Path(args.video), setup_label=args.setup, ffmpeg=args.ffmpeg,
                              ffprobe=args.ffprobe, port=args.port)
            else:
                print("ошибка: укажите видео или используйте --all", file=sys.stderr)
                return 1
        elif args.cmd == "run":
            if args.video:
                cmd_run(Path(args.video), ffmpeg=args.ffmpeg)
            else:
                _, failed = cmd_run_batch(ffmpeg=args.ffmpeg)
                if failed:
                    return 1
        elif args.cmd == "render":
            cmd_render(encoder=args.encoder, ffmpeg=args.ffmpeg)
    except _KNOWN_ERRORS as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
