# Punctuation Audit: Why PXL Transcript Is Unpunctuated

**Sources compared**

| Source | Reels | Unpunctuated |
|--------|-------|-------------|
| `2026-08-08 10h 59m 38s.mp4` (lecture) | 11 | 1 (9%) |
| `PXL_20260729_085910095_34f06abf.mp4` | 18 | 9 (50%) |

reel r11 (PXL, 1710–1800 s, 90 s) has zero sentence-terminal marks across all 118 words  
in that window — confirmed by inspecting `r.subtitles` in the manifest.

---

## 1. TRANSCRIPTION PARAMETERS

**Code path:** `src/autoreels/cloud/transcribe.py:87–110` (`GroqBackend._default_request`).

Parameters sent to Groq Whisper API for **every** request, with no per-source variation:

| Parameter | Value | Source |
|-----------|-------|--------|
| `model` | `whisper-large-v3` | `config/transcribe.yaml:groq.model` |
| `response_format` | `verbose_json` | hardcoded at line 106 |
| `timestamp_granularities[]` | `word` | hardcoded at line 107 |
| `language` | `ru` | `transcribe.py:209`, passed through chunking at line 249 |

**`initial_prompt` / context prompt:** NOT SENT. The `data` dict built at lines 104–110
contains only the four fields above. There is no `initial_prompt` key anywhere in
`_default_request`, and `grep -rn initial_prompt src/` returns zero hits. This is known
to affect Whisper punctuation behaviour — without an initial_prompt priming it to use
Russian punctuation, Whisper defaults to its own heuristics.

No parameter differs between the two sources.

---

## 2. PROVIDER USED

**Config (`config/transcribe.yaml:1`):** `backend: groq`. Environment variable
`TRANSCRIBE_BACKEND` can override this at runtime; no per-source logic exists.

**Is provider recorded in the manifest?** NO. The manifest schema
(`src/autoreels/core/models.py`) and both manifest files
(`manifests/2026-08-08 10h 59m 38s.json`, `manifests/PXL_20260729_085910095_34f06abf.json`)
contain only: `source`, `source_sha256`, `source_hash_scheme`, `duration_preset`, `setup`,
`run_key`, `status`, `reels`. No `provider`, `backend`, or `transcript_provider` field.

**Recoverable for these two runs?** NOT FOUND. The transcript cache files (`.transcript.json`)
also carry no provider metadata — only `{"language": "ru", "words": [...]}`.

**Do different providers receive identical parameters?** `src/autoreels/cloud/providers.py`
is the LLM (R0) provider, not the Whisper provider. Whisper is served exclusively through
`GroqBackend` (`src/autoreels/cloud/transcribe.py:65–153`). There is no OpenRouter or
secondary Whisper backend wired up anywhere in the codebase.

---

## 3. AUDIO PREPROCESSING

**Extraction command** is assembled by `build_extract_cmd`
(`src/autoreels/cloud/extract_audio.py:120–138`). Parameters come from
`config/render.yaml:audio_extract`:

```
-vn -ac 1 -ar 16000 -c:a libmp3lame -b:a 64k -f mp3
```

This command is **identical for all sources** — it does not inspect source properties.

**Extracted audio — both sources confirmed identical format:**

```
codec=mp3  sample_rate=16000  channels=1  bitrate=64000
```

lecture (`3c083b60….mp3`): duration 2590.7 s  
PXL (`f930ebd5….mp3`): duration 2862.4 s

**Source file properties** (ffprobe on originals):

| Property | Lecture (`2026-08-08 10h 59m 38s.mp4`) | PXL (`PXL_20260729_085910095_34f06abf.mp4`) |
|----------|---------------------------------------|---------------------------------------------|
| Video codec | hevc | hevc |
| Video bitrate | ~12.7 Mbps | ~43.0 Mbps |
| Audio codec | aac | aac |
| Audio bitrate | **64 kbps** | **192 kbps** |
| Audio sample rate | 44100 Hz | 48000 Hz |
| Channels | stereo | stereo |
| Duration | 2590.8 s (43.2 min) | 2862.6 s (47.7 min) |

PXL has materially higher source audio quality (192 kbps vs 64 kbps). After downmix to
64 kbps mono 16 kHz mp3 the difference narrows, but PXL starts from a less-degraded signal.
Low source audio quality cannot explain PXL's worse punctuation.

**Chunk extraction** uses `split_audio_chunk`
(`src/autoreels/cloud/chunk_transcribe.py:215–251`) with the same `audio_cfg` object,
so chunk files are also identical format. ffprobe confirms:

```
PXL chunk_00: codec=mp3, 16000 Hz, mono, 64k, 600.7 s
Lecture chunk_00: codec=mp3, 16000 Hz, mono, 64k, 600.0 s
```

---

## 4. CHUNKING

**Configuration** (`config/r0.yaml:chunking`):

```yaml
whisper_chunk_duration_sec: 600      # 10 min target
whisper_threshold_minutes: 15
silence_window_sec: 30
silence_threshold_db: -40
```

Both sources exceed 15 min → chunking is used for both.

**Chunks produced:**

| Source | Chunks | Chunk dir |
|--------|--------|-----------|
| Lecture | 5 | `data/cache/chunks/ec3ee0b6bba08222/` |
| PXL | 5 | `data/cache/chunks/77194f017bf1e73f/` |

