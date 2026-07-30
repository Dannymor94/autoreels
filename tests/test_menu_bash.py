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


def test_menu_transcribe_empty_input_cancels():
    r = _run_menu("6\n\n0\n")
    assert "отменено" in (r.stdout + r.stderr)
