"""Tests for `arl models` (cmd_models in __main__.py).

HTTP mocked via monkeypatch on cloud.providers._httpx_get (catalogue) and
cloud.providers._httpx_post (OpenRouter shared-pool ping).
No real network, no API keys required.
"""
import types
import pytest

import autoreels.__main__ as cli
import autoreels.cloud.providers as P


def _fake_response(data: dict, status: int = 200):
    r = types.SimpleNamespace()
    r.status_code = status
    r.json = lambda: data
    r.raise_for_status = lambda: (None if status < 400 else (_ for _ in ()).throw(
        Exception(f"HTTP {status}")))
    return r


def _models_payload(*ids):
    return {"data": [{"id": i} for i in ids]}


GROQ_LIVE = ["qwen/qwen3.8-27b", "llama3-70b-8192", "whisper-large-v3"]
OR_LIVE_FREE = ["google/gemma-3-27b-it:free", "meta-llama/llama-3.3-70b-instruct:free"]
OR_LIVE_PAID = ["openai/gpt-4o"]


def _make_get(groq_models=None, or_models=None):
    """Fake _httpx_get — serves /models catalogue by URL."""
    def get(url, *, headers, timeout):
        if "groq.com" in url:
            if groq_models is None:
                raise OSError("network error")
            return _fake_response(_models_payload(*groq_models))
        if "openrouter.ai" in url:
            if or_models is None:
                raise OSError("network error")
            return _fake_response(_models_payload(*or_models))
        raise AssertionError(f"unexpected url: {url}")
    return get


def _make_post_ok():
    """Fake _httpx_post — OpenRouter ping returns 200 (model accessible)."""
    def post(url, *, headers, json, timeout):
        return _fake_response({"choices": [{"message": {"content": "hi"}}]}, 200)
    return post


def _make_post_byok_blocked(model):
    """Fake _httpx_post — OpenRouter ping returns 429 with is_byok:false."""
    def post(url, *, headers, json, timeout):
        body = {"error": {"metadata": {"is_byok": False,
                                        "limit_source": "upstream_provider_shared_pool"}}}
        return _fake_response(body, 429)
    return post


def _make_cfg(model, openrouter_model="google/gemma-3-27b-it:free", fallbacks=None):
    """Minimal R0Config-like object."""
    cfg = types.SimpleNamespace()
    cfg.model = model
    cfg.openrouter_model = openrouter_model
    cfg.openrouter_fallback_models = fallbacks or []
    return cfg


# --- Test 1: all models present and OR ping passes → OK, exit 0 ---

