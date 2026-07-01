"""Транскрипция: аудио → word-level Transcript. Кэш по хэшу аудио (идемпотентность).

Один интерфейс (`TranscriptionBackend`), два бэкенда за ним, выбор рантайм по env
`TRANSCRIBE_BACKEND`:
- **groq** (ДЕФОЛТ, dev и prod) — Groq Whisper API, word-level timestamps;
- **faster_whisper** — необязательный CPU-fallback (offline). НЕ дефолт: prod на AMD-GPU
  без CUDA → CTranslate2 идёт только на CPU. Импорт faster_whisper ленивый.

Детерминированный слой — чистые парсеры (`parse_groq_response`, `parse_faster_whisper`):
сырой ответ бэкенда → схема `Transcript`. Они и есть главная цель тестов (без сети/моделей).
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Protocol

from autoreels.core import state
from autoreels.core.models import Transcript, Word

DEFAULT_BACKEND = "groq"
GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_WHISPER_MODEL = "whisper-large-v3"

# Groq Whisper: жёсткий лимит 25 МБ на запрос. Используем 24 МБ как безопасный порог,
# чтобы успеть дать внятную ошибку до разрыва соединения.
GROQ_MAX_AUDIO_BYTES = 24 * 1024 * 1024   # 24 МБ

# Retry: пробуем на transient-ошибках (disconnect, 5xx) до N раз с backoff.
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF = [2.0, 6.0]   # пауза между попытками 1→2, 2→3 (сек)


class TranscriptionError(Exception):
    """Проблема транскрипции (неизвестный бэкенд, нет ключа/пакета, ошибка API)."""


# ----------------------------------------------------------- детерминированные парсеры

def parse_groq_response(data: dict) -> Transcript:
    """Groq verbose_json (timestamp_granularities=['word']) → Transcript word-level."""
    words = [
        Word(word=w["word"], t0=float(w["start"]), t1=float(w["end"]))
        for w in data.get("words", [])
    ]
    return Transcript(language=data.get("language", ""), words=words)


def parse_faster_whisper(segments, language: str) -> Transcript:
    """Сегменты faster-whisper (каждый с .words) → Transcript word-level."""
    words: list[Word] = []
    for seg in segments:
        for w in (getattr(seg, "words", None) or []):
            words.append(Word(word=w.word, t0=float(w.start), t1=float(w.end)))
    return Transcript(language=language, words=words)


# ------------------------------------------------------------------------- бэкенды

class TranscriptionBackend(Protocol):
    def transcribe(self, audio_path: Path, *, language: str | None = None) -> Transcript: ...


class GroqBackend:
    """Groq Whisper API. Ключ из GROQ_API_KEY (нужен только при вызове, не при создании).

    `request_fn` — точка внедрения для тестов: (audio_path, language) -> сырой dict ответа.
    По умолчанию идёт реальный multipart-POST к Groq.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = GROQ_WHISPER_MODEL,
        request_fn: Callable[[Path, str | None], dict] | None = None,
    ):
        self._api_key = api_key
        self._model = model
        self._request_fn = request_fn

    def transcribe(self, audio_path: Path, *, language: str | None = None) -> Transcript:
        request = self._request_fn or self._default_request
        return parse_groq_response(request(Path(audio_path), language))

    def _default_request(self, audio_path: Path, language: str | None) -> dict:
        import httpx  # ленивый импорт: модуль грузится без сетевого стека

        api_key = (self._api_key or os.environ.get("GROQ_API_KEY", "")).strip()
        if not api_key:
            raise TranscriptionError(
                "нет GROQ_API_KEY — задайте ключ Groq в окружении для транскрипции"
            )

        # Pre-flight: проверяем РЕАЛЬНЫЙ РАЗМЕР файла ДО отправки — Groq рвёт по байтам.
        size = audio_path.stat().st_size
        if size > GROQ_MAX_AUDIO_BYTES:
            raise TranscriptionError(
                f"аудио {size // (1024 * 1024)} МБ превышает лимит Groq Whisper (25 МБ/запрос). "
                f"Нужен чанкинг (M1) — см. PLAN.md."
            )

        data = {
            "model": self._model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
        }
        if language:
            data["language"] = language

        last_exc: Exception | None = None
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                with audio_path.open("rb") as f:
                    resp = httpx.post(
                        GROQ_TRANSCRIBE_URL,
                        headers={"Authorization": f"Bearer {api_key}"},
                        data=data,
                        files={"file": (audio_path.name, f, "application/octet-stream")},
                        timeout=600,
                    )
                # 401/403 — ошибка ключа, ретраить бесполезно
                if resp.status_code in (401, 403):
                    raise TranscriptionError(
                        f"Groq отклонил ключ (HTTP {resp.status_code}): "
                        f"проверь GROQ_API_KEY в .env — невалиден, истёк или превышен лимит аккаунта"
                    )
                # 429 / 5xx — transient, ретраим
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_exc = TranscriptionError(
                        f"Groq Whisper API: HTTP {resp.status_code} (попытка {attempt + 1})"
                    )
                    if attempt < _RETRY_ATTEMPTS - 1:
                        time.sleep(_RETRY_BACKOFF[attempt])
                    continue
                resp.raise_for_status()
                return resp.json()
            except (httpx.RemoteProtocolError, httpx.ConnectError) as e:
                # Разрыв соединения — transient, ретраим
                last_exc = e
                if attempt < _RETRY_ATTEMPTS - 1:
                    time.sleep(_RETRY_BACKOFF[attempt])
            except TranscriptionError:
                raise
            except httpx.HTTPStatusError as e:
                raise TranscriptionError(f"Groq Whisper API ошибка {e.response.status_code}: {e}") from e
            except httpx.HTTPError as e:
                raise TranscriptionError(f"Groq Whisper API ошибка: {e}") from e

        raise TranscriptionError(
            f"Groq Whisper не ответил после {_RETRY_ATTEMPTS} попыток: {last_exc}"
        ) from last_exc


