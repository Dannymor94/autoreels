"""Загрузка config/ (YAML) + profiles/ (JSON). Ноль магических чисел в коде.

Принципы (CLAUDE.md):
- **Типизация, не сырые dict.** Конфиг валидируется в Pydantic-объект, опечатка в ключе
  (`extra='forbid'`) падает на загрузке, а не молча течёт внутрь R0.
- **Fail-fast.** Битый/неполный файл → `ConfigError` на загрузке, без молчаливых дефолтов.
- **Пресет → числа в одном месте.** `duration_preset` резолвится в `min_duration`/
  `max_duration` здесь (`R0Config`), больше нигде.
- **Профиль валидируется.** crop в границах кадра, scale = целевое вертикальное разрешение.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from autoreels.core.models import SetupProfile

# Целевое вертикальное разрешение 9:16 — единственно допустимое для профиля сетапа.
TARGET_SCALE = [1080, 1920]


class ConfigError(Exception):
    """Любая проблема загрузки/валидации конфига. Бросается на загрузке (fail-fast)."""


# --------------------------------------------------------------------------- R0

class Preset(BaseModel):
    """Пресет длины клипа в секундах."""

    model_config = ConfigDict(extra="forbid")

    min: int
    max: int


class PromptPaths(BaseModel):
    """Пути к рантайм-промптам R0 (относительно корня репо). Не хардкод в коде."""

    model_config = ConfigDict(extra="forbid")

    system: str
    fewshot: str


class ChunkingConfig(BaseModel):
    """Параметры чанкинга: Whisper-чанкинг аудио + R0-чанкинг транскрипта."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    whisper_chunk_duration_sec: int = 600       # целевая длина одного аудио-чанка (10 мин)
    whisper_threshold_minutes: float = 15       # порог «чанкить по длительности»
    whisper_threshold_bytes: int = 20 * 1024 * 1024  # порог «чанкить по размеру» (20 МБ)
    silence_window_sec: float = 30              # окно поиска тишины вокруг target-границы
    silence_threshold_db: float = -40           # порог silencedetect (дБ)
    r0_chunk_tokens: int = 2000                 # целевой размер R0-чанка транскрипта (токены)
    r0_overlap_tokens: int = 300                # перекрытие R0-чанков (≥60с)
    r0_chunk_delay_sec: float = 2.0             # пауза между R0-чанками (избежать 429 TPM)
    dedup_overlap_ratio: float = 0.5            # порог дедупа рилов из разных R0-чанков
    fail_fast: bool = False                     # False → продолжать при провале чанка


class R0Config(BaseModel):
    """Типизированный config/r0.yaml. Пресет резолвится в числа через свойства ниже."""

    model_config = ConfigDict(extra="forbid")

    duration_preset: str
    min_score: int
    max_reels: int | None
    chunk_tokens: int
    chunk_overlap_sec: int
    dedup_overlap_threshold: float
    sentence_pause_sec: float
    max_sentence_buffer_sec: float
    tail_sec: float            # хвост после последнего слова при snap границ (R4)
    snap_window_sec: float     # окно поиска границы слова/паузы при snap (±сек)
    title_style: str
    language: str
    prompt_language: str
    presets: dict[str, Preset]
    prompts: PromptPaths
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)

    @property
    def min_duration(self) -> int:
        """Нижняя граница длины клипа (сек) активного пресета."""
        return self.presets[self.duration_preset].min

    @property
    def max_duration(self) -> int:
        """Верхняя граница длины клипа (сек) активного пресета."""
        return self.presets[self.duration_preset].max

    @property
    def max_sentence_sec(self) -> float:
        """Порог дробления строк compress: max_duration пресета + запас.

        Привязан к пресету, чтобы НЕ рубить легальные моменты длиной до max_duration;
        дробятся только строки-гиганты длиннее этого порога.
        """
        return self.max_duration + self.max_sentence_buffer_sec


# ------------------------------------------------------------------------ Render

class Encoder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codec: str
    fallback_codec: str
    preset: str
    cq: int


