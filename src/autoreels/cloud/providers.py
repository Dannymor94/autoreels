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
import time
from typing import Callable, Protocol

import httpx

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# Актуальная Qwen на Groq. Модель конфигурируема через config/r0.yaml (model:).
DEFAULT_LLM_MODEL = "qwen/qwen3.6-27b"
# Бесплатная модель OpenRouter для распределения. Та же модель доступна и на Groq
# (openai/gpt-oss-20b) → выборка НЕ плавает между провайдерами, рубрика срабатывает
# одинаково на всех чанках. Надёжный JSON-mode (OpenAI-родословная). Свериться со списком:
# curl -s {OPENROUTER_MODELS_URL} | jq '.data[].id | select(endswith(":free"))'.
DEFAULT_OPENROUTER_MODEL = "openai/gpt-oss-20b:free"

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

# Допустимые стратегии распределения пула (валидируются на входе, fail-fast).
POOL_STRATEGIES = ("adaptive", "round_robin")


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
        if resp.status_code in (429, 413):
            last_status = resp.status_code
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
    detail = (
        "rate limit (429): подождите или уменьшите r0_chunk_tokens"
        if last_status == 429
        else "payload/TPM (413): уменьшите r0_chunk_tokens в config/r0.yaml"
    )
    raise ProviderError(
        f"{provider_name} троттлит (HTTP {last_status}) после {_MAX_THROTTLE_RETRIES} ретраев — {detail}"
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
        request_fn: Callable[[list[dict], float], dict] | None = None,
        defer_throttle: bool = False,
    ):
        self._reasoning_effort = reasoning_effort
        self._model = model
        self._api_key = api_key
        self._request_fn = request_fn
        self._defer_throttle = defer_throttle

    def complete(self, messages: list[dict], *, temperature: float = 0.0) -> str:
        """Вернуть текст ответа модели (content первого choice). Пустой → ProviderEmptyResponse."""
        request = self._request_fn or self._default_request
        data = request(messages, temperature)
        return _extract_content(data, self.name)

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

        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        if self._reasoning_effort is not None:
            payload["reasoning_effort"] = self._reasoning_effort

        headers = {"Authorization": f"Bearer {api_key}"}
        return _chat_request(
            GROQ_CHAT_URL, headers=headers, payload=payload,
            provider_name=self.name, defer_throttle=self._defer_throttle,
            not_found_hint=self._model_404_hint(),
        )


class OpenRouterLLM:
    """OpenRouter chat-completions — второй провайдер для распределения/failover.

    Ключ OPENROUTER_API_KEY только из окружения/.env. Интерфейс идентичен GroqLLM.
    """

    name = "OpenRouter"

    def __init__(
        self,
        *,
        model: str = DEFAULT_OPENROUTER_MODEL,
        api_key: str | None = None,
        request_fn: Callable[[list[dict], float], dict] | None = None,
        defer_throttle: bool = False,
    ):
        self._model = model
        self._api_key = api_key
        self._request_fn = request_fn
        self._defer_throttle = defer_throttle

    def complete(self, messages: list[dict], *, temperature: float = 0.0) -> str:
        request = self._request_fn or self._default_request
        data = request(messages, temperature)
        return _extract_content(data, self.name)

    def _model_404_hint(self) -> str:
        return (
            f"модель '{self._model}' не найдена у OpenRouter (404) — проверь "
            f"openrouter_model в config/r0.yaml (формат 'vendor/model:free'). "
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
        return _chat_request(
            OPENROUTER_CHAT_URL, headers=headers, payload=payload,
            provider_name=self.name, defer_throttle=self._defer_throttle,
            not_found_hint=self._model_404_hint(),
        )


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
        while True:
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
                except ProviderModelNotFound as e:
                    m.disabled = True
                    print(f"\n  ⚠ {e} — исключаю {m.name} из пула, продолжаю на остальных",
                          flush=True)
                    continue
                except ProviderExhausted as e:
                    self._cooldown(m, now, e, min_sec=_EXHAUSTED_THRESHOLD_SEC)
                    continue
                except ProviderThrottled as e:
                    self._cooldown(m, now, e, min_sec=1.0)
                    continue
                # успех: сбрасываем кулдаун, запоминаем провайдера для прогресса
                m.available_at = 0.0
                m.reason = ""
                self.last_provider = m.name
                return result
            # все свободные ушли в кулдаун/исключены → на следующем витке пул поспит или упадёт

    def _cooldown(self, member: _PoolMember, now: float, exc: ProviderError, *, min_sec: float) -> None:
        retry_after = getattr(exc, "retry_after", 0.0) or 0.0
        member.available_at = now + max(retry_after, min_sec)
        member.reason = "exhausted" if isinstance(exc, ProviderExhausted) else "throttled"

    def _wait_for_earliest(self) -> None:
        """Все АКТИВНЫЕ провайдеры в лимите → ЖИВАЯ пауза до ближайшего освобождения.

        Обновляемая строка (\\r) с обратным отсчётом и спиннером, тик ≈1с. Как только
        провайдер освобождается — сразу сообщаем «▶ … доступен» и выходим (не досыпаем).
        Оценка пересчитывается на КАЖДОМ тике: если пауза затянулась (кулдаун продлили) —
        показываем новую оценку, не молчим. Non-TTY печатает реже (print_provider_wait).
        """
        from autoreels.core.progress import print_provider_ready, print_provider_wait
        active = [m for m in self._members if not m.disabled]
        if not active:
            return
        print(flush=True)   # своя строка под \r-отсчёт (не затирать прогресс R0 сверху)
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

        Модель из конфига отсутствует в списке провайдера → исключить его сразу с внятным
        сообщением, а не падать 404-ом на 2-м R0-чанке после дорогой транскрипции. Если
        проверить нельзя (нет ключа/сети → available_models вернул None) — не блокируем:
        доверяем рантайму (404 отсеет провайдера на месте). Все модели неверны → ошибка."""
        for m in self._members:
            available = None
            try:
                available = m.provider.available_models()
            except Exception:  # noqa: BLE001 — префлайт не роняет прогон из-за сети
                available = None
            if not available:
                continue  # не смогли проверить → доверяем рантайму
            if m.model not in available:
                m.disabled = True
                key = "openrouter_model" if m.name == "OpenRouter" else "model"
                print(
                    f"\n  ⚠ {m.name}: модель '{m.model}' недоступна — исключаю провайдера "
                    f"(проверь {key} в config/r0.yaml)",
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


def build_pool(r0_cfg, *, strategy: str | None = None) -> ProviderPool:
    """Собрать ProviderPool из конфига и ключей окружения.

    Groq — всегда (основной, модель сильнее → предпочтителен по качеству). OpenRouter
    добавляется ТОЛЬКО если задан OPENROUTER_API_KEY — иначе пул из одного Groq работает как
    раньше (req: нет ключа → не падать). Провайдеры в defer-режиме: троттл уходит роутеру,
    а не спится внутри провайдера. Стратегия — из аргумента > r0_cfg.provider_strategy > adaptive.
    """
    strat = strategy or getattr(r0_cfg, "provider_strategy", "adaptive")
    providers: list[LLMProvider] = [
        GroqLLM(model=r0_cfg.model, defer_throttle=True)
    ]
    if os.environ.get("OPENROUTER_API_KEY"):
        providers.append(
            OpenRouterLLM(model=r0_cfg.openrouter_model, defer_throttle=True)
        )
    return ProviderPool(providers, strategy=strat)