class FasterWhisperBackend:
    """Необязательный CPU-fallback (offline). Импорт faster_whisper — ленивый."""

    def __init__(self, *, model_size: str = "large-v3", device: str = "cpu",
                 compute_type: str = "int8"):
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type

    def transcribe(self, audio_path: Path, *, language: str | None = None) -> Transcript:
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise TranscriptionError(
                "faster-whisper не установлен; поставьте extra: "
                "pip install -e '.[faster-whisper]' (или используйте дефолтный бэкенд groq)"
            ) from e
        model = WhisperModel(self._model_size, device=self._device, compute_type=self._compute_type)
        segments, info = model.transcribe(str(audio_path), language=language, word_timestamps=True)
        return parse_faster_whisper(segments, info.language)


def get_backend(config=None) -> TranscriptionBackend:
    """Бэкенд транскрипции. Источник выбора: config (transcribe.yaml), env перебивает.

    Порядок: env `TRANSCRIBE_BACKEND` (ad-hoc override) → `config.backend` → дефолт groq.
    Параметры бэкендов (модель Groq, faster-whisper) берутся из `config`, если он передан.
    """
    name = os.environ.get("TRANSCRIBE_BACKEND") or (
        config.backend if config is not None else DEFAULT_BACKEND
    )
    if name == "groq":
        model = config.groq.model if config is not None else GROQ_WHISPER_MODEL
        return GroqBackend(model=model)
    if name == "faster_whisper":
        if config is not None:
            fw = config.faster_whisper
            return FasterWhisperBackend(
                model_size=fw.model_size, device=fw.device, compute_type=fw.compute_type
            )
        return FasterWhisperBackend()
    raise TranscriptionError(
        f"неизвестный backend транскрипции: {name!r}; допустимо: groq | faster_whisper"
    )


# ------------------------------------------------------------------- верхний уровень

def transcribe(
    audio_path: str | Path,
    cache_dir: str | Path,
    *,
    backend: TranscriptionBackend | None = None,
    language: str | None = "ru",
    force: bool = False,
    chunking_cfg=None,
    audio_cfg=None,
    ffmpeg: str = "ffmpeg",
) -> Transcript:
    """Транскрибировать аудио с кэшем по хэшу аудио (идемпотентность, R0_SPEC §9).

    Если `chunking_cfg` передан и аудио превышает порог (>15мин или >20МБ) →
    автоматический Whisper-чанкинг через chunk_transcribe.transcribe_chunked.
    Без `chunking_cfg` → одиночный запрос (обратная совместимость с короткими видео).

    Кэш-хит → возвращаем без вызова бэкенда. После транскрипции кэшируем результат
    (и для одиночного запроса, и для склеенного чанкинга) по тому же ключу.
    """
    from autoreels.cloud.chunk_transcribe import (
        _probe_duration,
        should_chunk,
        transcribe_chunked,
    )

    audio_path = Path(audio_path)
    if not audio_path.is_file():
        raise TranscriptionError(f"аудиофайл не найден: {audio_path}")
    if audio_path.stat().st_size == 0:
        raise TranscriptionError(f"пустой аудиофайл: {audio_path}")

    cache_path = state.transcript_cache_path(cache_dir, audio_path)
    if cache_path.exists() and not force:
        return Transcript.model_validate_json(cache_path.read_text(encoding="utf-8"))

    backend = backend or get_backend()

    # Чанкинг: если конфиг передан и аудио превышает порог
    if chunking_cfg is not None and chunking_cfg.enabled:
        size     = audio_path.stat().st_size
        duration = _probe_duration(audio_path, ffmpeg)
        if should_chunk(size, duration, chunking_cfg):
            tr, _warns = transcribe_chunked(
                audio_path, chunking_cfg, audio_cfg, Path(cache_dir),
                backend, ffmpeg=ffmpeg, language=language or "ru",
            )
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(tr.model_dump_json(), encoding="utf-8")
            return tr

    # Одиночный запрос (короткое аудио или chunking_cfg не передан)
    tr = backend.transcribe(audio_path, language=language)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(tr.model_dump_json(), encoding="utf-8")
    return tr
