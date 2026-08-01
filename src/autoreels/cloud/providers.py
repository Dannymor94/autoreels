"""LLM-провайдер: Qwen через Groq chat-completions (для R0) + OpenRouter failover.

Это НЕ Whisper-слой (транскрипция — в transcribe.py). Здесь чат-комплишены/токены:
выбор моментов (select.py) ходит сюда.

Failover-цепочка: GroqLLM → OpenRouterLLM, собирается через FallbackLLM([...]).
При retry-after >= _EXHAUSTED_THRESHOLD_SEC Groq поднимает ProviderExhausted →
FallbackLLM ловит и переключается на OpenRouter, печатая сообщение пользователю.
API-ключи (GROQ_API_KEY, OPENROUTER_API_KEY) — только из окружения/.env, не в коде.
Тестируемость: инъекция `request_fn` (messages, temperature) -> сырой dict ответа.
"""
from __future__ import annotations

import os
import time
from typing import Callable, Protocol

import httpx

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

# Актуальная Qwen на Groq. Модель конфигурируема через config/r0.yaml (model:).
DEFAULT_LLM_MODEL = "qwen/qwen3.6-27b"
# Бесплатная модель OpenRouter для failover. Выбрана Qwen — тот же семейство,
# хорошая поддержка русского, JSON-mode.
DEFAULT_OPENROUTER_MODEL = "qwen/qwen3-8b:free"

# qwen3 — reasoning-модель; reasoning раздувает выходные токены → упор в 6K TPM.
# "none" глушит reasoning (Groq принимает только none|default).
DEFAULT_REASONING_EFFORT = "none"

_MAX_THROTTLE_RETRIES = 4
_THROTTLE_PAUSE_SEC = 8.0       # страховка, если retry-after не пришёл (413/429)
_EXHAUSTED_THRESHOLD_SEC = 120.0  # retry-after выше порога → дневной лимит, не минутный


def _httpx_post(url, *, headers, json, timeout):
    """Тонкая обёртка над httpx.post — вынесена на модульный уровень для monkeypatch в тестах."""
    return httpx.post(url, headers=headers, json=json, timeout=timeout)


class ProviderError(Exception):
    """Проблема LLM-провайдера (нет ключа, троттлинг, неожиданный формат ответа)."""


class ProviderExhausted(ProviderError):
    """Провайдер исчерпал суточный/часовой лимит (retry-after слишком большой).

    FallbackLLM ловит это исключение и переключается на следующий провайдер в цепочке.
    """


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
        api_key = self._api_key or os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ProviderError("нет GROQ_API_KEY — задайте ключ Groq в окружении для R0")

        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        if self._reasoning_effort is not None:
            payload["reasoning_effort"] = self._reasoning_effort

        headers = {"Authorization": f"Bearer {api_key}"}
        last_status: int | None = None
        for _ in range(_MAX_THROTTLE_RETRIES):
            resp = _httpx_post(GROQ_CHAT_URL, headers=headers, json=payload, timeout=120)
            if resp.status_code in (429, 413):
                last_status = resp.status_code
                wait = float(resp.headers.get("retry-after", _THROTTLE_PAUSE_SEC))
                # Длинный retry-after = суточный лимит исчерпан → сигнал для failover.
                if wait >= _EXHAUSTED_THRESHOLD_SEC:
                    raise ProviderExhausted(
                        f"Groq суточный лимит исчерпан (retry-after={wait:.0f}с) — "
                        f"переключаюсь на OpenRouter"
                    )
                from autoreels.core.progress import throttle_wait as _throttle_wait
                _throttle_wait(wait)
                time.sleep(wait)
                continue
            if resp.status_code == 404:
                raise ProviderError(
                    f"модель '{self._model}' не найдена на Groq (404) — вероятно снята "
                    f"или переименована. Укажи актуальную в config/r0.yaml (model:). "
                    f"Список моделей: curl -s {GROQ_MODELS_URL} "
                    f"-H \"Authorization: Bearer $GROQ_API_KEY\"  "
                    f"(или https://console.groq.com/docs/models)"
                )
            try:
                resp.raise_for_status()
            except httpx.HTTPError as e:
                raise ProviderError(f"Groq chat API ошибка: {e}") from e
            return resp.json()
        raise ProviderError(
            f"Groq троттлит (HTTP {last_status}) после {_MAX_THROTTLE_RETRIES} ретраев — "
            f"{'rate limit (429): подождите или уменьшите r0_chunk_tokens' if last_status == 429 else 'payload/TPM (413): уменьшите r0_chunk_tokens в config/r0.yaml'}"
        )


class OpenRouterLLM:
    """OpenRouter chat-completions — failover при исчерпании Groq.

    Ключ OPENROUTER_API_KEY только из окружения/.env. Интерфейс идентичен GroqLLM.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_OPENROUTER_MODEL,
        api_key: str | None = None,
        request_fn: Callable[[list[dict], float], dict] | None = None,
    ):
        self._model = model
        self._api_key = api_key
        self._request_fn = request_fn

    def complete(self, messages: list[dict], *, temperature: float = 0.0) -> str:
        request = self._request_fn or self._default_request
        data = request(messages, temperature)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"неожиданный формат ответа OpenRouter: {e}") from e

    def _default_request(self, messages: list[dict], temperature: float) -> dict:
        api_key = self._api_key or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ProviderError(
                "нет OPENROUTER_API_KEY — добавьте в .env для failover на OpenRouter"
            )
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/Dannymor94/autoreels",
            "X-Title": "autoreels",
        }
        last_status: int | None = None
        for _ in range(_MAX_THROTTLE_RETRIES):
            resp = _httpx_post(OPENROUTER_CHAT_URL, headers=headers, json=payload, timeout=120)
            if resp.status_code == 429:
                last_status = 429
                wait = float(resp.headers.get("retry-after", _THROTTLE_PAUSE_SEC))
                if wait >= _EXHAUSTED_THRESHOLD_SEC:
                    raise ProviderExhausted(
                        f"OpenRouter суточный лимит исчерпан (retry-after={wait:.0f}с)"
                    )
                from autoreels.core.progress import throttle_wait as _throttle_wait
                _throttle_wait(wait)
                time.sleep(wait)
                continue
            try:
                resp.raise_for_status()
            except httpx.HTTPError as e:
                raise ProviderError(f"OpenRouter chat API ошибка: {e}") from e
            return resp.json()
        raise ProviderError(
            f"OpenRouter троттлит (HTTP {last_status}) после {_MAX_THROTTLE_RETRIES} ретраев"
        )


class FallbackLLM:
    """Цепочка провайдеров: при ProviderExhausted переключается на следующий.

    Пример: FallbackLLM([GroqLLM(), OpenRouterLLM()])
    При исчерпании Groq печатает сообщение и переходит на OpenRouter.
    """

    def __init__(self, providers: list) -> None:
        self._providers = list(providers)
        self._current = 0

    def complete(self, messages: list[dict], *, temperature: float = 0.0) -> str:
        while self._current < len(self._providers):
            try:
                return self._providers[self._current].complete(
                    messages, temperature=temperature
                )
            except ProviderExhausted as e:
                self._current += 1
                if self._current < len(self._providers):
                    print(
                        f"\n  ℹ {e} — переключаюсь на следующий провайдер "
                        f"(OpenRouter #{self._current})",
                        flush=True,
                    )
                    continue
        raise ProviderError("все провайдеры исчерпаны — добавьте ключи или подождите сброса квоты")
