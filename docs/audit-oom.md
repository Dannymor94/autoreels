# Audit: OOM on full lecture analysis (Mac)

Read-only diagnosis. No behaviour changed. The only code added is an opt-in,
off-by-default memory trace (`src/autoreels/core/memtrace.py` + guarded `mark()`
calls in `cmd_run`); it is inert unless `AUTOREELS_MEMTRACE` is set.

Scope: the `run` (analysis) pipeline — `cmd_run` in `src/autoreels/__main__.py`.
`render` (ffmpeg cutting) is a separate command and out of scope. Analysis is:
extract_audio → transcribe (chunked) → compress → select (R0) → snap/padding/trim
→ subtitles → manifest.

---

## 1. What is held in memory, and for how long

Trace of the large objects across one run (`cmd_run`, `__main__.py:1133`):

| Object | Materialised? | Scales with | Lifetime | Released? |
|---|---|---|---|---|
| Raw video bytes | **Never loaded** | — | — | n/a — ffmpeg reads the file as a subprocess; hashing streams 1 MiB at a time (`state.file_sha256`, `file_sha256_partial`) |
| Extracted audio | Written to disk, never read into RAM by the pipeline | audio duration | disk file in `data/cache/<sha>.mp3` | streamed by ffmpeg (`extract_audio.py:141`) |
| Word-level transcript (`Transcript.words`) | Fully materialised | speech duration | **whole run** — used by snap, padding, trim, min_clip, subtitles | held until `cmd_run` returns; single reference on the `transcript` local |
| Compressed transcript (`str`) | Fully materialised | speech duration | select only | dropped after `_stage_select`; ~43 KB for 47 min |
| Per-chunk transcripts (chunked path) | Materialised one list at a time | per chunk | until `merge_transcripts` stitches them | see §3 |
| R0 responses | Parsed then discarded | per chunk | one chunk at a time | `_complete_and_parse` returns segs; raw JSON not retained (`select.py:483`) |
| Subtitle word lists per reel (`Reel.subtitles`) | Slices of `transcript.words` | reel duration × N reels | whole run | held on the manifest; ≤ full word list in total |
| Manifest under construction | Fully materialised | N reels | whole run | serialized once at the end (`_write_manifest`) |

**The only object whose size scales with source *duration* and is held for the whole
run is `Transcript.words`** (`models.py:83`). Nothing scales with source *file size* —
the video is never in memory.

Reference survival: no module-level cache, no closure, no accumulating list keeps a
per-run object alive past the run. `transcript` is a plain local; reels are plain
locals; the provider pool holds only scalar budget counters (`providers.py:458–465`),
confirming the earlier finding that the wait loop accumulates nothing.

## 2. Audio and ffmpeg

- **Extracted audio is written to disk and never read back whole by the pipeline.**
  `extract_audio` streams ffmpeg output straight to `data/cache/<sha>.mp3`
  (`extract_audio.py:141`). Consumers pass the *path* to Groq / faster-whisper.
- **Two exceptions read a whole file into RAM to compute a hash** (chunked path only):
  - `chunk_transcribe.py:418` — `audio_path.read_bytes()[:4096]`: reads the **entire
    audio file** into memory only to keep the first 4 KB. Transient, bounded by audio
    size (~20–55 MB), then freed. Wasteful, not OOM-scale. (A `read` of 4096 bytes
    would be the fix — noted, not applied.)
  - `chunk_transcribe.py:262` — `hashlib.sha256(chunk_path.read_bytes())`: reads each
    ~24 MB chunk fully, once per chunk, transient.
- **Subprocess output capture is unbounded on three paths**, all in the chunked
  transcription branch:
  - `detect_silences` (`chunk_transcribe.py:197`) — `capture_output=True` with **no
    `-loglevel error`** while decoding the full audio through `silencedetect`; stderr
    (banner + one line per silence event) is read into one string. For a talking-head
    lecture this is hundreds of KB to low MB, not GB.
  - `split_audio_chunk` (`:244`) and `_probe_duration` (`:291`) — `capture_output=True`;
    output is tiny.
  - `extract_audio._drain_stderr` (`extract_audio.py:82`) accumulates ffmpeg stderr in
    `stderr_chunks`, but the command uses `-loglevel error`, so it stays near-empty.
  A 14 GB source does **not** produce proportionally verbose output here — these read
  the *audio's* ffmpeg stderr, not the video.
- **Handles/temp files:** `subprocess.run` closes its pipes on both paths. The failed
  extract deletes its partial output (`extract_audio.py:171`). Per-chunk audio files in
  `data/cache/chunks/<sha>/` are intentionally kept for idempotency (not a leak).

## 3. Chunked transcription

- Per-chunk audio files: kept on disk after stitching (idempotency, by design), not in
  RAM.
- Per-chunk transcripts: `transcribe_chunks` returns `results: list[Transcript | None]`
  (`chunk_transcribe.py:331`) — all chunk transcripts held simultaneously, then
  `merge_transcripts` builds one `all_words` list from them (`:112`). At the seam both
  the per-chunk lists and the merged list exist, so peak ≈ 2× the word list. For a 47
  min lecture the word list is ~3.2 MB (measured, §5), so the seam peak is ~6 MB —
  negligible.

## 4. Caching (in-process)