Chunk boundaries are placed by **VAD** (`detect_silences` → `find_split_point`,
`chunk_transcribe.py:181–212`, `45–72`), not by fixed time.

**Does stitching drop or alter punctuation?** NO. `merge_transcripts`
(`chunk_transcribe.py:84–138`) concatenates word lists after applying a time-based offset.
The only trimming is at the overlap zone (lines 129–134): words whose `t0 < prev_t1` are
dropped — a time-based dedup, not text-based. No character is modified or removed from any
word string. Punctuation cannot be lost at seams by this mechanism.

---

## 5. MEASURE IT

### Per-transcript totals

| Source | Words | Terminal marks (. ? !) | Per 100 words | Longest unpunctuated run (words) |
|--------|-------|----------------------|---------------|----------------------------------|
| Lecture | 3 995 | 380 | **9.5** | 213 |
| PXL | 5 620 | 102 | **1.8** | 551 |

### Per-chunk detail — Lecture (`ec3ee0b6bba08222`)

| Chunk | Words | Duration (s) | Terminals | Per 100 | Longest run |
|-------|-------|-------------|-----------|---------|-------------|
| chunk_00 | 1 203 | 600 | 120 | 10.0 | 155 |
| chunk_01 | 1 271 | 599 | 110 | 8.7 | 205 |
| chunk_02 | 740 | 597 | 59 | 8.0 | 110 |
| chunk_03 | 456 | 600 | 79 | 17.3 | 25 |
| chunk_04 | 325 | 191 | 12 | 3.7 | 213 |

### Per-chunk detail — PXL (`77194f017bf1e73f`)

| Chunk | Words | Duration (s) | Terminals | Per 100 | Longest run |
|-------|-------|-------------|-----------|---------|-------------|
| chunk_00 | 1 089 | 600 | 18 | 1.7 | 313 |
| chunk_01 | 1 207 | 597 | 23 | 1.9 | 389 |
| chunk_02 | 1 180 | 601 | 20 | 1.7 | 330 |
| chunk_03 | 1 259 | 598 | 14 | **1.1** | 300 |
| chunk_04 | 885 | 460 | 27 | 3.1 | 381 |

PXL punctuation is uniformly low across all five chunks. There is no progressive pattern
(degradation toward end, or absence in specific chunks only) — the low rate is present from
chunk_00 through chunk_04.

### reel r11 (PXL, 1710–1800 s)

r11 falls inside chunk_02 (1200–1800 s). The subtitle word list in the manifest contains
118 words, none of which ends with `.`, `?`, or `!`. The snap code (`snap.py:279–294`) fell
through to the pause-based fallback (`end_snap_reason: "no_end"` recorded in the manifest),
setting the `unpunctuated` flag at `snap.py:411`.

---

## OBSERVATIONS

Listed in descending order of evidential support.

### 1. Speech register and delivery — strongest evidence

The PXL content is an informal, free-flowing interview with a yoga/psychology practitioner
speaking in an associative, unpunctuated stream-of-consciousness style in Russian
("вот и вот она точно четко суть моего какого-то метода она объяснять там даже не метод как
бы объяснение самой системы психики наверное да ну и конечно это сказать не в последней
инстанции да но то что я заметил то что я заметил…"). The lecture source contains
structured, pause-delimited academic speech.

Whisper large-v3 is known to add punctuation based on prosodic cues (pauses, intonation
contours) and linguistic structure. When a speaker delivers long, weakly-paused, informal
monologue with clause-chaining particles common in Russian colloquial speech (и, да, вот,
ну, а), Whisper consistently omits sentence-terminal marks. This is a content-driven
model behaviour, not an infrastructure difference.

The per-chunk data confirms this: all five PXL chunks show the same low rate (1.1–3.1 per
100), indicating the cause is not a single bad chunk or a boundary artefact — it is a
property of the entire recording's speech style.

### 2. Absence of `initial_prompt` — known amplifier

No `initial_prompt` is sent to Whisper for either source (`transcribe.py:104–110`).
Providing a punctuated Russian sentence as `initial_prompt` is documented as a way to
prime Whisper toward punctuated output. Its absence affects both sources equally, so it
cannot by itself explain the gap. However, it likely deepens the deficit for the source
where Whisper is already hesitant to punctuate (informal speech), while having less impact
on a source where prosody already signals sentence boundaries (structured lecture).

### 3. Provider difference — not supported by evidence

The provider is not recorded in any artifact (manifest, transcript cache, logs). Both
sources are expected to use Groq Whisper based on the config (`backend: groq`) and the
absence of any per-source routing logic. No evidence points to a provider switch between
runs.

### 4. Audio quality difference — not supported

PXL has higher source audio bitrate (192 kbps vs 64 kbps). After identical downsampling to
64 kbps mono 16 kHz mp3, any remaining quality difference favours PXL. Low audio quality
cannot explain worse punctuation on PXL.

---

**Summary:** The evidence points to **input speech content** (informal colloquial register
vs structured lecture) as the primary cause, amplified by the absence of `initial_prompt`
which would prime Whisper's punctuation model. No parameter difference, audio preprocessing
difference, or provider difference is detectable.
