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
    # Против РЕАЛЬНОЙ формы Groq Whisper (захвачена в 5b): language с заглавной,
    # start бывает int (0), segments=null, есть x_groq — парсер всё это переваривает.
    data = json.loads(GROQ_FIXTURE.read_text(encoding="utf-8"))
    tr = T.parse_groq_response(data)
    assert isinstance(tr, Transcript)
    assert tr.language == "Russian"
    assert len(tr.words) == 78
    first = tr.words[0]
    assert (first.word, first.t0, first.t1) == ("я", 0.0, 0.62)   # int 0 → float 0.0
    assert isinstance(first.t0, float)


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
    assert tr.words[0].word == "я"


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


# ------------------------------------------------------ Groq pre-flight + retry

def test_groq_api_key_stripped_of_whitespace(tmp_path, monkeypatch):
    """Ключ с trailing \\r\\n (CRLF из .env на Windows) strip'ается — не отправляется как мусор."""
    import httpx

    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"\x00" * 1024)
    monkeypatch.setenv("GROQ_API_KEY", "real-key\r\n")   # CRLF как в .env Windows

    captured_headers = {}

    class _FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"language": "ru", "words": []}

    def _fake_post(url, *, headers, **k):
        captured_headers.update(headers)
        return _FakeResp()

    monkeypatch.setattr("httpx.post", _fake_post)

    backend = T.GroqBackend()
    backend._default_request(audio, "ru")

    auth = captured_headers.get("Authorization", "")
    assert auth == "Bearer real-key"   # без \r\n


def test_groq_default_request_raises_on_oversized_audio(tmp_path, monkeypatch):
    """Аудио больше 24 МБ → внятная ошибка ДО отправки (не «Server disconnected»)."""
    audio = tmp_path / "big.wav"
    # Создаём файл > GROQ_MAX_AUDIO_BYTES (размер реального файла, содержимое не важно)
    oversized = T.GROQ_MAX_AUDIO_BYTES + 1
    audio.write_bytes(b"\x00" * oversized)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    backend = T.GroqBackend()
    with pytest.raises(T.TranscriptionError) as exc:
        backend._default_request(audio, "ru")

    assert "лимит" in str(exc.value).lower() or "limit" in str(exc.value).lower() or "мин" in str(exc.value)
    assert "чанкинг" in str(exc.value).lower() or "M1" in str(exc.value)


def test_groq_default_request_retries_on_disconnect(tmp_path, monkeypatch):
    """RemoteProtocolError (разрыв соединения) → retry, после успешного ответа возвращает данные."""
    import httpx

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"\x00" * 1024)   # маленький файл — pre-flight не срабатывает
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    data = {"language": "Russian", "words": [{"word": "тест", "start": 0.0, "end": 0.5}]}
    call_count = 0

    class _FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return data

    def _fake_post(*a, **k):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.RemoteProtocolError("Server disconnected", request=None)
        return _FakeResp()

    monkeypatch.setattr(T, "time", type("T", (), {"sleep": staticmethod(lambda _: None)})())
    monkeypatch.setattr("httpx.post", _fake_post)

    backend = T.GroqBackend()
    result = backend._default_request(audio, "ru")
    assert result == data
    assert call_count == 2   # первая попытка упала, вторая успешна


def test_groq_default_request_raises_after_all_retries_exhausted(tmp_path, monkeypatch):
    """Если все retry исчерпаны → TranscriptionError, не голый RemoteProtocolError."""
    import httpx

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"\x00" * 1024)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    monkeypatch.setattr(T, "time", type("T", (), {"sleep": staticmethod(lambda _: None)})())
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **k: (_ for _ in ()).throw(httpx.RemoteProtocolError("Server disconnected", request=None)),
    )

    backend = T.GroqBackend()
    with pytest.raises(T.TranscriptionError) as exc:
        backend._default_request(audio, "ru")
    assert "попыт" in str(exc.value).lower()   # «попыток» или «попытки»


def test_groq_403_raises_key_error_immediately(tmp_path, monkeypatch):
    """HTTP 403 → внятная ошибка про ключ, без ретраев."""
    import httpx

    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"\x00" * 1024)
    monkeypatch.setenv("GROQ_API_KEY", "bad-key")

    call_count = 0

    class _FakeResp:
        status_code = 403
        def raise_for_status(self): pass
        def json(self): return {}

    def _fake_post(*a, **k):
        nonlocal call_count
        call_count += 1
        return _FakeResp()

    monkeypatch.setattr("httpx.post", _fake_post)

    backend = T.GroqBackend()
    with pytest.raises(T.TranscriptionError) as exc:
        backend._default_request(audio, "ru")

    assert "403" in str(exc.value)
    assert "GROQ_API_KEY" in str(exc.value)
    assert call_count == 1   # нет ретраев


