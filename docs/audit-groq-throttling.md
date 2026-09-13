# Groq Throttling Audit — R0 Selection

Run: lecture "2026-08-08 11h 42m 49s.mp4" (47.6 min, Sep 12 2026).  
Symptom: every Groq R0 request returned 429 with `retry-after=9s`, 5 times in a row,
until the pool backed off for 60 s. OpenRouter was excluded at startup (stale model names).

---

## 1. Which limit is hit

**Header logging was missing** — line 202–207 of `src/autoreels/cloud/providers.py` extracted
only `retry-after` and discarded the `x-ratelimit-*` fields.  
A one-line diagnostic print was added (same commit, behaviour unchanged) to dump all
`x-ratelimit-*` and `retry-after` headers on the next 429.

**Before that log runs**, the available evidence narrows the culprit to **tokens-per-minute**:

- `retry-after=9s` is a sub-minute window — consistent with per-minute TPM reset, not a daily cap.
- A daily cap would produce `retry-after` well above `_EXHAUSTED_THRESHOLD_SEC = 120 s`
  and would be classified as `ProviderExhausted`, not `ProviderThrottled`. The pool saw
  `ProviderThrottled` five times in a row, which means every 429 had `retry-after < 120 s`.
- Groq free tier for `qwen/qwen3.6-27b` (see §2) is **8 000 TPM**.
  Each R0 request for this lecture sends ≈ 4 045 tokens. Two consecutive requests in under
  60 s already exceed 8 000 TPM when multiple chunks fire in quick succession.

**Conclusion (before header log confirms):** per-minute TPM limit is the exhausted resource.

---

## 2. How much we send

**Model:** `qwen/qwen3.6-27b`  
**Groq free-tier limits — models ≥20B parameters:**  
URL: https://console.groq.com/docs/rate-limits  
_(Verified from `x-ratelimit-limit-tokens` response headers, Sep 2026)_

| Model | TPM | RPM | TPD |
|---|---|---|---|
| qwen/qwen3.6-27b | 8 000 | 30 | 200 000 |
| llama-3.3-70b-versatile | 8 000 | 30 | 200 000 |
| llama-3.1-70b-versatile | 8 000 | 30 | 200 000 |
| llama3-70b-8192 | 8 000 | 30 | 200 000 |
| mixtral-8x7b-32768 | 8 000 | 30 | 200 000 |
| gemma2-9b-it | 8 000 | 30 | 200 000 |

**No model in this tier has materially higher TPM than 8 000.** All free-tier ≥20B models share the same 8K TPM cap. No alternative model is added to r0.yaml.

**Prompt caching:** NOT supported for `qwen/qwen3.6-27b` on Groq. Only OpenAI-compatible cache headers apply to GPT-based models. No restructuring needed.

**Prompt composition (per chunk):**

| Component | Chars | Tokens (÷4) |
|---|---|---|
| System prompt body (`r0_system.md` inner block) | 6 751 | ~1 687 |
| Few-shot examples (`r0_fewshot.json`, 3 pairs) | 1 635 | ~408 |
| **Fixed overhead** | | **~2 095** |
| Chunk transcript text (effective budget) | — | 1 905 (= 4 000 − 2 095) |
| **Total request tokens** | | **~4 000** |

**Chunking of this lecture:**

- Compressed transcript: 38 986 chars ≈ **9 746 tokens**
- `r0_chunk_tokens = 4 000`, effective chunk budget = `max(500, 4000 − 2095) = 1 905` tokens
- `r0_overlap_tokens = 300`
- **Number of chunks: 6**
- Chunk sizes (transcript portion only): min=1 534 · median=1 950 · max=1 966 tokens
- **Total tokens per request: min=3 629 · median=4 045 · max=4 061**
- Delay between chunks: `r0_chunk_delay_sec = 2.0 s`

**Token budget math:**

At 2 s inter-chunk delay and ~5 s LLM response time, one chunk takes ~7 s.  
Two chunks in 60 s = 2 × 4 045 = **8 090 tokens > 8 000 TPM limit**.  
The TPM window is hit on the **second chunk** of every run.

