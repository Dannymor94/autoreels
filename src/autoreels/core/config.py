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
    model: str = "qwen/qwen3.6-27b"          # LLM R0 на Groq (основная, сильнее по качеству)
    openrouter_model: str = "openai/gpt-oss-20b:free"  # та же модель есть на Groq → не плавает
    provider_strategy: str = "adaptive"      # распределение R0-нагрузки: adaptive | round_robin
                                             # adaptive: Groq основной, слив на OpenRouter под
                                             # троттлом (качество не плавает). round_robin:
                                             # чередовать поровну (макс. пропускная, но половина
                                             # чанков на слабую модель — компромисс качества).
    min_score: int
    min_meaningful_sec: float = 18    # планка «законченной мысли»: сегменты короче снимает
                                      # детерминированный пост-фильтр (выше техн. min_duration).
                                      # Лечит «пустые 15-сек клипы» на длинных видео.
    max_reels: int | None
    chunk_tokens: int
    chunk_overlap_sec: int
    dedup_overlap_threshold: float
    sentence_pause_sec: float
    max_sentence_buffer_sec: float
    tail_sec: float            # хвост при snap к границе слова (технический)
    tail_pad_sec: float = 0.7  # «воздух» после последнего слова клипа (apply_padding)
    lead_pad_sec: float = 0.3  # заход перед первым словом клипа (apply_padding)
    snap_window_sec: float     # окно поиска границы слова/паузы при snap (±сек)
    # Snap «до завершения мысли»: конец клипа тянется до конца предложения (пунктуация) или
    # длинной паузы, пока есть запас до max_duration. Не обрывать на висячих словах/микропаузах.
    min_pause_for_phrase_end: float = 1.5   # пауза > порога = конец мысли. 1.5: thinking-паузы
                                            # спикера 0.7-1.2с (подбирает слово) — НЕ конец;
                                            # реальные разрывы ≥2с — конец. Крутить под спикера.
    max_micro_pause: float = 0.4            # пауза < порога = микропауза внутри фразы (не конец)
    # Предпочтение более длинного клипа: если snap-конец даёт клип КОРОЧЕ ratio·max_duration
    # (грамматически завершён, но мысль спикер развивал дальше и был запас времени), тянуть
    # до следующей чистой границы предложения — максимум на max_extra_sentences вперёд.
    # ratio=0 отключает. Проверяется мгновенно через resnap (LLM не нужен).
    prefer_longer_below_ratio: float = 0.7  # <70% лимита (напр. <41с при 59с) → тянуть дальше
    max_extra_sentences: int = 2            # но не более +2 предложений (чтобы не уйти в др. тему)
    hanging_words: list[str] = Field(default_factory=lambda: [
        "и", "а", "но", "что", "это", "как", "в", "на",
        "потому", "чтобы", "если", "когда", "то", "есть", "вот",
    ])
    too_long_policy: str = "trim"   # trim | drop | keep (что делать с флагом too_long)
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

class CodecProfile(BaseModel):
    """Один кодек-профиль: связка ffmpeg-кодек + целевой битрейт.

    Кодек и битрейт связаны неразрывно (h264 нужен выше битрейт, hevc/av1 — ниже при том
    же качестве), поэтому живут в одной записи, а не в двух независимых таблицах.
    """

    model_config = ConfigDict(extra="forbid")

    codec: str        # ffmpeg-энкодер (h264_amf | hevc_amf | av1_amf | libx264 | …)
    bitrate: str      # целевой битрейт (напр. '5M'); при rate_control='cqp' игнорируется
    # Качество AMF (аппаратный кодер): часто важнее битрейта. Диагностика показала, что softness
    # на равном битрейте — от AMF, а не от 5 Мбит/с. Применяются ТОЛЬКО к *_amf кодекам.
    quality: str | None = None        # -quality: quality | balanced | speed (дефолт AMF — balanced)
    rate_control: str | None = None   # 'cqp' → -rc cqp + qp (лучше качество, размер непредсказуем);
                                      # иначе (None/'vbr') — целевой битрейт (предсказуемый размер)
    qp: int | None = None             # базовый QP для cqp (qp_i=qp, qp_p=qp+2); ниже = качественнее
    label: str = ""                   # заметка для меню: скорость/качество


