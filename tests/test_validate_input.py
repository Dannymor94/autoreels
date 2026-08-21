"""Ранняя валидация входного файла (validate_input) — ДО хэша/калибровки/аудио.

Битые/пустые/недокачанные файлы ловим первым шагом, с человекочитаемой причиной. Невалидный
файл — SKIPPED (не FAILED): его не архивируют, конвейер не тратит на него тяжёлую работу.
"""
import subprocess

import pytest

from autoreels.local import calibrate
from autoreels.local.calibrate import InputInvalid, validate_input


class _Proc:
    def __init__(self, code, stdout="", stderr=""):
        self.returncode = code
        self.stdout = stdout
        self.stderr = stderr


def _big_file(tmp_path, name="v.mp4", size=2 << 20) -> "Path":
    p = tmp_path / name
    p.write_bytes(b"\0" * size)
    return p


def _mock_ffprobe(monkeypatch, proc):
    monkeypatch.setattr(calibrate.shutil, "which", lambda b: "/usr/bin/ffprobe")
    monkeypatch.setattr(calibrate.subprocess, "run", lambda *a, **k: proc)


# ------------------------------------------------------------ размер: пустой/недокачанный

def test_empty_file_is_invalid_without_probing(tmp_path, monkeypatch):
    """0 байт → невалиден с понятным текстом; ffprobe даже не вызывается (выход по размеру)."""
    probed = {"called": False}
    monkeypatch.setattr(calibrate.subprocess, "run",
                        lambda *a, **k: probed.update(called=True) or _Proc(0))
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")

    with pytest.raises(InputInvalid) as e:
        validate_input(empty)

    assert "пуст" in str(e.value).lower()
    assert probed["called"] is False        # тяжёлую работу не начинали


def test_tiny_file_is_invalid(tmp_path, monkeypatch):
    """Файл < 1 МБ → «слишком мал / недокачан»."""
    monkeypatch.setattr(calibrate.subprocess, "run", lambda *a, **k: _Proc(0))
    tiny = tmp_path / "tiny.mp4"
    tiny.write_bytes(b"x" * 1000)
    with pytest.raises(InputInvalid) as e:
        validate_input(tiny)
    assert "мал" in str(e.value).lower() or "недокач" in str(e.value).lower()


def test_missing_file_is_invalid(tmp_path):
    with pytest.raises(InputInvalid):
        validate_input(tmp_path / "nope.mp4")


# ------------------------------------------------------------ ffprobe: типичные поломки

def test_moov_atom_error_is_humanized(tmp_path, monkeypatch):
    """«moov atom not found» → «недокачан или обрезан при копировании»."""
    _mock_ffprobe(monkeypatch, _Proc(1, stderr="moov atom not found\n"))
    with pytest.raises(InputInvalid) as e:
        validate_input(_big_file(tmp_path))
    msg = str(e.value).lower()
    assert "недокач" in msg or "обрезан" in msg


def test_invalid_data_error_is_humanized(tmp_path, monkeypatch):
    """«Invalid data found» → «не видеофайл или повреждён»."""
    _mock_ffprobe(monkeypatch, _Proc(1, stderr="Invalid data found when processing input\n"))
    with pytest.raises(InputInvalid) as e:
        validate_input(_big_file(tmp_path))
    assert "поврежд" in str(e.value).lower() or "не видеофайл" in str(e.value).lower()


def test_no_video_stream_is_invalid(tmp_path, monkeypatch):
    """ffprobe ок, но нет размеров/длительности (нет видеопотока) → невалиден."""
    _mock_ffprobe(monkeypatch, _Proc(0, stdout="\n"))     # пустой вывод — parse_probe не разберёт
    with pytest.raises(InputInvalid):
        validate_input(_big_file(tmp_path))


def test_zero_dimensions_invalid(tmp_path, monkeypatch):
    _mock_ffprobe(monkeypatch, _Proc(0, stdout="0\n0\n0\n"))
    with pytest.raises(InputInvalid):
        validate_input(_big_file(tmp_path))


# ------------------------------------------------------------ валидный файл проходит

def test_valid_file_returns_dimensions(tmp_path, monkeypatch):
    _mock_ffprobe(monkeypatch, _Proc(0, stdout="1920\n1080\n42.5\n"))
    assert validate_input(_big_file(tmp_path)) == (1920, 1080, 42.5)


# ------------------------------------------------------------ реальный ffprobe (integration)

@pytest.mark.integration
def test_real_ffprobe_rejects_garbage(tmp_path):
    """С настоящим ffprobe: >1 МБ мусора (не видео) → InputInvalid (Invalid data)."""
    import shutil
    if shutil.which("ffprobe") is None:
        pytest.skip("нет ffprobe")
    garbage = tmp_path / "garbage.mp4"
    garbage.write_bytes(b"not a video " * 100_000)     # ~1.2 МБ мусора
    with pytest.raises(InputInvalid):
        validate_input(garbage)
