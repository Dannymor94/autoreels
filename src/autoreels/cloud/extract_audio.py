"""Извлечение аудио: ffmpeg -vn → 16kHz mono под Whisper.

Сидит на границе тиров: ffmpeg локальный, но готовит вход облачному тиру (транскрипция),
поэтому модуль в cloud/. Видеоряд наружу не уходит — извлекается только аудио.

Принципы:
- параметры извлечения берутся из render.yaml (`AudioExtract`), не хардкодятся;
- выход в data/cache по хэшу содержимого источника → почва под идемпотентность шага 3
  (повторный прогон даёт то же имя, транскрипт не перетранскрибируется);
- fail-fast: нет источника / нет ffmpeg / ffmpeg упал → ExtractAudioError с внятным
  сообщением, а не голый traceback или тихий провал.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from autoreels.core import state
from autoreels.core.config import AudioExtract


class ExtractAudioError(Exception):
    """Извлечение аудио не удалось (нет файла, нет ffmpeg, ffmpeg вернул ошибку)."""


def extract_audio(
    source: str | Path,
    audio_cfg: AudioExtract,
    cache_dir: str | Path,
    *,
    ffmpeg: str = "ffmpeg",
) -> Path:
    """Извлечь аудиодорожку из `source` в `cache_dir`/<sha256>.<format>.

    Возвращает путь к извлечённому аудио. Параметры (частота/каналы/кодек/формат) — из
    `audio_cfg` (render.yaml). Имя файла детерминировано по хэшу содержимого источника.
    """
    source = Path(source)
    if not source.is_file():
        raise ExtractAudioError(f"исходный файл не найден: {source}")

    ffmpeg_bin = shutil.which(ffmpeg)
    if ffmpeg_bin is None:
        raise ExtractAudioError(
            f"ffmpeg не найден в PATH (искали '{ffmpeg}'); установите ffmpeg для извлечения аудио"
        )

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{state.file_sha256(source)}.{audio_cfg.format}"

    cmd = [
        ffmpeg_bin, "-y", "-loglevel", "error",
        "-i", str(source),
        "-vn",                                  # без видео — на границе тиров видео не идёт
        "-ac", str(audio_cfg.channels),
        "-ar", str(audio_cfg.sample_rate),
        "-c:a", audio_cfg.codec,
        "-f", audio_cfg.format,
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        out.unlink(missing_ok=True)             # не оставлять битый частичный выход
        stderr = proc.stderr.strip() or "(пустой stderr)"
        raise ExtractAudioError(
            f"ffmpeg не смог извлечь аудио из {source} (код {proc.returncode}): {stderr}"
        )
    return out
