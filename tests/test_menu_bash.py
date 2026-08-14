"""Интерактивные пункты меню (bash-цикл _ar_menu): промпт ввода источника и отмена.

Гоняем реальный _ar_menu через bash-подпроцесс, скармливая выбор пункта и пустой ввод.
Пустой источник → отмена (без запуска run/transcribe), возврат в меню. Распознавание
url/яндекс/путь проверяется в test_cli.py (Python-слой _classify_source/_classify_label).
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ALIASES = REPO_ROOT / "aliases.sh"
VENV_BIN = REPO_ROOT / ".venv" / "bin"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or not (VENV_BIN / "autoreels").exists(),
    reason="нужен bash и установленный autoreels в .venv",
)


def _run_menu(keys: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{VENV_BIN}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        ["bash", "-c", f'source "{ALIASES}"; _ar_menu'],
        input=keys, capture_output=True, text=True, cwd=REPO_ROOT, env=env, timeout=60,
    )


# -------------------- фолбэк CLI: прямой autoreels сломан → python -m autoreels

def test_ar_cli_falls_back_to_module_when_direct_broken(tmp_path):
    """Прямой `autoreels` не запускается (как на Windows Py3.14) → зовём python -m autoreels.

    Кладём фейковый `autoreels` (exit 1) первым в PATH — он затеняет рабочий console-script.
    Проба `autoreels --help` падает → _ar_cli переключается в module-режим. venv-`python`
    доступен (VENV_BIN в PATH), поэтому `python -m autoreels menu --resolve 3` → 'status'.
    """
    fake = tmp_path / "autoreels"
    fake.write_text("#!/usr/bin/env bash\nexit 1\n")
    fake.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{tmp_path}{os.pathsep}{VENV_BIN}{os.pathsep}{env.get('PATH', '')}"
    r = subprocess.run(
        ["bash", "-c", f'source "{ALIASES}"; _ar_cli menu --resolve 3'],
        capture_output=True, text=True, cwd=REPO_ROOT, env=env, timeout=60,
    )
    assert r.stdout.strip() == "status", (r.stdout, r.stderr)


def test_ar_cli_uses_direct_when_available():
    """Когда прямой `autoreels` работает — используется он (module-фолбэк не нужен)."""
    env = dict(os.environ)
    env["PATH"] = f"{VENV_BIN}{os.pathsep}{env.get('PATH', '')}"
    r = subprocess.run(
        ["bash", "-c", f'source "{ALIASES}"; _ar_cli menu --resolve 3; echo "mode=$_AR_CLI_MODE"'],
        capture_output=True, text=True, cwd=REPO_ROOT, env=env, timeout=60,
    )
    assert "status" in r.stdout
    assert "mode=direct" in r.stdout, (r.stdout, r.stderr)


def test_ar_menu_works_via_module_fallback(tmp_path):
    """Меню целиком работает через python -m, когда прямой autoreels сломан."""
    fake = tmp_path / "autoreels"
    fake.write_text("#!/usr/bin/env bash\nexit 1\n")
    fake.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{tmp_path}{os.pathsep}{VENV_BIN}{os.pathsep}{env.get('PATH', '')}"
    r = subprocess.run(
        ["bash", "-c", f'source "{ALIASES}"; _ar_menu'],
        input="3\n\n0\n", capture_output=True, text=True, cwd=REPO_ROOT, env=env, timeout=60,
    )
    # шапка меню отрисовалась (python -m autoreels menu отработал)
    assert "autoreels" in (r.stdout + r.stderr).lower()
    assert "inputs:" in (r.stdout + r.stderr)


def test_menu_path_item_prompts_for_source():
    """Пункт 5 после выбора спрашивает ссылку/путь."""
    r = _run_menu("5\n\n0\n")            # выбрать 5, пустой ввод, затем выход
    assert "Вставь ссылку" in (r.stdout + r.stderr)


def test_menu_path_empty_input_cancels():
    """Пустой ввод в пункте 5 → отмена, возврат в меню (run не запускается).

    Маркер «отменено» печатается в ветке пустого ввода ДО classify/run — его наличие и
    доказывает, что обработка не стартовала (иначе пошли бы этапы run: «считаю хэш…»).
    """
    r = _run_menu("5\n\n0\n")
    out = r.stdout + r.stderr
    assert "отменено" in out
    assert "считаю хэш" not in out        # конвейер run не запускался


def test_menu_transcribe_item_prompts_for_source():
    """Пункт 6 (транскрибация) тоже спрашивает источник после выбора."""
    r = _run_menu("6\n\n0\n")
    assert "транскрибировать" in (r.stdout + r.stderr).lower()


def test_menu_profile_item_prompts_and_cancels():
    """Пункт 9 показывает профили рендера и спрашивает выбор; пустой ввод → отмена (без записи)."""
    r = _run_menu("9\n\n0\n")              # выбрать 9, пустой ввод (отмена), выход
    out = r.stdout + r.stderr
    assert "Профиль рендера" in out        # промпт выбора профиля
    assert "hevc" in out and "h264" in out and "av1" in out   # опции
    assert "отменено" in out               # пустой ввод отменил, профиль не менялся


def test_menu_transcribe_empty_input_cancels():
    r = _run_menu("6\n\n0\n")
    assert "отменено" in (r.stdout + r.stderr)