| Cache | Keys accumulated in one run | Bounded? |
|---|---|---|
| `Transcript` cache (disk) `state.transcript_cache_path` | 1 file per run | disk, bounded |
| Chunk transcript cache (disk) `_chunk_cache_path` | 1 per chunk | disk, bounded |
| `data/cache/sha256/` (disk) | 1 per (path,size,mtime); **never evicted** — 3010 files present | disk only, not memory |
| `_load_token_scale` (`providers.py`) | read once per run | scalar |

**No in-process (`lru_cache`, module-level dict, growing list) cache accumulates per
iteration.** The disk caches grow across runs but are on disk, not RAM.

## 5. Measurement

Instrumentation added (off by default): `memtrace.mark(label)` logs peak RSS + delta
(and, with `AUTOREELS_MEMTRACE=full`, top-5 tracemalloc sites) at each stage boundary
in `cmd_run`. Enable with `AUTOREELS_MEMTRACE=1 arl run <video>`.

A live end-to-end `run` needs `GROQ_API_KEY` (R0 preflight) and re-decodes the source
with ffmpeg. To measure the **duration-scaling** part without network, an offline
harness exercised the stages that hold the big objects, on the **largest cached
transcript available** — a full **46.7-minute** lecture (5889 words), which is the
worst realistic case, not the shortest:

| Stage | Peak RSS | Δ from previous |
|---|---|---|
| baseline (imports) | 27.2 MB | — |
| after transcript load | 44.2 MB | +17.0 MB |
| after compress | 44.2 MB | +0.0 MB |
| after build reels | 44.2 MB | +0.0 MB |
| after subtitles | 44.2 MB | +0.0 MB |
| after manifest assembly + dump | 44.2 MB | +0.0 MB |
| **process peak** | **46.8 MB** | |

Top-5 allocations at the end (tracemalloc):

1. `pydantic/main.py:782` — 3154 KiB / 37058 objects — the `Word` models (the word list)
2. `json/decoder.py:361` — 320 KiB — transient JSON decode of the cached transcript
3. `pydantic/main.py:559` — 313 KiB — model init
4. `compress.py:87` — 84.7 KiB — the compressed projection string
5. `pydantic/main.py:263` — 26 KiB

**Extrapolation.** The whole word list for a 47-min lecture is ~3.2 MB and everything
downstream is flat. RSS grows ~0.5 KB per word; a 47-min lecture ≈ 6000 words ≈ 3 MB.
A 14.4 GB source is large in *bytes*, not necessarily in *speech* — memory tracks
speech duration, not file size. Even a 4-hour recording (~30k words) would add only
~15 MB. **Nothing in the traced pipeline approaches an OOM at any plausible duration.**

Not exercised live (honest gap): the network R0 loop and live chunked transcription.
R0 responses are parsed-and-dropped per chunk (§1) and the provider holds only scalars
(§4), so no per-iteration growth is expected there, but this run did not prove it under
real network conditions — transcription was a cache hit and R0 was not called.

---

## Observations

**The measurement did NOT reproduce the OOM. It is a negative result and is reported as
such: a full 46.7-minute lecture's analysis tail peaks at 46.8 MB and stays flat across
every stage.** No object in the `run` pipeline scales with source *file size*, and the
one object that scales with *duration* (`Transcript.words`) is single-digit MB.

Given that, the OOM is almost certainly **not** the pipeline's steady-state Python
objects. Ranked by likelihood, with evidence:

1. **The ffmpeg subprocess RSS, not Python (most likely).** `run` decodes the full
   source twice with ffmpeg — once in `extract_audio` and, on long (>15 min) inputs,
   again in `detect_silences` (`chunk_transcribe.py:407`), which decodes the *audio*
   but is itself preceded by a full-*video* decode in extract. A 14.4 GB high-bitrate
   phone source can drive ffmpeg's own resident memory (decode buffers, reordering)
   into the hundreds of MB–GB, and on the Mac that counts toward the same system
   memory pressure that triggered the kill. Evidence: OOM correlates with *large
   sources* and *long runs* (both = more/longer ffmpeg decode), and Python itself is
   provably flat. This is external to autoreels' own allocations; the code holds nothing
   large.

2. **Transient whole-file `read_bytes()` on the audio (chunked path).**
   `chunk_transcribe.py:418` and `:262` load the entire audio / each chunk into RAM to
   hash. Bounded by audio size (tens of MB), transient, and only on the >15 min path —
   consistent with "long runs, not immediately," but too small to OOM alone. Worth
   fixing regardless (stream the hash / read only 4 KB).

3. **Unbounded `capture_output` on `detect_silences`** (`chunk_transcribe.py:197`, no
   `-loglevel error`). Grows with the number of silence events over the whole recording
   — larger on long inputs, but hundreds of KB–low MB, not GB.

4. **Ruled out:** the provider wait loop (confirmed here — scalars only), in-process
   caches (none accumulate per iteration), and the steady-state transcript/reel/manifest
   objects (measured flat at <50 MB for 47 min).

The single most likely source of unbounded growth *within one process's memory picture*
is **#1 — ffmpeg's own memory while decoding a very large source**, not any Python
object. To confirm, run `AUTOREELS_MEMTRACE=1 arl run <the 14.4 GB source>` and watch
whether the jump appears at `after extract_audio` (Python RSS) or whether Python stays
flat while system memory is consumed by the ffmpeg child (the latter would confirm #1).
The instrumentation is in place for exactly that test; this audit could not run it
because that source is not present on this machine.
