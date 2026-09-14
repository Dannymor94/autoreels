"""LLM-провайдеры для R0: Qwen через Groq + OpenRouter, с распределением нагрузки.

Это НЕ Whisper-слой (транскрипция — в transcribe.py). Здесь чат-комплишены/токены:
выбор моментов (select.py) ходит сюда.

Зачем два провайдера. Часовое видео = ~51 R0-чанк упирается в дневную квоту Groq (free
tier): паузы до сотен секунд, прогон растягивается на часы. Распределение чанков между
Groq и OpenRouter увеличивает пропускную способность и отодвигает упор в лимит.

Слои:
- GroqLLM / OpenRouterLLM — один HTTP-запрос к OpenAI-совместимому chat API. Общая логика
  запроса/троттлинга — в `_chat_request`. В `defer_throttle`-режиме короткий 429 не спится
  внутри, а поднимается как ProviderThrottled, чтобы РОУТЕР увёл чанк на другой провайдер.
- ProviderPool — quota-aware роутер: держит провайдеров с состоянием кулдауна, льёт каждый
  запрос на лучший СВОБОДНЫЙ провайдер по стратегии (adaptive|round_robin), пропускает тех,
  кто в лимите, и спит только когда ВСЕ в лимите — с внятной оценкой, кто когда освободится.
- FallbackLLM — простая последовательная цепочка (устаревшая, оставлена для совместимости);
  ProviderPool её обобщает (failover = adaptive с кулдауном во всю квоту).

Стратегии распределения:
- adaptive (дефолт): предпочитать Groq (модель сильнее → качество выборки), сливать на
  OpenRouter только когда Groq троттлит, возвращаться когда Groq остыл. Качество не плавает:
  слабая бесплатная модель включается лишь под нагрузкой, а не на половине чанков.
- round_robin: чередовать провайдеров равномерно. Максимум пропускной, НО половина чанков
  уходит на более слабую модель → качество может плавать. Компромисс включать осознанно.

API-ключи (GROQ_API_KEY, OPENROUTER_API_KEY) — только из окружения/.env, не в коде.
Тестируемость: инъекция `request_fn` (messages, temperature) -> сырой dict ответа;
у пула — инъекция `clock`/`sleep` (детерминизм без реальных пауз).
"""
from __future__ import annotations

import os
import re
import time
from typing import Callable, Protocol

import httpx

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# Актуальная Qwen на Groq. Модель конфигурируема через config/r0.yaml (model:).
DEFAULT_LLM_MODEL = "qwen/qwen3.6-27b"
# Бесплатная модель OpenRouter для распределения нагрузки. Свериться со списком:
# curl -s https://openrouter.ai/api/v1/models | jq -r '.data[].id | select(endswith(":free"))'
DEFAULT_OPENROUTER_MODEL = "mistralai/mistral-small-3.1-24b-instruct:free"
DEFAULT_OPENROUTER_FALLBACKS = [
    "meta-llama/llama-3.1-8b-instruct:free",
    "google/gemma-2-9b-it:free",
]

# qwen3 — reasoning-модель; reasoning раздувает выходные токены → упор в 6K TPM.
# "none" глушит reasoning (Groq принимает только none|default).
DEFAULT_REASONING_EFFORT = "none"

_MAX_THROTTLE_RETRIES = 4
_THROTTLE_PAUSE_SEC = 8.0       # страховка, если retry-after не пришёл (413/429)
_EXHAUSTED_THRESHOLD_SEC = 120.0  # retry-after выше порога → дневной лимит, не минутный
_EMPTY_COOLDOWN_SEC = 1.0      # короткий кулдаун провайдера после пустого ответа (сиблинг подхватит)
_MAX_EMPTY_RESPONSES = 3       # сколько пустых ответов терпит пул за один запрос до чанк-фейла

# Сетевые таймауты R0. read большой: LLM (reasoning) думает долго на больших чанках; connect
# короткий — недоступный хост не должен висеть. Таймаут = транзиентный сбой (как пустой ответ).
_R0_READ_TIMEOUT_SEC = 300.0   # было 120 total → мало для длинных чанков, ловили read timeout
_R0_CONNECT_TIMEOUT_SEC = 10.0
_TIMEOUT_RETRIES_SAME = 2      # ретраи на ТОМ ЖЕ провайдере при таймауте (транзиентный блип)
_TIMEOUT_BACKOFF_SEC = 2.0     # короткий бэкофф между ретраями на том же провайдере
_MAX_TIMEOUTS = 3             # сколько таймаутов терпит пул (по сиблингам) до чанк-фейла
_TIMEOUT_COOLDOWN_SEC = 2.0

# Защита пула от бесконечного спина на одном провайдере.
# ponytail: flat constants, move to config if per-preset tuning needed
_POOL_MAX_CONSEC_FAILURES = 5    # после N подряд throttled/exhausted — экспоненциальный бэкофф
_POOL_BUDGET_SEC = 600.0         # суммарный бюджет ожидания на один complete() — 10 мин
_POOL_BACKOFF_BASE_SEC = 60.0    # база экспоненциального бэкоффа (×2^n, cap 3600с)

# Groq free-tier: conservative fallback when x-ratelimit-* headers absent.
# ponytail: flat constant; expose via build_pool/config if per-key tuning needed
_GROQ_FREE_FALLBACK_DELAY_SEC = 60.0
# Groq chat-template adds ~200 special tokens (BOS, role markers, etc.) on top of text content.
# Used in pacing and max_tokens computation so both mirror the actual admission check.
_GROQ_CHAT_TEMPLATE_OVERHEAD = 400  # conservative: 200 template + 200 buffer

