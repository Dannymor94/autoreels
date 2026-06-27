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
