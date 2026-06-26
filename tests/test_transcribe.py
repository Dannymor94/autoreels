"""Транскрипция (cloud/transcribe.py).

Дефолт везде — Groq Whisper API (prod на AMD-GPU без CUDA → faster-whisper только CPU,
поэтому он необязательный fallback, не дефолт). Выбор бэкенда — рантайм по env.
Тесты мокнуты: на dev-M1 реальные модели не гоняем; реальный faster-whisper — только
под @pytest.mark.integration на системнике.
"""
import json
from pathlib import Path

import pytest

from autoreels.core import state
from autoreels.core.models import Transcript, Word
from autoreels.cloud import transcribe as T

ROOT = Path(__file__).resolve().parents[1]
GROQ_FIXTURE = ROOT / "tests" / "fixtures" / "groq_whisper_word.json"


# ------------------------------------------------------ выбор бэкенда по env

def test_default_backend_is_groq(monkeypatch):
    monkeypatch.delenv("TRANSCRIBE_BACKEND", raising=False)
    assert isinstance(T.get_backend(), T.GroqBackend)


def test_env_selects_groq(monkeypatch):
    monkeypatch.setenv("TRANSCRIBE_BACKEND", "groq")
    assert isinstance(T.get_backend(), T.GroqBackend)


def test_env_selects_faster_whisper(monkeypatch):
    # Конструирование бэкенда не должно импортировать faster_whisper (ленивый импорт).
    monkeypatch.setenv("TRANSCRIBE_BACKEND", "faster_whisper")
    assert isinstance(T.get_backend(), T.FasterWhisperBackend)


def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("TRANSCRIBE_BACKEND", "whisperX")
    with pytest.raises(T.TranscriptionError) as e:
        T.get_backend()
    assert "whisperX" in str(e.value)


def test_backend_from_config(monkeypatch):
    # Источник выбора — transcribe.yaml; env не задан.
    from autoreels.core.config import TranscribeConfig

    monkeypatch.delenv("TRANSCRIBE_BACKEND", raising=False)
    assert isinstance(T.get_backend(TranscribeConfig(backend="groq")), T.GroqBackend)
    assert isinstance(
        T.get_backend(TranscribeConfig(backend="faster_whisper")), T.FasterWhisperBackend
    )


def test_env_overrides_config(monkeypatch):
    # env TRANSCRIBE_BACKEND перебивает конфиг (ad-hoc прогон).
    from autoreels.core.config import TranscribeConfig

    monkeypatch.setenv("TRANSCRIBE_BACKEND", "groq")
    assert isinstance(T.get_backend(TranscribeConfig(backend="faster_whisper")), T.GroqBackend)


# ------------------------------------------------------ детерминированные парсеры

def test_parse_groq_response_to_word_level():
    data = json.loads(GROQ_FIXTURE.read_text(encoding="utf-8"))
    tr = T.parse_groq_response(data)
    assert isinstance(tr, Transcript)
    assert tr.language == "russian"
    assert len(tr.words) == 11
    first = tr.words[0]
    assert (first.word, first.t0, first.t1) == ("Самый", 0.12, 0.46)


def test_parse_faster_whisper_segments():
    # Имитация faster-whisper: сегменты с .words (word/start/end), язык из info.
    from types import SimpleNamespace as NS

    segments = [
        NS(words=[NS(word="привет", start=0.0, end=0.5), NS(word="мир", start=0.5, end=0.9)]),
        NS(words=[NS(word="тест", start=1.0, end=1.4)]),
    ]
    tr = T.parse_faster_whisper(segments, language="ru")
    assert tr.language == "ru"
    assert [w.word for w in tr.words] == ["привет", "мир", "тест"]
    assert tr.words[0] == Word(word="привет", t0=0.0, t1=0.5)


# ------------------------------------------------------ groq backend без сети

def test_groq_backend_uses_injected_request():
    data = json.loads(GROQ_FIXTURE.read_text(encoding="utf-8"))
    # Внедряем фейковый request_fn → сеть/ключ не нужны.
    backend = T.GroqBackend(request_fn=lambda audio_path, language: data)
    tr = backend.transcribe(Path("whatever.wav"), language="ru")
    assert isinstance(tr, Transcript)
    assert tr.words[0].word == "Самый"


# ------------------------------------------------------ кэш / идемпотентность

class _SpyBackend:
    """Считает вызовы — проверяем, что кэш-хит не дёргает бэкенд повторно."""

    def __init__(self):
        self.calls = 0

    def transcribe(self, audio_path, *, language=None):
        self.calls += 1
        return Transcript(language="russian", words=[Word(word="а", t0=0.0, t1=0.1)])


def test_transcribe_caches_and_is_idempotent(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"fake audio bytes")
    cache_dir = tmp_path / "cache"
    spy = _SpyBackend()

    first = T.transcribe(audio, cache_dir, backend=spy)
    assert spy.calls == 1
    assert state.transcript_cache_path(cache_dir, audio).exists()

    second = T.transcribe(audio, cache_dir, backend=spy)
    assert spy.calls == 1            # кэш-хит: бэкенд НЕ вызван повторно
    assert second == first


def test_transcribe_missing_audio_raises(tmp_path):
    spy = _SpyBackend()
    with pytest.raises(T.TranscriptionError):
        T.transcribe(tmp_path / "nope.wav", tmp_path / "cache", backend=spy)
    assert spy.calls == 0          # fail-fast до вызова бэкенда


def test_transcribe_empty_audio_raises(tmp_path):
    audio = tmp_path / "empty.wav"
    audio.write_bytes(b"")
    spy = _SpyBackend()
    with pytest.raises(T.TranscriptionError):
        T.transcribe(audio, tmp_path / "cache", backend=spy)
    assert spy.calls == 0


def test_transcribe_force_bypasses_cache(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"fake audio bytes")
    cache_dir = tmp_path / "cache"
    spy = _SpyBackend()

    T.transcribe(audio, cache_dir, backend=spy)
    T.transcribe(audio, cache_dir, backend=spy, force=True)
    assert spy.calls == 2            # force обходит кэш


# ------------------------------------------------------ integration (только системник)

@pytest.mark.integration
def test_faster_whisper_real_run(synthetic_video, tmp_path):
    """Реальный faster-whisper на синтетическом клипе. Skip по умолчанию.

    Гоняется только на системнике: pytest -m integration. На dev-M1 не запускается.
    """
    pytest.importorskip("faster_whisper")
    from autoreels.core.config import load_render_config
    from autoreels.cloud.extract_audio import extract_audio

    audio_cfg = load_render_config(ROOT / "config" / "render.yaml").audio_extract
    audio = extract_audio(synthetic_video, audio_cfg, cache_dir=tmp_path)
    tr = T.FasterWhisperBackend().transcribe(audio, language="ru")
    assert isinstance(tr, Transcript)
