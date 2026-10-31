"""M201: a model that does not answer says why. m197–m200: every new paid request failed — 63 «заголовок: модель не
ответила (ProviderError)» in one run, no cost line, and the report read «из кэша, $0». The log line now carries the
error's text and Claude's cost line names the failed requests and the last error."""
from __future__ import annotations

import json

from autoreels.cloud import providers as P
from autoreels.cloud.autocut import pick_keywords
from autoreels.cloud.postcopy import describe_clip

# The error envelope of the Messages API as its documentation gives it (type error → error.type, error.message);
# not a recorded answer — the test is about what the code keeps of a non-200 answer, not about parsing it.
_LOW_CREDIT = {"type": "error", "error": {"type": "invalid_request_error",
                                          "message": "Your credit balance is too low to access the Anthropic API."}}


class _Resp:
    def __init__(self, code=200, body=None):
        self.status_code, self._body, self.headers = code, body, {}
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        return self._body


def _ok(text="{\"ok\": true}"):
    return {"id": "msg_x", "type": "message", "role": "assistant", "model": "m",
            "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 10}}


class _Fails:
    def complete(self, messages, *, temperature=0.0):
        raise P.ProviderError("Claude: HTTP 400: Your credit balance is too low to access the Anthropic API.")


def test_brief_error_is_one_line_with_class_and_text():
    assert P.brief_error(P.ProviderError("a\n  b")) == "ProviderError: a b"
    assert P.brief_error(ValueError()) == "ValueError"
    long = P.brief_error(P.ProviderError("x" * 500), limit=40)
    assert len(long) <= len("ProviderError: ") + 40 and long.endswith("…")


def test_claude_cost_line_names_failed_requests_and_the_last_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    llm = P.AnthropicLLM(model="m", prices=(2.0, 10.0), post_fn=lambda *a, **k: _Resp(400, _LOW_CREDIT))
    for _ in range(2):
        try:
            llm.complete([{"role": "user", "content": "q"}])
        except P.ProviderError:
            pass
    line = llm.usage_line()
    assert llm.calls == 0 and llm.failures == 2
    assert line.startswith("Claude m: запросов 0") and "отказов 2" in line and "credit balance is too low" in line


def test_claude_cost_line_without_failures_is_as_before(monkeypatch):
    # flag-off rule (invariant 8) for the console: a run with no failure prints the same cost line as before M201
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    llm = P.AnthropicLLM(model="m", prices=(2.0, 10.0), post_fn=lambda *a, **k: _Resp(200, _ok()))
    assert llm.usage_line() == ""
    llm.complete([{"role": "user", "content": "q"}])
    assert llm.usage_line() == "Claude m: запросов 1, вход 100, ответ 10 токенов ≈ $0.0003"


def test_pool_of_claude_keeps_the_failure_in_its_usage_lines(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    llm = P.AnthropicLLM(model="m", post_fn=lambda *a, **k: _Resp(400, _LOW_CREDIT))
    pool = P.ProviderPool([llm])
    try:
        pool.complete([{"role": "user", "content": "q"}])
    except P.ProviderError:
        pass
    assert any("отказов" in ln and "credit balance" in ln for ln in pool.usage_lines())


def test_keywords_and_post_log_the_reason_the_model_did_not_answer():
    logs: list[str] = []
    assert pick_keywords([("1.1", "Слово за словом.")], _Fails(), n=1, log=logs.append) == []
    assert describe_clip(_Fails(), "подпись", "текст ролика", log=logs.append) is None
    bad = [ln for ln in logs if "модель не ответила" in ln]
    assert len(bad) == 2 and all("credit balance is too low" in ln for ln in bad), logs
