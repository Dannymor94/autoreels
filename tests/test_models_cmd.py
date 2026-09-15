"""Tests for `arl models` (cmd_models in __main__.py).

HTTP mocked via monkeypatch on cloud.providers._httpx_get.
No real network, no API keys required.
"""
import json
import types
import pytest

import autoreels.__main__ as cli
import autoreels.cloud.providers as P


def _fake_response(data: dict, status: int = 200):
    r = types.SimpleNamespace()
    r.status_code = status
    r.json = lambda: data
    r.raise_for_status = lambda: None
    return r


def _models_payload(*ids):
    return {"data": [{"id": i} for i in ids]}


GROQ_LIVE = ["qwen/qwen3.8-27b", "llama3-70b-8192", "whisper-large-v3"]
OR_LIVE_FREE = ["google/gemma-3-27b-it:free", "meta-llama/llama-3.3-70b-instruct:free"]
OR_LIVE_PAID = ["openai/gpt-4o"]


def _make_get(groq_models=None, or_models=None):
    """Return a fake _httpx_get that serves model lists by URL."""
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


def _make_cfg(model, openrouter_model="google/gemma-3-27b-it:free", fallbacks=None):
    """Minimal R0Config-like object."""
    cfg = types.SimpleNamespace()
    cfg.model = model
    cfg.openrouter_model = openrouter_model
    cfg.openrouter_fallback_models = fallbacks or []
    return cfg


# --- Test 1: configured model present → OK, exit 0 ---

def test_models_all_present_exit_0(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(P, "_httpx_get", _make_get(
        groq_models=GROQ_LIVE,
        or_models=OR_LIVE_FREE + OR_LIVE_PAID,
    ))
    monkeypatch.setattr(cli, "load_r0_config",
                        lambda _: _make_cfg("qwen/qwen3.8-27b"))
    code = cli.cmd_models(root=str(tmp_path))
    out = capsys.readouterr().out
    assert code == 0
    assert "✓ OK" in out
    assert "✗ ОТСУТСТВУЕТ" not in out


# --- Test 2: configured model missing → flagged, exit 1 ---

def test_models_missing_configured_exit_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(P, "_httpx_get", _make_get(
        groq_models=GROQ_LIVE,
        or_models=OR_LIVE_FREE + OR_LIVE_PAID,
    ))
    monkeypatch.setattr(cli, "load_r0_config",
                        lambda _: _make_cfg("qwen/qwen3.6-27b"))  # old/removed model
    code = cli.cmd_models(root=str(tmp_path))
    out = capsys.readouterr().out
    assert code == 1
    assert "✗ ОТСУТСТВУЕТ" in out


# --- Test 3: one provider down → still shows the other ---

def test_models_groq_down_still_shows_openrouter(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(P, "_httpx_get", _make_get(
        groq_models=None,          # Groq times out
        or_models=OR_LIVE_FREE + OR_LIVE_PAID,
    ))
    monkeypatch.setattr(cli, "load_r0_config",
                        lambda _: _make_cfg("qwen/qwen3.8-27b",
                                            openrouter_model="google/gemma-3-27b-it:free"))
    code = cli.cmd_models(root=str(tmp_path))
    out = capsys.readouterr().out
    # OpenRouter output should appear
    assert "OpenRouter" in out
    # Groq model status unknown (provider unavailable), not crash
    assert "провайдер недоступен" in out


def test_models_no_groq_key_still_shows_openrouter(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(P, "_httpx_get", _make_get(
        groq_models=GROQ_LIVE,
        or_models=OR_LIVE_FREE + OR_LIVE_PAID,
    ))
    monkeypatch.setattr(cli, "load_r0_config",
                        lambda _: _make_cfg("qwen/qwen3.8-27b"))
    # Should not raise, just note missing key
    code = cli.cmd_models(root=str(tmp_path))
    out = capsys.readouterr().out
    assert "GROQ_API_KEY" in out
    assert "OpenRouter" in out
