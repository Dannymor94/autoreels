# M224 — Coordinator static preflight (not acceptance evidence)

Date: 2026-11-18. Production main pinned: `3c011e94263e16e5780936b4769d3490cd03b682`. M223 independent Sol **limited-scope PASS** is in `handoff/m223/SOL-REVIEW-R5.md`; M224 diagnostic stage A is now allowed. No production code was edited for this preflight.

**Status: STATIC HYPOTHESES ONLY.** These observations help design synthetic CLI fixtures; they do **not** establish production failure until the CLI code path with `config/r0.yaml` and independent Sol QA are executed. Refer to `handoff/m224/TASK-M224.md` for the binding task.

## #5 — min_sec after context_start repairs

Read `src/autoreels/cloud/autocut.py`:

- `context_start()` short dangling first-sentence branch around lines 706–714 drops the first ref and sets `u.t0 += rows[0][1]`; unlike the later `context_later` branch (around lines 750–756), this short-drop branch has **no explicit `p.min_sec` recheck**.
- In `propose()` around lines 1209–1280, `context_start` may change `clip` and its duration. Later `secs = sum(_dur(u) for u in clip)` is computed, and `Proposal(seconds=round(secs,1))` is emitted around line 1308, without an obvious subsequent `secs >= p.min_sec` guard.
- Production `config/r0.yaml` explicitly sets `autocut.min_sec=25`, `context_drop_words=5`, `context_later=false`, `context_start=true`, `generator=mixed`.

**High-value isolated CLI fixture:** a 25.0-second eligible seed with a 2.0s standalone-ineligible first sentence (≤5 words) followed by an independently meaningful 23.0s sentence. Make `context_start` select the short-drop branch, not `context_later`, and record exact `t0/t1`, `refs`, `seconds` before/after. Hypothesis: output may become **23s**, below the required 25s. If production filters prevent entry, adapt the fixture and mark the original one `NOT_REPRODUCED` rather than using direct `AutoParams()` defaults.

## #6 — refs/time drift when dropping sentence with a pause

- `fix_open_end()` around lines 625–648 sums only durations of removed sentence rows: `cut += rows[k][1]`, then sets `new_last.t1 = last.t1 - cut` while also trimming refs via `keep_refs_until`.
- **End case:** sentence `1.1` spans `0–24s`, pause `24–28s`, open-ending sentence `1.2` spans `28–31s`. `cut=3s`, original `t1=31`, so code would set `new_last.t1=28`, while last retained audible sentence ends at **24**. Ref says `1.1`, but thought time window may retain 4s of silence. Note `total-cut=28>=25` despite actual playable words being only 24s.
- **Start case:** `context_start()` short-drop path adjusts `t0 += duration(first sentence)` and may omit inter-sentence silence. Example first sentence `0–2s`, pause `2–6s`, second sentence `6–29s`: after dropping first sentence, `t0=2` while first retained audio begins at **6**.

**High-value isolated CLI fixture:** real sentence mapping + synthetic aligned times, actual `end_tone(ref)` from the safely loaded synthetic prosody path (if configured and attainable without real audio). Assert `refs`, `t0`, `t1`, exact playable speech duration and pauses. Repeat for beginning removal. Do not equate bounding `t1-t0` with **played duration**; account for gaps and the definitive refs used by montage.

## Gate and safety

- Proof-only M224 stage A; no changes to algorithm or `tests/` before independent Sol review.
- No paid LLM, full rendering, user recordings, owner manifests/reviews/transcripts, or unapproved external side effects. Temporary output must be isolated.
- Capture actual CLI config and branch visitation, stdout/stderr, real return codes and hashes. An isolated helper-only run is supporting information, not CLI proof.
- If synthetic validators block a scenario, capture exact `NOT_REPRODUCED` and failed preconditions. Independent Sol must verify M224 separately.
