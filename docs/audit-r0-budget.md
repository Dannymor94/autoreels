# Audit: R0 chunk-budget collapse — three levers

Read-only audit. No code or prompt changes. Task: find the largest available win
on the R0 chunk budget, which has collapsed to ~2500 tokens and cut a 47-min
lecture from ~5 chunks / 11-13 reels down to 2 chunks / 4 reels.

## TL;DR

**The framing is wrong, and our own prior audit already proved it.**
`docs/audit-groq-413.md` established that the binding free-tier limit is **OTPM
(output tokens per minute) = 1000**, NOT input TPM 8000. Input never blocks — a
whole 47-min transcript (~6.4K real input tokens) fits in a single request and
inside the 131072 context window with room to spare.

The `_effective_chunk_tokens` formula in `src/autoreels/cloud/select.py:72`
budgets the **input** axis against `groq_limit=8000`. That is the wrong axis.
Shrinking the input budget to 2500 does not relieve any real constraint, and —
worse — the drop from 11-13 reels to 4 is consistent with **output truncation at
`max_tokens=900`**, not with input starvation (arithmetic in §4).

The three requested levers, ranked: **(1) pay** removes the constraint entirely
for well under $1/month; **(2) prompt caching does NOT apply** (wrong model, and
even if it did it only relieves input, which is not the bottleneck); **(3) prompt
trimming** saves input tokens we do not need. See RECOMMENDATION.

---

## Lever 1 — PROMPT CACHING

