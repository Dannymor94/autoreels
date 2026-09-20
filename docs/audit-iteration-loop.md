# Audit — the iteration loop and where it can be made fast

READ-ONLY. No behaviour changed. Question: when you tweak a boundary, filter or
segmentation rule, how much of the pipeline must you actually re-run to see the
effect? Facts below are from the code (file:line) and from timings measured on
this machine against the two cached sources used in the segmentation audit:
- **PXL interview** — 4677 words, `219c91bf….84b62c5276da.transcript.json`.
- **lecture B** — 5889 words, `2046ef16….transcript.json`.

The full run pipeline is `_cmd_run_impl` (`src/autoreels/__main__.py:1419`); its
stage order is lines 1521–1596.

---

## Part A — what each stage costs on a SECOND run

Two "second run" cases exist and they behave very differently:

- **Plain `arl run <same source>` (no `--force`)** — `_guard_already_processed`
  (`__main__.py:241`) computes the source hash (cached, `state.file_sha256_cached_fast`,
  `state.py:86` — no re-hash of the 15.5 GB file) and then raises
  `AlreadyProcessedError` (`__main__.py:273`) **before any analysis**. The whole
  run is a near-instant no-op. Useful for idempotency, useless for testing a change.
- **`arl run --force`** — the guard returns early (`__main__.py:267`) and every
  stage below executes. This is the only way the full path re-evaluates a change,
  and it is where the cost lives.

Stage costs on a `--force` second run (source + transcript already cached):

| stage | code | re-executes? | cached? | wall (measured) | network |
|---|---|---|---|---|---|
| source hash | `state.py:86` | reuses | yes (path+size+mtime) | ~0 | no |
| **audio extract** | `_stage_extract_audio` `__main__.py:663` → `extract_audio` `cloud/extract_audio.py:141` | **RE-RUNS ffmpeg** | **NO guard** (see below) | **42.8 s** (15.5 GB source) | no |
| transcription | `_stage_transcribe` `__main__.py:670` → `transcribe` `cloud/transcribe.py:315` | reuses | **yes** (`cache_path.exists()` `transcribe.py:353`) | ~0.1–0.5 s (hashes the 22.9 MB mp3, `state.audio_hash` `state.py:53`, uncached) + JSON load | no |
| compress | `_stage_compress` `__main__.py:686` | recomputes | no | **~2 ms** | no |
| block segmentation | `candidate_blocks` `cloud/blocks.py:411` | recomputes | no | **~2–3 ms** | no |
| junk filters | `filter_blocks` `cloud/blocks.py:340` | recomputes | no | **~7 ms** | no |
| heuristic scoring | `score_block` `cloud/blocks.py:462` | recomputes | no | **~2–3 ms** | no |
| **R0 selection** | `_stage_select` `__main__.py:693` → `select` `cloud/select.py` | **RE-RUNS** | **NO** | **minutes** (OTPM-bound, see CLAUDE.md) | **YES** |
| snap | `_stage_snap` `__main__.py:729` → `snap_segments` | recomputes | no | ~ms (part of the 40 ms below) | no |
| padding / trim | `_stage_padding` 745 / `_stage_trim` 760 | recomputes | no | ~ms | no |
| dangling / interview / min-clip / meaningful / density | `__main__.py:1551–1595` | recomputes | no | ~ms | no |
| subtitle binding | `_stage_subtitles` `__main__.py:921` | recomputes | no | ~ms | no |
| manifest assembly | `_assemble_manifest` | recomputes | no | ~ms | no |
| render (if `--auto-render`) | `cmd_render` `__main__.py:1974` | re-encodes | no | minutes (ffmpeg per clip) | no |

**Note on audio extract:** `extract_audio` (`cloud/extract_audio.py:162–176`)
builds the ffmpeg command and runs it unconditionally — there is **no
`if out.exists()` guard** — even though its own docstring claims idempotency by
content hash. Measured: with the mp3 already in `data/cache`, a re-extract of the
15.5 GB PXL source took **42.8 s** and produced a byte-identical file.

### Plainly: what is already free, what is not

- **Free to re-run (zero network, milliseconds):** compress, block segmentation,
  junk filters, heuristic scoring, snap, padding, trim, the post-select gates,
  subtitle binding, manifest assembly. Everything from the transcript onward.
