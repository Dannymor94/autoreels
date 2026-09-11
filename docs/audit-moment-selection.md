# Audit — moment-selection path (read-only)

Scope: how a moment gets from LLM output to a final clip in the manifest.
Every claim cites file:line. "NOT FOUND" = not present in code.

Pipeline order (`src/autoreels/__main__.py:1169-1178`):
`compress → select (R0) → save r0_start/r0_end → snap → padding → trim → min_clip_filter → subtitles → assemble_manifest`.

---

## 1. CLIP BOUNDARIES

- **What the LLM returns:** a strict JSON object `{"segments":[{start,end,score,hook,title,description,reason,topic}]}`. `start`/`end` are absolute-second floats copied verbatim from transcript timestamps (`prompts/r0_system.md:22-35`, grounding rule `:43-46`). So the LLM returns **timecodes** (plus texts + score), **not** segment indices and **not** raw quoted spans as boundaries. Parsed at `src/autoreels/cloud/select.py:133-147`, mapped to `Reel` at `:150-160`.
- **Who sets final start/end:** the **code**. The R0 model boundaries are explicitly a draft: they are saved as `r0_start/r0_end` before any adjustment (`__main__.py:1171-1172`) and then rewritten by `snap_segments` (`snap.py:285-307`), `apply_padding` (`snap.py:310-393`), `trim_too_long` (`trim.py:34-63`), and `try_rescue_clip` (`snap.py:244-282`). Module docstring states the invariant: "LLM предлагает start/end приблизительно … КОД тянет границы" (`snap.py:1-19`).
- **Can a boundary EXPAND beyond the model's values?** **Yes.** Multiple stages move boundaries outward:
  - `_snap_end` pulls `end` **forward** to the next thought-completion within `max_duration` (`snap.py:202-208`), and `_prefer_longer_end` pushes it further to later sentence ends when the clip is short (`snap.py:167-183`).
  - `apply_padding` adds `tail_pad_sec` after the last word and `lead_pad_sec` before the first word (`snap.py:383, 376`), expanding both ends (clamped to neighbor words, `max_duration`, and `video_duration`).
  - `try_rescue_clip` moves `end` **later** to rescue a collapsed clip (`snap.py:269-280`).
  So boundaries can grow, not only shrink/snap. `_snap_start` can move `start` earlier or later within `±window_sec` (`snap.py:224-241`).

## 2. DURATION

- **Where defined / values:** presets in `config/r0.yaml:82-85` — `shorts {min:15,max:59}`, `reels {min:15,max:90}`, `tiktok {min:15,max:180}`. Active preset `shorts` (`r0.yaml:2`). Exposed as `min_duration`/`max_duration` (`core/config.py:126-134`). Additional duration knobs: `min_meaningful_sec: 18` (pre-snap floor, `r0.yaml:23`), `min_clip_duration: 8` (post-snap floor, `r0.yaml:26`), `max_sentence_buffer_sec: 30` → `max_sentence_sec = max_duration + 30` ≈ 89s (`core/config.py:136-143`).
- **Hard vs soft:**
  - `min_duration` from preset: soft — used only for `too_short` flag (`select.py:165-172`); nothing drops on it directly.
  - `min_meaningful_sec` (18): **hard pre-snap drop**, independent of score (`select.py:180-187`, called `select.py:268, 324`).
  - `min_clip_duration` (8): **hard post-snap drop**, but with a rescue attempt first (`__main__.py:617-663`).
  - `max_duration`: enforced as a hard ceiling by code — `_snap_end`/`padding` clamp to `start+max_duration` (`snap.py:195, 220, 388`).
- **A moment longer than max:** flagged `too_long` by code (`select.py:171`), then handled by `too_long_policy` (`r0.yaml:76` = `trim`). With `trim`, `_trim_end` cuts the end to the **latest word-end before a pause ≤ start+max_duration** (a sentence/phrase boundary); if no pause exists, the nearest word-end; if no words, a **hard time cut** at the limit (`trim.py:19-31`). `drop` removes the segment; `keep` leaves it. So default = **cut at a phrase/pause boundary, falling back to a hard time cut.** The rubric also asks the model to pre-tighten over-long moments (`prompts/r0_system.md:85-89`).

## 3. R0 CHUNKS

