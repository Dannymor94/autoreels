"""LLM-провайдер (cloud/providers.py) — Qwen через Groq chat + OpenRouter failover.

Это НЕ Whisper-слой (тот в transcribe.py): здесь чат-комплишены/токены. Тесты мокнуты
через инъекцию request_fn, сеть не дёргается.
"""
import pytest

from autoreels.cloud.providers import (
    FallbackLLM, GroqLLM, OpenRouterLLM, ProviderEmptyResponse, ProviderError,
    ProviderExhausted,
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
    monkeypatch.setattr(P.time, "sleep", lambda s: None)   # не спать реально в юнит-тесте
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


# ========================================================= ProviderThrottled (defer)

def test_groq_defer_throttle_raises_throttled_not_sleeps(monkeypatch):
    """defer_throttle=True: короткий 429 → ProviderThrottled немедленно (пул сам разрулит),
    без внутреннего sleep. Так пул может увести чанк на другой провайдер, а не ждать."""
    import autoreels.cloud.providers as P
    from autoreels.cloud.providers import ProviderThrottled
    sleeps = []
    monkeypatch.setattr(P.time, "sleep", lambda s: sleeps.append(s))

    def fake_post(url, *, headers, json, timeout):
        return _FakeResp(429, headers={"retry-after": "5"})

    monkeypatch.setattr(P, "_httpx_post", fake_post)
    monkeypatch.setenv("GROQ_API_KEY", "testkey")

    llm = GroqLLM(defer_throttle=True)
    with pytest.raises(ProviderThrottled) as exc:
        llm.complete([{"role": "user", "content": "hi"}])
    assert exc.value.retry_after == 5.0
    assert sleeps == [], "в defer-режиме провайдер не должен спать — это задача пула"


def test_groq_defer_throttle_still_exhausts_on_long_retry_after(monkeypatch):
    """Длинный retry-after → ProviderExhausted (суточный лимит) даже в defer-режиме."""
    import autoreels.cloud.providers as P
    from autoreels.cloud.providers import ProviderExhausted

    def fake_post(url, *, headers, json, timeout):
        return _FakeResp(429, headers={"retry-after": str(P._EXHAUSTED_THRESHOLD_SEC)})

    monkeypatch.setattr(P, "_httpx_post", fake_post)
    monkeypatch.setenv("GROQ_API_KEY", "testkey")

    llm = GroqLLM(defer_throttle=True)
    with pytest.raises(ProviderExhausted) as exc:
        llm.complete([{"role": "user", "content": "hi"}])
    assert exc.value.retry_after == P._EXHAUSTED_THRESHOLD_SEC


def test_providers_have_names():
    """Провайдеры несут человекочитаемое имя для строки прогресса «via …»."""
    assert GroqLLM().name == "Groq"
    assert OpenRouterLLM().name == "OpenRouter"


def test_openrouter_envelope_parses_to_same_segments():
    """Ответ OpenRouter (OpenAI-совместимый конверт) парсится в те же сегменты, что Groq."""
    from autoreels.cloud.select import parse_segments
    content = ('{"segments": [{"start": 1, "end": 30, "score": 80, '
               '"hook": "h", "title": "t", "description": "d"}]}')
    env = {"choices": [{"message": {"content": content}}]}
    llm = OpenRouterLLM(request_fn=lambda m, t: env)
    segs = parse_segments(llm.complete([]))
    assert len(segs) == 1
    assert segs[0]["start"] == 1 and segs[0]["score"] == 80


# ========================================================= ProviderPool (распределение)

import types

from autoreels.cloud.providers import (  # noqa: E402
    ProviderModelNotFound, ProviderPool, ProviderThrottled, build_pool,
)


class _Clock:
    """Инъектируемые монотонные часы: тест двигает время явно (без реального сна)."""
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _sleeper(clock):
    """Фейковый sleep: двигает инъектируемые часы вместо реальной паузы."""
    def _s(sec):
        clock.advance(sec)
    return _s


class _ScriptedProvider:
    """Провайдер по сценарию: каждый вызов complete() отдаёт следующий элемент.

    Элемент — либо строка (успех), либо Exception (поднять). Считает вызовы.
    `model`/`models` — для тестов префлайта: _model (какая модель в конфиге) и available_models()
    (None = проверить нельзя; set = список доступных).
    """
    def __init__(self, name, script, *, model="m", models=None):
        self.name = name
        self._model = model
        self._models = models
        self._script = list(script)
        self.calls = 0

    def complete(self, messages, *, temperature=0.0):
        self.calls += 1
        action = self._script.pop(0)
        if isinstance(action, Exception):
            raise action
        return action

    def available_models(self):
        return self._models


def _pool(*providers, strategy="adaptive"):
    clock = _Clock()
    pool = ProviderPool(list(providers), strategy=strategy,
                        clock=clock, sleep=_sleeper(clock))
    return pool, clock


def test_pool_adaptive_prefers_first_provider():
    """adaptive: пока Groq (первый) отвечает — второй провайдер не трогается (качество)."""
    groq = _ScriptedProvider("Groq", ["a", "b"])
    openr = _ScriptedProvider("OpenRouter", ["x", "y"])
    pool, _ = _pool(groq, openr)
    assert pool.complete([]) == "a"
    assert pool.complete([]) == "b"
    assert groq.calls == 2
    assert openr.calls == 0, "OpenRouter не должен вызываться пока Groq свободен"


def test_pool_routes_to_sibling_when_first_throttled():
    """Groq троттлит короткий → чанк уходит на OpenRouter немедленно (распределение)."""
    groq = _ScriptedProvider("Groq", [ProviderThrottled("tpm", retry_after=30)])
    openr = _ScriptedProvider("OpenRouter", ["from-openrouter"])
    pool, _ = _pool(groq, openr)
    assert pool.complete([]) == "from-openrouter"
    assert pool.last_provider == "OpenRouter"


def test_pool_skips_provider_in_cooldown():
    """Провайдер в кулдауне не долбится повторно, пока не остынет."""
    groq = _ScriptedProvider("Groq", [ProviderThrottled("tpm", retry_after=100)])
    openr = _ScriptedProvider("OpenRouter", ["one", "two"])
    pool, clock = _pool(groq, openr)
    assert pool.complete([]) == "one"     # Groq троттлит → OpenRouter
    assert pool.complete([]) == "two"     # Groq ещё в кулдауне (100с) → снова OpenRouter
    assert groq.calls == 1, "Groq не должен вызываться повторно в кулдауне"


def test_pool_adaptive_returns_to_groq_after_cooldown():
    """adaptive: когда Groq остыл — пул возвращается к нему (предпочтение по качеству)."""
    groq = _ScriptedProvider("Groq", [ProviderThrottled("tpm", retry_after=30), "groq-back"])
    openr = _ScriptedProvider("OpenRouter", ["openr"])
    pool, clock = _pool(groq, openr)
    assert pool.complete([]) == "openr"        # Groq троттлит → OpenRouter
    clock.advance(31)                          # Groq остыл
    assert pool.complete([]) == "groq-back"    # вернулись на Groq
    assert pool.last_provider == "Groq"


def test_pool_round_robin_alternates():
    """round_robin: чанки поочерёдно на оба провайдера — равномерная нагрузка."""
    groq = _ScriptedProvider("Groq", ["g1", "g2"])
    openr = _ScriptedProvider("OpenRouter", ["o1", "o2"])
    pool, _ = _pool(groq, openr, strategy="round_robin")
    used = [pool.complete([]) for _ in range(4)]
    assert used == ["g1", "o1", "g2", "o2"]
    assert groq.calls == 2 and openr.calls == 2


def test_pool_both_limited_sleeps_until_earliest(capsys):
    """Оба в лимите → пул паузит до ближайшего освобождения, затем продолжает."""
    groq = _ScriptedProvider("Groq", [ProviderThrottled("tpm", retry_after=30), "groq-ok"])
    openr = _ScriptedProvider("OpenRouter", [ProviderThrottled("tpm", retry_after=50)])
    pool, clock = _pool(groq, openr)
    result = pool.complete([])
    assert result == "groq-ok"
    assert clock.t == 30.0, "пул должен проспать до ближайшего (Groq, 30с)"
    out = capsys.readouterr().out
    assert "ждём провайдеров" in out and "осталось" in out   # живой отсчёт паузы


def test_pool_both_daily_exhausted_waits_and_recovers(capsys):
    """Оба упёрлись в суточный лимит → внятная пауза с ETA, затем восстановление."""
    from autoreels.cloud.providers import ProviderExhausted
    groq = _ScriptedProvider("Groq", [ProviderExhausted("daily", retry_after=200), "recovered"])
    openr = _ScriptedProvider("OpenRouter", [ProviderExhausted("daily", retry_after=300)])
    pool, clock = _pool(groq, openr)
    assert pool.complete([]) == "recovered"
    assert clock.t == 200.0
    out = capsys.readouterr().out
    assert "Groq" in out and "OpenRouter" in out   # какой когда освободится


def test_pool_hard_error_propagates():
    """Не-лимитная ошибка провайдера (напр. нет ключа) не глотается как кулдаун."""
    groq = _ScriptedProvider("Groq", [ProviderError("нет GROQ_API_KEY")])
    pool, _ = _pool(groq)
    with pytest.raises(ProviderError, match="GROQ_API_KEY"):
        pool.complete([])


# ------------------------------------------------ пустой ответ провайдера (не краш видео)

def test_provider_empty_content_raises_empty_response():
    """content=None (HTTP 200, JSON-mode под нагрузкой) → ProviderEmptyResponse с диагностикой,
    а не тихий None (который дальше ронял json.loads)."""
    env = {"choices": [{"message": {"content": None}}]}
    llm = GroqLLM(request_fn=lambda m, t: env)
    with pytest.raises(ProviderEmptyResponse) as e:
        llm.complete([])
    assert e.value.provider == "Groq"
    assert "content=None" in str(e.value)          # диагностика: что именно пришло


def test_provider_blank_string_raises_empty_response():
    """Пустая строка content → тоже ProviderEmptyResponse (оборванный ответ)."""
    env = {"choices": [{"message": {"content": "   "}}]}
    llm = OpenRouterLLM(request_fn=lambda m, t: env)
    with pytest.raises(ProviderEmptyResponse):
        llm.complete([])


def test_pool_empty_response_tries_sibling():
    """Пустой ответ Groq → пул пробует OpenRouter (сиблинга), а не роняет запрос."""
    groq = _ScriptedProvider("Groq", [ProviderEmptyResponse("Groq пустой", provider="Groq")])
    openr = _ScriptedProvider("OpenRouter", ["ok-from-openrouter"])
    pool, _ = _pool(groq, openr)
    assert pool.complete([]) == "ok-from-openrouter"
    assert pool.last_provider == "OpenRouter"


def test_pool_all_empty_raises_after_bound():
    """Оба провайдера пусты → пул исчерпывает попытки и пробрасывает ProviderEmptyResponse."""
    from autoreels.cloud.providers import _MAX_EMPTY_RESPONSES
    groq = _ScriptedProvider("Groq", [ProviderEmptyResponse("пусто", provider="Groq")] * 5)
    openr = _ScriptedProvider("OpenRouter", [ProviderEmptyResponse("пусто", provider="OpenRouter")] * 5)
    pool, _ = _pool(groq, openr)
    with pytest.raises(ProviderEmptyResponse):
        pool.complete([])
    assert groq.calls + openr.calls == _MAX_EMPTY_RESPONSES   # ограничено, не бесконечно


# ------------------------------------------------ сетевой таймаут чтения (транзиентный)

def test_read_timeout_retries_same_provider_then_raises_provider_timeout(monkeypatch):
    """Read timeout: _post_r0 ретраит на ТОМ ЖЕ провайдере, затем ProviderTimeout (транзиентный),
    а не сырой httpx.ReadTimeout, который ронял всё видео."""
    import autoreels.cloud.providers as P
    import httpx
    monkeypatch.setattr(P.time, "sleep", lambda s: None)      # не спать в юните
    seen = []

    def fake_post(url, *, headers, json, timeout):
        seen.append(timeout)
        raise httpx.ReadTimeout("The read operation timed out")

    monkeypatch.setattr(P, "_httpx_post", fake_post)
    monkeypatch.setenv("GROQ_API_KEY", "testkey")

    llm = GroqLLM()
    with pytest.raises(P.ProviderTimeout) as exc:
        llm.complete([{"role": "user", "content": "hi"}])
    assert "Groq" in str(exc.value) and "таймаут" in str(exc.value).lower()
    assert exc.value.provider == "Groq"
    assert len(seen) == P._TIMEOUT_RETRIES_SAME + 1          # первичный + ретраи на том же
    assert seen[0].read == P._R0_READ_TIMEOUT_SEC           # увеличенный read-timeout


def test_pool_routes_to_sibling_on_timeout():
    """Таймаут Groq → чанк уходит на OpenRouter (сиблинга) немедленно, не падает."""
    from autoreels.cloud.providers import ProviderTimeout
    groq = _ScriptedProvider("Groq", [ProviderTimeout("net timeout", provider="Groq")])
    openr = _ScriptedProvider("OpenRouter", ["from-openrouter"])
    pool, _ = _pool(groq, openr)
    assert pool.complete([]) == "from-openrouter"
    assert pool.last_provider == "OpenRouter"


def test_pool_all_timeout_fails_chunk_after_max():
    """Все сиблинги таймаутят → пул исчерпывает попытки и поднимает ProviderTimeout (чанк-фейл,
    видео продолжается), а не висит бесконечно."""
    from autoreels.cloud.providers import ProviderTimeout, _MAX_TIMEOUTS
    groq = _ScriptedProvider("Groq", [ProviderTimeout("t", provider="Groq")] * 5)
    openr = _ScriptedProvider("OpenRouter", [ProviderTimeout("t", provider="OpenRouter")] * 5)
    pool, _ = _pool(groq, openr)
    with pytest.raises(ProviderTimeout):
        pool.complete([])
    assert groq.calls + openr.calls == _MAX_TIMEOUTS         # ограничено, не бесконечно


# ------------------------------------------------ живая пауза «все провайдеры в лимите»

def test_pool_wait_shows_live_countdown(monkeypatch, capsys):
    """Пауза живая: обратный отсчёт обновляется каждую секунду (~3с → ~2с → ~1с), спиннер."""
    import autoreels.core.progress as prog
    monkeypatch.setattr(prog, "is_tty", lambda: True)      # TTY: строка на каждый тик
    groq = _ScriptedProvider("Groq", [])
    openr = _ScriptedProvider("OpenRouter", [])
    pool, clock = _pool(groq, openr)
    pool._members[0].available_at = 3.0
    pool._members[1].available_at = 5.0

    pool._wait_for_earliest()

    out = capsys.readouterr().out
    assert "ждём провайдеров" in out
    assert "осталось ~3с" in out and "осталось ~2с" in out and "осталось ~1с" in out
    assert "Groq через" in out and "OpenRouter через" in out   # ETA по каждому
    assert clock.t == 3.0                                       # проспали ровно до ближайшего


def test_pool_wait_stops_when_provider_frees(monkeypatch, capsys):
    """Провайдер освободился → сразу «▶ … доступен, продолжаю», не досыпаем до второго."""
    import autoreels.core.progress as prog
    monkeypatch.setattr(prog, "is_tty", lambda: True)
    groq = _ScriptedProvider("Groq", [])
    openr = _ScriptedProvider("OpenRouter", [])
    pool, clock = _pool(groq, openr)
    pool._members[0].available_at = 10.0    # Groq ещё долго
    pool._members[1].available_at = 2.0     # OpenRouter освободится первым

    pool._wait_for_earliest()

    out = capsys.readouterr().out
    assert "OpenRouter доступен" in out and "продолжаю" in out
    assert clock.t == 2.0                    # вышли на OpenRouter, а не ждали Groq (10с)


def test_pool_wait_recomputes_when_pause_extends(monkeypatch, capsys):
    """Пауза затянулась (кулдаун продлили в процессе) → пересчёт оценки, не молчим."""
    import autoreels.core.progress as prog
    monkeypatch.setattr(prog, "is_tty", lambda: True)
    groq = _ScriptedProvider("Groq", [])
    openr = _ScriptedProvider("OpenRouter", [])

    clock = _Clock()
    bumped = [False]

    def sleeper(sec):
        clock.advance(sec)
        # на 2-й секунде «провайдер не отпустил» — продлил кулдаун Groq с 2с до 5с
        if not bumped[0] and clock.t >= 2.0:
            pool._members[0].available_at = 5.0
            bumped[0] = True

    pool = ProviderPool([groq, openr], strategy="adaptive", clock=clock, sleep=sleeper)
    pool._members[0].available_at = 2.0
    pool._members[1].available_at = 5.0

    pool._wait_for_earliest()

    out = capsys.readouterr().out
    assert "осталось ~2с" in out       # начальная оценка
    assert "осталось ~3с" in out       # пересчёт вверх после продления (5.0 - clock 2.0)
    assert clock.t == 5.0              # дождались реального освобождения


def test_pool_wait_non_tty_does_not_spam(monkeypatch, capsys):
    """Non-TTY: печатать не каждую секунду (раз в N тиков) — не спамить лог."""
    import autoreels.core.progress as prog
    monkeypatch.setattr(prog, "is_tty", lambda: False)
    groq = _ScriptedProvider("Groq", [])
    pool, clock = _pool(groq)
    pool._members[0].available_at = 12.0    # 12 тиков

    pool._wait_for_earliest()

    out = capsys.readouterr().out
    wait_lines = [ln for ln in out.splitlines() if "ждём провайдеров" in ln]
    assert 0 < len(wait_lines) <= 4          # не 12 строк (throttle раз в 5 тиков → ~3)
    assert "доступен" in out


def test_pool_exposes_last_provider_for_progress():
    """last_provider отражает провайдера последнего успешного вызова (для «via …»)."""
    groq = _ScriptedProvider("Groq", ["ok"])
    pool, _ = _pool(groq)
    pool.complete([])
    assert pool.last_provider == "Groq"


def test_pool_requires_at_least_one_provider():
    with pytest.raises(ValueError):
        ProviderPool([])


def test_pool_unknown_strategy_raises():
    with pytest.raises(ValueError, match="strategy"):
        ProviderPool([_ScriptedProvider("Groq", [])], strategy="magic")


def test_pool_single_provider_throttle_waits_then_succeeds():
    """Один провайдер (нет OpenRouter-ключа) троттлит → пул ждёт кулдаун и повторяет."""
    groq = _ScriptedProvider("Groq", [ProviderThrottled("tpm", retry_after=8), "ok"])
    pool, clock = _pool(groq)
    assert pool.complete([]) == "ok"
    assert clock.t == 8.0


# ------------------------------------------------------- build_pool (сборка из конфига)

def _fake_r0(strategy="adaptive"):
    return types.SimpleNamespace(
        model="qwen/groq-model",
        openrouter_model="qwen/or-model:free",
        provider_strategy=strategy,
    )


def test_build_pool_groq_only_without_openrouter_key(monkeypatch):
    """Нет OPENROUTER_API_KEY → пул из одного Groq (не падать, работать на Groq)."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "k")
    pool = build_pool(_fake_r0())
    assert isinstance(pool, ProviderPool)
    names = [m.provider.name for m in pool._members]
    assert names == ["Groq"]


def test_build_pool_adds_openrouter_when_key_present(monkeypatch):
    """OPENROUTER_API_KEY задан → в пуле два провайдера (Groq первый, для качества)."""
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or")
    pool = build_pool(_fake_r0())
    names = [m.provider.name for m in pool._members]
    assert names == ["Groq", "OpenRouter"]


def test_build_pool_uses_models_from_config(monkeypatch):
    """Модели берутся из r0_cfg (model / openrouter_model), не хардкод."""
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or")
    pool = build_pool(_fake_r0())
    assert pool._members[0].provider._model == "qwen/groq-model"
    assert pool._members[1].provider._model == "qwen/or-model:free"


def test_build_pool_respects_strategy_from_config(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    pool = build_pool(_fake_r0(strategy="round_robin"))
    assert pool._strategy == "round_robin"


def test_build_pool_providers_defer_throttle(monkeypatch):
    """Провайдеры в пуле — в defer-режиме: троттл отдаётся пулу, а не спится внутри."""
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or")
    pool = build_pool(_fake_r0())
    assert all(m.provider._defer_throttle for m in pool._members)


# ============================================ 404: конфиг-ошибка модели → исключение из пула

def test_openrouter_404_raises_model_not_found(monkeypatch):
    """OpenRouter 404 → ProviderModelNotFound с именем модели и подсказкой про openrouter_model."""
    import autoreels.cloud.providers as P

    def fake_post(url, *, headers, json, timeout):
        return _FakeResp(404, body={"error": {"message": "No endpoints found"}})

    monkeypatch.setattr(P, "_httpx_post", fake_post)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or")

    llm = OpenRouterLLM(model="vendor/gone:free")
    with pytest.raises(ProviderModelNotFound) as exc:
        llm.complete([{"role": "user", "content": "hi"}])
    msg = str(exc.value)
    assert "vendor/gone:free" in msg          # какая модель
    assert "openrouter_model" in msg          # где чинить
    assert exc.value.model == "vendor/gone:free"
    assert exc.value.provider == "OpenRouter"


def test_pool_404_excludes_provider_and_continues():
    """404 одного провайдера (конфиг-ошибка модели) → исключён из пула, прогон на втором."""
    groq = _ScriptedProvider(
        "Groq", [ProviderModelNotFound("Groq: модель X 404", model="X", provider="Groq")]
    )
    openr = _ScriptedProvider("OpenRouter", ["ok-from-openrouter"])
    pool, _ = _pool(groq, openr)
    assert pool.complete([]) == "ok-from-openrouter"
    assert pool.last_provider == "OpenRouter"


def test_pool_404_provider_never_retried():
    """Исключённый по 404 провайдер не опрашивается повторно (это не кулдаун, а конфиг-ошибка)."""
    groq = _ScriptedProvider(
        "Groq", [ProviderModelNotFound("404", model="X", provider="Groq")]
    )
    openr = _ScriptedProvider("OpenRouter", ["a", "b", "c"])
    pool, _ = _pool(groq, openr)
    assert [pool.complete([]) for _ in range(3)] == ["a", "b", "c"]
    assert groq.calls == 1, "Groq вызван один раз (404), больше не трогаем"


def test_pool_all_404_raises_clear_error(capsys):
    """Все провайдеры вернули 404 → внятная ошибка про model/openrouter_model, не молчком."""
    groq = _ScriptedProvider("Groq", [ProviderModelNotFound("404", model="X", provider="Groq")])
    openr = _ScriptedProvider("OpenRouter", [ProviderModelNotFound("404", model="Y", provider="OpenRouter")])
    pool, _ = _pool(groq, openr)
    with pytest.raises(ProviderError, match="config/r0.yaml"):
        pool.complete([])
    out = capsys.readouterr().out
    assert "Groq" in out and "OpenRouter" in out    # оба исключены с сообщением


def test_pool_404_message_is_clear(capsys):
    """При исключении по 404 печатается внятное сообщение (какой провайдер, что делать)."""
    groq = _ScriptedProvider(
        "Groq", [ProviderModelNotFound("модель 'X' не найдена у Groq", model="X", provider="Groq")]
    )
    openr = _ScriptedProvider("OpenRouter", ["ok"])
    pool, _ = _pool(groq, openr)
    pool.complete([])
    out = capsys.readouterr().out
    assert "не найдена" in out and "Groq" in out


# ============================================ префлайт: валидация моделей на старте

def test_preflight_disables_provider_with_missing_model(capsys):
    """Модель конфига отсутствует в /models провайдера → он исключён ДО прогона."""
    groq = _ScriptedProvider("Groq", ["ok"], model="qwen/good", models={"qwen/good"})
    openr = _ScriptedProvider("OpenRouter", ["x"], model="vendor/missing:free",
                              models={"openai/gpt-oss-20b:free"})
    pool, _ = _pool(groq, openr)
    pool.preflight()
    # OpenRouter отключён (его модели нет в списке), Groq — активен
    assert pool.complete([]) == "ok"
    assert pool.last_provider == "Groq"
    out = capsys.readouterr().out
    assert "OpenRouter" in out and "openrouter_model" in out


def test_preflight_keeps_provider_with_valid_model():
    """Модель конфига есть в /models → провайдер НЕ исключается."""
    groq = _ScriptedProvider("Groq", ["ok"], model="qwen/good", models={"qwen/good", "other"})
    pool, _ = _pool(groq)
    pool.preflight()
    assert pool.complete([]) == "ok"


def test_preflight_skips_when_cannot_verify():
    """available_models() == None (нет ключа/сети) → не блокируем, доверяем рантайму."""
    groq = _ScriptedProvider("Groq", ["ok"], model="qwen/whatever", models=None)
    pool, _ = _pool(groq)
    pool.preflight()                       # не должно исключать/падать
    assert pool.complete([]) == "ok"


def test_preflight_all_missing_raises():
    """Все модели недоступны → ошибка ДО транскрипции (не тратим Whisper зря)."""
    groq = _ScriptedProvider("Groq", ["ok"], model="a", models={"b"})
    openr = _ScriptedProvider("OpenRouter", ["ok"], model="c", models={"d"})
    pool, _ = _pool(groq, openr)
    with pytest.raises(ProviderError, match="config/r0.yaml"):
        pool.preflight()


def test_openrouter_available_models_parses_list(monkeypatch):
    """available_models() парсит /models в множество id (для префлайта)."""
    import autoreels.cloud.providers as P

    def fake_get(url, *, headers, timeout):
        assert url == P.OPENROUTER_MODELS_URL
        return _FakeResp(200, body={"data": [
            {"id": "openai/gpt-oss-20b:free"}, {"id": "google/gemma-4-31b-it:free"},
        ]})

    monkeypatch.setattr(P, "_httpx_get", fake_get)
    ids = OpenRouterLLM().available_models()
    assert ids == {"openai/gpt-oss-20b:free", "google/gemma-4-31b-it:free"}


def test_available_models_none_on_network_error(monkeypatch):
    """Сбой /models (сеть/битый ответ) → None, а не исключение (префлайт не роняет прогон)."""
    import autoreels.cloud.providers as P

    def boom(url, *, headers, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr(P, "_httpx_get", boom)
    assert OpenRouterLLM().available_models() is None


def test_default_openrouter_model_is_available_free_model():
    """Дефолтная OpenRouter-модель — из актуального списка бесплатных (та же есть на Groq)."""
    from autoreels.cloud.providers import DEFAULT_OPENROUTER_MODEL
    assert DEFAULT_OPENROUTER_MODEL == "openai/gpt-oss-20b:free"


# ------------------------------------------- live-проверка провайдера для doctor (без сети)

def test_interpret_provider_status_decodes_codes():
    from autoreels.cloud.providers import interpret_provider_status as I
    assert I(200)[1] == "доступен"
    assert "неверный или протух" in I(401)[1]
    assert "регион заблокирован" in I(403)[1]
    assert "нет сети" in I(None)[1]                 # таймаут/сеть
    assert I(429)[0] == "429" and "лимит" in I(429)[1].lower()


def test_probe_provider_returns_status_code(monkeypatch):
    from autoreels.cloud.providers import probe_provider
    class _R:
        status_code = 200
    got = probe_provider("http://x/models", api_key="k",
                         get_fn=lambda url, *, headers, timeout: _R())
    assert got == 200


def test_probe_provider_none_on_network_error():
    from autoreels.cloud.providers import probe_provider
    def boom(url, *, headers, timeout):
        raise RuntimeError("no network")
    assert probe_provider("http://x/models", api_key="k", get_fn=boom) is None


def test_probe_provider_sends_bearer_when_key():
    from autoreels.cloud.providers import probe_provider
    seen = {}
    def cap(url, *, headers, timeout):
        seen.update(headers)
        class _R: status_code = 401
        return _R()
    probe_provider("http://x/models", api_key="secret", get_fn=cap)
    assert seen.get("Authorization") == "Bearer secret"
