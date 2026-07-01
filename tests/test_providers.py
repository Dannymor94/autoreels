"""LLM-провайдер (cloud/providers.py) — Qwen через Groq chat.

Это НЕ Whisper-слой (тот в transcribe.py): здесь чат-комплишены/токены. Тесты мокнуты
через инъекцию request_fn, сеть не дёргается.
"""
import pytest

from autoreels.cloud.providers import GroqLLM, ProviderError


def test_complete_extracts_content():
    envelope = {"choices": [{"message": {"content": '{"segments": []}'}}]}
    llm = GroqLLM(request_fn=lambda messages, temperature: envelope)
    assert llm.complete([{"role": "user", "content": "hi"}]) == '{"segments": []}'


def test_complete_bad_envelope_raises():
    llm = GroqLLM(request_fn=lambda messages, temperature: {"unexpected": True})
    with pytest.raises(ProviderError):
        llm.complete([{"role": "user", "content": "hi"}])


def test_missing_api_key_raises(monkeypatch):
    # Без request_fn и без ключа — внятная ошибка до сети.
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    llm = GroqLLM()
    with pytest.raises(ProviderError) as e:
        llm.complete([{"role": "user", "content": "hi"}])
    assert "GROQ_API_KEY" in str(e.value)


# ----------------------------------------------------------------- throttle / retry

class _FakeResp:
    """Минимальный stub httpx.Response для тестов провайдера."""
    def __init__(self, status_code: int, body: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._body = body or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=self)

    def json(self):
        return self._body


def _good_envelope():
    return {"choices": [{"message": {"content": '{"segments": []}'}}]}


def test_429_retries_and_raises_with_status_code(monkeypatch):
    """429 от Groq: ретраи (до MAX), итог — ProviderError с '429' в сообщении."""
    import autoreels.cloud.providers as P
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append(1)
        return _FakeResp(429, headers={"retry-after": "0"})

    monkeypatch.setattr(P, "_httpx_post", fake_post)
    monkeypatch.setenv("GROQ_API_KEY", "testkey")

    llm = GroqLLM()
    with pytest.raises(ProviderError) as exc:
        llm.complete([{"role": "user", "content": "hi"}])
    assert "429" in str(exc.value)
    assert len(calls) == P._MAX_THROTTLE_RETRIES


def test_413_retries_and_raises_with_status_code(monkeypatch):
    """413 от Groq: ретраи, итог — ProviderError с '413' в сообщении."""
    import autoreels.cloud.providers as P
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append(1)
        return _FakeResp(413, headers={})

    monkeypatch.setattr(P, "_httpx_post", fake_post)
    monkeypatch.setenv("GROQ_API_KEY", "testkey")

    llm = GroqLLM()
    with pytest.raises(ProviderError) as exc:
        llm.complete([{"role": "user", "content": "hi"}])
    assert "413" in str(exc.value)


def test_429_reads_retry_after_header(monkeypatch):
    """retry-after заголовок → sleep именно столько секунд (не fallback)."""
    import autoreels.cloud.providers as P
    sleeps = []
    monkeypatch.setattr(P.time, "sleep", lambda s: sleeps.append(s))

    attempt = [0]

    def fake_post(url, *, headers, json, timeout):
        attempt[0] += 1
        if attempt[0] < P._MAX_THROTTLE_RETRIES:
            return _FakeResp(429, headers={"retry-after": "7"})
        return _FakeResp(200, _good_envelope())

    monkeypatch.setattr(P, "_httpx_post", fake_post)
    monkeypatch.setenv("GROQ_API_KEY", "testkey")

    llm = GroqLLM()
    llm.complete([{"role": "user", "content": "hi"}])
    assert sleeps and all(s == 7.0 for s in sleeps), f"ожидали sleep(7), получили {sleeps}"


def test_success_after_one_429(monkeypatch):
    """Один 429, затем 200 → успешный ответ без исключения."""
    import autoreels.cloud.providers as P
    monkeypatch.setattr(P.time, "sleep", lambda s: None)

    attempt = [0]

    def fake_post(url, *, headers, json, timeout):
        attempt[0] += 1
        if attempt[0] == 1:
            return _FakeResp(429, headers={"retry-after": "0"})
        return _FakeResp(200, _good_envelope())

    monkeypatch.setattr(P, "_httpx_post", fake_post)
    monkeypatch.setenv("GROQ_API_KEY", "testkey")

    result = GroqLLM().complete([{"role": "user", "content": "hi"}])
    assert result == '{"segments": []}'
