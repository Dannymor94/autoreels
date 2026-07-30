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