# Дефолтные профили: prod — системник Windows AMD (AMF-энкодеры).
_DEFAULT_PROFILES: dict[str, dict] = {
    "h264":    {"codec": "h264_amf", "bitrate": "7M", "quality": "quality",
                "label": "быстро, совместимый"},
    "hevc":    {"codec": "hevc_amf", "bitrate": "5M", "quality": "quality",
                "label": "быстро, компактный (дефолт)"},
    "hevc_hq": {"codec": "hevc_amf", "bitrate": "12M", "quality": "quality",
                "rate_control": "cqp", "qp": 18, "label": "быстро, лучше качество (крупнее файл)"},
    "h264_hq": {"codec": "h264_amf", "bitrate": "16M", "quality": "quality",
                "label": "быстро, лучше, совместимый (крупный файл)"},
    "hevc_sw": {"codec": "libx265", "bitrate": "5M",
                "label": "МЕДЛЕННО, максимум качества (для избранных клипов)"},
    "av1":     {"codec": "av1_amf", "bitrate": "4M", "label": "экспериментально, компактно"},
}


class Encoder(BaseModel):
    """Видеоэнкодер + rate-control под соцсети.

    Кодек выбирается ПРОФИЛЕМ (`profiles[profile]`): каждый профиль — связка кодек+битрейт.
    h264 (безопасный, универсальный) / hevc (компактный, дефолт) / av1 (экспериментальный).
    Размер файла контролируется ЦЕЛЕВЫМ БИТРЕЙТОМ, а не CRF: битрейт предсказуемо задаёт
    размер (30с ≈ битрейт×30/8) одним проходом и, главное, работает на аппаратном AMF
    (который без rate-control раздувает файл в разы — отсюда прежняя нужда дожимать HandBrake).
    `cq` оставлен для совместимости конфига.
    """

    model_config = ConfigDict(extra="forbid")

    profile: str = "hevc"                    # активный кодек-профиль (h264 | hevc | av1)
    profiles: dict[str, CodecProfile] = Field(
        default_factory=lambda: {k: CodecProfile(**v) for k, v in _DEFAULT_PROFILES.items()}
    )
    preset: str
    cq: int
    pix_fmt: str = "yuv420p"                 # универсальная совместимость соцсетей/плееров
    faststart: bool = True                   # moov-atom в начало (соцсети требуют для стрима)

    @property
    def active(self) -> CodecProfile:
        """Активный кодек-профиль (по имени `profile`)."""
        return self.profiles[self.profile]

    @property
    def codec(self) -> str:
        """ffmpeg-кодек активного профиля (напр. 'hevc_amf')."""
        return self.active.codec

    @property
    def video_bitrate(self) -> str:
        """Целевой битрейт активного профиля (напр. '5M')."""
        return self.active.bitrate


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


class PaletteEq(BaseModel):
    """eq-фильтр цветокоррекции. Дефолты = нейтрально (картинка не меняется)."""
    model_config = ConfigDict(extra="forbid")
    brightness: float = 0.0   # -1..1
    contrast: float = 1.0     # 0..2
    saturation: float = 1.0   # 0..3
    gamma: float = 1.0        # 0.1..10


class PaletteUnsharp(BaseModel):
    """unsharp (резкость). ВЫКЛ по умолчанию — перебор даёт звон по контурам, соцсети усилят."""
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    luma_msize_x: int = 5
    luma_msize_y: int = 5
    luma_amount: float = 0.8


