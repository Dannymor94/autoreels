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
    msg = str(e.value)
    assert "ffmpeg" in msg.lower()            # внятная ошибка, не голый traceback
    assert "render.local.yaml" in msg and "--ffmpeg" in msg   # КАК задать путь


def test_popen_filenotfound_becomes_clean_error(monkeypatch, tmp_path, audio_cfg):
    """Бинарь резолвнулся (which вернул путь), но Popen падает FileNotFoundError ([WinError 2]).
    Должны получить внятную ExtractAudioError с подсказкой, а НЕ голый WinError 2."""
    import autoreels.cloud.extract_audio as EA
    src = tmp_path / "v.mp4"; src.write_bytes(b"x")
    monkeypatch.setattr(EA.shutil, "which", lambda b: f"/fake/{b}")   # which «нашёл» путь
    monkeypatch.setattr(EA, "_probe_duration_sec", lambda ffmpeg_bin, source: None)

    def _popen_boom(*a, **k):
        raise FileNotFoundError(2, "Не удаётся найти указанный файл")
    monkeypatch.setattr(EA.subprocess, "Popen", _popen_boom)

    with pytest.raises(ExtractAudioError) as e:
        extract_audio(src, audio_cfg, cache_dir=tmp_path / "c",
                      ffmpeg=r"D:\ffmpeg\bin\ffmpeg.exe", source_sha="e" * 64)
    msg = str(e.value)
    assert "ffmpeg" in msg.lower() and "render.local.yaml" in msg   # внятно + как чинить


# ------------------------------------------------------ прогресс-бар (мок ffmpeg)

def _fake_ffmpeg_progress_proc(out_time_us_steps, returncode=0, stderr=""):
    """Фабрика фейкового Popen: stdout отдаёт -progress строки out_time_ms=…, stderr — текст."""
    class _FakeProc:
        def __init__(self, cmd, **kwargs):
            self.stdout = iter([f"out_time_ms={us}\n" for us in out_time_us_steps])
            self.stderr = iter([stderr] if stderr else [])
            self.returncode = returncode
        def wait(self):
            return self.returncode
    return _FakeProc


def test_extract_prints_live_bar(monkeypatch, tmp_path, audio_cfg, capsys):
    """extract_audio рисует живой прогресс-бар по времени ffmpeg (мок Popen + ffprobe)."""
    import autoreels.cloud.extract_audio as EA
    import autoreels.core.progress as prog

    monkeypatch.setattr(prog, "is_tty", lambda: False)
    monkeypatch.setattr(EA.shutil, "which", lambda b: f"/fake/{b}")
    monkeypatch.setattr(EA, "_probe_duration_sec", lambda ffmpeg_bin, source: 100.0)
    # 30с и 100с из 100с → бар растёт до 30%, затем финальный 100%
    monkeypatch.setattr(EA.subprocess, "Popen",
                        _fake_ffmpeg_progress_proc([30_000_000, 100_000_000]))

    src = tmp_path / "v.mp4"
    src.write_bytes(b"x")
    out = extract_audio(src, audio_cfg, cache_dir=tmp_path / "c", source_sha="a" * 64)

    assert out == tmp_path / "c" / f"{'a'*64}.{audio_cfg.format}"
    printed = capsys.readouterr().out
    assert "█" in printed and "░" in printed          # визуальный бар
    assert "30%" in printed                            # промежуточный прогресс
    assert "100%" in printed and "✓" in printed        # финал


def test_extract_spinner_when_duration_unknown(monkeypatch, tmp_path, audio_cfg, capsys):
    """Длительность не определить (ffprobe нет) → живой спиннер вместо бара, финал печатается."""
    import autoreels.cloud.extract_audio as EA
    import autoreels.core.progress as prog

    monkeypatch.setattr(prog, "is_tty", lambda: False)
    monkeypatch.setattr(EA.shutil, "which", lambda b: f"/fake/{b}")
    monkeypatch.setattr(EA, "_probe_duration_sec", lambda ffmpeg_bin, source: None)
    monkeypatch.setattr(EA.subprocess, "Popen",
                        _fake_ffmpeg_progress_proc([10_000_000, 20_000_000]))

    src = tmp_path / "v.mp4"
    src.write_bytes(b"x")
    extract_audio(src, audio_cfg, cache_dir=tmp_path / "c", source_sha="b" * 64)

    printed = capsys.readouterr().out
    assert "извлекаю аудио" in printed and "✓" in printed   # финальная строка спиннера


def test_extract_ffmpeg_failure_raises_with_stderr(monkeypatch, tmp_path, audio_cfg):
    """ffmpeg вернул код != 0 → ExtractAudioError со stderr (поведение сохранено на Popen)."""
    import autoreels.cloud.extract_audio as EA
    import autoreels.core.progress as prog

    monkeypatch.setattr(prog, "is_tty", lambda: False)
    monkeypatch.setattr(EA.shutil, "which", lambda b: f"/fake/{b}")
    monkeypatch.setattr(EA, "_probe_duration_sec", lambda ffmpeg_bin, source: 100.0)
    monkeypatch.setattr(EA.subprocess, "Popen",
                        _fake_ffmpeg_progress_proc([], returncode=1, stderr="boom decode error\n"))

    src = tmp_path / "v.mp4"
    src.write_bytes(b"x")
    with pytest.raises(ExtractAudioError) as e:
        extract_audio(src, audio_cfg, cache_dir=tmp_path / "c", source_sha="c" * 64)
    assert "boom decode error" in str(e.value)
