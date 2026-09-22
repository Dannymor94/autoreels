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
    # Выравнивание горизонта: поворот кадра на малый угол при наклонённой съёмке (градусы,
    # + = по часовой, как CSS-превью калибратора). Дефолт 0 — старые манифесты без поля валидны.
    # Разумный диапазон ±10° (больше — уже не «выравнивание»); ±45 — жёсткая граница от опечаток.
    # НЕ путать с rotation_applied (метаданные ориентации телефона — их autorotate уже применил).
    # Порядок в рендере: rotate → crop → scale (поворот ДО кропа: кроп берёт заполненную область).
    rotation_deg: float = Field(default=0.0, ge=-45.0, le=45.0)
    # Палитра цветокора для ЭТОГО видео (выбрана в калибраторе). None → палитра по умолчанию из
    # render.yaml. Едет в манифесте вместе с кропом (per-video override), как crop/rotation_deg.
    palette: str | None = None


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
    # Параметры, которыми получен транскрипт (для воспроизводимости и инвалидации кэша).
    # Пустые в старых кэшах, снятых до фичи — читаются без ошибки (дефолты).
    model: str = ""
    provider: str = ""
    prompt_hash: str = ""
    # Count of words removed by the prompt-leak filter across all chunks.
    prompt_leak_removed: int = 0
    # source_sha256 of the video the audio was extracted from.  "" in old transcripts
    # (created before this field was added); used to resolve transcript → manifest without
    # scanning mp3 content hashes.
    source_sha256: str = ""


class Segment(BaseModel):
    """One contiguous source window of a reel. A reel plays its segments concatenated in order.

    A single-span reel carries no segments (empty list) and is read as the one window [start, end]
    — old manifests keep working. Multi-segment reels (sentence bounds, filler removal, cold open)
    list two or more windows; `reel.start`/`reel.end` stay the overall span for range-only tools.
    """

    model_config = ConfigDict(extra="forbid")

    start: float
    end: float


class Reel(BaseModel):
    """Один кандидат-клип. Без crop/scale — наследует их из `manifest.setup`."""

    model_config = ConfigDict(extra="forbid")

    id: str
    start: float
    end: float
    # Ordered source windows played back-to-back. Empty = one contiguous window [start, end]
    # (legacy / automatic path). Non-empty = an edited reel (cut filler, sentence bounds, cold
    # open); `start`/`end` remain the overall span. Populated by the manual/edit path only.
    segments: list[Segment] = Field(default_factory=list)
    score: int = Field(ge=0, le=100)
    hook: str
    title: str
    description: str
    reason: str = ""
    topic: str = ""
    # Границы от LLM ДО snap/padding — сохраняются в run сразу после выбора. Позволяют
    # `resnap` пересчитать границы (snap→padding→trim) без повторного R0. None — старые
    # манифесты без этих полей (снятые до фичи): resnap просит один полный run.
    r0_start: float | None = None
    r0_end: float | None = None
    # Чек-флаги (too_long/too_short/no_hook/cut_midword) ставит детерминированный код.
    flags: list[str] = Field(default_factory=list)
    # Самодостаточное начало: модель судит, понятна ли первая фраза без предыдущего контекста
    # (нет висячего "поэтому"/"он"/"это" без антецедента внутри клипа). False → клип снимается
    # в select (не чиним в коде). None — старые манифесты без поля (обратная совместимость).
    self_contained_start: bool | None = None
    start_justification: str = ""
    # Ранг по score среди отобранных (1 = сильнейший). None — до ранжирования / старые манифесты.
    rank: int | None = None
    # Сырой word-level. Группировку в строки делает R3 (local/subtitles.py), не схема.
    subtitles: list[Word] = Field(default_factory=list)
    # Метрики snap: насколько end сдвинулся от r0_end и по какой причине.
    end_drift_sec: float | None = None
    end_snap_reason: str | None = None  # "sentence" | "pause" | "cap" | None
    # Метрики start-trim: насколько start сдвинулся вперёд при too_long trim.
    start_drift_sec: float | None = None
    start_snap_reason: str | None = None  # "sentence" | "pause" | "hard_cut" | "repaired_to_sentence" | None
    start_repair_sec: float | None = None  # seconds trimmed from front during dangling-start repair
    ends_on_host_turn: bool = False  # diagnostic: would have ended inside a host question without interview snap
    # Playback speed applied at render time (1.0 = normal, >1 = faster). Set by --apply.
    speed: float = 1.0
    # Human-review warnings: what a bypassed deciding stage would have flagged (dangling start,
    # long internal pause, short clip, overlap). Warn-only — nothing is dropped on the human's
    # behalf. Empty for the automatic path (those stages actually run there).
    warnings: list[str] = Field(default_factory=list)

    def effective_segments(self) -> list["Segment"]:
        """Playback windows: the explicit `segments`, or the single span [start, end] if none.

        The one place code turns a possibly-segmented reel into a concrete list of windows —
        render, subtitle remap and duration all read through here so legacy single-span reels
        and edited multi-segment reels take one path.
        """
        return list(self.segments) if self.segments else [Segment(start=self.start, end=self.end)]

    def playback_duration(self) -> float:
        """Total played length = sum of segment durations (gaps between segments are removed).

        Equals `end - start` for a single-span reel; smaller once filler is cut into gaps.
        """
        return sum(s.end - s.start for s in self.effective_segments())

    def check_segments(self, *, eps: float = 1e-3) -> None:
        """Assert the segment list is consistent with [start, end]; raise ValueError otherwise.

        The one enforced invariant so a bound moved after segmentation (dangling repair, interview
        snap, sentence bounds, padding) can never render silently: the first segment must start at
        reel.start, the last must end at reel.end, and segments must be ordered, non-overlapping and
        inside [start, end]. A single-span reel (no explicit segments) is always valid.
        """
        segs = self.segments
        if not segs:
            return
        if abs(segs[0].start - self.start) > eps:
            raise ValueError(f"reel {self.id}: segments[0].start {segs[0].start:.3f} != "
                             f"reel.start {self.start:.3f} (a bound moved after segmentation?)")
        if abs(segs[-1].end - self.end) > eps:
            raise ValueError(f"reel {self.id}: segments[-1].end {segs[-1].end:.3f} != "
                             f"reel.end {self.end:.3f}")
        prev = self.start
        for i, s in enumerate(segs):
            if s.end <= s.start:
                raise ValueError(f"reel {self.id}: segment {i} empty/reversed [{s.start:.3f}, {s.end:.3f}]")
            if s.start < prev - eps:
                raise ValueError(f"reel {self.id}: segment {i} starts {s.start:.3f} before the previous "
                                 f"segment ends {prev:.3f} (unordered or overlapping)")
            if s.start < self.start - eps or s.end > self.end + eps:
                raise ValueError(f"reel {self.id}: segment {i} [{s.start:.3f}, {s.end:.3f}] outside "
                                 f"reel [start, end] [{self.start:.3f}, {self.end:.3f}]")
            prev = s.end


