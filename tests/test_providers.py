"""LLM-провайдер (cloud/providers.py) — Qwen через Groq chat + OpenRouter failover.

Это НЕ Whisper-слой (тот в transcribe.py): здесь чат-комплишены/токены. Тесты мокнуты
через инъекцию request_fn, сеть не дёргается.
"""
import pytest

from autoreels.cloud.providers import (
    FallbackLLM, GroqLLM, OpenRouterLLM, ProviderError, ProviderExhausted,
)


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


# ----------------------------------------------------------------- 404: модель устарела

def test_404_model_not_found_clear_error(monkeypatch):
    """404 от Groq (модель убрана/переименована) → внятная ошибка с именем и подсказкой,
    а не голый HTTP 404."""
    import autoreels.cloud.providers as P

    def fake_post(url, *, headers, json, timeout):
        return _FakeResp(404, body={"error": {"message": "model not found"}})

    monkeypatch.setattr(P, "_httpx_post", fake_post)
    monkeypatch.setenv("GROQ_API_KEY", "testkey")

    llm = GroqLLM(model="qwen/does-not-exist")
    with pytest.raises(ProviderError) as exc:
        llm.complete([{"role": "user", "content": "hi"}])
    msg = str(exc.value)
    assert "qwen/does-not-exist" in msg      # какая модель не найдена
    assert "config/r0.yaml" in msg           # где чинить
    assert "404" in msg


def test_default_model_is_current_groq_qwen():
    """Дефолтная модель провайдера — актуальная на Groq (не удалённая qwen3-32b)."""
    from autoreels.cloud.providers import DEFAULT_LLM_MODEL
    assert DEFAULT_LLM_MODEL == "qwen/qwen3.6-27b"


# ========================================================= ProviderExhausted / failover

def test_groq_raises_provider_exhausted_on_long_retry_after(monkeypatch):
    """Groq 429 с retry-after >= порога → ProviderExhausted немедленно, без ожидания."""
    import autoreels.cloud.providers as P
    sleeps = []
    monkeypatch.setattr(P.time, "sleep", lambda s: sleeps.append(s))

    def fake_post(url, *, headers, json, timeout):
        return _FakeResp(429, headers={"retry-after": str(P._EXHAUSTED_THRESHOLD_SEC)})

    monkeypatch.setattr(P, "_httpx_post", fake_post)
    monkeypatch.setenv("GROQ_API_KEY", "testkey")

    llm = GroqLLM()
    with pytest.raises(ProviderExhausted) as exc:
        llm.complete([{"role": "user", "content": "hi"}])
    assert "Groq" in str(exc.value)
    assert sleeps == [], "не должно быть sleep при exhausted"


def test_groq_still_waits_on_short_retry_after(monkeypatch):
    """Groq 429 с retry-after ниже порога → ждёт и ретраит (прежнее поведение)."""
    import autoreels.cloud.providers as P
    sleeps = []
    monkeypatch.setattr(P.time, "sleep", lambda s: sleeps.append(s))

    attempt = [0]

    def fake_post(url, *, headers, json, timeout):
        attempt[0] += 1
        if attempt[0] == 1:
            return _FakeResp(429, headers={"retry-after": "5"})
        return _FakeResp(200, _good_envelope())

    monkeypatch.setattr(P, "_httpx_post", fake_post)
    monkeypatch.setenv("GROQ_API_KEY", "testkey")

    result = GroqLLM().complete([{"role": "user", "content": "hi"}])
    assert result == '{"segments": []}'
    assert sleeps == [5.0]


def test_openrouter_llm_uses_correct_url_and_key(monkeypatch):
    """OpenRouterLLM POST идёт на OpenRouter API с Bearer ключом."""
    import autoreels.cloud.providers as P
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append({"url": url, "auth": headers.get("Authorization", "")})
        return _FakeResp(200, _good_envelope())

    monkeypatch.setattr(P, "_httpx_post", fake_post)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-testkey")

    llm = OpenRouterLLM()
    result = llm.complete([{"role": "user", "content": "hi"}])
    assert result == '{"segments": []}'
    assert calls[0]["url"] == P.OPENROUTER_CHAT_URL
    assert calls[0]["auth"] == "Bearer or-testkey"


def test_openrouter_llm_missing_key_raises(monkeypatch):
    """OpenRouterLLM без OPENROUTER_API_KEY → ProviderError с внятным сообщением."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    llm = OpenRouterLLM()
    with pytest.raises(ProviderError) as exc:
        llm.complete([{"role": "user", "content": "hi"}])
    assert "OPENROUTER_API_KEY" in str(exc.value)


def test_fallback_llm_returns_first_provider_result():
    """FallbackLLM возвращает ответ первого провайдера если он работает."""
    primary = GroqLLM(request_fn=lambda m, t: _good_envelope())
    secondary = GroqLLM(request_fn=lambda m, t: (_ for _ in ()).throw(AssertionError("не должно вызываться")))
    fb = FallbackLLM([primary, secondary])
    assert fb.complete([]) == '{"segments": []}'


def test_fallback_llm_switches_on_exhausted():
    """FallbackLLM переключается на второй провайдер при ProviderExhausted первого."""
    primary = GroqLLM(request_fn=lambda m, t: (_ for _ in ()).throw(ProviderExhausted("Groq исчерпан")))
    secondary = GroqLLM(request_fn=lambda m, t: _good_envelope())
    fb = FallbackLLM([primary, secondary])
    assert fb.complete([]) == '{"segments": []}'


def test_fallback_llm_raises_when_all_exhausted():
    """FallbackLLM поднимает ProviderError когда все провайдеры исчерпаны."""
    def _exhausted(m, t):
        raise ProviderExhausted("лимит")
    fb = FallbackLLM([GroqLLM(request_fn=_exhausted), GroqLLM(request_fn=_exhausted)])
    with pytest.raises(ProviderError, match="все провайдеры"):
        fb.complete([])


def test_fallback_llm_prints_switch_message(capsys):
    """FallbackLLM печатает сообщение о переключении провайдера."""
    primary = GroqLLM(request_fn=lambda m, t: (_ for _ in ()).throw(ProviderExhausted("Groq исчерпан")))
    secondary = GroqLLM(request_fn=lambda m, t: _good_envelope())
    FallbackLLM([primary, secondary]).complete([])
    out = capsys.readouterr().out
    assert "OpenRouter" in out or "провайдер" in out.lower()
