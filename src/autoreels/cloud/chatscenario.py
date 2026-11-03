"""M207: the scenarist through any chat — no paid API.

Owner (2026-11-02): «готовый экспорт с заготовленным промтом и инструкцией для чата: я беру текстовый файл, закидываю в
чат, чат работает сценаристом, я скидываю ответ обратно — и по нему идёт сборка». The task is the very request the API
scenarist gets (cloud/scenario.py: the rules + the numbered talk + the owner's examples); the answer goes through the same
parse and the same checks. Files, exchange/<source>.*:
  scenario.md          — the task: a short instruction for the owner, then everything for the chat;
  scenario.answer.txt  — the chat's answer, saved by the owner (only the reel lines; markdown and ``` are tolerated);
  scenario.fix.md      — `arl scenario-check`: the lines the code did not take, with the reason — a message for the chat.
The task carries the fingerprint of the numbered talk: an answer to another talk (the transcript changed) is not used —
a new task is written. The same answer file always gives the same reels."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

EXCHANGE = "exchange"
MODEL_ID = "chat"
_KEY = re.compile(r"<!-- autoreels: сценарист через чат; источник (\S+); текст ([0-9a-f]{16}) -->")


class ChatScenarioPending(Exception):
    """The chat has not answered yet (or the answer belongs to another talk): the task is written, the run stops."""


def paths(root: Path, stem: str) -> tuple[Path, Path, Path]:
    d = Path(root) / EXCHANGE
    return d / f"{stem}.scenario.md", d / f"{stem}.scenario.answer.txt", d / f"{stem}.scenario.fix.md"


def text_key(numbered: str) -> str:
    """The fingerprint of the numbered talk — what the answer's sentence numbers refer to."""
    return hashlib.sha256(numbered.encode("utf-8")).hexdigest()[:16]


def task_key(task_text: str) -> tuple[str, str] | None:
    m = _KEY.search(task_text or "")
    return (m.group(1), m.group(2)) if m else None


def render_task(stem: str, key: str, system: str, user: str) -> str:
    md, ans, fix = (f"exchange/{stem}.scenario.md", f"exchange/{stem}.scenario.answer.txt",
                    f"exchange/{stem}.scenario.fix.md")
    return (f"<!-- autoreels: сценарист через чат; источник {stem}; текст {key} -->\n"
            f"# Сценарист через чат — {stem}\n\n"
            "**Владельцу** (эта часть чату не нужна):\n"
            f"1. Отдайте чату всё ниже линии «ЗАДАНИЕ» — вставкой или приложив этот файл ({md}).\n"
            f"2. Ответ чата сохраните в `{ans}` — только строки роликов (обёртку ``` можно оставить).\n"
            f"3. Проверка: `arl scenario-check {stem}` — что принято, что нет и почему; отклонённое — в `{fix}`, "
            "его можно отдать тому же чату.\n"
            f"4. Сборка: `arl auto {stem} --mode scenario --scenario-llm chat` — дальше обычный путь.\n\n"
            "======== ЗАДАНИЕ ДЛЯ ЧАТА ========\n\n"
            "Ты — сценарист коротких вертикальных роликов. Ниже правила, затем пронумерованный текст видео.\n\n"
            f"{system.strip()}\n\n---\n\n{user.strip()}\n\n---\n\n"
            "Ответь только строками роликов в формате из правил — по одной строке на ролик, без пояснений.\n")


def read_answer(path: Path) -> str | None:
    """The saved answer, or None when there is none (or it is empty)."""
    p = Path(path)
    if not p.is_file():
        return None
    raw = p.read_text(encoding="utf-8", errors="replace")
    return raw if raw.strip() else None


def render_fix(stem: str, taken: int, refused: list[tuple[str, str]]) -> str:
    """A message for the same chat: which lines the code did not take and why."""
    if not refused:
        return (f"# {stem}: все строки приняты ({taken})\n\nИсправлять нечего — `arl auto {stem} --mode scenario "
                "--scenario-llm chat`.\n")
    lines = "\n".join(f"- {why}" + (f": `{pieces}`" if pieces else "") for pieces, why in refused)
    return (f"# {stem}: принято {taken}, не принято {len(refused)}\n\n"
            "Сообщение для чата (скопируйте целиком):\n\n---\n\n"
            "Эти строки не прошли проверку — исправь их по тем же правилам и пришли заново ВСЕ строки роликов "
            "(и принятые, и исправленные), по одной на ролик, без пояснений:\n\n"
            f"{lines}\n")
