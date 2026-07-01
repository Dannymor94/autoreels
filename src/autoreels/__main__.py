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
from autoreels.cloud.transcribe import TranscriptionError, get_backend, transcribe
from autoreels.core import state
from autoreels.core.calibration import (
    CalibrationError,
    _probe_frame_size_for_auto,
    load_calibration,
    load_or_auto_calibrate,
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
from autoreels.local.render import RenderError, load_manifest, render_crop
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


def _stage_transcribe(audio, *, transcribe_cfg, cache_dir):
    print("транскрипция…", flush=True)
    backend = get_backend(transcribe_cfg)
    return transcribe(audio, cache_dir, backend=backend, language=transcribe_cfg.language)


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
    transcript = _stage_transcribe(audio, transcribe_cfg=transcribe_cfg, cache_dir=cache_dir)
    compressed = _stage_compress(transcript, r0_cfg=r0_cfg)
    reels = _stage_select(compressed, r0_cfg=r0_cfg, root=root)
    reels = _stage_snap(reels, transcript, r0_cfg=r0_cfg)
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

    Каждый манифест рендерится независимо; упавший → остальные продолжают.
    После успеха источник перемещается в inputs-archive/ (идемпотентно).
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
    failed: list[tuple[str, Exception]] = []

    for mf in manifest_files:
        try:
            manifest = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
            stem = Path(manifest.source).stem
            out_dir_final = out_dir / stem
            print(f"=== render: {mf.name} ({len(manifest.reels)} клипов, {enc}) → {out_dir_final} ===",
                  flush=True)
            outputs = render_crop(
                manifest, inputs_dir=inputs_dir, out_dir=out_dir_final, render_cfg=render_cfg,
                ffmpeg=ffmpeg, encoder=encoder, subtitles_cfg=subtitles_cfg,
            )
            all_outputs.extend(outputs)
            print(f"готово: {len(outputs)} клипов → {out_dir_final}", flush=True)
            _archive_video(inputs_dir / Path(manifest.source).name, archive_dir)
        except Exception as e:  # noqa: BLE001
            print(f"\n[ОШИБКА] {mf.name}: {e}", file=sys.stderr, flush=True)
            failed.append((mf.name, e))

    if len(manifest_files) > 1 or failed:
        print(f"\n=== batch render: {len(manifest_files) - len(failed)} ok / {len(failed)} failed ===",
              flush=True)
        for name, err in failed:
            print(f"  ✗ {name}: {err}", file=sys.stderr)
    return all_outputs


# ----------------------------------------------------------------------------- main

def _build_parser():
    import argparse

    p = argparse.ArgumentParser(
        prog="autoreels",
        description="Длинное talking-head видео → вертикальные Reels 9:16 (две команды по тирам).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("calibrate", help="визуальная калибровка кропа для файла (per-file)")
    pc.add_argument("video", help="путь к видео для калибровки")
    pc.add_argument("--setup", default=None, help="метка сетапа (→ setup_id манифеста)")
    pc.add_argument("--ffmpeg", default="ffmpeg", help="путь к ffmpeg-бинарю")
    pc.add_argument("--ffprobe", default="ffprobe", help="путь к ffprobe-бинарю")
    pc.add_argument("--port", type=int, default=8765, help="порт localhost-сервера калибровки")

    pr = sub.add_parser("run", help="облачный тир: видео → manifests/<stem>.json")
    pr.add_argument("video", nargs="?", default=None,
                    help="путь к видео; без аргумента — batch: все *.mp4 из inputs/")
    pr.add_argument("--ffmpeg", default="ffmpeg", help="путь к ffmpeg-бинарю")

    pd = sub.add_parser("render", help="локальный тир: manifests/*.json → reels-out/")
    pd.add_argument("--encoder", default=None, help="видеоэнкодер (на системнике h264_amf)")
    pd.add_argument("--ffmpeg", default="ffmpeg", help="путь к ffmpeg-бинарю (Windows: D:\\ffmpeg\\bin)")

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
    try:
        if args.cmd == "calibrate":
            cmd_calibrate(Path(args.video), setup_label=args.setup, ffmpeg=args.ffmpeg,
                          ffprobe=args.ffprobe, port=args.port)
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
