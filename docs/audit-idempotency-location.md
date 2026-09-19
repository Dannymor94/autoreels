# Audit — idempotency and file-location coupling

READ-ONLY audit. No behaviour changed. Goal: establish what "already processed"
actually rests on today, and what breaks when a source stops moving out of
`inputs/` (in-place processing of large files, no copy, no archive).

All line numbers are as of this commit.

---

## Part A — idempotency as it exists today

### 1. Every mechanism that prevents re-doing work

**Transcript cache** — `core/state.py:105` `transcript_cache_path()` →
`<cache_dir>/<audio_hash>[.<params_key>].transcript.json`.
- Key contents: `audio_hash` = **full** sha256 of the *extracted audio file*
  (`state.py:53-55`), **not** the video; plus `params_key`, a fingerprint of
  transcription params (model + initial prompt), appended to the filename.
- What invalidates it: different audio content → different `audio_hash` →
  different filename → miss; different transcribe params → different
  `params_key` → different filename → miss. Nothing else.
- Readers: `_stage_transcribe` (`__main__.py:598`) via `transcribe()`, and
  `transcribe --from-cache` (`__main__.py:1487-1499`). The extracted-audio file
  itself is also cached (`_stage_extract_audio`, `__main__.py:591`), keyed on
  `source_sha`.
- **Location-independent**: keyed on content, never on where the video sits.

**`run_key`** — `__main__.py:211` `_run_key(source_sha256, duration_preset)` =
`sha256(f"{sha}:{preset}")[:16]`.
- Written: into the manifest at assembly (`__main__.py:816`, inside
  `_assemble_manifest`), and copied through on recrop/resnap
  (`__main__.py:2642`).
- **Read to skip work: never.** `grep` for `.run_key` / `run_key ==` across
  `src` and `tests` finds only writes and copies — no consumer. The field's own
  docstring (`models.py:164`) calls it "ключ идемпотентности", but **it is
  inert**: nothing compares it, nothing branches on it. The bug-class note that
  it is "written but not read" is **confirmed**.

**Block score cache** — **does not exist.** `score_block` (`cloud/blocks.py:422`)
computes a heuristic score in memory on every run. The block `id` field
(`blocks.py:42`) is `sha256[:16]` of normalised text, commented "stable cache
key" — that is aspirational; no code reads or writes a score cache keyed on it.

**Move to `inputs-archive/` as the de-facto "done" marker** —
`_archive_video` (`__main__.py:578`) moves `inputs/<x>` → `inputs-archive/<x>`
after a successful run (`__main__.py:1414`, and `1403` for the silent-transcript
case). Who checks it and how:
- The batch (`cmd_run`/`go`, `__main__.py:1563`) enumerates work with
  `_scan_inputs(inputs_dir)` — **`inputs/` only** (`__main__.py:134-149`). A
  successfully-processed video is no longer in `inputs/`, so the next `arl go`
  simply does not enumerate it. **The absence from `inputs/` *is* the "done"
  signal** — nothing ever reads `inputs-archive/` to decide "processed".
- Note: `local/archive.py` implements a proper content-identity pre-skip
  (`is_archived`, name **and** sha256) and a safe move (`archive_input`). **That
  module is dead in production** — it is not imported by `__main__.py` (only by
  `tests/test_archive.py`). The live path is the simpler `_archive_video`, which
  moves by name and has no pre-skip.

### 2. The actual guarantee (one sentence)

Re-processing is prevented **only by the source being physically moved out of
`inputs/`**; the transcript cache makes any re-run cheaper (Whisper is skipped),
but a source still present in `inputs/` gets a **full R0 re-run** from scratch,
and since R0 is non-deterministic the resulting manifest can differ from the
first.

So: re-running the same file is **not** a no-op. For an archived file it never
happens (it's gone from the scan). For a file still in `inputs/` (zero-harvest,
broken, or manually re-added) it is a **full re-run that happens to reuse the
transcript**.

### 3. Cost of a second run of an already-processed source