- **Not free:** **R0 selection** is the only network stage after the transcript,
  it is never cached (only skipped wholesale by `run_key`), and it is OTPM-bound
  (minutes). **Audio extract** is not network but re-runs ffmpeg over the whole
  source (~43 s) because of the missing cache guard. Transcription is cached, so
  it is effectively free on a second run.

**The interesting number:** once a transcript is cached, **100 % of the
selection→boundary→filter→manifest logic re-executes with zero API calls in
~15 ms.** The only thing forcing a network round-trip is re-running R0 itself —
which a boundary/filter/segmentation change does **not** require, because R0's
output (`r0_start`/`r0_end`) is stored in the manifest.

---

## Part B — what can already be re-run without the LLM

### 3. `resnap` — what it recomputes, and the gap

`cmd_resnap` (`__main__.py:2428`) → `_resnap_reels` (`__main__.py:2409`) resets
each reel to its stored `r0_start`/`r0_end` and re-runs **only three** stages:
`snap_segments` → `apply_padding` → `trim_too_long` (`__main__.py:2414–2425`).
Transcript comes from cache; no network.

What resnap **does not** recompute (the gap — these are in the full run but not in
resnap):

- **block segmentation** (`candidate_blocks`) and **junk filters**
  (`filter_blocks`) — resnap starts from stored R0 bounds, so a segmentation or
  filter change is invisible to it.
- **interview host-turn snap** (`_stage_interview_snap`, `__main__.py:1551`).
- **dangling-start repair** (`filter_dangling_start`, `__main__.py:1565`).
- **min-clip / meaningful-sec / speech-density gates**
  (`__main__.py:1590–1595`).
- **subtitle binding** (`_stage_subtitles`).

So resnap answers "did my **snap/padding/trim** change move the boundaries?" and
nothing else. Measured compute: **40 ms** for the 23-reel PXL manifest.

**Caveat that bites today:** resnap refuses any manifest without a stored
`transcript_params_key` (`__main__.py:2483–2488`). The committed
`manifests/PXL_20260729….json` has `transcript_params_key=""` (predates that
field) — so **resnap refuses the reference source outright**; you would need one
full `arl run` first to re-stamp it. `arl blocks` does not have this problem (it
falls back to the newest transcript by audio-hash, `__main__.py:3002–3011`).

### 4. `arl blocks` — segmentation + filters + scoring, no network

`cmd_blocks` (`__main__.py:2933`) loads a cached transcript
(`.transcript.json` directly, or resolved from a manifest via audio-hash,
`__main__.py:2981–3011`), compresses it, then runs `candidate_blocks` →
`filter_blocks` → `score_block`. `cloud/blocks.py` imports nothing network —
confirmed pure. It does not touch audio or R0.

Measured wall time, `arl blocks <transcript.json>` end-to-end (warm):

| source | end-to-end CLI | of which compute (compress+segment+filter+score) |
|---|---|---|
| PXL (4677w) | **~0.25 s** | **~15 ms** |
| lecture B (5889w) | **~0.25 s** | **~15 ms** |

The CLI wall time is dominated by Python import startup (~0.23 s); the actual
work is ~15 ms. No sidecar is written when the target is a `.transcript.json`
(verified: clean `git status` after the run).

### 5. Fastest honest way to answer each question today

- **"did this segmentation change alter the blocks?"** → **fast path exists.**
  `arl blocks <cached .transcript.json>` — ~0.25 s, no network. Diff the printed
  block list before/after. (This is exactly how the segmentation follow-up in
  `audit-video-review-defects.md` was measured.)
- **"did this snap change alter the clip boundaries?"** → **no clean fast path.**
  `resnap` recomputes boundaries from stored R0 bounds in 40 ms, but it (a)
  **writes the manifest and git-pushes by default** (`push=True`,
  `pull_first=True`, `__main__.py:2434–2435`) and (b) **refuses the reference PXL
  manifest** for the missing-`params_key` reason above. So today the honest
  offline answer requires a scratch script calling `_resnap_reels`, or a full
  `arl run --force`. This is the real gap. (See Part C / ranked.)
- **"did this filter change drop something it should not?"** → **fast path
  exists.** `arl blocks` prints per-block filter verdicts (kept vs dropped with
  reason); diff the kept/dropped set before/after. ~0.25 s, no network.

---

## Part C — what is missing

### 6. Can a stored manifest replay the post-selection stages?

