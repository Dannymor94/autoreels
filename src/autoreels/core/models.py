"""Pydantic-схема манифеста — ЕДИНСТВЕННЫЙ контракт между тирами ОБЛАКО/ЛОКАЛЬ.

Любое изменение контракта между тирами — только здесь.

Несущие решения схемы (по указанию владельца проекта):
- **Двухуровневость.** Профиль сетапа (`crop`/`scale`/`frame`) живёт на уровне `Manifest`
  (поле `setup`), а не дублируется в каждом `Reel`. Один сетап = один кроп на все клипы;
  `Reel` наследует прямоугольник из `manifest.setup`, копии не хранит.
- **Word-level субтитры.** `Reel.subtitles` несёт `Word{word,t0,t1}` — сырой word-level,
  переживающий R0→R1→R3. Готовый текст/разбивку на строки схема НЕ хранит: группировку
  2–4 слова делает `local/subtitles.py` на R3, не модель.
- **Two-phase в типах.** `status` (ProjectStatus) и `run_key` (ключ идемпотентности)
  заложены сразу, даже если M0 при auto-approve их почти не двигает.
- **Пустой массив валиден.** `reels`/`subtitles` — обычный list с дефолтом []; никаких
  min_items / валидаторов непустоты («хороших моментов нет» — норма, не ошибка).
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ProjectStatus(str, Enum):
    """Статус прогона. Граница Phase 1 / Phase 2 — `awaiting_review` → `approved`.

    Phase 1 (выбор+нарезка) гонит автоматически до `awaiting_review`. Phase 2 (финальный
    рендер+выдача) — только по approve. В MVP-0 переход auto-approve, но граница в типах.
    """

    pending = "pending"
    awaiting_review = "awaiting_review"
    approved = "approved"
    done = "done"
    failed = "failed"


class Crop(BaseModel):
    """Прямоугольник кропа в пикселях исходного кадра (ffmpeg crop=w:h:x:y)."""

    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)


class SetupProfile(BaseModel):
    """Профиль сетапа — калибруется один раз. Уровень манифеста, не клипа.

    `frame` — разрешение исходного кадра, под которое откалиброван кроп (нужно для проверки
    «кроп в границах кадра» в core/config.py). `scale` — целевое вертикальное разрешение.
    """

    model_config = ConfigDict(extra="forbid")

    setup_id: str
    crop: Crop
    scale: list[int]
    frame: list[int]


class Word(BaseModel):
    """Word-level субтитр: слово + его границы во времени. Переживает R0→R1→R3."""

    model_config = ConfigDict(extra="forbid")

    word: str
    t0: float
    t1: float


class Transcript(BaseModel):
    """Word-level транскрипт аудио (выход cloud/transcribe.py).

    Внутренний контракт облачного тира (transcribe → compress → select), кэшируется по
    хэшу аудио. Слова — та же форма `Word{word,t0,t1}`, что переживает до субтитров R3.
    Пустой `words` валиден (тишина — не ошибка).
    """

    model_config = ConfigDict(extra="forbid")

    language: str
    words: list[Word] = Field(default_factory=list)


class Reel(BaseModel):
    """Один кандидат-клип. Без crop/scale — наследует их из `manifest.setup`."""

    model_config = ConfigDict(extra="forbid")

    id: str
    start: float
    end: float
    score: int = Field(ge=0, le=100)
    hook: str
    title: str
    description: str
    reason: str = ""
    topic: str = ""
    # Чек-флаги (too_long/too_short/no_hook/cut_midword) ставит детерминированный код.
    flags: list[str] = Field(default_factory=list)
    # Сырой word-level. Группировку в строки делает R3 (local/subtitles.py), не схема.
    subtitles: list[Word] = Field(default_factory=list)


class Manifest(BaseModel):
    """Лёгкий JSON-план — единственный мост ОБЛАКО→ЛОКАЛЬ. Видео сюда не попадает."""

    model_config = ConfigDict(extra="forbid")

    source: str
    duration_preset: str
    setup: SetupProfile
    # Ключ идемпотентности = хэш(source + preset + версия рубрики). Ставит state.py.
    run_key: str
    status: ProjectStatus = ProjectStatus.pending
    # Пустой список валиден: «хороших моментов нет» — ожидаемый исход, не ошибка.
    reels: list[Reel] = Field(default_factory=list)
