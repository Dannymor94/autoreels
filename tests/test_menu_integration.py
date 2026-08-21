"""Интеграция интерактивного меню — сквозная проверка на ДВЕ платформы.

Меню живёт в двух местах: отрисовка + разбор в Python (`autoreels menu` / `_menu_action`),
цикл выбора в bash (`_ar_menu` в aliases.sh). Юнит-тесты Python не достают до bash-диспетчера,
поэтому пункт легко добавить в отрисовку, забыв про диспетчер (или наоборот) — на Windows это
и проявляется как «пункт ничего не делает». Эти тесты замыкают цепочку:

    пункт меню (цифра) → --resolve отдаёт токен → токен есть в bash-диспетчере → токен
    вызывает РЕАЛЬНУЮ CLI-команду (существует в argparse).

Параметризация по ВСЕМ пунктам: новый пункт нельзя добавить в отрисовку, не добавив ветку в
диспетчер и не связав с существующей командой — тест упадёт.
"""
import argparse
import re
from pathlib import Path

import pytest

import autoreels.__main__ as cli

REPO_ROOT = Path(__file__).resolve().parents[1]
ALIASES = (REPO_ROOT / "aliases.sh").read_text(encoding="utf-8")


# --------------------------------------------------------------- разбор aliases.sh (bash)

def _func_body(text: str, name: str) -> str:
    """Тело shell-функции `name` — от `name() {` до строки `}` в начале строки."""
    m = re.search(rf"^{re.escape(name)}\(\) \{{\s*$", text, re.M)
    assert m, f"функция {name}() не найдена в aliases.sh"
    rest = text[m.end():]
    end = re.search(r"^\}", rest, re.M)
    return rest[: end.start()]


_MENU_BODY = _func_body(ALIASES, "_ar_menu")
_ARL_BODY = _func_body(ALIASES, "arl")


def _outer_case_arms(body: str, indent: int) -> list[re.Match]:
    """Ветки внешнего case на заданном отступе (внутренние case — на большем отступе, не ловятся)."""
    pad = " " * indent
    return list(re.finditer(rf"^{pad}([a-z\"|]+|\*)\)", body, re.M))


def _menu_case_tokens() -> set[str]:
    """Токены веток внешнего `case \"$_action\"` в _ar_menu (отступ 12), без catch-all `*`."""
    return {m.group(1) for m in _outer_case_arms(_MENU_BODY, 12) if m.group(1) != "*"}


def _menu_handlers() -> dict[str, str]:
    """token → текст его ветки-обработчика в _ar_menu (до следующей ветки)."""
    arms = _outer_case_arms(_MENU_BODY, 12)
    out: dict[str, str] = {}
    for i, m in enumerate(arms):
        end = arms[i + 1].start() if i + 1 < len(arms) else len(_MENU_BODY)
        out[m.group(1)] = _MENU_BODY[m.end(): end]
    return out


def _arl_short_map() -> dict[str, str]:
    """Короткая команда arl → полная CLI-подкоманда (из диспетчера `arl()`): go→run, r→render, …"""
    arms = _outer_case_arms(_ARL_BODY, 8)
    m: dict[str, str] = {}
    for i, a in enumerate(arms):
        end = arms[i + 1].start() if i + 1 < len(arms) else len(_ARL_BODY)
        body = _ARL_BODY[a.end(): end]
        cm = re.search(r"_ar_cli ([a-z][a-z-]+)", body)
        if cm:
            for tok in a.group(1).split("|"):
                tok = tok.strip('"')
                if tok:
                    m[tok] = cm.group(1)
    return m


def _argparse_subcommands() -> set[str]:
    parser = cli._build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return set(sub.choices)


_ARL_SHORT = _arl_short_map()
_SUBCOMMANDS = _argparse_subcommands()
_PY_TOKENS = [action for (_num, action, _lbl, _hint) in cli._MENU_ITEMS]


def _cli_command(name: str) -> str:
    """Резолв команды из bash-обработчика в CLI-подкоманду: короткая arl → полная, иначе как есть."""
    return _ARL_SHORT.get(name, name)


# --------------------------------------------------------------- тесты