Partly. The manifest (`core/models.py:144`) stores per reel `r0_start`/`r0_end`
(`models.py:121–122`) and `transcript_params_key` (`models.py:176`), which is
enough to replay **snap → padding → trim** — that is exactly what resnap does.

But the manifest carries **no block set** — there is no `Block` field on
`Manifest` or `Reel`. So the candidate blocks that produced the selection are
**not recoverable from the manifest**; they must be recomputed from the
transcript via `candidate_blocks`. Since `candidate_blocks` reads live config
(`block_target_sec`, `min_meaningful_sec`, `max_duration`,
`min_pause_for_phrase_end`), a recomputed block set **can differ** from the one
that produced the manifest if the config or the segmentation code changed in
between. For iterating that is the point; but it means the manifest cannot be
used to verify "what were the blocks at the time this manifest was built" — that
information is gone.

### 7. What a dry-run mode would need

There is **no dry-run for the pipeline** — the only `dry_run` in the code is on
`install-aliases` (`__main__.py:4405`). To print, without writing:

- **blocks + filter verdicts + scores** — already exists as `arl blocks`
  (prints all three). Nothing missing here.
- **resulting clip boundaries for a chosen selection** — **missing.** `arl blocks`
  stops at blocks (no snap/padding). `resnap` computes the boundaries but only by
  **writing the manifest and pushing** — it already computes `n_changed`
  (`__main__.py:2510`) but has no flag to compute-and-print without persisting.

So the whole "dry-run" gap is narrow: a `--dry-run` on `resnap` that runs
`_resnap_reels`, prints the new boundaries / `n_changed`, and skips the
write+push branch (`__main__.py:2512–2517`). Everything it needs is already
computed.

### 8. Could test fixtures stand in for a cached source?

Not today, and this is a portability gap. `tests/test_blocks.py` builds
compressed-transcript lines **synthetically** in-memory (`_line`/`_compressed`) —
good for unit logic, but not a realistic 45-minute corpus. The realistic cached
transcripts live in `data/cache/*.transcript.json`, which is **git-ignored**
(confirmed via `git check-ignore`). The only committed JSON fixtures are LLM
response envelopes and per-clip texts (`tests/fixtures/`), **no full
transcript**. Consequence: a segmentation/filter change can be evaluated in
seconds on this machine (the cached transcripts are here), but there is **no
committed fixture** that would let CI — or another machine — run the same check.
Committing one PXL + one lecture transcript as a fixture would close that.

---

## RANKED — three cheapest changes that most shorten the loop

Ranked by loop-shortening value for the stated purpose (checking whether a
boundary / filter / segmentation change did anything). No fixes applied here.

1. **`arl resnap --dry-run` (+ read-only best-effort transcript resolve).**
   *Saves: minutes → ~0.3 s per snap/boundary iteration; also removes a git
   pull+push round-trip.* Today, checking a snap/padding change offline has no
   clean path: resnap writes+pushes and refuses the reference PXL manifest. A
   `--dry-run` that runs `_resnap_reels`, prints new boundaries and `n_changed`,
   and skips the write+push (and, for dry-run only, resolves the transcript
   best-effort like `diagnose-cuts` instead of hard-refusing on empty
   `params_key`) turns the boundary loop into a sub-second offline command.
   **Small edit** (one flag, guard two branches).

2. **Cache guard in `extract_audio`.** *Saves: ~43 s per `arl run --force`.*
   One line — `if out.exists() and out.stat().st_size > 0: return out` before
   building the ffmpeg command (`cloud/extract_audio.py:166`). Does not touch the
   fast blocks/resnap loop, but it removes the single biggest avoidable wait on
   the full-run fallback (the path you take when you *do* need to re-run R0).
   **Small edit** (one line); the content-hash filename already guarantees
   correctness.

3. **Commit one real transcript fixture per source kind (PXL + lecture).**
   *Saves: makes the already-fast `arl blocks` loop portable and
   regression-safe; ~0 per iteration but enables CI and off-machine checks.*
   Today the fast segmentation/filter loop depends on git-ignored
   `data/cache` transcripts that exist only on this machine. Committing two
   trimmed real transcripts as fixtures lets a segmentation/filter change be
   asserted in CI in seconds and reproduced anywhere. **Structural-ish** (add
   fixtures + a small test that runs `candidate_blocks`/`filter_blocks` over
   them), but no production code changes.