class Audio(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codec: str
    bitrate: str


class AudioExtract(BaseModel):
    """Параметры извлечения аудиодорожки под Whisper (cloud/extract_audio.py)."""

    model_config = ConfigDict(extra="forbid")

    sample_rate: int
    channels: int
    codec: str
    format: str
    bitrate: str | None = None   # напр. "64k" для mp3; None для PCM (bitrate неприменим)


class SubtitleStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    font: str
    font_size: int
    margin_v: int
    words_per_line: list[int]
    font_dir: str | None


class RenderConfig(BaseModel):
    """Типизированный config/render.yaml."""

    model_config = ConfigDict(extra="forbid")

    scale: list[int]
    encoder: Encoder
    audio: Audio
    audio_extract: AudioExtract
    subtitles: SubtitleStyle


# ----------------------------------------------------------------------- Subtitles

class SubtitlesConfig(BaseModel):
    """Типизированный config/subtitles.yaml — стиль выжигаемых субтитров (R3).

    Все параметры числами/строками-числами, чтобы крутить стиль без кода (UI-крутилку
    осознанно отложили). Цвета — RRGGBB; в ASS уходят как &HAABBGGRR (см. subtitles.ass_color).
    """

    model_config = ConfigDict(extra="forbid")

    font: str
    font_size: int
    text_color: str
    bold: bool
    uppercase: bool
    outline_color: str
    outline_width: int
    shadow: int
    fill_enabled: bool
    fill_color: str
    fill_opacity: int          # % непрозрачности подложки-бокса (если fill_enabled)
    position_v: int            # MarginV — подъём от низа кадра
    words_per_line: int
    subtitle_break_pause_sec: float   # пауза-граница фразы рвёт группу субтитров (R3-fix)
    fade_in_ms: int            # плавное появление группы (\fad); 0 = без fade
    fade_out_ms: int           # плавное исчезновение группы (\fad); 0 = без fade
    alignment: str             # center | left | right
    char_width_ratio: float    # оценка ширины символа (доля font_size) для подгонки строки
    max_text_width_px: int     # макс. ширина строки в px


# --------------------------------------------------------------------- Transcribe

class GroqWhisper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "whisper-large-v3"


class FasterWhisperParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_size: str = "large-v3"
    device: str = "cpu"
    compute_type: str = "int8"


class TranscribeConfig(BaseModel):
    """Типизированный config/transcribe.yaml. backend отсюда, ключ — из env."""

    model_config = ConfigDict(extra="forbid")

    backend: str = "groq"
    language: str = "ru"
    groq: GroqWhisper = Field(default_factory=GroqWhisper)
    faster_whisper: FasterWhisperParams = Field(default_factory=FasterWhisperParams)


# ------------------------------------------------------------------------ readers

def _read_yaml(path: Path) -> dict:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"не удалось прочитать конфиг {path}: {e}") from e
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ConfigError(f"битый YAML в {path}: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(
            f"конфиг {path} должен быть YAML-маппингом, получено: {type(data).__name__}"
        )
    return data


def _read_json(path: Path) -> dict:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"не удалось прочитать профиль {path}: {e}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"битый JSON в {path}: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"профиль {path} должен быть JSON-объектом")
    return data


def load_r0_config(path: str | Path) -> R0Config:
    """config/r0.yaml → R0Config. Падает на неизвестном пресете и любой опечатке ключа."""
    data = _read_yaml(Path(path))
    try:
        cfg = R0Config.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"невалидный r0-конфиг {path}:\n{e}") from e
    if cfg.duration_preset not in cfg.presets:
        known = ", ".join(sorted(cfg.presets))
        raise ConfigError(
            f"неизвестный duration_preset '{cfg.duration_preset}' в {path}; "
            f"известные пресеты: {known}"
        )
    return cfg


def load_render_config(path: str | Path) -> RenderConfig:
    """config/render.yaml → RenderConfig."""
    data = _read_yaml(Path(path))
    try:
        return RenderConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"невалидный render-конфиг {path}:\n{e}") from e


def load_subtitles_config(path: str | Path) -> SubtitlesConfig:
    """config/subtitles.yaml → SubtitlesConfig."""
    data = _read_yaml(Path(path))
    try:
        return SubtitlesConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"невалидный subtitles-конфиг {path}:\n{e}") from e


def load_transcribe_config(path: str | Path) -> TranscribeConfig:
    """config/transcribe.yaml → TranscribeConfig."""
    data = _read_yaml(Path(path))
    try:
        return TranscribeConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"невалидный transcribe-конфиг {path}:\n{e}") from e


def load_profile(path: str | Path) -> SetupProfile:
    """profiles/*.json → SetupProfile. Валидирует кроп в границах кадра и целевой scale."""
    data = _read_json(Path(path))
    # Документирующие ключи-комментарии (_comment и т.п.) — не часть схемы.
    data = {k: v for k, v in data.items() if not k.startswith("_")}
    try:
        prof = SetupProfile.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"невалидный профиль {path}:\n{e}") from e

    if prof.scale != TARGET_SCALE:
        raise ConfigError(
            f"профиль {path}: scale должен быть {TARGET_SCALE} (целевое 9:16), "
            f"получено {prof.scale}"
        )
    if len(prof.frame) != 2:
        raise ConfigError(
            f"профиль {path}: frame должен быть [w, h], получено {prof.frame}"
        )

    frame_w, frame_h = prof.frame
    c = prof.crop
    if c.x + c.w > frame_w or c.y + c.h > frame_h:
        raise ConfigError(
            f"профиль {path}: кроп выходит за границы кадра — "
            f"crop right={c.x + c.w}/bottom={c.y + c.h} при кадре {frame_w}x{frame_h}"
        )
    return prof