- **Window size / overlap:** `r0_chunk_tokens: 4000`, `r0_overlap_tokens: 300` (≈60s) (`r0.yaml:100, 104`). Effective window = `4000 − prompt(system+fewshot)` tokens, floored at 500 (`select.py:72-82`). Token estimate is chars//4 (`select.py:20-22`). Chunking triggers only when transcript > `r0_chunk_tokens` (`select.py:359`). Chunks are built from whole sentence-lines, never mid-line (`select.py:25-69`).
- **Can a moment span a chunk boundary?** No — the LLM only sees one chunk at a time and selects within it (`select.py:304-324`). The **overlap zone** (`r0_overlap_tokens`, ≈60s) is the only guard: a moment near a boundary should also appear in the neighboring chunk's overlap, then be deduped (`select.py:286-291` docstring).
- **Guard against "truncated by window, not by meaning":** **NOT FOUND** as an explicit guard. There is no code flag or check for "moment ran into the chunk edge." The only mitigation is the 300-token overlap (`r0.yaml:104`) so a boundary-straddling moment can be captured whole in the adjacent chunk. Nothing detects or marks a clip whose `end` coincides with the chunk's last line.
- **Cross-chunk dedup:** `dedup_reels` (`chunk_transcribe.py:141-156`), called at `select.py:337`. Works **by timecodes** — overlap ratio = intersection / shorter-duration (`chunk_transcribe.py:167-170`); if ratio > `dedup_overlap_ratio` (0.5, `r0.yaml:106`) the **chronologically earlier** (smaller `start`) wins (sorted by `start`, `chunk_transcribe.py:148`). Not by text, not by id. (In-chunk single-request path uses score-greedy dedup instead: `select.py:223-229`.)

## 4. RUBRIC

Full runtime rubric (the fenced block in `prompts/r0_system.md:8-129`; `{{...}}` filled by `build_prompt` at `select.py:117-122`):

```
You are a deterministic highlight-selection engine for a video-to-Reels pipeline.
Your only job: read a timestamped transcript chunk and return self-contained
segments that work as standalone short vertical videos (Reels / Shorts / TikTok).

You do NOT write prose. You do NOT explain. You return ONLY a JSON object.

# INPUT
A transcript chunk. One line per sentence:
[START-END] sentence text
Timestamps are absolute seconds in the source video. Use them verbatim.

# OUTPUT — STRICT JSON, NOTHING ELSE
No preamble, no markdown, no code fences. A single JSON object:
{ "segments": [ { "start", "end", "score", "hook", "title", "description", "reason", "topic" } ] }

An EMPTY result is valid and expected:
{ "segments": [] }
Return it whenever the chunk has no strong standalone moment. Do not invent
weak segments to fill space. "Nothing good here" is a correct answer.

# GROUNDING (non-negotiable)
- start/end MUST come from timestamps present in the input. Never fabricate times.
- hook/title/description MUST be supported by what is actually said in the segment.
- If you cannot ground a field in the transcript, the segment is invalid — drop it.

# SELECTION RUBRIC — score each candidate

## HARD GATE — check FIRST, before scoring
COMPLETE THOUGHT (hard gate): the clip stands as a finished idea — the viewer
gets a whole point, not a fragment. Either a setup that lands its payoff inside
the window, OR a self-contained insight/statement that needs no lead-up.
A point raised but not resolved -> reject. A statement cut before it completes -> reject.
"Understandable" is not enough; it must feel WHOLE and finished.
A candidate that fails this gate is NOT a low-score segment — it is not a segment
at all. Do not score it, do not include it.

Strong signals (raise score):
- HOOK in the first ~3 seconds: opens on a grab, not a wind-up. No hook = dead clip.
- EMOTIONAL PEAK: surprise, conflict, insight, reversal of expectation.
- QUOTABLE: contains a line a viewer would want to repeat.
- QUESTION -> ANSWER: a closed micro-arc inside the clip.
- COUNTERINTUITIVE: "actually it's the opposite of what you think".

Anti-signals (lower score or reject):
- Cuts in mid-thought, or references "as I said earlier" / external context.
- Organizational talk ("let's take a break", "turn up the volume").
- Long wind-up with no payoff.

Disqualifiers (return NOTHING for these):
- Service / organizational / transitional talk, greetings, housekeeping.
- Intro or setup whose payoff falls outside the window.
- Filler — "sounds fine but says nothing transferable".
- A thought that begins but does not conclude within the segment.

Score calibration:
- 80-100: publish with confidence.
- 65-79: usable — but ONLY if the COMPLETE THOUGHT gate holds.
- below {{min_score}}: too weak, do NOT include.

# LENGTH & SELF-CONTAINMENT (hard constraint)
Every segment MUST satisfy: {{min_duration}}s <= (end - start) <= {{max_duration}}s.
- If a strong moment runs longer than {{max_duration}}s: tighten it — move `start`
  closer to the payoff — or split it into two independent clips.
- Never return a segment outside these bounds. The downstream code will reject it.

# TITLE RULES (clickbait) / # DESCRIPTION RULES  [see file :91-104]

# COVERAGE — return ALL qualifying moments, but a chunk is not a quota
[full text at prompts/r0_system.md:106-123]

# DEDUP
Within this chunk, do not return two segments covering the same moment.
(Cross-chunk dedup is handled downstream — just don't self-overlap.)

Return the JSON object now.
```