def test_models_all_present_exit_0(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or_test")
    monkeypatch.setattr(P, "_httpx_get", _make_get(
        groq_models=GROQ_LIVE,
        or_models=OR_LIVE_FREE + OR_LIVE_PAID,
    ))
    monkeypatch.setattr(P, "_httpx_post", _make_post_ok())
    monkeypatch.setattr(cli, "load_r0_config",
                        lambda _: _make_cfg("qwen/qwen3.8-27b"))
    code = cli.cmd_models(root=str(tmp_path))
    out = capsys.readouterr().out
    assert code == 0
    assert "✓ OK" in out
    assert "✗" not in out


# --- Test 2: configured Groq model missing from catalogue → exit 1 ---

def test_models_groq_missing_exit_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or_test")
    monkeypatch.setattr(P, "_httpx_get", _make_get(
        groq_models=GROQ_LIVE,
        or_models=OR_LIVE_FREE + OR_LIVE_PAID,
    ))
    monkeypatch.setattr(P, "_httpx_post", _make_post_ok())
    monkeypatch.setattr(cli, "load_r0_config",
                        lambda _: _make_cfg("qwen/qwen3.6-27b"))  # removed model
    code = cli.cmd_models(root=str(tmp_path))
    out = capsys.readouterr().out
    assert code == 1
    assert "✗ ОТСУТСТВУЕТ" in out


# --- Test 3: OR model in catalogue but rejected by shared pool → НЕДОСТУПНА, exit 1 ---

def test_models_or_in_catalogue_but_byok_blocked_exit_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or_test")
    monkeypatch.setattr(P, "_httpx_get", _make_get(
        groq_models=GROQ_LIVE,
        or_models=OR_LIVE_FREE + OR_LIVE_PAID,  # model IS in catalogue
    ))
    monkeypatch.setattr(P, "_httpx_post", _make_post_byok_blocked("google/gemma-3-27b-it:free"))
    monkeypatch.setattr(cli, "load_r0_config",
                        lambda _: _make_cfg("qwen/qwen3.8-27b",
                                            openrouter_model="google/gemma-3-27b-it:free"))
    code = cli.cmd_models(root=str(tmp_path))
    out = capsys.readouterr().out
    assert code == 1
    assert "НЕДОСТУПНА" in out
    assert "shared pool" in out.lower() or "byok" in out.lower()
    # Must NOT report OK
    assert "✓ OK" not in out.split("OpenRouter model")[1]


# --- Test 4: OR model in catalogue and ping passes → OK ---

def test_models_or_in_catalogue_and_ping_ok(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or_test")
    monkeypatch.setattr(P, "_httpx_get", _make_get(
        groq_models=GROQ_LIVE,
        or_models=OR_LIVE_FREE + OR_LIVE_PAID,
    ))
    monkeypatch.setattr(P, "_httpx_post", _make_post_ok())
    monkeypatch.setattr(cli, "load_r0_config",
                        lambda _: _make_cfg("qwen/qwen3.8-27b",
                                            openrouter_model="google/gemma-3-27b-it:free"))
    code = cli.cmd_models(root=str(tmp_path))
    out = capsys.readouterr().out
    assert code == 0
    assert "✓ OK" in out


# --- Test 5: one provider down → still shows the other ---

def test_models_groq_down_still_shows_openrouter(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or_test")
    monkeypatch.setattr(P, "_httpx_get", _make_get(
        groq_models=None,          # Groq times out
        or_models=OR_LIVE_FREE + OR_LIVE_PAID,
    ))
    monkeypatch.setattr(P, "_httpx_post", _make_post_ok())
    monkeypatch.setattr(cli, "load_r0_config",
                        lambda _: _make_cfg("qwen/qwen3.8-27b",
                                            openrouter_model="google/gemma-3-27b-it:free"))
    code = cli.cmd_models(root=str(tmp_path))
    out = capsys.readouterr().out
    assert "OpenRouter" in out
    assert "провайдер недоступен" in out  # Groq status


# --- Test 6: Groq catalogue check is catalogue-only (no _httpx_post call for Groq) ---

def test_models_groq_uses_catalogue_only(monkeypatch, tmp_path, capsys):
    """Groq models are checked via catalogue, not via a chat ping."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or_test")
    post_called = []

    def tracking_post(url, *, headers, json, timeout):
        post_called.append(url)
        return _fake_response({}, 200)

    monkeypatch.setattr(P, "_httpx_get", _make_get(
        groq_models=GROQ_LIVE,
        or_models=OR_LIVE_FREE + OR_LIVE_PAID,
    ))
    monkeypatch.setattr(P, "_httpx_post", tracking_post)
    monkeypatch.setattr(cli, "load_r0_config",
                        lambda _: _make_cfg("qwen/qwen3.8-27b",
                                            openrouter_model="google/gemma-3-27b-it:free",
                                            fallbacks=[]))
    cli.cmd_models(root=str(tmp_path))
    # Only one _httpx_post should be made: the OpenRouter ping (not a Groq ping)
    assert all("openrouter" in u for u in post_called), (
        f"Expected only OpenRouter pings, got: {post_called}"
    )
    assert len(post_called) == 1  # one OR model configured
