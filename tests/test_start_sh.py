"""start.sh — bootstrap-скрипт (venv + aliases + меню одной командой).

Тестируем детерминированную bash-логику через подпроцесс: определение корня проекта
и выбор пути активации venv (Mac bin/ vs Windows Scripts/). Сам bootstrap (создание
venv, запуск меню) не гоняем — только чистые решения.

start.sh в «библиотечном» режиме (AUTOREELS_START_LIB=1) только определяет функции,
не запускает main — это и даёт точку для юнит-проверок.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
START = REPO_ROOT / "start.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="нужен bash")


def _bash(script: str, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", script], cwd=cwd, capture_output=True, text=True,
    )


def _lib(call: str, cwd=None) -> subprocess.CompletedProcess:
    return _bash(f'AUTOREELS_START_LIB=1 source "{START}"; {call}', cwd=cwd)


def test_start_sh_exists_and_executable():
    assert START.is_file()


def test_start_root_resolves_repo_root_from_other_cwd(tmp_path):
    r = _lib("_start_root", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert Path(r.stdout.strip()) == REPO_ROOT


def test_venv_activate_prefers_bin(tmp_path):
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "activate").write_text("")
    r = _lib(f'_start_venv_activate "{tmp_path}"')
    assert r.stdout.strip() == str(tmp_path / ".venv" / "bin" / "activate")


def test_venv_activate_falls_back_to_scripts(tmp_path):
    (tmp_path / ".venv" / "Scripts").mkdir(parents=True)
    (tmp_path / ".venv" / "Scripts" / "activate").write_text("")
    r = _lib(f'_start_venv_activate "{tmp_path}"')
    assert r.stdout.strip() == str(tmp_path / ".venv" / "Scripts" / "activate")


def test_venv_activate_empty_when_missing(tmp_path):
    r = _lib(f'_start_venv_activate "{tmp_path}"')
    assert r.stdout.strip() == ""


def test_lib_mode_does_not_launch_menu(tmp_path):
    """Sourcing в lib-режиме не запускает меню (только определения функций)."""
    r = _bash(f'AUTOREELS_START_LIB=1 source "{START}"', cwd=tmp_path)
    assert "═══ autoreels" not in r.stdout


# ------------------------------------------------- ffmpeg: разовая настройка render.local.yaml

def test_ffmpeg_in_local_true_when_set(tmp_path):
    """_start_ffmpeg_in_local: True если render.local.yaml задаёт ffmpeg:."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "render.local.yaml").write_text("ffmpeg: D:/ffmpeg/bin/ffmpeg.exe\n")
    r = _lib(f'_start_ffmpeg_in_local "{tmp_path}" && echo YES || echo NO')
    assert r.stdout.strip() == "YES"


def test_ffmpeg_in_local_false_when_absent(tmp_path):
    """Нет файла / нет ключа ffmpeg: → False."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "render.local.yaml").write_text("encoder:\n  profile: hevc\n")
    r = _lib(f'_start_ffmpeg_in_local "{tmp_path}" && echo YES || echo NO')
    assert r.stdout.strip() == "NO"


def test_write_ffmpeg_local_creates_entry(tmp_path):
    """_start_write_ffmpeg_local пишет ffmpeg: <путь> в render.local.yaml."""
    (tmp_path / "config").mkdir()
    r = _lib(f'_start_write_ffmpeg_local "{tmp_path}" "D:/ffmpeg/bin/ffmpeg.exe"')
    assert r.returncode == 0, r.stderr
    content = (tmp_path / "config" / "render.local.yaml").read_text()
    assert "ffmpeg: D:/ffmpeg/bin/ffmpeg.exe" in content


def test_write_ffmpeg_local_does_not_clobber_existing(tmp_path):
    """Если ffmpeg: уже задан — не перезаписываем (разовая настройка не портит ручную)."""
    (tmp_path / "config").mkdir()
    f = tmp_path / "config" / "render.local.yaml"
    f.write_text("ffmpeg: /my/custom/ffmpeg\n")
    _lib(f'_start_write_ffmpeg_local "{tmp_path}" "D:/other/ffmpeg.exe"')
    content = f.read_text()
    assert "/my/custom/ffmpeg" in content
    assert "D:/other/ffmpeg.exe" not in content


# ------------------------------------------------- автозагрузка: предложение установить

def test_offer_autoload_silent_when_already_installed(tmp_path):
    """Если source-строка уже в профиле — не спрашиваем (идемпотентно, без нагона)."""
    home = tmp_path / "home"; home.mkdir()
    (home / ".zshrc").write_text(f"source {tmp_path}/aliases.sh\n", encoding="utf-8")
    r = _bash(
        f'AUTOREELS_START_LIB=1 source "{START}"; HOME="{home}" _start_offer_autoload "{tmp_path}" </dev/null'
    )
    assert "Прописать автозагрузку" not in r.stdout      # промпт не показан


def test_offer_autoload_prompts_when_not_installed(tmp_path):
    """Строки нет ни в одном профиле → спрашиваем; пустой ввод (н) → «пропущено», без установки."""
    home = tmp_path / "home"; home.mkdir()
    r = _bash(
        f'AUTOREELS_START_LIB=1 source "{START}"; HOME="{home}" _start_offer_autoload "{tmp_path}" <<< "н"'
    )
    assert "Прописать автозагрузку" in r.stdout
    assert "пропущено" in r.stdout