def test_groq_401_raises_key_error_immediately(tmp_path, monkeypatch):
    """HTTP 401 → внятная ошибка про ключ, без ретраев."""
    import httpx

    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"\x00" * 1024)
    monkeypatch.setenv("GROQ_API_KEY", "bad-key")

    call_count = 0

    class _FakeResp:
        status_code = 401
        def raise_for_status(self): pass
        def json(self): return {}

    def _fake_post(*a, **k):
        nonlocal call_count
        call_count += 1
        return _FakeResp()

    monkeypatch.setattr("httpx.post", _fake_post)

    backend = T.GroqBackend()
    with pytest.raises(T.TranscriptionError) as exc:
        backend._default_request(audio, "ru")

    assert "401" in str(exc.value)
    assert "GROQ_API_KEY" in str(exc.value)
    assert call_count == 1   # нет ретраев


# ------------------------------------------------------ chunking dispatch

def test_transcribe_routes_to_chunked_when_over_threshold(tmp_path, monkeypatch):
    """transcribe() на аудио >порога → вызывает transcribe_chunked, НЕ backend.transcribe."""
    from autoreels.core.config import AudioExtract, ChunkingConfig
    from autoreels.core.models import Transcript, Word
    from autoreels.cloud import chunk_transcribe as CT

    audio = tmp_path / "long.mp3"
    audio.write_bytes(b"\x00" * 1024)

    # Мок: длительность = 20 мин (> 15 мин порог)
    monkeypatch.setattr(CT, "_probe_duration", lambda path, ffmpeg: 20 * 60.0)

    chunked_called = []

    def _fake_transcribe_chunked(path, cfg, acfg, cache_dir, backend, **kw):
        chunked_called.append(True)
        return Transcript(language="ru", words=[Word(word="ок", t0=0.0, t1=0.5)]), []

    monkeypatch.setattr(CT, "transcribe_chunked", _fake_transcribe_chunked)

    chunking_cfg = ChunkingConfig(whisper_threshold_minutes=15)
    audio_cfg    = AudioExtract(sample_rate=16000, channels=1,
                                codec="libmp3lame", format="mp3", bitrate="64k")

    result = T.transcribe(audio, tmp_path,
                          chunking_cfg=chunking_cfg, audio_cfg=audio_cfg)

    assert chunked_called, "transcribe_chunked не был вызван для длинного аудио"
    assert result.words[0].word == "ок"


def test_transcribe_single_request_when_under_threshold(tmp_path, monkeypatch):
    """transcribe() на аудио <=порога → одиночный backend.transcribe, не chunked."""
    from autoreels.core.config import AudioExtract, ChunkingConfig
    from autoreels.core.models import Transcript, Word
    from autoreels.cloud import chunk_transcribe as CT

    audio = tmp_path / "short.mp3"
    audio.write_bytes(b"\x00" * 1024)

    # Мок: длительность = 5 мин (< 15 мин порог)
    monkeypatch.setattr(CT, "_probe_duration", lambda path, ffmpeg: 5 * 60.0)

    chunked_called = []
    monkeypatch.setattr(CT, "transcribe_chunked",
                        lambda *a, **k: chunked_called.append(True) or (Transcript(language="ru", words=[]), []))

    class _Backend:
        def transcribe(self, path, *, language=None):
            return Transcript(language="ru", words=[Word(word="коротко", t0=0.0, t1=0.5)])

    chunking_cfg = ChunkingConfig(whisper_threshold_minutes=15)
    audio_cfg    = AudioExtract(sample_rate=16000, channels=1,
                                codec="libmp3lame", format="mp3", bitrate="64k")

    result = T.transcribe(audio, tmp_path,
                          backend=_Backend(),
                          chunking_cfg=chunking_cfg, audio_cfg=audio_cfg)

    assert not chunked_called, "transcribe_chunked не должен вызываться для короткого аудио"
    assert result.words[0].word == "коротко"


def test_transcribe_no_chunking_cfg_uses_single_request(tmp_path):
    """transcribe() без chunking_cfg → всегда одиночный запрос (обратная совместимость)."""
    from autoreels.core.models import Transcript, Word

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"\x00" * 1024)

    class _Backend:
        def transcribe(self, path, *, language=None):
            return Transcript(language="ru", words=[Word(word="тест", t0=0.0, t1=0.5)])

    result = T.transcribe(audio, tmp_path, backend=_Backend())
    assert result.words[0].word == "тест"


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