- **Hard gates / disqualifiers:** COMPLETE THOUGHT hard gate (`:50-59`); length hard constraint `min ≤ end-start ≤ max` (`:85-89`); disqualifier list (`:73-78`); anti-signals (`:68-72`); grounding non-negotiable (`:42-46`).
- **Self-contained opening (no dangling "so/he/this" without antecedent):** **partially / NOT explicit.** The rubric requires "self-contained … needs no lead-up" and rejects "references 'as I said earlier' / external context" (`:52-53, :70`), but there is **no explicit rule naming dangling connectives/pronouns without an antecedent at the opening.** (Such words are handled only later, deterministically, via `hanging_words` in snap — see §6, not in the rubric.)
- **Completed thought at the end:** **Yes, explicit** — "A statement cut before it completes -> reject" and "A thought that begins but does not conclude within the segment" disqualifier (`:54, :78`).

## 5. POST-SELECTION VALIDATION

- **Second pass / verification / re-scoring of selected clips:** **No.** No LLM or code stage re-reads or re-scores a chosen clip after selection. Post-selection code stages are deterministic boundary/duration operations only: `flag_durations`, `filter_by_score`, `filter_by_duration`, `dedup` (`select.py:266-269`), then snap/padding/trim/min_clip_filter (`__main__.py:1173-1176`). Scores are never recomputed — only sorted (`select.py:270, 338`). No verifier agent, no adversarial check, NOT FOUND.
- **Over-generation + ranking (keep top-N):** **Partially.** The model is told to return *all* qualifying moments and explicitly *not* to hit a quota (`prompts/r0_system.md:106-123`), so this is not deliberate over-generation. There **is** a top-N cap mechanism: sort by score desc then `reels[:max_reels]` (`select.py:270-272, 338-340`), but `max_reels: null` (`r0.yaml:32`) — the cap is currently **disabled** (keep all that pass thresholds).

## 6. SNAP

All in `snap.py`, config in `r0.yaml`/`core/config.py`. Values:

- `min_pause_for_phrase_end: 1.5` — pause > this = end of thought (`r0.yaml:46`, `config.py:104`).
- `max_micro_pause: 0.4` — pause ≤ this never counts as an end (`r0.yaml:50`, used `snap.py:96`).
- `snap_window_sec: 1.5` — search window ±sec around the LLM boundary (`r0.yaml:42`).
- `tail_sec: 0.3` — technical tail added after chosen end (`r0.yaml:39`, `snap.py:220`).
- `tail_pad_sec: 0.7` / `lead_pad_sec: 0.3` — padding air (post-snap) (`r0.yaml:40-41`).
- `prefer_longer_below_ratio: 0.7`, `max_extra_sentences: 2` — extend short clips (`r0.yaml:54-55`).
- `hanging_words` list — never begin/end on these (`r0.yaml:56-71`, `config.py:114-117`).

Rules (end): sentence-punctuation (`.!?…`) is always a valid end (`snap.py:88-90, 42-45`); mid-phrase punctuation (`,;:—–-`) is never an end regardless of pause (`snap.py:91-92, 48-51`); micro-pause ≤0.4s never an end (`snap.py:96`); long pause >1.5s or end-of-speech is an end **only if the word is not hanging** (`snap.py:98-99`). Forward-first: nearest completion ≥ `end − window` within `max_duration` (`snap.py:202-204`); if none fits, fall back to the **last** whole phrase within limit (`snap.py:210-213`); if still none, `_relaxed_end` hierarchy (b) soft pause ≥0.4s → (c) non-hanging word before the max pause → (d) last non-hanging word / nearest word-end, never mid-word (`snap.py:121-159`). Start rule: snap to a phrase start (after a pause, not after a comma), never onto a hanging word (shift forward) (`snap.py:104-118, 224-241`).

