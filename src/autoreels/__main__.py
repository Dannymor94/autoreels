"""CLI-склейка тиров: две команды по границе ОБЛАКО/ЛОКАЛЬ (M0 шаг 8).

Убирает терминал-ритуал (ручная активация venv, многострочные `python -c`, ручные пути,
`source .env`, невидимый прогресс). Без субтитров — R3 встанет одним блоком между select
и render (этапы `run` оформлены как отдельные функции-блоки именно ради этого).

    autoreels run <video> --setup tearoom_main   # Mac: видео → manifests/manifest.json
    autoreels render                              # системник: manifest.json → reels-out/

Граница тиров: `run` живёт в облачном конвейере (аудио/текст), `render` — локальный ffmpeg.
Видео между тирами не ходит: манифест несёт source_sha256, render ищет файл в inputs/.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from autoreels.cloud.compress import compress_transcript
from autoreels.cloud.extract_audio import ExtractAudioError, extract_audio
from autoreels.cloud.providers import GroqLLM, ProviderError
from autoreels.cloud.select import SelectError, select
from autoreels.cloud.snap import snap_segments
from autoreels.cloud.transcribe import TranscriptionError, get_backend, transcribe
from autoreels.core import state
from autoreels.core.calibration import CalibrationError, load_calibration
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

MANIFEST_NAME = "manifest.json"


# --------------------------------------------------------------------------- .env

def _load_env(dotenv_path: str | Path | None = None) -> None:
    """Подхватить .env в окружение (закрывает ручной `source .env`, долг 5a).

    Без аргумента — авто-поиск .env в cwd/родителях; с путём — конкретный файл (тест).
    Существующие переменные окружения не перетираются (приоритет реального окружения).
    """
    from dotenv import load_dotenv

    load_dotenv(str(dotenv_path) if dotenv_path is not None else None)


def _run_key(source_sha256: str, duration_preset: str) -> str:
    """Детерминированный ключ прогона от source+preset (полноценная версия рубрики — M1)."""
    return hashlib.sha256(f"{source_sha256}:{duration_preset}".encode()).hexdigest()[:16]


# ----------------------------------------------------- этапы конвейера `run` (блоки)

def _stage_extract_audio(video, *, render_cfg, cache_dir, ffmpeg):
    print("извлекаю аудио…", flush=True)
    return extract_audio(video, render_cfg.audio_extract, cache_dir, ffmpeg=ffmpeg)


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
    """R3: привязать word-level транскрипта к каждому reel (слова в окне start-end).

    Кладёт сырой word-level в reel.subtitles; группировку в строки и ASS делает render (R3),
    не схема. Это блок между snap и сборкой манифеста (run собран блоками)."""
    print("субтитры: привязка слов к сегментам…", flush=True)
    for reel in reels:
        reel.subtitles = words_in_window(transcript.words, reel.start, reel.end)
    return reels


def _assemble_manifest(video, reels, *, sha, setup, duration_preset):
    """Собрать манифест: кроп/setup_id — из калибровки (setup), source_sha256 — от файла."""
    return Manifest(
        source=Path(video).name,
        source_sha256=sha,
        duration_preset=duration_preset,
        setup=setup,                        # SetupProfile из calibrations/<sha>.json
        run_key=_run_key(sha, duration_preset),
        reels=reels,
    )


def _write_manifest(manifest, manifests_dir) -> Path:
    manifests_dir = Path(manifests_dir)
    manifests_dir.mkdir(parents=True, exist_ok=True)
    path = manifests_dir / MANIFEST_NAME
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
    ffmpeg: str = "ffmpeg",
) -> Path:
    """ОБЛАЧНЫЙ тир: видео → manifests/manifest.json (extract→transcribe→compress→select).

    Кроп per-file: берётся из `calibrations/<sha256>.json` (его пишет `autoreels calibrate`).
    Калибровки нет → CalibrationError ДО конвейера: run останавливается с подсказкой
    «сначала: autoreels calibrate <video>», а не молча продолжает без кропа.
    """
    root = Path(root)
    cfg = root / "config"
    render_cfg = load_render_config(cfg / "render.yaml")
    r0_cfg = load_r0_config(cfg / "r0.yaml")
    transcribe_cfg = load_transcribe_config(cfg / "transcribe.yaml")
    calibrations_dir = Path(calibrations_dir) if calibrations_dir else root / "calibrations"
    cache_dir = Path(cache_dir) if cache_dir else root / "data" / "cache"
    manifests_dir = Path(manifests_dir) if manifests_dir else root / "manifests"

    # Идентичность файла + кроп ДО запуска конвейера. Нет калибровки → стоп (fail-fast),
    # ни один облачный этап не дёргается (не жжём Groq на видео без кропа).
    size_gb = Path(video).stat().st_size / (1 << 30)
    print(f"считаю хэш видео ({size_gb:.1f} ГБ)…", flush=True)
    sha = state.file_sha256_cached(video, cache_dir)
    print("хэш готов.", flush=True)
    setup = load_calibration(calibrations_dir, sha)

    print(f"=== run: {Path(video).name} (setup={setup.setup_id}) ===", flush=True)
    audio = _stage_extract_audio(video, render_cfg=render_cfg, cache_dir=cache_dir, ffmpeg=ffmpeg)
    transcript = _stage_transcribe(audio, transcribe_cfg=transcribe_cfg, cache_dir=cache_dir)
    compressed = _stage_compress(transcript, r0_cfg=r0_cfg)
    reels = _stage_select(compressed, r0_cfg=r0_cfg, root=root)
    reels = _stage_snap(reels, transcript, r0_cfg=r0_cfg)   # код подтягивает границы LLM к словам
    reels = _stage_subtitles(reels, transcript)             # word-level в reel.subtitles (R3)
    manifest = _assemble_manifest(
        video, reels, sha=sha, setup=setup, duration_preset=r0_cfg.duration_preset
    )
    path = _write_manifest(manifest, manifests_dir)
    print(f"манифест собран: {len(manifest.reels)} reels → {path}", flush=True)
    return path


def cmd_render(
    *,
    manifests_dir=None,
    inputs_dir=None,
    out_dir=None,
    root=".",
    ffmpeg: str = "ffmpeg",
    encoder=None,
) -> list[Path]:
    """ЛОКАЛЬНЫЙ тир: manifests/manifest.json → reels-out/ (render_crop, вертикальный 9:16).

    Энкодер: `--encoder` > env RENDER_ENCODER > render.yaml (на системнике h264_amf).
    Путь ffmpeg конфигурируем. Пути inputs/ reels-out/ manifests/ — дефолтные, без аргументов.
    """
    root = Path(root)
    render_cfg = load_render_config(root / "config" / "render.yaml")
    subtitles_cfg = load_subtitles_config(root / "config" / "subtitles.yaml")
    manifests_dir = Path(manifests_dir) if manifests_dir else root / "manifests"
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"
    out_dir = Path(out_dir) if out_dir else root / "reels-out"

    manifest = load_manifest(manifests_dir)
    enc = encoder or os.environ.get("RENDER_ENCODER") or render_cfg.encoder.codec
    print(f"=== render: {len(manifest.reels)} клипов, энкодер {enc} ===", flush=True)

    outputs = render_crop(
        manifest, inputs_dir=inputs_dir, out_dir=out_dir, render_cfg=render_cfg,
        ffmpeg=ffmpeg, encoder=encoder, subtitles_cfg=subtitles_cfg,
        progress=lambda rid: print(f"рендер {rid}…", flush=True),
    )
    print(f"готово: {len(outputs)} клипов → {out_dir}", flush=True)
    return outputs


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

    pr = sub.add_parser("run", help="облачный тир: видео → manifests/manifest.json")
    pr.add_argument("video", help="путь к исходному видео (Mac)")
    # Кроп per-file берётся из calibrations/<sha>.json (см. autoreels calibrate), не из --setup.
    pr.add_argument("--ffmpeg", default="ffmpeg", help="путь к ffmpeg-бинарю")

    pd = sub.add_parser("render", help="локальный тир: manifest.json → reels-out/")
    pd.add_argument("--encoder", default=None, help="видеоэнкодер (на системнике h264_amf)")
    pd.add_argument("--ffmpeg", default="ffmpeg", help="путь к ffmpeg-бинарю (Windows: D:\\ffmpeg\\bin)")

    return p


def main(argv=None) -> int:
    """Точка входа CLI. Автоподхват .env, диспетч по команде, ошибки тиров → код 1 + сообщение."""
    # Windows: консоль по умолчанию cp1251 → кириллица ломается. Форсируем utf-8.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except AttributeError:
            pass  # не TextIOWrapper (pytest capture, pipe) — не трогаем

    _load_env()
    args = _build_parser().parse_args(argv)
    try:
        if args.cmd == "calibrate":
            cmd_calibrate(Path(args.video), setup_label=args.setup, ffmpeg=args.ffmpeg,
                          ffprobe=args.ffprobe, port=args.port)
        elif args.cmd == "run":
            cmd_run(Path(args.video), ffmpeg=args.ffmpeg)
        elif args.cmd == "render":
            cmd_render(encoder=args.encoder, ffmpeg=args.ffmpeg)
    except _KNOWN_ERRORS as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
