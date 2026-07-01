"""Извлечение аудио (cloud/extract_audio.py).

Граница тиров: ffmpeg локальный, но готовит вход облачному тиру (Whisper). Инварианты:
параметры из render.yaml (не хардкод), выход в data/cache по хэшу источника (почва под
идемпотентность шага 3), fail-fast на отсутствии ffmpeg / битом файле.

Формат под Whisper: компактный (mp3 64k) — аудио 46 мин < 24 МБ лимита Groq.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from autoreels.cloud.extract_audio import ExtractAudioError, build_extract_cmd, extract_audio
from autoreels.core.config import AudioExtract, load_render_config

ROOT = Path(__file__).resolve().parents[1]
RENDER_YAML = ROOT / "config" / "render.yaml"


@pytest.fixture
def audio_cfg():
    return load_render_config(RENDER_YAML).audio_extract


# ------------------------------------------------------ unit: ffmpeg-команда

def test_build_extract_cmd_includes_bitrate():
    cfg = AudioExtract(sample_rate=16000, channels=1, codec="libmp3lame",
                       format="mp3", bitrate="64k")
    cmd = build_extract_cmd("ffmpeg", Path("src.mp4"), Path("out.mp3"), cfg)
    assert "-b:a" in cmd
    assert "64k" in cmd


def test_build_extract_cmd_no_bitrate_for_pcm():
    cfg = AudioExtract(sample_rate=16000, channels=1, codec="pcm_s16le",
                       format="wav", bitrate=None)
    cmd = build_extract_cmd("ffmpeg", Path("src.mp4"), Path("out.wav"), cfg)
    assert "-b:a" not in cmd


def test_build_extract_cmd_format_from_config():
    cfg = AudioExtract(sample_rate=16000, channels=1, codec="libmp3lame",
                       format="mp3", bitrate="64k")
    cmd = build_extract_cmd("ffmpeg", Path("v.mp4"), Path("out.mp3"), cfg)
    assert "mp3" in cmd   # -f mp3
    assert "libmp3lame" in cmd


# ------------------------------------------------------ integration (нужен ffmpeg)

def test_extracts_compact_audio_correct_format(synthetic_video, audio_cfg, tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("нужен ffmpeg")
    out = extract_audio(synthetic_video, audio_cfg, cache_dir=tmp_path)
    assert out.exists()
    assert out.suffix == f".{audio_cfg.format}"
    assert out.stat().st_size > 0
    # Длительность через ffprobe — работает для любого формата (wav, mp3, …)
    if shutil.which("ffprobe"):
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(out)],
            capture_output=True, text=True, check=False,
        )
        duration = float(proc.stdout.strip())
        assert abs(duration - 5.0) < 0.3


def test_output_named_by_source_hash_deterministic(synthetic_video, audio_cfg, tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("нужен ffmpeg")
    a = extract_audio(synthetic_video, audio_cfg, cache_dir=tmp_path)
    b = extract_audio(synthetic_video, audio_cfg, cache_dir=tmp_path)
    assert a == b                 # тот же источник → то же имя
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