Only reachable if the source is still in `inputs/` (normal successes are
archived and never re-enumerated). Stage by stage:
- `extract_audio` — cache hit on `source_sha`, skipped.
- `transcribe` — cache hit on `audio_hash`, **Whisper not called**.
- `compress` — recomputed (cheap, local).
- **`select` / R0 — full LLM calls again**, one per chunk. This is the whole
  cost and the whole non-determinism.
- `snap` / `padding` / `trim` / `min_clip` / `subtitles` — recomputed (local).

**Can the manifest differ?** Yes. R0 is non-deterministic, so a second run can
yield different reels, a different reel count, different titles — a materially
different manifest from the same source.

---

## Part B — everything coupled to file location

For each site: what it does if the source is at an arbitrary absolute path,
i.e. **neither in `inputs/` nor in `inputs-archive/`**.

| # | Site | file:line | Keyed on | Behaviour for in-place source |
|---|------|-----------|----------|-------------------------------|
| discovery | `_scan_inputs` (batch) | `__main__.py:134`, `1563` | `inputs/` listing | **Invisible** — never enumerated, `arl go` never processes it |
| status counts | `cmd_status` | `__main__.py:3437-3441` | globs `inputs/*.mp4`, `inputs-archive/*.mp4`, manifests, reels-out dirs | Not counted in either bucket |
| status per-file table | `cmd_status` | `__main__.py:3453-3471` | walks `inputs/` | Row never shown |
| status "manifest without video" | `cmd_status` | `__main__.py:3479-3485` | name in `inputs/` **or** `inputs-archive/` | **False "манифест без видео"** warning (name in neither dir) |
| "ждут обработки" hint / menu | `_next_hint` | `__main__.py:3659-3664` | `inputs/*.mp4` glob | Never counted — neither "waiting" nor "done" |
| render source resolution | `resolve_source` | `local/render.py:267` | `source_sha256` (partial-p1/full), `inputs_dir` only, name as hint | `SourceNotFoundError` → "⊘ нет видео" skip |
| render post-archive | `cmd_render` | `__main__.py:1910` | `inputs_dir / source.name` | No-op / silent (name not in `inputs/`) |
| recrop + auto-crop probe | `_find_source_video` | `__main__.py:2029-2035` | name in `inputs/` **then** `inputs-archive/` | Returns `None` → `CalibrationError` "видео недоступно" when auto-crop is needed |
| resnap | `cmd_resnap` | `__main__.py:2197` | manifest + cached transcript (via `source_sha256`→audio→transcript) | **Works** — never touches the video file |
| diagnose-cuts | `cmd_diagnose_cuts` | `__main__.py:3345`, `3431-3441`, `3479-3480` | globs `inputs/`+`inputs-archive/` for a name/existence display flag; transcript from cache | **Works** — absence only flips a display flag |
| dump-clips | `cmd_dump_clips` | `__main__.py:2321` | manifest only | **Works** — no video needed |
| calibrate --all | `cmd_calibrate_batch` | `__main__.py:3214` | `inputs_dir.glob("*.mp4")` | Not offered for calibration |
| calibrate (single) | `cmd_calibrate` | via `args.video` | explicit path arg | **Works** with any path |
| archive step | `_archive_video` | `__main__.py:578` | moves by name to `archive_dir` | The step we intend to drop for in-place |

### 5. What the manifest records about the source

`core/models.py:150-160`:
- `source` — the original path **string**. Explicitly a hint/label, not an
  access path (invalid on the render machine).
- `source_sha256` — content identity.
- `source_hash_scheme` — `"partial-p1"` (new manifests) or `"full"` (legacy
  default).

**Sufficient to find the file at an arbitrary path? No.** The manifest stores
*identity* (hash) and a *basename hint*, but no resolvable absolute path. Every
finder either globs a fixed directory or matches by basename; none can locate a
file sitting at `/mnt/big/lecture.mp4`. A **new field** (an absolute
`source_path`) would be needed — with the caveat that an absolute path is
machine/drive-specific, which is exactly why `source` is treated as a hint
today. Identity-by-hash stays the correct primary key; the path is a lookup hint
that must be allowed to be stale.

### 6. Calibration lookup