class Manifest(BaseModel):
    """Лёгкий JSON-план — единственный мост ОБЛАКО→ЛОКАЛЬ. Видео сюда не попадает."""

    model_config = ConfigDict(extra="forbid")

    # `source` — провенанс с машины облака (Mac-путь/имя): подсказка и человекочитаемая
    # метка, НЕ путь для доступа к файлу на машине рендера (он там невалиден).
    source: str
    # Абсолютный путь, откуда исходник был прочитан на машине анализа (in-place — реальное
    # место файла; inputs-поток — путь в inputs/, устаревает после архивации). Подсказка для
    # быстрого resolve: render сперва пробует его, затем ищет по хэшу в inputs/ и архиве.
    # "" = легаси-манифест без поля. Идентичность всё равно по sha256, путь — только подсказка.
    source_path: str = ""
    # Идентичность исходника = sha256 содержимого. Локальный тир ищет файл в inputs/
    # по этому хэшу, а не по `source`. Тот же хэш — основа ключа идемпотентности (state.py).
    source_sha256: str
    # Схема хэширования source_sha256:
    #   "partial-p1" — sha256(head‖mid‖tail‖size), быстро для многогигабайтных видео;
    #   "full"       — полный sha256 содержимого (дефолт для обратной совместимости).
    # Дефолт "full" означает: старые манифесты без поля читаются корректно.
    # _assemble_manifest (run) явно ставит "partial-p1" для новых манифестов.
    source_hash_scheme: str = "full"
    source_kind: str = ""          # "interview" | "lecture" | "" (absent in old manifests)
    duration_preset: str
    setup: SetupProfile
    # Ключ идемпотентности = хэш(source + preset + версия рубрики). Ставит state.py.
    run_key: str
    # params_key транскрипта (отпечаток model|provider|prompt_hash), на котором СОБРАН манифест.
    # Позволяет diagnose-cuts/resnap найти ТОТ ЖЕ транскрипт, а не устаревшего «сироту» без
    # params_key (другая пунктуация → фантомные мид-слово обрывы при чтении и порча границ при
    # resnap-записи). "" = легаси-манифест, снятый до этого поля: resnap для него отказан (нельзя
    # проверить совпадение), нужен один полный run. Ставит cmd_run из stamped-мета транскрипта.
    transcript_params_key: str = ""
    selection_source: str = ""  # "human" = manual review path; "" = automatic (LLM)
    status: ProjectStatus = ProjectStatus.pending
    # Пустой список валиден: «хороших моментов нет» — ожидаемый исход, не ошибка.
    reels: list[Reel] = Field(default_factory=list)