- **Moves which end?** **Both.** `snap_segments` calls `_snap_start` then `_snap_end` (`snap.py:296-307`).
- **Cap on how far snap may move a boundary?**
  - `start`: capped — only within `±snap_window_sec` (1.5s) of the LLM start (`_nearest_in_window`, `snap.py:59-62, 229-231`).
  - `end`: **asymmetric / no small cap.** Backward reach is limited by `window_sec` (`end − window`, `snap.py:202`), but forward extension is bounded only by `max_duration` (`snap.py:195`) — end can be pulled far forward (up to the preset max, plus `prefer_longer` to later sentence ends), not limited to `window_sec`. So there is no tight cap on forward end movement.

## 7. MANIFEST CONTENTS

`Manifest` (`core/models.py:122-145`): `source`, `source_sha256`, `source_hash_scheme` ("full"|"partial-p1"), `duration_preset`, `setup` (SetupProfile), `run_key`, `status`, `reels: list[Reel]`.

`Reel` clip entry — every field (`core/models.py:97-119`):
- `id: str` (e.g. `r01`)
- `start: float`, `end: float` — final boundaries
- `score: int` (0-100)
- `hook: str`, `title: str`, `description: str`, `reason: str`, `topic: str`
- `r0_start: float|None`, `r0_end: float|None` — LLM boundaries before snap (for resnap without re-LLM)
- `flags: list[str]` — `too_long`/`too_short`/etc, set by code
- `subtitles: list[Word]` — raw word-level (`Word{word,t0,t1}`), bound at `__main__.py:670` via `words_in_window(transcript.words, start, end)`
- No `crop`/`scale` on the reel — inherited from `manifest.setup` (`models.py:98`).

- **Is clip text or transcript-index-range persisted?** The **clip text is persisted implicitly** as `subtitles` (word-level `Word` list per reel, `models.py:119`, filled `__main__.py:670`). A **transcript segment-index range is NOT stored** — reels carry only absolute-second `start/end` (`models.py:104-105`) and the word list, no index into the original transcript.
- **Can clip texts be exported without re-transcribing?** **Yes** — join `reel.subtitles[*].word` per reel; the words are in the manifest. (Whole-transcript text is also written separately at `__main__.py:1165-1168`.)

---

## OBSERVATIONS
Places where a boundary is decided by a technical constraint, not by meaning. (Observations only.)

- **Chunk edge, no completeness guard (§3).** A moment near a chunk's last line can be selected against a boundary the window imposed; nothing flags "truncated by window vs. by meaning." Only the 300-token overlap (`r0.yaml:104`) mitigates it, and only if the neighbor chunk captures the moment whole.
- **`max_duration` hard ceiling (§2, §6).** `_snap_end`/`apply_padding` clamp `end` to `start+max_duration` (`snap.py:195, 220, 388`) — a thought that completes just past the limit is cut at a time constant, not at its natural end.
- **`too_long` hard-cut fallback (§2).** When no pause exists before the limit, `_trim_end` returns `limit` — a pure time cut mid-speech (`trim.py:31`).
- **`min_meaningful_sec: 18` pre-snap drop (§2).** Any moment under 18s is discarded regardless of whether it is a complete thought and regardless of score (`select.py:180-187`) — a duration constant overrides meaning.
- **`min_clip_duration: 8` post-snap drop (§2).** A clip snap collapsed below 8s is dropped if rescue fails (`__main__.py:633-658`) — outcome set by a length constant plus what phrase boundaries happen to exist.
- **`compress` forced sentence splitting at ~89s (§2, compress.py).** Sentence-lines longer than `max_sentence_sec` (max_duration+30) are split by longest internal pause (`compress.py:63-73`); the LLM can only pick whole lines, so these code-chosen split points constrain where a moment inside a long monologue can begin/end.
- **Token-budget window sizing (§3).** Effective chunk window = `4000 − prompt tokens`, floored at 500 (`select.py:72-82`), computed from a chars//4 estimate (`select.py:20-22`) — window extent (and thus where boundaries can fall) is a TPM/token artifact, not content.
- **Asymmetric snap reach (§6).** `start` is capped to ±1.5s of the LLM value, but `end` can be pulled forward up to `max_duration` (`snap.py:195, 202-208`) — end placement is governed by the duration limit and available sentence ends, not symmetric proximity to intent.
- **`prefer_longer_below_ratio: 0.7` extension (§6).** A grammatically complete clip under 70% of max is lengthened to later sentence ends, up to +2 sentences (`snap.py:167-183`) — the target length is driven by a ratio constant, potentially past where the moment's point lands.
- **Cross-chunk dedup keeps the chronologically earlier copy (§3).** On >0.5 overlap, `dedup_reels` keeps the earlier-`start` reel (`chunk_transcribe.py:148-155`), not the better-bounded or higher-scored one — the surviving boundary is chosen by chunk order/time, not quality.
