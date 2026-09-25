# Audit — recurring bug classes (READ-ONLY)

Date: 2026-09-17. No code changed. Each defect below was fixed once at the site it was
noticed; this pass finds the siblings the same class still lives in. Line numbers are against
the tree at commit `12b8e19`.

Legend: **HARMFUL** = misbehaves today under a normal invocation. **LATENT** = correct now,
fires when a specific (plausible) condition is met. **RESOLVED** = the named instance is
genuinely fixed (recorded so the next audit doesn't re-flag it).

---

## Class 1 — Paths resolved against the current working directory

`_project_root()` (`__main__.py:1130`) exists and is the package-anchored root. `arl` does **not**
`cd` into the project (`aliases.sh:37` runs `python -m autoreels "$@"` from the caller's cwd), so
any relative literal resolves against wherever the user stands.

| # | Location | State | Notes |
|---|----------|-------|-------|
| 1 | `cloud/providers.py:98` — `_TOKEN_SCALE_FILE = Path("data/token_scale.json")` | **HARMFUL (silent)** | Module-level constant, read by `_load_token_scale` (110) and written by `_save_token_scale` (120). From any cwd ≠ root the read finds nothing → returns `None` → falls back to the conservative default `1.45`; the write lands in `./data/` outside the project. The learned OTPM token-underestimation factor **never accumulates**, so the documented R0 bottleneck (OTPM=1000) runs permanently on the default. Graceful (no crash), which is why it went unseen. Contrast: the *same* `data/` dir is resolved correctly root-relative at `__main__.py:2506` (`root / "data" / "blocks_dataset"`). |
| 2 | `__main__.py:4800, 4802, 4804` (`run`) and `4835, 4837` (`transcribe`) — `Path("inputs")` | **HARMFUL** | The explicit single-target dispatch downloads/ingests the source into `./inputs` (cwd), but `render` resolves `inputs/` from `_project_root()`. Run `arl run <url>` / `arl run ~/x.mp4` / `arl transcribe <url>` from any cwd ≠ root and the source lands outside the project → render later reports "no source". The batch paths (`cmd_run_batch`, `_auto_discover_manifests`) already thread `root`; only the explicit dispatch regressed. This is the exact class already fixed for the inputs scanner, dump-clips and `arl blocks`. |
| — | `core/config.py:603/637/673/682/691` — `"config/r0.yaml → …"` etc. | not a finding | Docstring text describing the mapping, no `open()`. Listed so it isn't mistaken for an occurrence. |

Everything else that touches `config/`, `prompts/`, `manifests/`, `transcripts/`, `calibrations/`
is threaded through `root` (e.g. prompt load `__main__.py:626-627` = `root / r0_cfg.prompts.system`).

---

## Class 2 — Shared lists/constants used for two different purposes

The named instance is **RESOLVED**: `bad_open_words` (first-word check, `blocks.py:439`) and
`dangling_pronouns` (density check, `blocks.py:461`) are now separate lists (`config.py:141` vs
`config.py:150`) with an explicit comment forbidding the cross-use. Remaining couplings:

| # | Constant / list | Two consumers | Want same contents? | State |
|---|-----------------|---------------|---------------------|-------|
| 1 | `hanging_words` (`config.py:208`) | Drives **≥5 distinct decisions**: snap end-detection (`snap.py:54,99,148,156`), start-repair (`snap.py:313`), rescue extension (`try_rescue_clip`), padding tail-trim (`apply_padding`, `snap.py:493`), subtitle trim (`trim_hanging_subtitles`, `snap.py:541`), plus diagnose (`diagnose.py:100`). | Mostly yes ("a word a clip shouldn't end on") — but adding a word to fix the *subtitle* trim silently shifts every snap boundary and rescue extension. | **LATENT** — same shape as the `bad_open_words` bug, wider blast radius, undocumented coupling. Highest-risk of this class. |
| 2 | `min_meaningful_sec = 18` (`config.py`, R0Config) vs `BlockScoringConfig.min_sec = 18.0` (`config.py:117` block) | Post-filter "completed thought" floor vs stage-3 score-zero floor. `min_sec` carries the comment *"matches min_meaningful_sec"*. | Yes, they should agree — but they're coupled by a **hand-copied literal**, not a reference. Change one, the other stays 18. | **LATENT** |
| 3 | Density thresholds | `low_density` filter uses `speech_density_min = 0.4` (`blocks.py:273`); score `density_penalty` **hardcodes** `< 0.5` (`blocks.py:471`). | Two "near-silence" decisions, two different numbers already. | **LATENT / low** — divergence is invisible in output; not necessarily meant to agree, but nothing links them. |

---

## Class 3 — Discovery globs that pick up files they should not

`_glob_manifests` (`__main__.py:2208`) with `_SIDECAR_SUFFIXES = (".discarded.json",)`
(`__main__.py:2205`) is the discovery choke point, used by render (`__main__.py:1699`) and
dump-clips auto-discovery (`__main__.py:2216`). It excludes `.discarded.json` and, by suffix
match, `.blocks.discarded.json`. It does **not** exclude these, all written into `manifests/`:

| # | Sidecar (write site) | Shape | What discovery does with it | State |
|---|----------------------|-------|-----------------------------|-------|
| 1 | `.review.json` (`__main__.py:2500`) | **Manifest-shaped** (`selection_source="human"`) | Passes `Manifest.model_validate_json` → **rendered as a second manifest for the same source** → duplicate reels, silent. Violates idempotency invariant #4 (the "Meeting→Tasks duplication" trap named in CLAUDE.md). | **HARMFUL** |
| 2 | `.failed_chunks.json` (`__main__.py:640` → written at `1349`) | list | Fails validation → caught by render's per-file `try` (`__main__.py:1734`) → reported as a **failed** render (false failure, non-zero exit, alarming error line). | **HARMFUL (noise / false signal)** |
| 3 | `.blocks.topk_cut.json` (`__main__.py:2722`) | list | Same false-failure path as #2. | **HARMFUL (noise)** |

Reviewed and **clean** (dedicated dir + single shape, or own suffix): transcript caches
`{hash}*.transcript.json` (`1447/2368/2584`), calibrations `*.json` (`2837`, `calibration.py:386`),
inputs/archive `*.mp4`, music `*`, dataset `.jsonl` (append, never globbed as manifest).

Nit: docstring at `__main__.py:2530` says `.blocks.dropped.json` but the code writes
`.blocks.discarded.json` (`2660`) — cosmetic naming drift, no behaviour impact.

---

## Class 4 — Checks that run before a transformation that invalidates them

The named instance is **RESOLVED**: the duration floor is re-checked after artefact-tail scrub as
`too_short_after_scrub` (`blocks.py:325,354`, commit `12b8e19`). Remaining:

| # | Check (site) | Invalidating transform | Re-checked after? | State |
|---|--------------|------------------------|-------------------|-------|
| 1 | `filter_by_duration(min_meaningful_sec=18)` in `_stage_select` (pre-snap, `__main__.py:1285`) | `_stage_snap` (`1289`) can **shorten** a clip (snap end to an earlier word/pause) | Only `min_clip_duration = 8.0` is re-applied downstream (`min_clip_filter` `1336`; `snap.py:432`). **The 18 s "completed thought" floor is never re-applied.** | **HARMFUL (silent)** — a 20 s clip snapped to ~10 s (> 8, < 18) survives: exactly the "empty short clip" the floor exists to kill. Same shape as the artefact-scrub bug. |
| 2 | `flag_durations` sets `too_long`/`too_short` on **raw R0 boundaries** in `_stage_select` (`select.py:426, 499`) | `_stage_snap` (`1289`) + `_stage_padding` (`1334`) move boundaries | `too_short` re-added post-snap but against a **different** threshold (`min_clip_duration`, `snap.py:432`); `too_long` **never** recomputed. `trim_too_long` then acts only on the stale flag with no re-measure (`trim.py:53`). | **LATENT / moderate** — harm bounded because snap caps end at `max_duration`, but the manifest's check-flags describe R0 boundaries, not the rendered clip; misleads review and breaks invariant #6 ("flags are measured, deterministic"). |

---

## Class 5 — Cache keys that omit inputs affecting the result

| # | Cache / key (site) | Key contains | Inputs affecting result but absent | State |
|---|--------------------|--------------|-------------------------------------|-------|
| 1 | `_run_key(source_sha256, duration_preset)` (`__main__.py:208`) | source sha + preset | **Rubric/prompt version, model, r0.yaml thresholds** — its own docstring defers the rubric version to M1. Invariant #4 mandates source+preset+**rubric version**. | **LATENT** — currently `run_key` is *written* (`778, 2493`) but never *read* to gate re-runs, so it's inert. When M1 wires "skip if run_key matches", changing the rubric/prompt/thresholds won't invalidate → stale segments. Exact transcript-cache bug, one level up. |
| 2 | Transcript resolution fallback (`__main__.py:2368, 2584`; also `1447`) | tries exact `{hash}.{params_key}.transcript.json` first (the documented fix) | On empty `manifest.transcript_params_key` (legacy manifests) falls back to `glob({hash}*.transcript.json)` newest-by-mtime → can resolve a **different params variant** | **LATENT** — the diagnose/resnap wrong-transcript bug survives for manifests written before `transcript_params_key` existed. |
| 3 | Audio-extract cache (`extract_audio.py:165`, `{sha}.{format}`) | source sha + output format | Other `audio_cfg` params (sample rate, channels) | **LATENT / low** — rarely changed. |
| — | `transcript_cache_path` (`state.py:105`) | now includes `params_key` (model + initial_prompt) | — | **RESOLVED** (the original bug). |

---

## Class 6 — Platform-specific assumptions on the main path

Effectively **clean** after the `import resource` fix. Checked and fine:

- `core/memtrace.py:27` — `import resource` is lazy (inside the function) and `sys.platform`-guarded (`29`). **RESOLVED.**
- `__main__.py:1024` — `os.name == "nt"` is a correct branch, not an assumption.
- Every `D:\…` literal (`__main__.py:1072-1074, 4455`; `extract_audio.py:34-36`; `render.py:631`) is in **help/error text**, not path construction.
- Temp files use `tempfile.TemporaryDirectory` (`render.py:654`) — cross-platform. No `/tmp` literal, no hand-built separators, no drive-letter path building on the main path.
- `scripts/probe_groq.py` is a dev-only probe, off the main path.

No live Class-6 finding. (Note: `providers.py:98`'s relative path is a Class-1 cwd issue, not a separator/platform one.)

---

## RANKED — most dangerous first

1. **Class 3 · `.review.json` ingested by `_glob_manifests`** (`__main__.py:2205-2210` + `2500`).
   Silently renders the same source twice → duplicate client-facing reels, breaking idempotency
   invariant #4 — the very duplication trap CLAUDE.md calls out. **Structural fix:** decide
   review-manifest semantics (does it *replace* `<stem>.json` or sit beside it?), then either
   exclude `.review.json` from discovery or dedupe discovery by source stem, and centralize the
   sidecar-suffix list. Not a pure one-liner: naïvely excluding it means the human selection never
   renders.

2. **Class 4 · `min_meaningful_sec` floor bypassed by snap shortening** (`__main__.py:1285` vs
   `1289/1336`). Silent — sub-"completed-thought" clips reach the output, defeating the floor's
   whole purpose, and it's invisible without eyeballing lengths. **~One-line fix:** re-apply the
   18 s floor after snap/padding (move `filter_by_duration` downstream, or re-run it in
   `min_clip_filter`).

3. **Class 1 · `Path("inputs")` in the run/transcribe dispatch** (`__main__.py:4800-4837`).
   `arl run <url>` from any non-root cwd puts the source where render can't find it. Visible
   failure, so lower than the silent ones. **One-line fix** each: resolve against
   `_project_root()`.

4. **Class 1 · `_TOKEN_SCALE_FILE` cwd-relative** (`providers.py:98`). Silent and continuous:
   the OTPM calibration on the documented bottleneck never persists, but degrades gracefully.
   **One-line fix:** anchor to `_project_root() / "data"`.

5. **Class 5 · `_run_key` omits rubric version** (`__main__.py:208`). Inert today; lands the day
   M1 wires run_key-based skipping. **~One-line fix** once a rubric/config version source exists —
   fold it into the hash.

6. **Class 3 · `.failed_chunks.json` / `.blocks.topk_cut.json` → false render failures**
   (`__main__.py:640/2722` vs `2205`). Noise and a false non-zero exit, no data damage.
   **One-line fix:** extend/centralize `_SIDECAR_SUFFIXES`.

7. **Class 4 · stale `too_long`/`too_short` flags** (`select.py:426/499`). Flags describe R0
   boundaries, not the rendered clip; misleads review. **One-line fix:** re-run `flag_durations`
   at the end of the pipeline.

8. **Class 2 · `hanging_words` drives ≥5 decisions** (`config.py:208`). Wide blast radius but
   defensible (one genuine notion). **No fix needed now — document the coupling** so an edit to
   fix subtitle trim isn't made blind to its effect on snap boundaries.

9. **Class 5 · legacy-manifest transcript mtime fallback** (`__main__.py:2368/2584`). Only bites
   pre-`transcript_params_key` manifests. **Structural:** backfill `params_key` or refuse the
   ambiguous fallback.

---

## Class 7 — Rebuilding a model by constructor drops new fields

**Pattern:** `Segment(start=s.start, end=s.end)` anywhere in the pipeline discards every field
added after the original schema (`shot`, `close_intervals`, and any future M1.7+ additions).
The constructor creates a fresh model with all defaults.

**Where it bit us:** `_snap_windows_to_frames` (`render.py`) iterated over segments and rebuilt
each as `Segment(start=snapped, end=snapped)`, silently dropping `shot` and `close_intervals`.
Rendered as wide even after `--apply` had written `shot="close"`.

**Fix:** `s.model_copy(update={"start": …, "end": …})` (Pydantic v2). Always copy-with-update
when modifying fields of a model — never reconstruct from another model's fields.

**Grep for similar sites:** `Segment(start=`, `Segment(s.start`, any place that constructs a
model from another model's fields.

**All sites fixed (af39631+):**
- `_snap_windows_to_frames` — `Segment(start=snapped, end=snapped)` → `s.model_copy(update={…})` (commit 12175ed)
- `assign_close_shots` — two `Segment(start=seg.start, end=seg.end, shot=…)` → `seg.model_copy(update={…})`
- Tail-trim (render.py ×2) — `Segment(start=segs[-1].start, end=_new_end)` → `segs[-1].model_copy(update={"end": …})`

**Test guard:** `test_snap_preserves_all_segment_fields` and `test_assign_close_shots_preserves_extra_fields` in `tests/test_two_shot.py` — fail immediately if this class recurs.