# Допустимые стратегии распределения пула (валидируются на входе, fail-fast).
POOL_STRATEGIES = ("adaptive", "round_robin")


def _count_tokens_approx(text: str) -> int:
    """4 chars ≈ 1 token — rough but consistent with select.py's _count_tokens."""
    return max(1, len(text) // 4)


def _parse_groq_reset(s: str) -> float | None:
    """Parse Groq x-ratelimit-reset-* value ('29.5s', '1m29.5s') → seconds float."""
    m = re.match(r'^(?:(\d+)m)?(\d+(?:\.\d+)?)s$', str(s).strip())
    if m:
        return int(m.group(1) or 0) * 60 + float(m.group(2))
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _httpx_post(url, *, headers, json, timeout):
    """Тонкая обёртка над httpx.post — вынесена на модульный уровень для monkeypatch в тестах."""
    return httpx.post(url, headers=headers, json=json, timeout=timeout)


def _post_r0(url, *, headers, payload, provider_name):
    """POST к chat API с увеличенным read-timeout и ретраями на ТОМ ЖЕ провайдере при сетевом
    таймауте (read/connect) или обрыве соединения. Исчерпав ретраи — ProviderTimeout
    (транзиентный: пул уведёт на сиблинга, затем чанк-фейл, а не падение всего видео)."""
    timeout = httpx.Timeout(_R0_READ_TIMEOUT_SEC, connect=_R0_CONNECT_TIMEOUT_SEC,
                            write=30.0, pool=10.0)
    last: Exception | None = None
    for attempt in range(_TIMEOUT_RETRIES_SAME + 1):
        try:
            return _httpx_post(url, headers=headers, json=payload, timeout=timeout)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last = e
            if attempt < _TIMEOUT_RETRIES_SAME:
                time.sleep(_TIMEOUT_BACKOFF_SEC)
                continue
    raise ProviderTimeout(
        f"{provider_name}: сетевой таймаут R0-запроса (read>{_R0_READ_TIMEOUT_SEC:.0f}с) "
        f"после {_TIMEOUT_RETRIES_SAME + 1} попыток: {type(last).__name__}: {last}",
        provider=provider_name,
    )


def _httpx_get(url, *, headers, timeout):
    """Тонкая обёртка над httpx.get — модульный уровень для monkeypatch (префлайт /models)."""
    return httpx.get(url, headers=headers, timeout=timeout)


class ProviderError(Exception):
    """Проблема LLM-провайдера (нет ключа, троттлинг, неожиданный формат ответа)."""


class ProviderEmptyResponse(ProviderError):
    """Провайдер вернул HTTP 200, но пустое/None тело вместо JSON (перегрузка/исчерпанная квота).

    Мягкий транзиентный сбой (НЕ конфиг-ошибка): пул пробует сиблинга, а select трактует как
    провал ЧАНКА (retry → sibling → failed-чанк), не роняя всё видео. Несёт имя провайдера."""

    def __init__(self, message: str, *, provider: str = ""):
        super().__init__(message)
        self.provider = provider


class ProviderTimeout(ProviderError):
    """Сетевой таймаут чтения ответа (read/connect timeout) или обрыв соединения.

    Транзиентный сбой (как ProviderEmptyResponse): _post_r0 ретраит на ТОМ ЖЕ провайдере,
    пул уводит на сиблинга, select трактует как провал ЧАНКА — всё видео НЕ падает."""

    def __init__(self, message: str, *, provider: str = ""):
        super().__init__(message)
        self.provider = provider


class ProviderModelNotFound(ProviderError):
    """Провайдер вернул 404 на chat/completions — модель в конфиге не существует/недоступна.

    Это КОНФИГ-ошибка (неверное `model`/`openrouter_model`), а не транзиентный сбой: пул
    ловит её, ИСКЛЮЧАЕТ провайдера из ротации навсегда и продолжает на остальных — один
    неверный openrouter_model не должен ронять весь прогон после успешной транскрипции.
    """

    def __init__(self, message: str, *, model: str = "", provider: str = ""):
        super().__init__(message)
        self.model = model
        self.provider = provider


class ProviderThrottled(ProviderError):
    """Транзиентный лимит (per-minute TPM/RPM). Несёт retry_after, чтобы пул успел
    пометить провайдера остывающим и увести запрос на другого — а не ждать впустую."""

    def __init__(self, message: str, *, retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderExhausted(ProviderError):
    """Провайдер исчерпал суточный/часовой лимит (retry-after слишком большой).

    Пул трактует это как ДЛИННЫЙ кулдаун (не как вечную смерть провайдера): по истечении
    retry_after провайдер снова опрашивается — так реализуется «вернуться когда остынет».
    FallbackLLM же ловит это исключение и переключается на следующий провайдер навсегда.
    """

    def __init__(self, message: str, *, retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderRequestTooLarge(ProviderError):
    """Запрос отклонён (HTTP 413): prompt_tokens + max_tokens превышает лимит окна.

    Не транзиентный — тот же запрос никогда не пройдёт на том же провайдере. Пул пробует
    сиблинга; если провайдер один — поднимает сразу с деталями размеров."""

    def __init__(self, message: str, *, prompt_tokens: int = 0, max_tokens: int = 0, limit: int = 0):
        super().__init__(message)
        self.prompt_tokens = prompt_tokens
        self.max_tokens = max_tokens
        self.limit = limit


class ProviderOTPMExceeded(ProviderError):
    """Groq OTPM (output-tokens-per-minute) cap hit — Type B 429.

    Diagnostic: remaining-tokens == limit-tokens (input never the constraint), no retry-after.
    Waiting is useless; only lowering max_output_tokens in config/r0.yaml helps.
    """

    def __init__(self, message: str, *, otpm_limit: int = 0, max_tokens_sent: int = 0):
        super().__init__(message)
        self.otpm_limit = otpm_limit
        self.max_tokens_sent = max_tokens_sent


class LLMProvider(Protocol):
    def complete(self, messages: list[dict], *, temperature: float = 0.0) -> str: ...


def _chat_request(
    url: str,
    *,
    headers: dict,
    payload: dict,
    provider_name: str,
    defer_throttle: bool,
    not_found_hint: str | None = None,
    out_headers: dict | None = None,
) -> dict:
    """Единый HTTP-цикл к OpenAI-совместимому chat API (Groq и OpenRouter идентичны).

    Троттлинг:
    - retry-after >= порога → ProviderExhausted (суточный лимит) — всегда, независимо от режима;
    - короткий retry-after + defer_throttle=True → ProviderThrottled (пул уведёт на другого);
    - короткий retry-after + defer_throttle=False → ждём и ретраим внутри (standalone-режим).
    404 с `not_found_hint` → внятная ошибка «модель снята/переименована», а не голый HTTP.
    """
    last_status: int | None = None
    for _ in range(_MAX_THROTTLE_RETRIES):
        # Сетевой таймаут/обрыв → ProviderTimeout (ретраи на том же провайдере внутри _post_r0).
        resp = _post_r0(url, headers=headers, payload=payload, provider_name=provider_name)
        # Capture response headers before any raise so callers can read rate-limit state.
        if out_headers is not None:
            out_headers.update({k.lower(): v for k, v in resp.headers.items()})
        if resp.status_code == 413:
            # Non-retryable: prompt+max_tokens exceeds the provider's per-window admission cap.
            # Same request can never succeed on this provider — raise immediately, no retry.
            _rl_keys = [k for k in resp.headers if "ratelimit" in k.lower() or k.lower() == "retry-after"]
            if _rl_keys:
                print(f"  [diag] {provider_name} 413 headers: " +
                      ", ".join(f"{k}={resp.headers[k]}" for k in sorted(_rl_keys)), flush=True)
            limit_hdr = resp.headers.get("x-ratelimit-limit-tokens", "?")
            prompt_tok = sum(_count_tokens_approx(m.get("content") or "") for m in payload.get("messages", []))
            max_tok = payload.get("max_tokens", 0)
            raise ProviderRequestTooLarge(
                f"{provider_name}: 413 — prompt ~{prompt_tok}tok + max_tokens={max_tok} "
                f"превышает лимит {limit_hdr}tok. Уменьши r0_chunk_tokens или max_tokens.",
                prompt_tokens=prompt_tok, max_tokens=max_tok,
                limit=int(limit_hdr) if str(limit_hdr).isdigit() else 0,
            )
        if resp.status_code == 429:
            last_status = resp.status_code
            _rl_keys = [k for k in resp.headers if "ratelimit" in k.lower() or k.lower() == "retry-after"]
            if _rl_keys:
                print(f"  [diag] {provider_name} 429 headers: " +
                      ", ".join(f"{k}={resp.headers[k]}" for k in sorted(_rl_keys)), flush=True)
            # Type B: OTPM hit — remaining==limit (input full), no retry-after. Waiting is useless.
            _remaining = resp.headers.get("x-ratelimit-remaining-tokens")
            _limit = resp.headers.get("x-ratelimit-limit-tokens")
            _has_retry_after = "retry-after" in resp.headers
            if (not _has_retry_after and _remaining is not None and _limit is not None
                    and _remaining == _limit):
                _max_tok = payload.get("max_tokens", 0)
                _otpm_limit = int(_limit) if str(_limit).isdigit() else 0
                raise ProviderOTPMExceeded(
                    f"{provider_name}: OTPM limit {_otpm_limit}/min — waiting won't help; "
                    f"lower max_output_tokens in config/r0.yaml below {_otpm_limit} "
                    f"(sent max_tokens={_max_tok})",
                    otpm_limit=_otpm_limit,
                    max_tokens_sent=_max_tok,
                )
            wait = float(resp.headers.get("retry-after", _THROTTLE_PAUSE_SEC))
            if wait >= _EXHAUSTED_THRESHOLD_SEC:
                raise ProviderExhausted(
                    f"{provider_name} суточный лимит исчерпан (retry-after={wait:.0f}с)",
                    retry_after=wait,
                )
            if defer_throttle:
                raise ProviderThrottled(
                    f"{provider_name} троттлит (retry-after={wait:.0f}с)", retry_after=wait
                )
            from autoreels.core.progress import throttle_wait as _throttle_wait
            _throttle_wait(wait, provider_name)
            time.sleep(wait)
            continue
        if resp.status_code == 404:
            model = payload.get("model", "?")
            raise ProviderModelNotFound(
                not_found_hint or f"{provider_name}: модель '{model}' не найдена (404)",
                model=model, provider=provider_name,
            )
        try:
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise ProviderError(f"{provider_name} chat API ошибка: {e}") from e
        return resp.json()
    raise ProviderError(
        f"{provider_name} троттлит (HTTP 429) после {_MAX_THROTTLE_RETRIES} ретраев — "
        f"подождите или уменьшите r0_chunk_tokens в config/r0.yaml"
    )


def _extract_content(data, provider_name: str) -> str:
    """Достать content первого choice; пустой/None → ProviderEmptyResponse (диагностика).

    Провайдеры на free-tier под нагрузкой иногда отдают HTTP 200 с content=None или пустой
    строкой (оборванный/пустой ответ). Раньше это молча возвращалось наверх → json.loads(None)
    → TypeError, роняя всё видео. Теперь — явный мягкий сбой с указанием, ЧТО пришло."""
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise ProviderError(f"неожиданный формат ответа {provider_name}: {e}") from e
    if content is None or (isinstance(content, str) and not content.strip()):
        raise ProviderEmptyResponse(
            f"{provider_name} вернул пустой ответ (HTTP 200, content={content!r}) — "
            f"вероятно перегрузка/исчерпанная квота",
            provider=provider_name,
        )
    return content


def interpret_provider_status(status: int | None) -> tuple[str, str]:
    """HTTP-код префлайта провайдера → (короткий вердикт, человеческая расшифровка) для doctor.

    None = сеть недоступна/таймаут (не дождались ответа). Расшифровки покрывают ровно то, что
    важно на месте: рабочий ключ, протухший ключ, гео-блок региона, отвал сети/VPN."""
    if status is None:
        return ("нет сети", "нет сети / VPN отвалился (таймаут при обращении к API)")
    if status == 200:
        return ("доступен", "доступен")
    if status == 401:
        return ("401", "ключ неверный или протух")
    if status == 403:
        return ("403", "регион заблокирован — анализ на этой машине невозможен (нужен VPN)")
    if status == 429:
        return ("429", "лимит запросов исчерпан (ключ рабочий) — подожди сброса квоты")
    return (str(status), f"неожиданный ответ HTTP {status}")


def probe_provider(url: str, *, api_key: str | None, get_fn=None, timeout: float = 15.0) -> int | None:
    """Лёгкая live-проверка провайдера: GET /models. Вернуть HTTP-код или None при таймауте/
    сетевой ошибке. Тело ответа не важно — интересует лишь статус (200/401/403/…)."""
    get_fn = get_fn or _httpx_get
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        resp = get_fn(url, headers=headers, timeout=timeout)
    except Exception:  # noqa: BLE001 — любая сетевая ошибка/таймаут → «нет сети»
        return None
    return getattr(resp, "status_code", None)


def _list_models(url: str, *, headers: dict) -> set[str] | None:
    """Список id доступных моделей провайдера (GET /models). None — если проверить нельзя
    (нет ключа/сети/битый ответ): тогда не блокируем — доверяем рантайму (404 отсеет на месте)."""
    try:
        resp = _httpx_get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception:  # noqa: BLE001 — префлайт не должен ронять прогон из-за сети/формата
        return None
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        return None
    ids = {m.get("id") for m in data["data"] if isinstance(m, dict)}
    return {i for i in ids if i}


class GroqLLM:
    """Groq chat-completions. Ключ нужен только при вызове, не при создании."""

    name = "Groq"

    def __init__(
        self,
        *,
        model: str = DEFAULT_LLM_MODEL,
        api_key: str | None = None,
        reasoning_effort: str | None = DEFAULT_REASONING_EFFORT,
        max_output_tokens: int = 900,
        request_fn: Callable[[list[dict], float], dict] | None = None,
        defer_throttle: bool = False,
        fallback_delay_sec: float = _GROQ_FREE_FALLBACK_DELAY_SEC,
        _sleep_fn: Callable[[float], None] | None = None,
        _monotonic_fn: Callable[[], float] | None = None,
    ):
        self._reasoning_effort = reasoning_effort
        self._model = model
        self._api_key = api_key
        self._max_output_tokens = max_output_tokens
        self._request_fn = request_fn
        self._defer_throttle = defer_throttle
        self._fallback_delay_sec = fallback_delay_sec
        self._sleep_fn = _sleep_fn or time.sleep
        self._monotonic_fn = _monotonic_fn or time.monotonic
        # token-budget state (updated from x-ratelimit-* headers after each response)
        self._budget_remaining: int = 999_999
        self._budget_reset_at: float = 0.0
        self._budget_limit: int = 8000   # conservative default; updated from x-ratelimit-limit-tokens
        self._got_budget_headers: bool = False
        self._request_count: int = 0

    def complete(self, messages: list[dict], *, temperature: float = 0.0) -> str:
        """Вернуть текст ответа модели (content первого choice). Пустой → ProviderEmptyResponse."""
        request = self._request_fn or self._default_request
        data = request(messages, temperature)
        return _extract_content(data, self.name)

    def _pace_if_needed(self, total_tokens: int) -> None:
        """Wait before sending if the remaining TPM budget would be exceeded.

        total_tokens = estimated prompt tokens + max_tokens (the full admission cost).
        Two modes:
        - Headers seen: compare remaining against total; sleep until reset + 0.5s buffer.
        - No headers yet: apply fallback_delay_sec on 2nd+ request.
        One log line per wait event.
        """
        now = self._monotonic_fn()
        estimated_tokens = total_tokens  # alias for log messages
        if self._got_budget_headers:
            if self._budget_remaining < total_tokens and self._budget_reset_at > now:
                wait = self._budget_reset_at - now + 0.5
                print(
                    f"\n  ⏳ Groq TPM: remaining={self._budget_remaining} < ~{estimated_tokens}"
                    f" — ждём {wait:.0f}с до сброса квоты",
                    flush=True,
                )
                self._sleep_fn(wait)
        elif self._request_count > 0 and self._fallback_delay_sec > 0:
            print(
                f"\n  ⏳ Groq: нет x-ratelimit-* заголовков"
                f" — fallback {self._fallback_delay_sec:.0f}с",
                flush=True,
            )
            self._sleep_fn(self._fallback_delay_sec)

    def _update_budget(self, resp_headers: dict) -> None:
        """Read x-ratelimit-{limit,remaining,reset}-tokens from a response."""
        limit = resp_headers.get("x-ratelimit-limit-tokens")
        remaining = resp_headers.get("x-ratelimit-remaining-tokens")
        reset = resp_headers.get("x-ratelimit-reset-tokens")
        if limit is not None:
            try:
                self._budget_limit = int(limit)
            except (ValueError, TypeError):
                pass
        if remaining is not None:
            try:
                self._budget_remaining = int(remaining)
                self._got_budget_headers = True
            except (ValueError, TypeError):
                pass
        if reset is not None:
            parsed = _parse_groq_reset(str(reset))
            if parsed is not None:
                self._budget_reset_at = self._monotonic_fn() + parsed

    def _model_404_hint(self) -> str:
        return (
            f"модель '{self._model}' не найдена на Groq (404) — вероятно снята "
            f"или переименована. Укажи актуальную в config/r0.yaml (model:). "
            f"Список моделей: curl -s {GROQ_MODELS_URL} "
            f"-H \"Authorization: Bearer $GROQ_API_KEY\"  "
            f"(или https://console.groq.com/docs/models)"
        )

    def available_models(self) -> set[str] | None:
        """id моделей, доступных на Groq (для префлайта). None — нет ключа/сети → не проверяем."""
        api_key = self._api_key or os.environ.get("GROQ_API_KEY")
        if not api_key:
            return None
        return _list_models(GROQ_MODELS_URL, headers={"Authorization": f"Bearer {api_key}"})

    def _default_request(self, messages: list[dict], temperature: float) -> dict:
        api_key = self._api_key or os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ProviderError("нет GROQ_API_KEY — задайте ключ Groq в окружении для R0")

        estimated = sum(_count_tokens_approx(m.get("content") or "") for m in messages)
        # max_output_tokens from config (default 900); must stay below Groq free-tier OTPM cap
        # of 1000 tok/min (not exposed in any x-ratelimit-* header — see docs/audit-groq-413.md).
        # Actual R0 output is typically 200-600 tokens; 900 gives ~10% headroom below 1000.
        max_tokens = self._max_output_tokens
        # Pace on the full admission cost: text estimate + chat-template overhead + max_tokens.
        self._pace_if_needed(estimated + _GROQ_CHAT_TEMPLATE_OVERHEAD + max_tokens)
        self._request_count += 1

        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        if self._reasoning_effort is not None:
            payload["reasoning_effort"] = self._reasoning_effort

        headers = {"Authorization": f"Bearer {api_key}"}
        out_headers: dict = {}
        try:
            return _chat_request(
                GROQ_CHAT_URL, headers=headers, payload=payload,
                provider_name=self.name, defer_throttle=self._defer_throttle,
                not_found_hint=self._model_404_hint(),
                out_headers=out_headers,
            )
        finally:
            # Always update budget from response headers, even on ProviderThrottled/Exhausted.
            self._update_budget(out_headers)


class OpenRouterLLM:
    """OpenRouter chat-completions — второй провайдер для распределения/failover.

    Ключ OPENROUTER_API_KEY только из окружения/.env. Интерфейс идентичен GroqLLM.
    """

    name = "OpenRouter"

    def __init__(
        self,
        *,
        model: str = DEFAULT_OPENROUTER_MODEL,
        model_fallbacks: list[str] | None = None,
        api_key: str | None = None,
        request_fn: Callable[[list[dict], float], dict] | None = None,
        defer_throttle: bool = False,
    ):
        self._model = model
        self._model_fallbacks: list[str] = model_fallbacks if model_fallbacks is not None else list(DEFAULT_OPENROUTER_FALLBACKS)
        self._api_key = api_key
        self._request_fn = request_fn
        self._defer_throttle = defer_throttle

    @property
    def _model_queue(self) -> list[str]:
        """Все модели для попытки: основная + запасные."""
        return [self._model] + self._model_fallbacks

    def complete(self, messages: list[dict], *, temperature: float = 0.0) -> str:
        request = self._request_fn or self._default_request
        data = request(messages, temperature)
        return _extract_content(data, self.name)

    def _model_404_hint(self, model: str) -> str:
        return (
            f"модель '{model}' не найдена у OpenRouter (404) — снята или переименована. "
            f"Обнови openrouter_model в config/r0.yaml (формат 'vendor/model:free'). "
            f"Актуальный список бесплатных: curl -s {OPENROUTER_MODELS_URL} | "
            f"jq -r '.data[].id | select(endswith(\":free\"))'"
        )

    def available_models(self) -> set[str] | None:
        """id моделей OpenRouter (для префлайта). None — нет сети/битый ответ → не проверяем."""
        api_key = self._api_key or os.environ.get("OPENROUTER_API_KEY")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        return _list_models(OPENROUTER_MODELS_URL, headers=headers)

    def _default_request(self, messages: list[dict], temperature: float) -> dict:
        api_key = self._api_key or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ProviderError(
                "нет OPENROUTER_API_KEY — добавьте в .env для распределения нагрузки на OpenRouter"
            )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/Dannymor94/autoreels",
            "X-Title": "autoreels",
        }
        last_exc: ProviderModelNotFound | None = None
        for model in self._model_queue:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            }
            try:
                result = _chat_request(
                    OPENROUTER_CHAT_URL, headers=headers, payload=payload,
                    provider_name=self.name, defer_throttle=self._defer_throttle,
                    not_found_hint=self._model_404_hint(model),
                )
                if model != self._model:
                    # Зафиксировать переключение на запасную модель для следующих запросов
                    print(f"  ℹ OpenRouter: перешёл на модель '{model}'", flush=True)
                    self._model = model
                return result
            except ProviderModelNotFound as e:
                last_exc = e
                if model != self._model_queue[-1]:
                    print(
                        f"\n  ⚠ OpenRouter: модель '{model}' недоступна, "
                        f"пробую следующую из запасных…",
                        flush=True,
                    )
        primary = self._model_queue[0]
        tried = ", ".join(f"'{m}'" for m in self._model_queue)
        raise ProviderModelNotFound(
            f"OpenRouter: все модели недоступны ({tried}). "
            f"Обнови openrouter_model/openrouter_fallback_models в config/r0.yaml. "
            f"Актуальный список бесплатных: curl -s {OPENROUTER_MODELS_URL} | "
            f"jq -r '.data[].id | select(endswith(\":free\"))'",
            model=primary,
            provider="OpenRouter",
        ) from last_exc


class _PoolMember:
    """Провайдер + его состояние внутри пула.

    `available_at` — момент (по часам пула), когда провайдер снова свободен. 0 = свободен.
    `reason` — почему в кулдауне (для сообщений): '' | 'throttled' | 'exhausted'.
    `disabled` — навсегда исключён из ротации (конфиг-ошибка модели: 404). В отличие от
    кулдауна (временный), disabled не возвращается — модель в конфиге надо чинить.
    """

    def __init__(self, provider: LLMProvider):
        self.provider = provider
        self.available_at = 0.0
        self.reason = ""
        self.disabled = False
        self.consec_failures = 0  # consecutive throttled/exhausted failures this complete() call

    @property
    def name(self) -> str:
        return getattr(self.provider, "name", "?")

    @property
    def model(self) -> str:
        return getattr(self.provider, "_model", "?")


class ProviderPool:
    """Quota-aware роутер: распределяет запросы между провайдерами, обходя дневные лимиты.

    Каждый провайдер несёт состояние кулдауна. На каждый запрос пул по стратегии выбирает
    ЛУЧШИЙ свободный провайдер, пропускает тех, кто в лимите, а когда свободных нет — спит
    до ближайшего освобождения с внятной оценкой. Лимит (транзиентный или суточный) — это
    просто кулдаун разной длины, поэтому «вернуться когда остынет» работает единообразно.

    Стратегии: 'adaptive' (предпочитать первого = Groq, для качества) | 'round_robin'
    (чередовать равномерно). Инъекция clock/sleep — для детерминизма в тестах.
    """

    def __init__(
        self,
        providers: list[LLMProvider],
        *,
        strategy: str = "adaptive",
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        if not providers:
            raise ValueError("ProviderPool требует хотя бы одного провайдера")
        if strategy not in POOL_STRATEGIES:
            raise ValueError(
                f"неизвестная strategy '{strategy}'; допустимо: {', '.join(POOL_STRATEGIES)}"
            )
        self._members = [_PoolMember(p) for p in providers]
        self._strategy = strategy
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._rr_cursor = 0
        self.last_provider: str | None = None

    @property
    def name(self) -> str:
        return "pool(" + ",".join(m.name for m in self._members) + ")"

    def _candidate_order(self) -> list[int]:
        """Порядок предпочтения индексов провайдеров по стратегии.

        adaptive → порядок создания (Groq первый, для качества).
        round_robin → сдвигаемый курсор: каждый вызов стартует со следующего провайдера.
        """
        n = len(self._members)
        if self._strategy == "round_robin":
            start = self._rr_cursor % n
            self._rr_cursor += 1
            return [(start + k) % n for k in range(n)]
        return list(range(n))

    def complete(self, messages: list[dict], *, temperature: float = 0.0) -> str:
        """Выполнить запрос на лучшем свободном провайдере; ждать только если все в лимите.

        Провайдер, ответивший 404 (конфиг-ошибка модели), исключается из ротации навсегда
        и прогон продолжается на остальных. Если исключены ВСЕ — внятная ошибка. Пустой ответ
        (ProviderEmptyResponse) — мягкий сбой: пробуем сиблинга; после _MAX_EMPTY_RESPONSES
        пустых подряд — пробрасываем наверх (select пометит чанк failed, видео не падает)."""
        empty_count = 0
        timeout_count = 0
        _budget_start = self._clock()
        _fail_counts: dict[str, int] = {}
        # reset per-call consecutive failure counters
        for _m in self._members:
            _m.consec_failures = 0
        while True:
            elapsed = self._clock() - _budget_start
            if elapsed > _POOL_BUDGET_SEC:
                counts = ", ".join(f"{n}: {c}" for n, c in sorted(_fail_counts.items()))
                raise ProviderError(
                    f"бюджет ожидания {_POOL_BUDGET_SEC:.0f}с исчерпан без ответа "
                    f"(отказы: {counts or '—'})"
                )
            active = [m for m in self._members if not m.disabled]
            if not active:
                raise ProviderError(
                    "все провайдеры исключены из-за неверных моделей — "
                    "проверь model/openrouter_model в config/r0.yaml"
                )
            now = self._clock()
            order = [i for i in self._candidate_order() if not self._members[i].disabled]
            available = [i for i in order if self._members[i].available_at <= now]
            if not available:
                self._wait_for_earliest()
                continue
            for idx in available:
                m = self._members[idx]
                try:
                    result = m.provider.complete(messages, temperature=temperature)
                except ProviderEmptyResponse as e:
                    empty_count += 1
                    if empty_count >= _MAX_EMPTY_RESPONSES:
                        raise   # пул исчерпал попытки → чанк-фейл наверх (видео продолжается)
                    print(f"\n  ⚠ {e} — пробую другого провайдера", flush=True)
                    self._cooldown(m, now, e, min_sec=_EMPTY_COOLDOWN_SEC)
                    continue
                except ProviderTimeout as e:
                    timeout_count += 1
                    if timeout_count >= _MAX_TIMEOUTS:
                        raise   # сиблинги тоже таймаутят → чанк-фейл наверх (видео продолжается)
                    print(f"\n  ⚠ {e} — пробую другого провайдера", flush=True)
                    self._cooldown(m, now, e, min_sec=_TIMEOUT_COOLDOWN_SEC)
                    continue
                except ProviderOTPMExceeded as e:
                    # Type B 429: waiting is useless, only lowering max_tokens helps.
                    # Don't cooldown, don't increment consec_failures. Log once, fail fast.
                    print(
                        f"\n  ✗ {m.name} OTPM: {e}",
                        flush=True,
                    )
                    raise ProviderError(str(e)) from e
                except ProviderRequestTooLarge as e:
                    _fail_counts[m.name] = _fail_counts.get(m.name, 0) + 1
                    print(f"\n  ✗ {m.name} 413: {e}", flush=True)
                    # Skip this provider for this call — same request won't fit.
                    # Other providers (OpenRouter) may have a different limit.
                    m.available_at = _budget_start + _POOL_BUDGET_SEC + 1.0
                    m.reason = "too_large"
                    m.consec_failures += 1
                    others = [x for x in self._members if not x.disabled and x is not m]
                    if not others:
                        raise ProviderError(str(e)) from e
                    continue
                except ProviderModelNotFound as e:
                    m.disabled = True
                    print(f"\n  ⚠ {e} — исключаю {m.name} из пула, продолжаю на остальных",
                          flush=True)
                    continue
                except ProviderExhausted as e:
                    _fail_counts[m.name] = _fail_counts.get(m.name, 0) + 1
                    self._cooldown(m, now, e, min_sec=_EXHAUSTED_THRESHOLD_SEC)
                    if m.consec_failures == 1:
                        print(f"\n  ⏳ {m.name} исчерпан (retry-after={e.retry_after:.0f}с)", flush=True)
                    continue
                except ProviderThrottled as e:
                    _fail_counts[m.name] = _fail_counts.get(m.name, 0) + 1
                    self._cooldown(m, now, e, min_sec=1.0)
                    if m.consec_failures == 1:
                        print(f"\n  ⏳ {m.name} троттлит (retry-after={e.retry_after:.0f}с)", flush=True)
                    elif m.consec_failures == _POOL_MAX_CONSEC_FAILURES:
                        wait = m.available_at - now
                        print(f"\n  ⚠ {m.name} {m.consec_failures}× подряд — бэкофф {wait:.0f}с",
                              flush=True)
                    continue
                # успех: сбрасываем кулдаун и счётчик, запоминаем провайдера для прогресса
                m.available_at = 0.0
                m.reason = ""
                m.consec_failures = 0
                self.last_provider = m.name
                return result
            # все свободные ушли в кулдаун/исключены → на следующем витке пул поспит или упадёт

    def _cooldown(self, member: _PoolMember, now: float, exc: ProviderError, *, min_sec: float) -> None:
        retry_after = getattr(exc, "retry_after", 0.0) or 0.0
        member.consec_failures += 1
        if member.consec_failures >= _POOL_MAX_CONSEC_FAILURES:
            # exponential backoff: 60, 120, 240, … cap 3600s — forces fallthrough to sibling
            extra = _POOL_BACKOFF_BASE_SEC * (2 ** (member.consec_failures - _POOL_MAX_CONSEC_FAILURES))
            cooldown = min(max(retry_after, extra), 3600.0)
        else:
            cooldown = max(retry_after, min_sec)
        member.available_at = now + cooldown
        member.reason = "exhausted" if isinstance(exc, ProviderExhausted) else "throttled"

    def _wait_for_earliest(self) -> None:
        """Все АКТИВНЫЕ провайдеры в лимите → ЖИВАЯ пауза до ближайшего освобождения.

        Обновляемая строка (\\r) с обратным отсчётом и спиннером, тик ≈1с. Как только
        провайдер освобождается — сразу сообщаем «▶ … доступен» и выходим (не досыпаем).
        Оценка пересчитывается на КАЖДОМ тике: если пауза затянулась (кулдаун продлили) —
        показываем новую оценку, не молчим. Non-TTY печатает реже (print_provider_wait).
        """
        from autoreels.core.progress import is_tty, print_provider_ready, print_provider_wait
        active = [m for m in self._members if not m.disabled]
        if not active:
            return
        if is_tty():
            print(flush=True)   # своя строка под \r-отсчёт (не затирать прогресс R0 сверху)
        else:
            now0 = self._clock()
            earliest0 = min(m.available_at for m in active)
            details0 = " · ".join(
                f"{m.name} через ~{max(0.0, m.available_at - now0):.0f}с" for m in active
            )
            print(f"⏸ ждём провайдеров: осталось ~{max(0.0, earliest0 - now0):.0f}с · {details0}", flush=True)
        tick = 0
        while True:
            now = self._clock()
            ready = [m for m in active if m.available_at <= now]
            if ready:
                print_provider_ready(ready[0].name)
                return
            earliest = min(m.available_at for m in active)
            remaining = max(0.0, earliest - now)
            details = " · ".join(
                f"{m.name} через ~{max(0.0, m.available_at - now):.0f}с" for m in active
            )
            print_provider_wait(remaining, details, tick)
            tick += 1
            self._sleep(min(1.0, remaining) if remaining > 0 else 1.0)

    def preflight(self) -> None:
        """Проверить доступность моделей ДО прогона (лёгкий GET /models на провайдера).

        Если проверить нельзя (нет ключа/сети → available_models вернул None) — не блокируем:
        доверяем рантайму (404 отсеет провайдера на месте). Для OpenRouter: проверяет и запасные
        модели (_model_queue) — провайдер остаётся в пуле, пока хотя бы одна модель доступна."""
        for m in self._members:
            available = None
            try:
                available = m.provider.available_models()
            except Exception:  # noqa: BLE001 — префлайт не роняет прогон из-за сети
                available = None
            if not available:
                continue  # не смогли проверить → доверяем рантайму

            # Список всех моделей провайдера (основная + запасные, если есть)
            all_models: list[str] = getattr(m.provider, "_model_queue", [m.model])
            reachable = [mod for mod in all_models if mod in available]

            if not reachable:
                m.disabled = True
                tried = ", ".join(f"'{x}'" for x in all_models)
                key = "openrouter_model" if m.name == "OpenRouter" else "model"
                print(
                    f"\n  ⚠ {m.name}: ни одна модель не доступна ({tried}) — "
                    f"исключаю провайдера. Обнови {key} в config/r0.yaml. "
                    f"Актуальный список бесплатных OpenRouter: "
                    f"curl -s {OPENROUTER_MODELS_URL} | jq -r '.data[].id | select(endswith(\":free\"))'",
                    flush=True,
                )
            elif m.model not in available:
                # Основная модель недоступна, но есть рабочая запасная — провайдер остаётся.
                working = reachable[0]
                print(
                    f"\n  ℹ {m.name}: основная модель '{m.model}' недоступна, "
                    f"буду использовать '{working}' (запасная из config/r0.yaml)",
                    flush=True,
                )

        if all(m.disabled for m in self._members):
            raise ProviderError(
                "ни одна модель провайдеров не доступна — проверь model/openrouter_model "
                "в config/r0.yaml"
            )


class FallbackLLM:
    """Цепочка провайдеров: при ProviderExhausted переключается на следующий (навсегда).

    Устаревшая простая стратегия; ProviderPool её обобщает (распределение + возврат после
    кулдауна). Оставлена для обратной совместимости. Пример: FallbackLLM([GroqLLM(), OpenRouterLLM()]).
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


def _openrouter_shared_pool_blocked(model: str, api_key: str) -> str | None:
    """Minimal chat-completion ping to OpenRouter. Returns reason string if the model is
    blocked by the upstream shared pool (is_byok:false), else None.

    Called at pool construction so we don't burn retries on every chunk for a provider
    that is permanently unavailable on the free shared pool."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/Dannymor94/autoreels",
        "X-Title": "autoreels",
    }
    payload = {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
    try:
        resp = _httpx_post(
            OPENROUTER_CHAT_URL, headers=headers, json=payload,
            timeout=httpx.Timeout(15.0),
        )
    except Exception:  # noqa: BLE001 — network error at construction: let runtime handle it
        return None
    if resp.status_code != 429:
        return None
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        return None
    error = body.get("error", {}) if isinstance(body, dict) else {}
    metadata = error.get("metadata", {}) if isinstance(error, dict) else {}
    if not isinstance(metadata, dict):
        return None
    if metadata.get("is_byok") is False or metadata.get("limit_source") == "upstream_provider_shared_pool":
        return (
            f"model '{model}' rejected by upstream shared pool (is_byok:false) — "
            f"use BYOK key or pick a different free model in config/r0.yaml (openrouter_model:)"
        )
    return None


def build_pool(r0_cfg, *, strategy: str | None = None) -> ProviderPool:
    """Собрать ProviderPool из конфига и ключей окружения.

    Groq — всегда (основной, модель сильнее → предпочтителен по качеству). OpenRouter
    добавляется ТОЛЬКО если задан OPENROUTER_API_KEY — иначе пул из одного Groq работает как
    раньше (req: нет ключа → не падать). Провайдеры в defer-режиме: троттл уходит роутеру,
    а не спится внутри провайдера. Стратегия — из аргумента > r0_cfg.provider_strategy > adaptive.
    """
    strat = strategy or getattr(r0_cfg, "provider_strategy", "adaptive")
    max_out = getattr(r0_cfg, "max_output_tokens", 900)
    providers: list[LLMProvider] = [
        GroqLLM(model=r0_cfg.model, defer_throttle=True, max_output_tokens=max_out)
    ]
    or_key = os.environ.get("OPENROUTER_API_KEY")
    if or_key:
        reason = _openrouter_shared_pool_blocked(r0_cfg.openrouter_model, or_key)
        if reason:
            print(f"\n  ⚠ OpenRouter: {reason} — исключаю из пула", flush=True)
        else:
            fallbacks = getattr(r0_cfg, "openrouter_fallback_models", None)
            providers.append(
                OpenRouterLLM(
                    model=r0_cfg.openrouter_model,
                    model_fallbacks=fallbacks,
                    defer_throttle=True,
                )
            )
    return ProviderPool(providers, strategy=strat)