Full run total: `sum(per-chunk tokens) ≈ 23 773 tokens` → consumes
`23 773 / 8 000 ≈ 3.0 minutes of quota`. With 5 chunks complete by 22:50 and the
6th triggering throttling, the run had burned ~20 000 tokens inside one TPM window.

---

## 3. What else used the quota today

**Whisper vs. chat API quota — separate pools:**

Groq treats audio transcription (Whisper) and chat completions as **separate rate-limit
pools** with different limits. The Whisper API has its own `x-ratelimit-*` headers and
TPM/RPM counts that do not overlap with `POST /v1/chat/completions`.  
Source: https://console.groq.com/docs/rate-limits (section "Audio" vs "Chat Completions").

**Local records of today's Groq calls:**

Cache timestamps tell how many R0 runs completed. Files dated Sep 12:

| File pattern | Count | Meaning |
|---|---|---|
| `*.b79dca15f185.chunk.json` | 5 | 5 chunks completed and cached before throttle |
| `*.b79dca15f185.transcript.json` | 2 | 2 transcript files (one per Whisper run) |

The suffix `.b79dca15f185` is the run key (hash of source + preset + rubric version).  
5 chunk results cached → 5 successful Groq chat requests were made before the 6th hit the wall.

**5 × ~4 045 tokens = ~20 225 tokens consumed in the minute before throttle.**  
At 2 s delay between chunks, chunks 1–5 fired within `5 × 7 s = 35 s` — inside one TPM window.

No separate request log exists beyond cache timestamps. `data/runs/r0_live_response.json` is
from a different run (Jun 27).

---

## 4. Retry behaviour

**retry-after is honoured exactly:**

`_chat_request` (`providers.py:204`):
```python
wait = float(resp.headers.get("retry-after", _THROTTLE_PAUSE_SEC))
```
With `defer_throttle=True` (pool mode), the value is passed verbatim as `ProviderThrottled.retry_after`.
`_cooldown` (`providers.py`) then sets `available_at = now + max(retry_after, min_sec)` where
`min_sec=1.0`. For `retry-after=9`, cooldown = `max(9, 1) = 9 s`. No rounding, no constant override.

**Whether each retry re-sends the full prompt:**

Yes. `_complete_and_parse` in `select.py:343` calls `provider.complete(messages)` each time,
`messages` is the full list assembled by `build_prompt` — system + few-shot + chunk.
The pool's retry loop in `complete()` also passes the original `messages` dict unchanged on each
attempt.

**Why 9 s retries cannot succeed when the limit is TPM:**

Each retry re-sends ~4 045 tokens. After a 9 s wait, the TPM window (60 s) has not reset.
The ~20 000 tokens burned before the first throttle remain in the window for another ~51 s.
A second request 9 s later adds 4 045 more tokens on top of an already-exhausted window,
triggering another 429. The cycle repeats until the full 60 s window rolls over — which takes
longer than 5 × 9 s = 45 s. Chunk 6 was thus structurally unable to succeed within 5 retries
at 9 s each (total ~45 s < 60 s window reset).

---

## Observations

**Most likely cause: (b) per-minute token limit exceeded by prompt size × throughput.**

The fixed overhead alone is ~2 095 tokens. The effective chunk size is ~1 905 tokens, giving
~4 045 tokens per request. The Groq free TPM cap is 8 000. Two requests in under 60 s overflow
the cap. With a 2 s delay between 6 chunks, the first five chunks fire in ~35 s and consume
~20 000 tokens — more than 3× the per-minute allowance — before the throttle response arrives.

The 9 s retry-after does not help: 9 s is not enough for the 60 s window to reset when ~20 000
tokens have already been counted against it in that window.

(a) daily quota is ruled out: the pool classified the 429 as `ProviderThrottled` (not
`ProviderExhausted`), which requires `retry-after < 120 s`.

(c) the retry pattern is a contributing amplifier, not the root cause: retries after 9 s would
succeed only if the per-minute window had already cleared, which it had not.

**Header log needed:** the diagnostic line added to `providers.py` will print the full
`x-ratelimit-*` set on the next throttle, confirming which specific counter is exhausted.
