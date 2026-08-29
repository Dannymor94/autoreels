"""Устойчивое чтение .env (core/env.py) — Windows-грабли: CRLF, кавычки, .env.txt, корень.

Инварианты, которые тесты защищают:
- значение чистится от \r/\n/пробелов и одной пары кавычек (CRLF → 401 больше не воспроизводится);
- .env ищется от корня проекта, а не только от cwd;
- .env.txt (Windows прячет расширения) замечается и фиксируется в отчёте;
- ключ есть, но пуст после очистки → понятная MissingKeyError, не молчаливый 401;
- секрет целиком не печатается — только префикс.
"""
from pathlib import Path

import pytest

from autoreels.core.env import (
    MissingKeyError,
    clean_key,
    key_prefix,
    load_env,
    require_key,
    scan_env,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))          # байты: сохраняем \r как есть (CRLF-тест)


# ------------------------------------------------------------------- очистка значений

def test_crlf_value_read_without_trailing_cr(tmp_path):
    """CRLF в .env: ключ читается без \r (иначе Authorization-заголовок ломается → 401)."""
    _write(tmp_path / ".env", "GROQ_API_KEY=gsk_abc123\r\nOPENROUTER_API_KEY=or_def\r\n")
    env: dict = {}
    load_env(tmp_path, environ=env)
    assert env["GROQ_API_KEY"] == "gsk_abc123"       # без хвостового \r
    assert "\r" not in env["GROQ_API_KEY"]
    assert env["OPENROUTER_API_KEY"] == "or_def"


def test_quotes_stripped(tmp_path):
    """Кавычки вокруг значения снимаются (и двойные, и одинарные)."""
    _write(tmp_path / ".env", 'GROQ_API_KEY="gsk_abc"\nOPENROUTER_API_KEY=\'or_def\'\n')
    env: dict = {}
    load_env(tmp_path, environ=env)
    assert env["GROQ_API_KEY"] == "gsk_abc"
    assert env["OPENROUTER_API_KEY"] == "or_def"


def test_quoted_value_with_trailing_crlf(tmp_path):
    """Кавычки + CRLF в конце строки (`"gsk"\\r\\n`) → чистое значение без \\r и кавычек."""
    _write(tmp_path / ".env", 'GROQ_API_KEY="gsk_abc"\r\n')
    env: dict = {}
    load_env(tmp_path, environ=env)
    assert env["GROQ_API_KEY"] == "gsk_abc"


def test_export_prefix_and_comments_and_blanks(tmp_path):
    """Поддержка `export KEY=...`, комментариев (#) и пустых строк."""
    _write(tmp_path / ".env", "# comment\n\nexport GROQ_API_KEY=gsk_x\n")
    env: dict = {}
    load_env(tmp_path, environ=env)
    assert env["GROQ_API_KEY"] == "gsk_x"


# ------------------------------------------------------------------- поиск файла

def test_env_found_from_project_root_not_cwd(tmp_path):
    """.env ищется от КОРНЯ проекта, даже если cwd — другая папка."""
    root = tmp_path / "proj"
    _write(root / ".env", "GROQ_API_KEY=gsk_root\n")
    other = tmp_path / "elsewhere"
    other.mkdir()
    env: dict = {}
    report = load_env(root, cwd=other, environ=env)
    assert report.path == (root / ".env").resolve()
    assert env["GROQ_API_KEY"] == "gsk_root"


def test_dotenv_txt_detected_when_no_env(tmp_path):
    """Есть .env.txt, но нет .env → фиксируем .env.txt в отчёте (doctor подскажет переименовать)."""
    _write(tmp_path / ".env.txt", "GROQ_API_KEY=gsk_x\n")
    report = scan_env(tmp_path)
    assert report.path is None
    assert report.dotenv_txt == (tmp_path / ".env.txt").resolve()


def test_no_env_file_returns_empty_report(tmp_path):
    """Нет ни .env, ни .env.txt → пустой отчёт, без падения."""
    report = scan_env(tmp_path)
    assert report.path is None and report.dotenv_txt is None and report.file_keys == {}


# ------------------------------------------------------------------- не затираем реальный env

def test_existing_env_not_overridden(tmp_path):
    """Реально заданный НЕпустой ключ окружения не затирается значением из файла."""
    _write(tmp_path / ".env", "GROQ_API_KEY=gsk_file\n")
    env = {"GROQ_API_KEY": "gsk_real"}
    load_env(tmp_path, environ=env)
    assert env["GROQ_API_KEY"] == "gsk_real"        # из окружения, не из файла


def test_empty_existing_env_filled_from_file(tmp_path):
    """Пустой ключ окружения заполняется из файла (пустой = как отсутствующий)."""
    _write(tmp_path / ".env", "GROQ_API_KEY=gsk_file\n")
    env = {"GROQ_API_KEY": "   "}
    load_env(tmp_path, environ=env)
    assert env["GROQ_API_KEY"] == "gsk_file"


# ------------------------------------------------------------------- пустой ключ → внятная ошибка

def test_empty_key_reported_and_require_raises(tmp_path):
    """Ключ есть, но пуст после очистки → в empty_keys и require_key бросает MissingKeyError."""
    _write(tmp_path / ".env", 'GROQ_API_KEY=""\n')
    env: dict = {}
    report = load_env(tmp_path, environ=env)
    assert "GROQ_API_KEY" in report.empty_keys
    with pytest.raises(MissingKeyError) as e:
        require_key("GROQ_API_KEY", report, environ=env)
    assert "GROQ_API_KEY" in str(e.value) and "doctor" in str(e.value)


def test_require_key_missing_mentions_env_path(tmp_path):
    """Нет ключа → сообщение с путём .env и подсказкой doctor (а не traceback/401)."""
    _write(tmp_path / ".env", "OPENROUTER_API_KEY=or_x\n")
    env: dict = {}
    report = load_env(tmp_path, environ=env)
    with pytest.raises(MissingKeyError) as e:
        require_key("GROQ_API_KEY", report, environ=env)
    assert str((tmp_path / ".env").resolve()) in str(e.value)


def test_require_key_hint_when_only_dotenv_txt(tmp_path):
    """Нет .env, но есть .env.txt → require_key подсказывает переименовать."""
    _write(tmp_path / ".env.txt", "GROQ_API_KEY=gsk_x\n")
    env: dict = {}
    report = load_env(tmp_path, environ=env)
    with pytest.raises(MissingKeyError) as e:
        require_key("GROQ_API_KEY", report, environ=env)
    assert ".env.txt" in str(e.value) and "переименуй" in str(e.value).lower()


def test_require_key_returns_cleaned_value(tmp_path):
    """Есть ключ → require_key возвращает очищенное значение."""
    _write(tmp_path / ".env", "GROQ_API_KEY=gsk_ok\r\n")
    env: dict = {}
    report = load_env(tmp_path, environ=env)
    assert require_key("GROQ_API_KEY", report, environ=env) == "gsk_ok"


# ------------------------------------------------------------------- показ префикса (без утечки)

def test_key_prefix_masks_secret():
    assert key_prefix("gsk_abcdef1234567890") == "gsk_abcd…"
    assert key_prefix("") == ""
    assert key_prefix("short") == "short"           # короткий — не маскируем (нечего прятать)


def test_clean_key_strips_cr_from_real_env():
    """clean_key чистит \r и из реального окружения (не только из файла)."""
    assert clean_key("GROQ_API_KEY", environ={"GROQ_API_KEY": "gsk_x\r"}) == "gsk_x"
