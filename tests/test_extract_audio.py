"""Извлечение аудио (cloud/extract_audio.py).

Граница тиров: ffmpeg локальный, но готовит вход облачному тиру (Whisper). Инварианты:
параметры из render.yaml (не хардкод), выход в data/cache по хэшу источника (почва под
идемпотентность шага 3), fail-fast на отсутствии ffmpeg / битом файле.
"""
import shutil
import wave
from pathlib import Path

import pytest

from autoreels.cloud.extract_audio import extract_audio, ExtractAudioError
from autoreels.core.config import load_render_config

ROOT = Path(__file__).resolve().parents[1]
RENDER_YAML = ROOT / "config" / "render.yaml"


@pytest.fixture
def audio_cfg():
    # Параметры извлечения берутся из render.yaml, а не хардкодятся в модуле/тесте.
    return load_render_config(RENDER_YAML).audio_extract


def test_extracts_16k_mono_wav_matching_duration(synthetic_video, audio_cfg, tmp_path):
    out = extract_audio(synthetic_video, audio_cfg, cache_dir=tmp_path)
    assert out.exists()
    assert out.suffix == ".wav"
    with wave.open(str(out), "rb") as w:
        assert w.getframerate() == 16000      # формат = конфиг (16kHz)
        assert w.getnchannels() == 1          # mono
        duration = w.getnframes() / w.getframerate()
    # Длительность аудио совпадает с исходником (5с) в пределах допуска.
    assert abs(duration - 5.0) < 0.2


def test_output_named_by_source_hash_deterministic(synthetic_video, audio_cfg, tmp_path):
    a = extract_audio(synthetic_video, audio_cfg, cache_dir=tmp_path)
    b = extract_audio(synthetic_video, audio_cfg, cache_dir=tmp_path)
    assert a == b                 # тот же источник → то же имя (почва под идемпотентность)
    assert len(a.stem) == 64      # sha256 hex источника


def test_missing_source_raises(audio_cfg, tmp_path):
    # Проверка существования источника — до обращения к ffmpeg (работает и без ffmpeg).
    with pytest.raises(ExtractAudioError):
        extract_audio(tmp_path / "nope.mp4", audio_cfg, cache_dir=tmp_path)


def test_corrupt_source_raises(audio_cfg, tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("нужен ffmpeg для проверки битого источника")
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"this is definitely not a video container")
    with pytest.raises(ExtractAudioError):
        extract_audio(bad, audio_cfg, cache_dir=tmp_path)


def test_ffmpeg_not_found_raises(audio_cfg, tmp_path):
    dummy = tmp_path / "x.mp4"
    dummy.write_bytes(b"x")
    with pytest.raises(ExtractAudioError) as e:
        extract_audio(dummy, audio_cfg, cache_dir=tmp_path, ffmpeg="ffmpeg-does-not-exist-xyz")
    assert "ffmpeg" in str(e.value).lower()   # внятная ошибка, не голый traceback