**Does Groq support it on our selection model?** No — not on `qwen/qwen3.6-27b`.
Per [Groq's prompt-caching docs](https://console.groq.com/docs/prompt-caching),
caching is currently limited to **GPT-OSS 20B, GPT-OSS 120B, GPT-OSS-Safeguard
20B**. Our configured `model` (and the OpenRouter gemma/nemotron fallbacks) are
not on the list. "Rolling out to more models soon" — not today.

**Does a cached prefix still count against TPM?** This is the decisive question
and the answer is favourable: *"Cached tokens do not count towards your rate
limits"* — cached input is billing-discounted (50%) **and** exempt from TPM. So
if it applied, it would genuinely recover input budget, not just money.

**But it does not help us, for two independent reasons:**
1. It is not available on our model.
2. Even on a supported model, caching relieves the **input** axis. Our binding
   limit is **output OTPM** (`audit-groq-413.md`). Freeing input budget we are
   not short of buys nothing.

Enabling is automatic (no code change) — so if we ever switch the selection model
to GPT-OSS, caching of the stable system+few-shot prefix (~2100 est / ~2900 real
tokens, sent on every request) would come for free. Recoverable input budget in
that hypothetical: the full prefix per request. Not actionable now.

*One line: Groq does not support caching on our model, and it targets the wrong
axis anyway.*

## Lever 2 — PROMPT SIZE

Measured with the pipeline's own estimator (`_count_tokens`, chars/4). Real Groq
tokens run **~1.37×** higher on Cyrillic (the persisted `token_scale`, confirmed
against `usage.prompt_tokens` in `audit-groq-413.md`).

| Component | est tok | ~real tok |
|---|---:|---:|
| `prompts/r0_system.md` (fenced body) | 1687 | ~2310 |
| `prompts/r0_fewshot.json` (3 pairs) | 408 | ~560 |
| chat-template overhead (`_GROQ_CHAT_TEMPLATE_OVERHEAD`) | 400 | 400 |
| **fixed per-request overhead** | **~2495** | **~3270** |

System prompt by section (est tok):

| Section | est tok | Load-bearing? |
|---|---:|---|
| SELECTION RUBRIC (gates + signals + calibration) | **654** | core — completed-thought + self-contained-start gates live here |
| COVERAGE (exhaustive-scan / not-a-quota) | 298 | behavioural, prevents "least-bad fragment" |
| OUTPUT — STRICT JSON schema | 208 | core — JSON conformance |
| TITLE RULES | 107 | style only |
| PREAMBLE | 79 | trimmable |
| LENGTH & SELF-CONTAINMENT | 79 | duplicated by code validators |
| GROUNDING | 76 | core — real timecodes |
| DEDUP | 42 | duplicated by code (`dedup()`) |
| INPUT format | 35 | keep |
| DESCRIPTION RULES | 26 | keep |

**What could be cut without losing behaviour we depend on** (we depend on: the
completed-thought gate, self-contained-start wording, JSON conformance, grounding
to real timecodes — none of these move):

- **DEDUP (42) + LENGTH bounds prose (part of 79)** — both are re-enforced
  deterministically by code (`dedup()`, `flag_durations()`). Telling the model to
  self-dedup and self-bound is belt-and-suspenders. Safe to trim to one line each.
  Saving: **~60-80 est tok**.
- **COVERAGE (298)** — three paragraphs restating "a chunk is not a quota" and
  "don't reach for the least-bad fragment". Compressible to ~120 tok without
  losing the anti-quota signal. Saving: **~150-180 est tok**.
- **SELECTION RUBRIC (654)** — the strong/anti/disqualifier signal lists overlap
  heavily (e.g. "cuts mid-thought" appears in both anti-signals and
  disqualifiers). Dedup the lists, keep both hard gates verbatim. Saving:
  **~100-150 est tok** at some risk — this is the highest-value behavioural block,
  trim carefully.

Realistic total trim: **~300-400 est tok (~400-550 real)** ≈ 15-18% of the fixed
overhead. Do NOT touch the two HARD GATE blocks or the OUTPUT schema.

**Few-shot 3→1 pairs:** the two negative examples (service talk → `[]`, and the
real PXL-corpus mid-thought garbage → `[]`) cost ~63 est tok combined; the
positive costs ~250. Dropping to 1 pair saves ~63-155 est tok. **Risk: high.**
The negatives are what teach "empty is the right answer" and anchor JSON
conformance for the `[]` case (CLAUDE.md invariant 3). Dropping them invites the
model to fill every chunk. Not recommended — the saving is small and the two
negatives carry disproportionate behavioural weight.

**Net:** prompt trimming is real but recovers **input** budget, which §4 shows is
not the binding constraint. Low value against this problem.

## Lever 3 — PAID TIER

**Limits & pricing** ([Groq pricing 2026](https://www.eesel.ai/blog/groq-pricing),
[free-tier limits](https://tokenmix.ai/blog/groq-free-tier-limits-2026)):
adding a card moves the org from free (`on_demand`: ~6-8K TPM, **1000 OTPM**, 30
RPM) to the **Developer tier: ~250-300K TPM, ~1000 RPM**, roughly **10×+**, plus a
25% token discount. Crucially the Developer tier lifts the **OTPM** cap that is
our actual bottleneck.

**Estimated monthly cost.** Assumptions: 1 source of 45-90 min per run, ~5 runs /
week ≈ **20 runs/month**. Per run: transcript ~6-13K real input tokens, sent
across chunks with ~1.3× overlap + the ~3.3K fixed prefix per chunk ≈ **~40K
input tok/run**; output ~3-4K tok/run (11-13 reels × ~250 tok). Monthly: **~800K
input, ~80K output**.

Our model (27-31B class) is not individually listed, so bracket it:
- At Llama-3.3-70B rates ($0.59 in / $0.79 out per M): 0.8M×$0.59 + 0.08M×$0.79 =
  **~$0.53/month**.
- At GPT-OSS-120B rates ($0.15 / $0.60): **~$0.17/month**.

Either way **well under $1/month**, before the 25% Developer discount.

**Does paying remove the constraint?** **Yes, completely.** The entire
chunk-budget / token-scale / OTPM-avoidance apparatus exists solely to survive the
free tier's 1000 OTPM and 8K TPM. The Developer tier's ~250K TPM and lifted OTPM
make chunking a quality choice (bounding output per response) rather than a
survival constraint, and `max_tokens` can rise well above 900. Cost is negligible.

## Lever 4 — MUST WE SEND THE SYSTEM PROMPT WITH EVERY CHUNK?

Yes, we currently do — `build_prompt()` (`select.py:122`) prepends system +
few-shot to every chunk's messages, so each of N chunks pays the ~3.3K real-token
fixed overhead. But the more important question is whether we need N chunks at all.

**Chunks a typical lecture needs — on input:** the 47-min transcript is ~4700 est
/ ~6400 real input tokens. That fits in **one** request: under the 8K input-TPM
ceiling within a single minute, and trivially inside the 131072 context window
(binding limit is throughput/min, not context — confirmed). Input does not force
chunking at all.

**So why can't it be one request? Output.** The binding limit is OTPM 1000/min and
per-request `max_tokens=900`. A single request covering the whole lecture would
have to emit all 11-13 reels of JSON (~3000-4000 output tokens) in one response —
truncated hard at 900 tokens. **This is almost certainly the real cause of the
reel-count collapse:**

- `max_tokens=900` ≈ **3 segments** of JSON output per response.
- 2 fat chunks × ~2 reels each ≈ **4 reels** — exactly what was observed.
- 5 smaller chunks × ~2-3 reels each ≈ **11-13 reels** — the earlier result.

Larger input chunks pack more good moments into one response, and the response
then **silently truncates** at `max_tokens`, dropping the surplus. Fewer/larger
chunks lose reels; **smaller** chunks recover them — the opposite of what the
"raise the budget" framing assumes.

**Waiting longer between fewer, larger requests?** Does not help. Throughput is
bounded by OTPM: total output ÷ 1000/min. 11-13 reels ≈ ~3-4K output tokens ⇒ a
floor of **~4 paced requests/minute regardless of how input is chunked**. You
cannot trade input size for fewer requests, because the requests are gated by
output volume, not input volume. Bigger input chunks just truncate.

---

## RECOMMENDATION

**Highest-value change: pay for the Developer tier (~$0.20-0.55/month).**
It lifts the OTPM cap that is the actual binding constraint (per our own
`audit-groq-413.md`), raises TPM ~10×, and lets `max_tokens` climb well above 900
so a chunk can report all its moments without truncation. Every other lever here
is engineering to survive a limit that costs less than a coffee per month to
remove. Gain: the constraint disappears. Cost/risk: a credit card on file; ~$0.20-
$0.55/month at our volume; no code change required to benefit.

**If staying on the free tier, ranked below:**

2. **Stop budgeting the wrong axis; size chunks by expected output, not input.**
   The reel collapse is output truncation at `max_tokens=900`, not input
   starvation. Smaller chunks (more, not fewer) keep each response under the OTPM
   cap and recover the missing reels. This is a behavioural fix, not a budget
   fix — flagged here, not applied (task is read-only). Gain: recovers the 11-13
   reel count. Risk: more requests → more wall-clock under the ~1 req/min pace.

3. **Trim the system prompt by ~300-400 est tokens** (dedup the rubric signal
   lists; compress COVERAGE; drop the code-duplicated DEDUP/LENGTH prose). Keep
   both HARD GATEs, the OUTPUT schema, and GROUNDING untouched. Gain: ~15-18% of
   input overhead — but input is not the binding limit, so near-zero effect on the
   actual problem. Value: marginal.

4. **Prompt caching: not applicable.** Wrong model (GPT-OSS only) and wrong axis
   (input, not output). Revisit only if the selection model ever moves to GPT-OSS.

5. **Few-shot 3→1: do not.** Saves ~60-155 est tokens at high risk to the
   "empty is valid" behaviour and JSON conformance the two negatives anchor.

## Sources

- [Groq Prompt Caching docs](https://console.groq.com/docs/prompt-caching)
- [Groq pricing 2026 — eesel AI](https://www.eesel.ai/blog/groq-pricing)
- [Groq free-tier limits 2026 — TokenMix](https://tokenmix.ai/blog/groq-free-tier-limits-2026)
- Internal: `docs/audit-groq-413.md` (OTPM=1000 is the binding limit), `src/autoreels/cloud/select.py`, `config/r0.yaml`