def test_python_and_bash_menu_tokens_match_exactly():
    """Множество отрисованных пунктов (Python) == множество веток диспетчера (bash). Ловит и
    «нарисован, но не диспетчеризован», и «ветка-сирота без пункта»."""
    py = set(_PY_TOKENS)
    bash = _menu_case_tokens()
    missing_in_bash = py - bash
    orphan_in_bash = bash - py
    assert not missing_in_bash, f"пункты без ветки в _ar_menu (aliases.sh): {missing_in_bash}"
    assert not orphan_in_bash, f"ветки в _ar_menu без пункта меню: {orphan_in_bash}"


@pytest.mark.parametrize("num,action", [(n, a) for (n, a, _l, _h) in cli._MENU_ITEMS])
def test_menu_digit_resolves_to_its_token(num, action):
    """Цифра пункта → --resolve отдаёт ровно его action-токен (отрисовка ↔ разбор согласованы)."""
    assert cli._menu_action(num) == action


@pytest.mark.parametrize("token", [t for t in _PY_TOKENS if t != "quit"])
def test_token_has_dispatcher_case(token):
    """Каждый пункт (кроме quit) имеет ветку в bash-диспетчере _ar_menu."""
    assert token in _menu_case_tokens(), f"пункт «{token}» нарисован, но нет ветки в _ar_menu"


@pytest.mark.parametrize("token", [t for t in _PY_TOKENS if t != "quit"])
def test_token_handler_invokes_real_cli_command(token):
    """Ветка обработчика вызывает хотя бы одну РЕАЛЬНУЮ CLI-подкоманду (существует в argparse).

    Ловит опечатку/переименование: пункт диспетчеризован, но зовёт несуществующую команду."""
    handler = _menu_handlers()[token]
    invoked = re.findall(r"\barl ([a-z][a-z-]*)", handler) + \
        re.findall(r"_ar_cli ([a-z][a-z-]+)", handler)
    resolved = {_cli_command(c) for c in invoked}
    real = resolved & _SUBCOMMANDS
    assert real, (f"пункт «{token}»: обработчик не вызывает ни одной существующей CLI-команды "
                  f"(вызвано: {sorted(invoked)} → {sorted(resolved)}; есть: {sorted(_SUBCOMMANDS)})")


def test_all_ar_cli_subcommands_in_aliases_are_real():
    """Любая `_ar_cli <подкоманда>` в aliases.sh существует в argparse (нет мёртвых вызовов)."""
    used = set(re.findall(r"_ar_cli ([a-z][a-z-]+)", ALIASES))
    unknown = used - _SUBCOMMANDS
    assert not unknown, f"в aliases.sh зовутся несуществующие CLI-команды: {unknown}"


def test_arl_short_commands_map_to_real_subcommands():
    """Короткие команды arl (go/r/s/c/rs/dc/pv/rc/t/h) резолвятся в существующие подкоманды."""
    for short, full in _ARL_SHORT.items():
        assert full in _SUBCOMMANDS, f"arl {short} → {full}: такой CLI-команды нет"


def test_resolve_capture_strips_cr_for_windows():
    """Windows-специфика: захват --resolve чистит CRLF (иначе $_action=\"token\\r\" и case не
    матчится — меню «ничего не делает» на Git Bash). Гвоздь: строка обязана резать \\r."""
    m = re.search(r"^.*menu --resolve.*$", _MENU_BODY, re.M)
    assert m, "строка захвата `menu --resolve` не найдена в _ar_menu"
    assert "tr -d" in m.group(0) and "\\r" in m.group(0), \
        f"захват --resolve не срезает CR (Windows CRLF сломает case): {m.group(0).strip()}"


def test_new_setting_items_present_both_sides():
    """Явная фиксация НОВЫХ пунктов-настроек (профиль/палитра): и в отрисовке, и в диспетчере."""
    py = set(_PY_TOKENS)
    bash = _menu_case_tokens()
    for token in ("profile", "palette", "diagnose", "resnap"):
        assert token in py, f"пункт «{token}» пропал из отрисовки _MENU_ITEMS"
        assert token in bash, f"пункт «{token}» пропал из диспетчера _ar_menu"
