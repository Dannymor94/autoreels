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
from pathlib import Path

from autoreels.core import state
from autoreels.core.config import AudioExtract


class ExtractAudioError(Exception):
    """Извлечение аудио не удалось (нет файла, нет ffmpeg, ffmpeg вернул ошибку)."""


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
) -> Path:
    """Извлечь аудиодорожку из `source` в `cache_dir`/<sha256>.<format>.

    Возвращает путь к извлечённому аудио. Имя детерминировано по хэшу содержимого.
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

    cmd = build_extract_cmd(ffmpeg_bin, source, out, audio_cfg)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        out.unlink(missing_ok=True)
        stderr = proc.stderr.strip() or "(пустой stderr)"
        raise ExtractAudioError(
            f"ffmpeg не смог извлечь аудио из {source} (код {proc.returncode}): {stderr}"
        )
    return out
