"""LLM-провайдер: Qwen через Groq chat-completions (для R0).

Это НЕ Whisper-слой (транскрипция — в transcribe.py). Здесь чат-комплишены/токены:
выбор моментов (select.py) ходит сюда.

MVP-0: один провайдер (Groq) + минимальный бэкофф по 429 (retry-after). Полный троттлинг
по заголовкам x-ratelimit и OpenRouter-failover — M1 (интерфейс заложен, не реализован).
API-ключ (GROQ_API_KEY) — только из окружения/.env, никогда не в коде/конфиге.
Тестируемость: инъекция `request_fn` (messages, temperature) -> сырой dict ответа.
"""
from __future__ import annotations

import os
from typing import Callable, Protocol

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_LLM_MODEL = "qwen/qwen3-32b"
# qwen3 — reasoning-модель. Для структурной выборки по чёткой рубрике глубокий reasoning
# не нужен и раздувает выходные токены → упор в 6K TPM Groq (413). "none" глушит его
# (Groq принимает только none|default). Заметно снижает выхлоп, убирает перемежающийся 413.
DEFAULT_REASONING_EFFORT = "none"
_MAX_THROTTLE_RETRIES = 4
_THROTTLE_PAUSE_SEC = 8.0  # пауза-страховка, если retry-after не пришёл (413/429)


class ProviderError(Exception):
    """Проблема LLM-провайдера (нет ключа, троттлинг, неожиданный формат ответа)."""


class LLMProvider(Protocol):
    def complete(self, messages: list[dict], *, temperature: float = 0.0) -> str: ...


class GroqLLM:
    """Groq chat-completions. Ключ нужен только при вызове, не при создании."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_LLM_MODEL,
        api_key: str | None = None,
        reasoning_effort: str | None = DEFAULT_REASONING_EFFORT,
        request_fn: Callable[[list[dict], float], dict] | None = None,
    ):
        self._reasoning_effort = reasoning_effort
        self._model = model
        self._api_key = api_key
        self._request_fn = request_fn

    def complete(self, messages: list[dict], *, temperature: float = 0.0) -> str:
        """Вернуть текст ответа модели (content первого choice)."""
        request = self._request_fn or self._default_request
        data = request(messages, temperature)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"неожиданный формат ответа LLM: {e}") from e

    def _default_request(self, messages: list[dict], temperature: float) -> dict:
        import time

        import httpx

        api_key = self._api_key or os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ProviderError("нет GROQ_API_KEY — задайте ключ Groq в окружении для R0")

        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            # Строгий JSON-контракт R0 → просим объект, не свободный текст.
            "response_format": {"type": "json_object"},
        }
        if self._reasoning_effort is not None:
            payload["reasoning_effort"] = self._reasoning_effort  # глушим reasoning (TPM)

        headers = {"Authorization": f"Bearer {api_key}"}
        for _ in range(_MAX_THROTTLE_RETRIES):
            resp = httpx.post(GROQ_CHAT_URL, headers=headers, json=payload, timeout=120)
            # 429 (rate) и 413 (payload/TPM) — троттлинг: страховочный ретрай с паузой.
            # Основное лечение 413 — приглушённый reasoning выше. Полный троттлинг по
            # x-ratelimit + чанкинг — M1.
            if resp.status_code in (429, 413):
                time.sleep(float(resp.headers.get("retry-after", _THROTTLE_PAUSE_SEC)))
                continue
            try:
                resp.raise_for_status()
            except httpx.HTTPError as e:
                raise ProviderError(f"Groq chat API ошибка: {e}") from e
            return resp.json()
        raise ProviderError("Groq троттлит (429/413) после ретраев")
