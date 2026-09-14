#!/usr/bin/env python3
"""Standalone probe: isolate why Groq returns 429/413 on a full quota.

Self-contained. Imports NO pipeline code. Reads only:
  - the model ids from config/r0.yaml
  - GROQ_API_KEY / OPENROUTER_API_KEY from the environment (or a KEY=VALUE .env)

Hypothesis under test (from config/r0.yaml comment): Groq validates
`prompt_tokens + max_tokens` against the per-minute token budget (TPM, 8000) at
ADMISSION time. If so, a request is rejected with the budget still showing
remaining=8000/reset=1ms, because max_tokens is *reserved* up front — waiting
never helps, and shrinking only the prompt helps only if it drops the sum below
the cap.

The probe bisects the two axes independently:
  1. minimal ping                    -> auth/connectivity sanity (no size)
  2. prompt size walk @ max_tokens=2048
  3. same walk @ max_tokens=512 and @ max_tokens=8192   (isolates max_tokens)
For the first failure it dumps payload bytes + the full error body (Groq states
the real limit and the computed request size there). 70 s between every request
so per-minute windows never confound the result.

Usage:
    GROQ_API_KEY=... .venv/bin/python scripts/probe_groq.py
    .venv/bin/python scripts/probe_groq.py --no-wait   # 2s gaps, quick smoke
    .venv/bin/python scripts/probe_groq.py --provider groq   # skip OpenRouter
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
R0_YAML = REPO_ROOT / "config" / "r0.yaml"
ENV_FILE = REPO_ROOT / ".env"

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

# Same estimator the pipeline uses (providers.py::_count_tokens_approx): 4 chars ~= 1 token.
def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# One Cyrillic sentence, repeated to hit a target token estimate. Real content, so the
# provider's own tokenizer (Cyrillic packs fewer chars/token than Latin) reports a
# usage.prompt_tokens we can compare against our 4-chars/token guess.
_FILLER_SENTENCE = (
    "Это тестовое предложение на русском языке для наполнения промпта. "
    "Оно повторяется много раз, чтобы набрать нужный объём токенов и проверить "
    "поведение провайдера при разном размере запроса. "
)


def make_filler(target_tokens: int) -> str:
    """~target_tokens by our 4-chars/token estimate (target*4 chars of Russian)."""
    target_chars = target_tokens * 4
    reps = (target_chars // len(_FILLER_SENTENCE)) + 1
    return (_FILLER_SENTENCE * reps)[:target_chars]


def load_env() -> None:
    """Load KEY=VALUE lines from .env into os.environ (does not overwrite existing)."""
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


def load_models() -> tuple[str, str]:
    cfg = yaml.safe_load(R0_YAML.read_text(encoding="utf-8"))
    return cfg["model"], cfg["openrouter_model"]


def rl_headers(headers) -> dict:
    """Extract just the x-ratelimit-* / retry-after headers, lowercased."""
    return {
        k.lower(): v
        for k, v in headers.items()
        if "ratelimit" in k.lower() or k.lower() == "retry-after"
    }


def send(url: str, api_key: str, model: str, *, system: str, user: str,
         max_tokens: int, response_format: bool, reasoning_none: bool,
         extra_headers: dict | None = None) -> dict:
    """One chat-completions call. Returns a result record; never raises on HTTP status."""
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    payload: dict = {"model": model, "messages": messages, "temperature": 0.0,
                     "max_tokens": max_tokens}
    if response_format:
        payload["response_format"] = {"type": "json_object"}
    if reasoning_none:
        payload["reasoning_effort"] = "none"

    headers = {"Authorization": f"Bearer {api_key}"}
    if extra_headers:
        headers.update(extra_headers)

    body_bytes = len(json.dumps(payload).encode("utf-8"))
    our_est = est_tokens(system) + est_tokens(user)

    rec: dict = {"our_est_prompt": our_est, "max_tokens": max_tokens,
                 "payload_bytes": body_bytes}
    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=httpx.Timeout(120.0))
    except Exception as e:  # noqa: BLE001 — network error is itself a datum
        rec.update(status=None, error=f"{type(e).__name__}: {e}", rl={}, api_prompt_tokens=None)
        return rec

    rec["status"] = resp.status_code
    rec["rl"] = rl_headers(resp.headers)
    if resp.status_code == 200:
        data = resp.json()
        usage = data.get("usage") or {}
        rec["api_prompt_tokens"] = usage.get("prompt_tokens")
        rec["error"] = None
    else:
        rec["api_prompt_tokens"] = None
        rec["error"] = resp.text
    return rec


def wait(sec: float) -> None:
    if sec <= 0:
        return
    print(f"    …ждём {sec:.0f}с (чтобы per-minute окно не смешало результат)", flush=True)
    time.sleep(sec)


PROMPT_SIZES = [500, 1000, 2000, 3000, 4000, 5000, 6000]
MAX_TOKENS_VARIANTS = [512, 2048, 8192]
PING_SYSTEM = "You are a test endpoint."
PING_USER = "ping"
FILLER_SYSTEM = "Reply with a short json object like {\"ok\": true}."


def run_probe(label: str, url: str, api_key: str, model: str, *,
              reasoning_none: bool, extra_headers: dict | None,
              gap_sec: float) -> list[dict]:
    print(f"\n{'='*70}\n  ПРОБНИК: {label}  (model={model})\n{'='*70}", flush=True)

    # --- Step 1: minimal ping. If this fails, size is not the cause. ---
    print("\n[1] minimal ping (system+user='ping', max_tokens=16, без response_format)", flush=True)
    ping = send(url, api_key, model, system=PING_SYSTEM, user=PING_USER, max_tokens=16,
                response_format=False, reasoning_none=reasoning_none, extra_headers=extra_headers)
    print(f"    status={ping['status']}  rl={ping['rl']}", flush=True)
    if ping["status"] != 200:
        print(f"    ✗ PING FAILED — проблема НЕ в размере. Полное тело ошибки:\n{ping['error']}",
              flush=True)
        return [{"phase": "ping", **ping}]
    print(f"    ✓ ping ok  (api prompt_tokens={ping['api_prompt_tokens']})", flush=True)

    # --- Steps 2+3: prompt size × max_tokens grid ---
    results: list[dict] = []
    first_failure: dict | None = None
    for mt in MAX_TOKENS_VARIANTS:
        for size in PROMPT_SIZES:
            filler = make_filler(size)
            wait(gap_sec)
            print(f"\n[grid] prompt~{size}tok  max_tokens={mt}", flush=True)
            rec = send(url, api_key, model, system=FILLER_SYSTEM, user=filler,
                       max_tokens=mt, response_format=True, reasoning_none=reasoning_none,
                       extra_headers=extra_headers)
            rec["phase"] = "grid"
            rec["req_prompt_size"] = size
            results.append(rec)
            status = rec["status"]
            api_pt = rec["api_prompt_tokens"]
            print(f"    status={status}  api_prompt_tokens={api_pt}  "
                  f"our_est={rec['our_est_prompt']}  bytes={rec['payload_bytes']}  rl={rec['rl']}",
                  flush=True)
            if status != 200 and first_failure is None:
                first_failure = rec
                print(f"    ✗ ПЕРВЫЙ ОТКАЗ. payload={rec['payload_bytes']} байт. "
                      f"Полное тело ошибки:\n{rec['error']}", flush=True)

    print_table(label, results)
    return results


def print_table(label: str, results: list[dict]) -> None:
    grid = [r for r in results if r.get("phase") == "grid"]
    if not grid:
        return
    print(f"\n{'-'*70}\n  ТАБЛИЦА: {label}\n{'-'*70}", flush=True)
    print(f"  {'max_tok':>8} {'prompt~':>8} {'status':>7} {'api_pt':>8} "
          f"{'our_est':>8} {'sum(pt+mt)':>11}", flush=True)
    for r in grid:
        api_pt = r["api_prompt_tokens"]
        s = "PASS" if r["status"] == 200 else f"FAIL/{r['status']}"
        total = (api_pt + r["max_tokens"]) if api_pt is not None else None
        print(f"  {r['max_tokens']:>8} {r['req_prompt_size']:>8} {s:>7} "
              f"{str(api_pt):>8} {r['our_est_prompt']:>8} {str(total):>11}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["groq", "openrouter", "both"], default="both")
    ap.add_argument("--no-wait", action="store_true",
                    help="2s gaps instead of 70s (quick smoke, may confound per-minute windows)")
    args = ap.parse_args()
    gap = 2.0 if args.no_wait else 70.0

    load_env()
    groq_model, or_model = load_models()

    if args.provider in ("groq", "both"):
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            print("нет GROQ_API_KEY в окружении/.env — пропускаю Groq", flush=True)
        else:
            run_probe("GROQ", GROQ_CHAT_URL, key, groq_model,
                      reasoning_none=True, extra_headers=None, gap_sec=gap)

    if args.provider in ("openrouter", "both"):
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            print("нет OPENROUTER_API_KEY в окружении/.env — пропускаю OpenRouter", flush=True)
        else:
            run_probe("OPENROUTER", OPENROUTER_CHAT_URL, key, or_model,
                      reasoning_none=False,
                      extra_headers={"HTTP-Referer": "https://github.com/Dannymor94/autoreels",
                                     "X-Title": "autoreels"},
                      gap_sec=gap)
    return 0


if __name__ == "__main__":
    sys.exit(main())
