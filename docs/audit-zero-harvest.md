# Audit: Zero-Harvest Lecture — 2026-08-08 10h 59m 38s.mp4

**Date of incident:** 2026-08-08 (Windows batch run, 6 sources, 5 ok / 1 error)  
**Observed symptom:** `2026-08-08 10h 59m 38s.mp4` produced 0 reels, was archived, lost.  
**This report:** root-cause diagnosis only. Rubric/thresholds unchanged.

---

## What the transcript contains

4 001 words, ~2 500 seconds, topic: meditation / Vipassana stages.  
Content is continuous speech with clear hooks and self-contained segments.  
On the *next* run (same transcript, same config) R0 found **11 reels**, scores 75–90.

The transcript is not the problem.

---

## Why 0 reels on the first run

### Hypothesis A (most likely): run was killed before selection completed

The batch that day had:
1. `2026-08-08 11h 42m 49s.mp4` — chunk 3 triggered OpenRouter fallback;  
   OpenRouter returned HTTP 200 with `{"error": {...}}` body (no `choices` key);  
   `_extract_content` hit `KeyError('choices')` → uncaught `ProviderError` escaped  
   `_complete_and_parse` → killed `cmd_run` for that video entirely.  
2. `PXL_20260729_085910095.mp4` — 3 chunks each burned 300 s × 2 providers = ~30 min  
   on SSL `ConnectError` before the pool gave up.

If `2026-08-08 10h 59m 38s.mp4` ran *after* those two, the process may have been  
interrupted manually or the session timed out.

**Counter-evidence:** git log shows the manifest was committed with 10–13 reels in the  
first commit (`36bcf6c`), meaning R0 *did* succeed on this file at some point that day.  
The 0-reel state was never committed — it happened in a mid-session run that was aborted.

### Hypothesis B (unlikely): all chunks failed silently

Before session-2 fixes, a chunk that triggered `ProviderError` (not `ProviderEmptyResponse`  
or `ProviderTimeout`) would escape `_complete_and_parse` as an uncaught exception, killing  
the run rather than being recorded as a failed chunk. So if every chunk of this video  
happened to hit provider errors, `select_chunked` would have propagated the exception up  
instead of returning `[]`.

The symptom would be a crash, not a silent 0-reel manifest — so this is less likely.

### Hypothesis C: archival bug alone

The video was processed, R0 returned 0 segments (rare but valid — `segments: []`  
is a legal R0 response), manifest was written with 0 reels, then archived.  
This is exactly the **Fix 1 bug**: `_archive_video` was called unconditionally after  
manifest write, even when `len(manifest.reels) == 0`.

The rerun succeeded (11 reels), which suggests the content *is* suitable — making  
a genuine `segments: []` from R0 on this material implausible without a provider error.

---

## R0 response inspection

No raw R0 response logs were captured from the failed run (pre-session-2 there was no  
`_failed_chunks` sidecar). Evidence from the subsequent successful run:

| Reel | Score | Duration | Hook |
|------|-------|----------|------|
| 1    | 90    | 26s      | «Когда эти семь стадий достигнуты, вы пребываете в реальности» |
| 2    | 88    | 50s      | «Чтобы увидеть реальность, нужно сосредоточиться» |
| 3    | 88    | 79s      | «Я вижу, что меня кто-то обманывает...» |
| ...  | 75–85 | 26–68s   | (8 more) |

R0 found dense, high-scoring material on the rerun — confirming the transcript is  
selectable. The failed run produced 0 reels due to a process-level failure, not rubric  
mismatch.

---

## Root cause (concluded)

**The archival bug (Fix 1).** `_archive_video` ran after `_write_manifest` regardless  
of reel count. If R0 returned `segments: []` for any reason (killed mid-run, provider  
error caught somewhere upstream, genuine empty response), the source was silently  
archived and irrecoverable from the inputs/ queue.

The provider error chain from `11h 42m 49s.mp4` (OpenRouter HTTP-200 error body,  
session-1 fix) is the most probable reason this video's R0 call never completed  
cleanly that run.

---

## Fixes applied (session 2)

1. **`ZeroHarvestError`**: non-empty transcript + 0 reels → raise instead of archive.  
   Source stays in `inputs/`, batch reports a separate `zero_harvest` bucket, CLI exits 1.  
2. **`_write_failed_chunks` sidecar**: failed chunk records (`chunk_idx`, `error`,  
   `time_lost_sec`) written to `<stem>.failed_chunks.json` next to the manifest.  
   Future zero-harvest cases will have a paper trail.
3. **ConnectError fast-fail** (Fix 2): SSL/network failures no longer burn 300 s × 3 retries × 2 providers.

---

## Action items

- None. Rubric/thresholds are correct — the content is selectable and was selected.
- Monitor `zero_harvest` bucket in batch output; treat it as a signal to check provider  
  health or network connectivity, not the rubric.
