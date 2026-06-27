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
from autoreels.cloud.transcribe import TranscriptionError, get_backend, transcribe
from autoreels.core import state
from autoreels.core.config import (
    ConfigError,
    load_profile,
    load_r0_config,
    load_render_config,
    load_transcribe_config,
)
from autoreels.core.models import Manifest
from autoreels.local.render import RenderError, load_manifest, render_crop

# Ошибки тиров, которые CLI превращает во внятное сообщение (а не голый traceback).
_KNOWN_ERRORS = (
    ExtractAudioError,
    TranscriptionError,
    ProviderError,
    SelectError,
    RenderError,
    ConfigError,
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


def _assemble_manifest(video, reels, *, profile, duration_preset):
    """Собрать манифест: setup_id И кроп берутся ИЗ профиля, source_sha256 — от файла."""
    sha = state.file_sha256(video)
    return Manifest(
        source=Path(video).name,
        source_sha256=sha,
        duration_preset=duration_preset,
        setup=profile,                      # весь профиль сетапа (id + crop) — отсюда
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
    setup: str = "tearoom_main",
    profile=None,
    root=".",
    manifests_dir=None,
    cache_dir=None,
    ffmpeg: str = "ffmpeg",
) -> Path:
    """ОБЛАЧНЫЙ тир: видео → manifests/manifest.json (extract→transcribe→compress→select).

    Кроп и setup_id берутся из `profiles/<setup>.json` (или `--profile`), НЕ хардкод и НЕ из
    старого манифеста — это чинит расхождение setup_id (pxl_sasha vs tearoom_main).
    """
    root = Path(root)
    cfg = root / "config"
    render_cfg = load_render_config(cfg / "render.yaml")
    r0_cfg = load_r0_config(cfg / "r0.yaml")
    transcribe_cfg = load_transcribe_config(cfg / "transcribe.yaml")

    profile_path = Path(profile) if profile else root / "profiles" / f"{setup}.json"
    profile_obj = load_profile(profile_path)

    cache_dir = Path(cache_dir) if cache_dir else root / "data" / "cache"
    manifests_dir = Path(manifests_dir) if manifests_dir else root / "manifests"

    print(f"=== run: {Path(video).name} (setup={profile_obj.setup_id}) ===", flush=True)
    audio = _stage_extract_audio(video, render_cfg=render_cfg, cache_dir=cache_dir, ffmpeg=ffmpeg)
    transcript = _stage_transcribe(audio, transcribe_cfg=transcribe_cfg, cache_dir=cache_dir)
    compressed = _stage_compress(transcript, r0_cfg=r0_cfg)
    reels = _stage_select(compressed, r0_cfg=r0_cfg, root=root)
    manifest = _assemble_manifest(
        video, reels, profile=profile_obj, duration_preset=r0_cfg.duration_preset
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
    manifests_dir = Path(manifests_dir) if manifests_dir else root / "manifests"
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"
    out_dir = Path(out_dir) if out_dir else root / "reels-out"

    manifest = load_manifest(manifests_dir)
    enc = encoder or os.environ.get("RENDER_ENCODER") or render_cfg.encoder.codec
    print(f"=== render: {len(manifest.reels)} клипов, энкодер {enc} ===", flush=True)

    outputs = render_crop(
        manifest, inputs_dir=inputs_dir, out_dir=out_dir, render_cfg=render_cfg,
        ffmpeg=ffmpeg, encoder=encoder, progress=lambda rid: print(f"рендер {rid}…", flush=True),
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

    pr = sub.add_parser("run", help="облачный тир: видео → manifests/manifest.json")
    pr.add_argument("video", help="путь к исходному видео (Mac)")
    pr.add_argument("--setup", default="tearoom_main", help="профиль сетапа из profiles/")
    pr.add_argument("--profile", default=None, help="путь к профилю (перебивает --setup)")
    pr.add_argument("--ffmpeg", default="ffmpeg", help="путь к ffmpeg-бинарю")

    pd = sub.add_parser("render", help="локальный тир: manifest.json → reels-out/")
    pd.add_argument("--encoder", default=None, help="видеоэнкодер (на системнике h264_amf)")
    pd.add_argument("--ffmpeg", default="ffmpeg", help="путь к ffmpeg-бинарю (Windows: D:\\ffmpeg\\bin)")

    return p


def main(argv=None) -> int:
    """Точка входа CLI. Автоподхват .env, диспетч по команде, ошибки тиров → код 1 + сообщение."""
    _load_env()
    args = _build_parser().parse_args(argv)
    try:
        if args.cmd == "run":
            cmd_run(args.video, setup=args.setup, profile=args.profile, ffmpeg=args.ffmpeg)
        elif args.cmd == "render":
            cmd_render(encoder=args.encoder, ffmpeg=args.ffmpeg)
    except _KNOWN_ERRORS as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
