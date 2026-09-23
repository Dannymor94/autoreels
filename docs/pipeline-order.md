# Pipeline stage order

Quick reference for what runs when and where. Canonical authority: `__main__.py` and `local/render.py`.

---

## Analysis path (`arl run`)

| # | Stage | Where | Key file |
|---|---|---|---|
| 1 | Extract audio | local | `local/extract_audio.py` |
| 2 | Transcribe (Whisper) | cloud (Groq) | `cloud/chunk_transcribe.py` |
| 3 | Compress transcript | cloud | `cloud/compress.py` |
| 4 | Candidate blocks | cloud | `cloud/blocks.py` → `candidate_blocks` |
| 5 | Filter blocks (artefacts, promo, density…) | cloud | `cloud/blocks.py` → `filter_blocks` |
| 6 | Heuristic scoring + top-K | cloud | `cloud/blocks.py` → `score_block` |
| 7 | LLM scoring (R0) | cloud (Groq/OpenRouter) | `cloud/select.py` |
| 8 | Dedup overlaps | cloud | `cloud/select.py` |
| 9 | Snap boundaries | cloud | `cloud/snap.py` |
| 10 | Dangling-start repair | cloud | `cloud/snap.py` |
| 11 | Top-N, write manifest | cloud | `__main__.py` → `awaiting_review` |

## Manual review path (`arl blocks --apply`)

| # | Stage | Notes |
|---|---|---|
| 1 | Parse review file | detect compact vs verbose format |
| 2 | Fingerprint check | refuse if block set changed since export |
| 3 | Rebuild blocks (stages 1–6 above) | same deterministic pipeline |
| 4 | Snap boundaries (formatting only) | `cloud/snap.py` |
| 5 | Interview-snap repair (move only, never drop) | |
| 6 | Dangling-start repair (move only, never drop) | |
| 7 | Renumber reels | |
| 8 | Padding | |
| 9 | Sentence bounds (`s:`/`e:`) | `cloud/edit.py` → `split_sentences` |
| 10 | Filler removal (`f:`) | `cloud/edit.py` → `remove_fillers` |
| 11 | Subtitles | `cloud/snap.py` → `trim_hanging_subtitles` |
| 12 | Collect human warnings (deciding-stage bypass) | |
| 13 | Write manifest (`selection_source: human`) | |

**Deciding stages** (top-N, dedup, duration/density floors, dangling-start drop) are **bypassed** on the manual path. Anything that would trigger them becomes a warning in the manifest.

## Render path (`arl r`)

| # | Stage | Notes |
|---|---|---|
| 1 | Resolve source by sha256 | `inputs/` then `inputs-archive/` |
| 2 | `_snap_windows_to_frames` | frame-grid alignment per segment |
| 3 | cold_open window (if `h:N`) | prepended before body |
| 4 | Speed (`setpts`/`atempo`) | applied if `reel.speed != 1.0` |
| 5 | Filler removal (multi-segment concat) | xfade between segments |
| 6 | Crop + scale (9:16) | static rectangle from calibration |
| 7 | Colour palette (curves/eq/unsharp) | optional, config `palette:` |
| 8 | Subtitles burn-in (ASS, `ass` filter) | requires ffmpeg with libass |
| 9 | Title overlay (`title_overlay`, first `title_lead_sec`) | optional |
| 10 | Tail pad + `afade` (trailing air) | uses `tail_last_word_end` / `tail_next_word_start` |
| 11 | Intruded-tail trim + fade | `_intruded_end_src` + `_tail_speech_fade` |
| 12 | Loudnorm / denoise / music mix | audio processing chain |
| 13 | Encode + faststart | hevc_videotoolbox (Mac) / hevc_amf (Windows) |
| 14 | Write `<id>.render.json` fingerprint | idempotency for re-runs |
| 15 | Write `<id>.txt` + `index.md` (publish sidecars) | hashtags from `hashtags_always` + reviewer `d:` |

**Duration invariant:** actual clip duration must be within 2.5 frames of the expected duration. 2.5 = 1 (xfade boundary) + 1 (encoder artifact) + 0.5 (rounding safety).
