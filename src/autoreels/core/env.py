"""Устойчивое чтение .env + отчёт для `doctor`.

Windows постоянно подкидывает грабли с .env, из-за которых провайдер молча отвечает 401:
- CRLF: значение приходит как "gsk_...\r" — невидимый \r ломает Authorization-заголовок;
- кавычки: `KEY="gsk_..."` — python-dotenv их снимает не всегда, ключ уезжает в кавычках;
- .env.txt: проводник прячет расширения, файл сохраняется как .env.txt и не читается;
- .env ищется только от cwd, а команда стартует из произвольной папки (после autoload arl).

Здесь один устойчивый парсер: чистит \r\n/пробелы/кавычки, ищет .env от КОРНЯ проекта,
замечает .env.txt, отдаёт EnvReport для команды `doctor` и внятную ошибку при пустом ключе.
Секреты наружу не текут: EnvReport хранит значения, но doctor печатает только префикс.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Ключи провайдеров, которые нас интересуют (для отчёта doctor и preflight run).
API_KEY_NAMES = ("GROQ_API_KEY", "OPENROUTER_API_KEY")


class MissingKeyError(Exception):
    """Нужный ключ не найден/пустой после очистки. CLI ловит и печатает внятное сообщение
    с путём .env и подсказкой `arl doctor`, а не голый traceback или 401 из глубины."""


@dataclass
class EnvReport:
    """Что удалось выяснить про .env (для doctor и диагностики)."""
    path: Path | None = None                       # откуда прочитан .env (абсолютный) или None
    dotenv_txt: Path | None = None                 # найденный .env.txt (Windows прячет .ext)
    file_keys: dict[str, str] = field(default_factory=dict)   # ключ→очищенное значение из файла
    empty_keys: list[str] = field(default_factory=list)       # в файле есть, но пусто после чистки
    searched: list[Path] = field(default_factory=list)        # где искали .env (для сообщения)


def _clean_value(raw: str) -> str:
    """Очистить значение из .env: убрать \r\n/пробелы по краям и одну пару кавычек.

    Два strip() (до и после снятия кавычек) неслучайны: покрывают и `gsk\r`, и `"gsk\r"`
    (CR внутри кавычек). str.strip() убирает \r, \n, пробелы и табы."""
    v = raw.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        v = v[1:-1]
    return v.strip()


def _parse_dotenv(text: str) -> tuple[dict[str, str], list[str]]:
    """Разобрать текст .env → (ключи→очищенные значения, список пустых-после-очистки ключей).

    Поддержка: комментарии (#), пустые строки, префикс `export`. Значение чистится
    _clean_value. Пустое значение после очистки → ключ в empty (понятная ошибка вместо 401)."""
    keys: dict[str, str] = {}
    empty: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export ") or s.startswith("export\t"):
            s = s[len("export"):].lstrip()
        if "=" not in s:
            continue
        name, _, value = s.partition("=")
        name = name.strip()
        if not name:
            continue
        cleaned = _clean_value(value)
        keys[name] = cleaned
        if cleaned == "":
            empty.append(name)
    return keys, empty


def _search_bases(root: str | Path | None, cwd: str | Path | None) -> list[Path]:
    """Порядок поиска .env: корень проекта (если задан), затем cwd. Дедуп с сохранением порядка.

    cwd берётся только если задан явно ИЛИ корень не задан — иначе поиск от корня «протекал»
    бы в текущий каталог и подхватывал чужой .env (в проде корень авторитетен)."""
    bases: list[Path] = []
    if root is not None:
        bases.append(Path(root))
    if cwd is not None:
        bases.append(Path(cwd))
    elif root is None:
        bases.append(Path.cwd())
    out: list[Path] = []
    for p in bases:
        if p not in out:
            out.append(p)
    return out


def scan_env(root: str | Path | None = None, *, cwd: str | Path | None = None) -> EnvReport:
    """Найти и разобрать .env БЕЗ изменения окружения (для doctor и load_env).

    Ищет .env от корня проекта, потом от cwd. Если .env нет, но есть .env.txt — фиксирует его
    в отчёте (doctor подскажет переименовать). Значения возвращаются уже очищенными."""
    report = EnvReport()
    for base in _search_bases(root, cwd):
        cand = base / ".env"
        report.searched.append(cand)
        if report.path is None and cand.is_file():
            report.path = cand.resolve()
        if report.dotenv_txt is None:
            txt = base / ".env.txt"
            if txt.is_file():
                report.dotenv_txt = txt.resolve()
    if report.path is not None:
        try:
            text = report.path.read_text(encoding="utf-8-sig")   # utf-8-sig снимает BOM
        except OSError:
            text = ""
        report.file_keys, report.empty_keys = _parse_dotenv(text)
    return report


def load_env(
    root: str | Path | None = None,
    *,
    cwd: str | Path | None = None,
    environ: dict | None = None,
) -> EnvReport:
    """Подхватить .env в окружение устойчиво (закрывает ручной `source .env`).

    Не переопределяет уже заданные НЕпустые переменные окружения (как python-dotenv), но
    заполняет отсутствующие/пустые очищенными значениями из файла. Возвращает EnvReport."""
    environ = environ if environ is not None else os.environ
    report = scan_env(root, cwd=cwd)
    for name, value in report.file_keys.items():
        if value == "":
            continue
        existing = (environ.get(name) or "").strip()
        if not existing:                     # не затираем реально заданный ключ окружения
            environ[name] = value
    return report


def clean_key(name: str, *, environ: dict | None = None) -> str:
    """Значение ключа из окружения, очищенное от \r\n/пробелов (защита от CRLF из реального env)."""
    environ = environ if environ is not None else os.environ
    return (environ.get(name) or "").strip().strip("\r").strip()


def key_prefix(value: str, *, keep: int = 8) -> str:
    """Безопасный для показа префикс ключа: `gsk_abcd…`. Секрет целиком НИКОГДА не печатаем."""
    v = (value or "").strip()
    if not v:
        return ""
    return v if len(v) <= keep else f"{v[:keep]}…"


def require_key(name: str, report: EnvReport | None = None, *, environ: dict | None = None) -> str:
    """Вернуть непустой ключ или бросить MissingKeyError с путём .env и подсказкой `arl doctor`.

    Закрывает «run стартует без ключа → traceback/401 из глубины»: ошибка ранняя и внятная."""
    value = clean_key(name, environ=environ)
    if value:
        return value
    where = str(report.path) if report is not None and report.path else "не найден"
    hint = ""
    if report is not None and report.dotenv_txt is not None and report.path is None:
        hint = f" Найден {report.dotenv_txt.name} — переименуй в .env."
    raise MissingKeyError(
        f"{name} не найден (.env: {where}).{hint} Запусти `arl doctor` — покажет, где .env, "
        f"какие ключи видны и доступны ли провайдеры."
    )