class Palette(BaseModel):
    """Пресет палитры: eq + unsharp + опц. цветовая температура. neutral = всё по дефолтам."""
    model_config = ConfigDict(extra="forbid")
    eq: PaletteEq = Field(default_factory=PaletteEq)
    unsharp: PaletteUnsharp = Field(default_factory=PaletteUnsharp)
    colortemperature: int | None = None   # Кельвины; <6500 теплее, >6500 холоднее; None = выкл
    label: str = ""                       # заметка для меню


# Готовые пресеты палитры (значения — не хардкод в коде рендера).
_DEFAULT_PALETTES: dict[str, dict] = {
    "neutral": {"label": "без изменений (дефолт)"},
    "vivid":   {"eq": {"saturation": 1.15, "contrast": 1.10},
                "label": "живее: насыщенность +15%, контраст +10% (соцсети)"},
    "soft":    {"eq": {"contrast": 0.95, "saturation": 1.05}, "colortemperature": 5400,
                "label": "мягче + теплее (talking-head)"},
    "sharp":   {"eq": {"contrast": 1.05}, "unsharp": {"enabled": True, "luma_amount": 0.6},
                "label": "умеренный unsharp + лёгкий контраст"},
}


class RenderConfig(BaseModel):
    """Типизированный config/render.yaml."""

    model_config = ConfigDict(extra="forbid")

    scale: list[int]
    encoder: Encoder
    audio: Audio
    audio_extract: AudioExtract
    subtitles: SubtitleStyle
    ffmpeg: str = "ffmpeg"   # путь к ffmpeg-бинарю; Windows: D:\ffmpeg\bin\ffmpeg.exe
    palette: str = "neutral"                 # активная палитра (--palette / render.local.yaml)
    palettes: dict[str, Palette] = Field(
        default_factory=lambda: {k: Palette(**v) for k, v in _DEFAULT_PALETTES.items()}
    )

    @property
    def active_palette(self) -> Palette:
        """Активный пресет палитры (по имени `palette`)."""
        return self.palettes[self.palette]


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
    from autoreels.cloud.providers import POOL_STRATEGIES
    if cfg.provider_strategy not in POOL_STRATEGIES:
        raise ConfigError(
            f"неизвестный provider_strategy '{cfg.provider_strategy}' в {path}; "
            f"допустимо: {', '.join(POOL_STRATEGIES)}"
        )
    return cfg


def _deep_merge(base: dict, override: dict) -> dict:
    """Рекурсивно наложить override на base: вложенные маппинги мержатся по ключам,
    скаляры/списки заменяются целиком. Не мутирует аргументы."""
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_render_config(path: str | Path, *, local_path: str | Path | None = None) -> RenderConfig:
    """config/render.yaml → RenderConfig.

    Машинно-локальные настройки (путь к ffmpeg, кодек энкодера, font_dir) кладутся в
    сосед `render.local.yaml` (в .gitignore) и накладываются поверх общего render.yaml
    через deep-merge. Так машинный путь ffmpeg не уезжает в git и не ломает другую машину
    (у Mac свой ffmpeg из PATH). Override частичный — задаются только отличающиеся ключи.
    """
    path = Path(path)
    data = _read_yaml(path)
    if local_path is None:
        local_path = path.with_name(f"{path.stem}.local{path.suffix}")
    else:
        local_path = Path(local_path)
    if local_path.is_file():
        data = _deep_merge(data, _read_yaml(local_path))
    try:
        cfg = RenderConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"невалидный render-конфиг {path}:\n{e}") from e
    validate_profile(cfg.encoder.profile, cfg.encoder.profiles, where=str(path))
    return cfg


def validate_profile(profile: str, profiles: dict, *, where: str) -> None:
    """Профиль существует в таблице профилей → иначе ConfigError (fail-fast).

    Переиспользуется валидацией конфига И CLI-флагом `--profile` (опечатка ловится сразу,
    а не падает KeyError глубоко в рендере)."""
    if profile not in profiles:
        known = ", ".join(sorted(profiles))
        raise ConfigError(
            f"неизвестный профиль кодека '{profile}' в {where}; известные: {known}"
        )


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
