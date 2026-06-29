"""Архивация обработанного входа: inputs/ → inputs-archive/ ПОСЛЕ полного успеха (batch).

Локальный тир, машинно-локальная операция (видео между тирами не ходит). Машины
независимы: у Mac своя inputs/+inputs-archive/, у системника свои. Архивация на одной
машине не мешает другой брать своё видео из своей inputs/ по sha (render смотрит в
inputs/, не в архив).

Контракт `archive_input`: после успеха видео гарантированно в архиве и НЕ в inputs/
(дренаж). Идемпотентно — повторный batch не падает:
- архива ещё нет / имени нет → move (ARCHIVED);
- то же имя И то же содержимое уже в архиве → дубль из inputs/ убрать, архив не трогать
  (SKIPPED);
- то же имя, но ДРУГОЕ содержимое → ArchiveError, ничего не двигаем (не теряем данные
  молчаливой перезаписью).
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from autoreels.core import state


class ArchiveError(Exception):
    """Архивация невозможна без потери данных (в архиве тёзка с другим содержимым)."""


@dataclass(frozen=True)
class ArchiveResult:
    status: str          # "archived" | "skipped"
    dest: Path


def is_archived(video: str | Path, archive_dir: str | Path) -> bool:
    """Видео уже в архиве? True только при совпадении имени И sha256 (контентная идентичность).

    Используется batch'ем как pre-skip ДО обработки (не жечь Groq на уже обработанном)."""
    video = Path(video)
    target = Path(archive_dir) / video.name
    if not target.is_file():
        return False
    return state.file_sha256(target) == state.file_sha256(video)


def archive_input(video: str | Path, archive_dir: str | Path) -> ArchiveResult:
    """Переместить видео в архив после успеха. Идемпотентно (см. модульный docstring)."""
    video = Path(video)
    archive_dir = Path(archive_dir)
    target = archive_dir / video.name

    if target.is_file():
        if state.file_sha256(target) == state.file_sha256(video):
            video.unlink()                       # дубль идентичен архиву → дренируем inputs/
            return ArchiveResult(status="skipped", dest=target)
        raise ArchiveError(
            f"в архиве уже есть {video.name} с ДРУГИМ содержимым "
            f"({archive_dir}) — не перезаписываю, чтобы не потерять данные"
        )

    archive_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(video), str(target))
    return ArchiveResult(status="archived", dest=target)