`core/calibration.py:214` `calibration_path()` → `calibrations/<sha256>.json`;
`load_or_auto_calibrate` (`calibration.py:356`) and `load_calibration`
(`calibration.py:257`) both key on `source_sha256`. `calibrate`
(`file_sha256_cached_fast` = partial-p1) and `run` (same) use the same hash.

**An in-place source still finds its calibration** — the lookup is
content-keyed and location-independent. The only failure mode is a hash-scheme
mismatch, which is already handled.

### 7. Missing source: error vs. normal state

- `resolve_source` → `SourceNotFoundError`, caught in `cmd_render`
  (`__main__.py:1911`) → "⊘ нет видео" skip. Non-fatal to the batch, but framed
  as an anomaly.
- recrop auto-crop → `CalibrationError` "видео недоступно (ни inputs/, ни
  архив)" (`__main__.py:2047`). Hard error for that manifest.
- status → "манифест без видео" warning (`__main__.py:3482`).

None of these distinguishes **"gone"** (deleted) from **"not here right now"**
(unplugged external drive). With in-place processing a large source may
legitimately live on a disconnected drive; that is a *normal transient state*,
but every message above currently reads as an error/anomaly.

---

## Part C — what a run-history file would have to carry

### 8. To replace location as the "already processed" signal

The history must record, per processed source:
- **content hash** (partial-p1) **+ scheme** — the identity key; "processed?"
  becomes "is there an entry for this hash?".
- **resolvable absolute path** (and basename) — because the file no longer
  moves to a known directory, this is now the only way any finder can locate it;
  it must be treated as a stale-able hint (re-scan / re-prompt if the path no
  longer resolves).
- **`run_key` ingredients** — `duration_preset` and rubric version — so a
  preset/rubric change can force reprocessing. This finally gives `run_key`
  (Part A.1, currently inert) a reader.

**Hash stability:**
- `file_sha256_partial` (`state.py:63`) = `sha256(head‖mid‖tail‖size)`. It is
  **stable across renames and moves** (content-based, path-ignorant) — good, an
  in-place file that gets renamed is still recognised as processed.
- It is **not** stable across an in-place **edit** (re-encode, trim, remux):
  size and/or sampled bytes change → new hash → treated as new/unprocessed. For
  the "file edited in place" case this is the *correct* outcome (reprocess), but
  it means "processed" cannot survive an edit — acceptable.
- Known ceiling: two different recordings that share head+size and differ only
  outside the sampled windows collide. The mid-file sample (`state.py:59`)
  mitigates the "same camera, same header" case but does not eliminate it. A
  history keyed on the partial hash inherits this ceiling.

### 9. What already benefits from such a history today

- **The batch** answers "is this done?" purely by directory membership (absent
  from `inputs/`). A history removes the need to move the file at all.
- **status** ("ждут обработки", the per-file table, "манифест без видео") all
  infer state from directory listings; a history would let them report
  processed/not-processed directly instead of guessing from layout.
- **`run_key`** exists precisely to answer "have we run this
  source+preset+rubric?" and is inert for lack of a store to compare against — a
  history is its missing consumer.

---

## OBSERVATIONS

**Single riskiest coupling to break:** the pair
`_scan_inputs` (discovery = `inputs/` listing) **+** `_archive_video` (the move).
Together they are the *only* thing preventing re-processing. Drop the move for
in-place sources without first introducing an explicit processed-check and every
`arl go` will re-enumerate every in-place file and re-run R0 on it — full LLM
cost, and a **different** (non-deterministic) manifest each time, silently
overwriting the reviewed one. The processed-check must land **before** the
archive move is removed, not after.

**Small edit or structural:** **structural.** No single finder is hard to
change, but "processed" is an *emergent property of filesystem layout*
distributed across ~8 sites (discovery, three status paths, render resolution,
recrop, calibrate, archive). Replacing it means introducing a real
identity→history record and teaching each site to consult it instead of a
directory listing. The good news: the two hardest things to make portable —
transcript cache and calibration lookup — are **already content-keyed and
location-independent**. The debt is entirely in the location assumptions and in
the inert `run_key`, which the history would activate.
