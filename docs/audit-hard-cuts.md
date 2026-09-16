# Audit: 9 HARD clip-endings that "appeared where there used to be none"

READ-ONLY diagnosis. No behaviour changed. Establishes whether the HARD cuts are a snap
regression, stale manifests, or something else.

## TL;DR

Neither a snap regression nor stale manifests. **`diagnose-cuts` and `resnap` read the wrong
transcript.** Both resolve the transcript for a manifest *without* the transcription
`params_key`, so when more than one transcript variant exists for an audio they load the
params-key-less orphan (produced by an old empty-`initial_prompt` run) instead of the
params-keyed transcript the manifest was actually built on. The orphan has far less punctuation
(Whisper drops Russian sentence marks without prompt priming — the exact problem
`config/transcribe.yaml`'s `initial_prompt` was added to fix on 2026-09-13), so sentence-terminal
clip ends vanish and clean endings are re-classified as mid-word HARD cuts.

Measured on the interview manifest, against its **own** transcript vs. the orphan:

| transcript scored against          | clean | soft | HARD | HARD clips |
|------------------------------------|:-----:|:----:|:----:|------------|
| orphan (what `diagnose-cuts` loads)|   4   |  7   |  4   | r05,r06,r08,r14 |
| `84b62c` = current `params_key`    |  14   |  0   |  1   | r14 |

The manifest is **14/15 clean in its own transcript**; the extra HARD/soft are an artefact of the
diagnostic reading a different, worse-punctuated transcription.

---

## Scope note: this machine vs. the Windows evidence

The `17 clean · 19 soft · 9 HARD / 45` figures were gathered on the Windows box, across manifests
that are **not on this dev Mac**. Local `diagnose-cuts` here reports `26 · 11 · 5 / 42` over four
manifests. In particular the non-suffixed `PXL_20260729_085910095.json` (the run that owns the
Windows examples "в котором мы не бываем" r02, "так она и работает естественно" r13) does not exist
in this machine's `manifests/`. So the exact Windows count cannot be reproduced here — its manifests
and its cache are elsewhere. What *is* reproduced here is the **mechanism**, which is machine-
independent code (`_transcript_for_manifest`), plus one interview manifest that carries the same
class of HARD the Windows report describes. The mechanism explains the Windows pattern; the exact
9 is not re-derivable without that machine's files.

Note the two runs of the same source really are different R0 runs: the Windows example
"пробовал мне как-то это запомни" (pause 0.38) is attributed there to `PXL_…095 r07`, and appears
here as `PXL_…_34f06abf r14` (pause 0.38) — same speech, different reel id, different selection.

---

## 1. Age of the manifests carrying HARD

All manifests that carry a HARD cut are **post-M1.5** (they contain `end_snap_reason`,
`end_drift_sec`, `r0_start/r0_end`, `rank`). None predate the clip-ending work.

| manifest                     | mtime            | source_kind | r0_start/end | end_drift/reason | start_snap_reason | rank | HARD (local diagnose) |
|------------------------------|------------------|-------------|:------------:|:----------------:|:-----------------:|:----:|:---------------------:|
| 2026-08-08 09h 33m 14s       | 2026-08-21 22:47 | (none)      | ✓            | ✗                | ✗                 | ✗    | 0 |
| 2026-08-08 10h 59m 38s       | 2026-09-11 22:03 | (none)      | ✓            | ✓                | ✗                 | ✗    | 0 |
| 2026-08-08 11h 42m 49s       | 2026-09-15 11:40 | lecture     | ✓            | ✓                | ✗                 | ✓    | 1 (r01) |
| PXL_…_34f06abf               | 2026-09-14 21:22 | interview   | ✓            | ✓                | ✓                 | ✓    | 4 (r05,r06,r08,r14) |

The two zero-HARD manifests (09h33, 10h59) have **only one transcript variant in cache** (the
empty-prompt `…​.transcript.json`), so `diagnose-cuts` loads exactly the transcript they were built
on → faithful → 0 HARD. The two HARD-carrying manifests (11h42, PXL) each have **three variants**
(`84b62c`, `b79dca`, and the no-params orphan); `diagnose-cuts` loads the orphan, which is *not*
what they were built on. The split of HARD tracks transcript-variant availability, not manifest age.

### Two runs of the same source

Locally only `PXL_…_34f06abf.json` is present (plus `PXL_…_34f06abf.discarded.json`, which is not
a second run — it is the over-generation reject list: 9 entries flagged `overlap_dedup` /
`dangling_start`). The non-suffixed `PXL_20260729_085910095.json` exists only as a transcript
(`transcripts/…095.txt`), not as a manifest here, so a direct manifest-to-manifest comparison of the
two runs cannot be done on this machine. Both share source speech (the shared clip above), both are
interview-kind, and both are therefore subject to the same transcript-resolution bug.

## 2. What the snap actually did (stored fields vs. diagnostic label)

Key point from the task — "a clip ending mid-word should never have reason `sentence`". It does here,
and the reason is instructive: **`end_snap_reason` describes the snap step; the diagnostic re-derives
its own verdict from word timings in a *different* transcript.** The two disagree because they look at
two different transcriptions.

| clip | diagnostic verdict / cause (orphan transcript) | stored end_snap_reason | stored drift | mechanism |
|------|-----------------------------------------------|------------------------|:------------:|-----------|
| PXL r05 | HARD · висячее (snap-fallback)                | `no_end` (`unpunctuated`) | +0.00 | snap found no end ≥ r0_end in the *orphan*; kept r0_end on "в". In `84b62c` there is a sentence end → CLEAN. |
| PXL r06 | HARD · PAD-хвост +0.12с                        | `sentence`             | +0.32 | correct sentence snap, then `apply_padding` +0.7 tail pulled the next word "И". Padding overshoot, not snap. |
| PXL r08 | HARD · snap-fallback (нет чистой границы)      | `before_host_turn`     | +2.60 | interview host-turn stage cut end back to just before a host turn → mid-word "вы". Not snap-fallback at all. |
| PXL r14 | HARD · snap-fallback (нет чистой границы)      | `sentence`             | +0.34 | stored `sentence` matches "запомнило." (168.84) in `84b62c`; the orphan has "запомни" with no period → мид-слово. |
| 11h42 r01 | HARD · PAD-хвост +0.10с                      | `sentence`             | +5.78 | correct sentence snap (+5.78s to "…поступать."), padding tail then pulled "Она". Padding overshoot. |

So of the five local HARD, the stored reasons are `no_end`, `before_host_turn`, `sentence`×3 — none
is a "snap-fallback (нет чистой границы)". The diagnostic's `snap-fallback (нет чистой границы)`
label is a heuristic re-derivation in `diagnose.py::_hard_cause`, computed from the loaded
(orphan) transcript; it does not reflect the mechanism that actually set the boundary.

## 3. Why the fallback was reached — what was in the window

Punctuation density measured over ±15 s around `r0_end`, in the transcript `diagnose-cuts` loads
(the orphan):

| clip | words ±15s | punctuated | sentence-ends | nearest sentence-end to r0_end | largest real pause in window | verdict |
|------|:----------:|:----------:|:-------------:|-------------------------------|------------------------------|---------|
| PXL r05 | 73 | 13 | 3 | Δ0.76 s | 0.40 s | region **has** punctuation nearby |
| PXL r06 | 68 | 11 | 3 | Δ0.10 s | 0.86 s | region **has** punctuation nearby |
| PXL r08 | 47 | 0  | 0 | none in window | 0.00 s | **unpunctuated desert** |
| PXL r14 | 78 | 0  | 0 | none in window | 0.00 s | **unpunctuated desert** |

r08 and r14 sit in fully unpunctuated, gap-less stretches (verified word-by-word: e.g. around r14
the visible 2.0 s "gap" is actually the *duration* of the word "где" 171.00–173.02; every
inter-word gap is 0.00 s and there is no sentence mark for ~20 s). There the punctuation-first snap
correctly returns `no_end`, end stays at `r0_end`, and `r0_end` — placed by R0/LLM on a
compressed-sentence boundary Whisper never punctuated — lands on a sub-`max_micro_pause` (0.4 s)
word boundary → мид-слово.

But r05 and r06 come from regions that **do** have punctuation within 0.1–0.8 s. Their HARD is not a
punctuation desert at all: r05 is `no_end` only in the orphan (the punctuated variant finds the
sentence), and r06 is a padding overshoot after a correct sentence snap. This is the second tell
that the orphan transcript, not the snap logic, is driving the count.

## 4. Reproduce or not — resnap before/after

`resnap` recomputes boundaries from stored R0 bounds with today's snap/padding/trim, no LLM.
Reproduced **read-only** (deep-copied reels; nothing written to disk or git — the real
`arl resnap` writes and pushes, so it was not run). Both before and after are classified against the
transcript the tool loads (the orphan):

| manifest | before (manifest) | after (resnap) |
|----------|-------------------|----------------|
| 09h33    | 9c / 0s / 0H | 7c / 2s / 0H |
| 10h59    | 10c / 1s / 0H | 8c / 2s / **1H** (PAD-хвост) |
| 11h42    | 3c / 3s / 1H | 4c / 2s / 1H (different clip) |
| PXL      | 4c / 7s / 4H | 7c / 5s / 3H |
| **grand**| **26 / 11 / 5** | **26 / 11 / 5** |

resnap does **not** clear them (grand total unchanged) and even shuffles the set — it introduces a
new PAD-хвост HARD in 10h59, and in PXL it drops r08 (because resnap does not replay the interview
`before_host_turn` stage) while r14 stays HARD. But this "does not clear" is **against the orphan
transcript**; it is measuring the same wrong input, so it neither confirms nor clears a real defect.

The decisive test is re-scoring the frozen manifest boundaries against the transcript the run
actually used (current `params_key` = `84b62c5276da`, computed from `config/transcribe.yaml`):

- **PXL interview:** orphan `4c/7s/4H` → `84b62c` **`14c/0s/1H`**. Only r14 survives.
- **11h42 lecture:** orphan `3c/3s/1H` → `84b62c` `5c/0s/2H` (shifts to r03,r06). For the lecture the
  correct variant is not uniformly kinder — it confirms only that the verdict is transcript-dependent
  and that the orphan is the wrong yardstick.

The one HARD that survives on the correct transcript, PXL **r14**, is marginal: the stored end
168.77 falls 0.07 s short of the sentence-terminal "запомнило." (t1 = 168.84), so the classifier
takes the previous word "это" and calls it мид-слово. That is a genuine but tiny boundary
undershoot, not the "punctuation desert / snap-fallback" the label claims.

### Root of the mismatch (mechanism, for the record — no fix proposed)

- `transcribe()` caches at `transcript_cache_path(cache_dir, audio, params_key)` where
  `params_key = sha256(provider|model|prompt_hash)[:12]` — currently `84b62c5276da`.
- `_transcript_for_manifest()` (used by **both** `cmd_diagnose_cuts` and `cmd_resnap`,
  `__main__.py:2578`) calls `transcript_cache_path(cache_dir, audio)` with **no** `params_key`, so it
  resolves `…​.transcript.json` — the empty-prompt orphan.
- Timeline: the `initial_prompt` priming landed 2026-09-13 (`90c964f`), which is exactly what makes
  Whisper emit Russian sentence punctuation. Runs after that date build manifests on `84b62c`;
  the pre-prompt empty-`initial_prompt` transcripts remain in cache as orphans. Any manifest built
  after the prompt fix, whose audio still has a pre-fix orphan in cache, is now scored by
  `diagnose-cuts`/`resnap` against that orphan.
- When only the orphan exists (09h33, 10h59), the loaded transcript happens to match the build →
  faithful → 0 HARD. When both exist (11h42, PXL), the tool loads the wrong one → phantom HARD.
- `resnap` shares the same resolution, so it does not merely *misreport* — run for real it would
  recompute and **write** boundaries against the orphan transcript, then commit/push them.

## OBSERVATIONS

1. **It is neither.** Not a snap regression (the frozen manifest boundaries are ≈14/15 clean when
   scored against the transcript they were built on) and not "manifests predate the fixes" (every
   HARD-carrying manifest is post-M1.5 and was built on the punctuated `84b62c` transcript). It is a
   **measurement bug in the diagnostic and in resnap**: `_transcript_for_manifest` resolves the
   transcript without `params_key` and loads a stale, empty-prompt, poorly-punctuated orphan instead
   of the transcript the manifest was produced from. Against the correct transcript the "9 HARD"
   class collapses (PXL: 4→1).

2. The trigger is the 2026-09-13 `initial_prompt` punctuation improvement (`90c964f`): it changed
   what `run` transcribes to (`84b62c`) but the diagnostic/resnap transcript lookup was never updated
   to match, so an improvement to real output surfaced as phantom HARD cuts in the tooling.

3. The diagnostic's cause label `snap-fallback (нет чистой границы)` is unreliable as an attribution:
   for the local clips the real mechanisms are `before_host_turn` (r08), `apply_padding` overshoot
   (r06, 11h42 r01), and `no_end` in the wrong transcript (r05). Only r08/r14 sit in true
   unpunctuated deserts, and r14 is the single HARD that survives on the correct transcript — as a
   0.07 s boundary undershoot, not a fallback.

4. Residual genuine issue (small, separate from this audit's question): on truly unpunctuated,
   gap-less interview stretches the punctuation-first snap has no sentence mark and no
   pause ≥ 0.4 s to land on, so it keeps `r0_end`, which itself can sit mid-thought (PXL r14). This
   is the known weak spot on interview material and is real under today's code — but it is one clip,
   not nine.

---

## FIX APPLIED (2026-09-16)

The measurement/write bug above is now fixed. Changes:

- **Manifest schema** gains `transcript_params_key` — `cmd_run` records the params_key of the
  transcript the manifest was built from (from the transcript's stamped `provider|model|prompt_hash`).
- **`_transcript_for_manifest` → `_resolve_transcript`**: resolves the transcript **strictly by
  params_key** — the manifest's recorded key (authoritative), or the current config's key as a
  read-only legacy best-effort. It **never** falls back to the params-key-less orphan
  (`<hash>.transcript.json`).
- **`diagnose-cuts`**: when no matching transcript exists it prints `нет транскрипта с
  params_key=… — пропуск` and skips (a wrong measurement is worse than none). The per-clip HARD
  `cause` now reports the **real** stored `end_snap_reason` (`before_host_turn` / `no_end` /
  `sentence`(+`PAD-хвост`)) instead of the catch-all `snap-fallback (нет чистой границы)`, which is
  kept only as the legacy fallback for manifests without the field.
- **`resnap`**: requires a recorded `transcript_params_key`; resolves by it only (never the config
  fallback); a guard verifies the resolved transcript's stamped identity equals the manifest's key
  and **refuses to write** (naming both keys) on absence or mismatch. Legacy manifests without the
  key are refused until one full `arl run` — the same migration precedent as the `r0_start/r0_end`
  fields.

Tests: `tests/test_transcript_resolution.py` (params-keyed wins over orphan; orphan-only → diagnose
skips + resnap refuses; guard rejects a params_key mismatch) plus the updated `test_cli.py`
diagnose/resnap fixtures.

### Corrupted-manifest audit (on-disk, this machine)

Detection: classify each manifest's frozen boundaries against the transcript it was actually built
from (its recorded key, or the current-config `84b62c` variant). An orphan-resnapped manifest's
ends would land mid-word when viewed in the correct transcript.

| manifest | cache variants | built-on | verdict vs. correct transcript | corrupted? |
|----------|----------------|----------|--------------------------------|------------|
| PXL_…_34f06abf         | orphan + `84b62c` | `84b62c`            | 14 clean / 1 HARD (r14, 0.07 s undershoot) | **NO** |
| 2026-08-08 11h 42m 49s | orphan + `84b62c` | `84b62c`            | 5 clean / 2 HARD (genuine)                 | **NO** |
| 2026-08-08 10h 59m 38s | orphan only       | empty-prompt build | — (now skipped)                            | **NO** |
| 2026-08-08 09h 33m 14s | orphan only       | empty-prompt build | — (now skipped)                            | **NO** |

None of the four manifests on this dev Mac are orphan-corrupted. PXL and 11h42 were last written by a
correct run against `84b62c` (their stored r14 end matches "запомнило." in `84b62c`, not "запомни" in
the orphan; classifying their frozen boundaries against `84b62c` yields the clean picture above).
09h33/10h59 were genuinely built with an empty `initial_prompt` (only the orphan exists for their
audio) — not corrupted, but now skipped by `diagnose-cuts` and refused by `resnap` until one re-run,
rather than measured/written against a transcript that isn't provably theirs.

**The six manifests resnapped on the Windows machine yesterday are not present on this Mac and cannot
be inspected here** — they are the suspect set named in the task. Recovery is deterministic and does
not need this machine: with the fix, `arl resnap` now **refuses** every legacy manifest lacking
`transcript_params_key` (all pre-fix manifests) instead of rewriting it against an orphan, and
`arl diagnose-cuts` skips or measures correctly. Re-run each of the six with `arl run` (records the
key and rebuilds boundaries on the correct transcript); **do not** `resnap` them.
