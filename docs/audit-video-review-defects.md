# Audit — three defects from the first on-video review

First review done by **watching the rendered clips** (23 clips, PXL, `selection_source:
human`) rather than on text. Two of the three defects are invisible in the transcript. Fix 1
(final speech density) and Fix 2 (multi-block / backward merges) are implemented in this commit;
Fix 3 (segmentation) is reported here only — we decide from the numbers, not impression.

Numbers are measured on the cached transcripts, no R0 re-run:
- **PXL interview** — the reviewed source (47.7 min, 4677 words, 30 reviewed selections).
- **lecture B** — a second cached full source (46.7 min, 5889 words), for cross-checking that the
  segmentation pattern is not a one-source artefact.
Config at time of audit: `min_pause_for_phrase_end=1.5s`, preset ceiling `max_duration=90s`,
`min_meaningful_sec=18s`, new `final_speech_density_min=0.80`, `speech_density_split_gap_sec=3s`.

---

## Fix 1 — silence inside the finished clip

### Speech density of every shipped PXL clip (before → after)

Density = spoken time / clip wall-time, computed on the FINAL clip (after merge/snap/padding),
which is where the defect lives — the block stage measured density per block, so a clip
assembled from two blocks across a long pause passed.

| clip | reel | dur | density | action |
|---|---|---|---|---|
| 1 | r01 | 36.5s | 93% | keep |
| 2 | r03 | 52.0s | 92% | keep |
| 3 | r04 | 34.5s | 98% | keep |
| 4 | r05 | 35.3s | 100% | keep |
| 5 | r06 | 46.8s | 95% | keep |
| 6 | r07 | 27.5s | 95% | keep |
| **7** | **r08** | **54.7s** | **73%** | **split → keep 40.4s @ 89%** |
| 8 | r09 | 28.6s | 98% | keep |
| 9 | r10 | 38.7s | 99% | keep |
| 10 | r11 | 25.5s | 99% | keep |
| 11 | r12 | 52.3s | 98% | keep |
| 12–23 | r13–r26 | 18–48s | 88–100% | keep |

**One clip (r08) is the sole outlier at 73%**; every other clip sits at 88–100%. r08 carries a
14.6s pause (interviewer searching for the next question). The new density stage finds the single
gap ≥ 3s, cuts there, and keeps the longer half — **40.4s at 89% density**, above the 0.80 floor.
No other clip is touched; nothing is dropped on this corpus.

### Co-occurrence with `unpunctuated` + `no_end`

r08 is also the only clip flagged `unpunctuated` and the only clip with `end_snap_reason: no_end`.
Across the 23 clips: `unpunctuated = 1`, `no_end = 1`, **both on the same clip = 1**. The overlap
is perfect but the sample is a single clip, so this is **suggestive, not yet a rule**: the clip that
lacked terminal punctuation is exactly the one snap could not end cleanly and the one that ran long
and empty. It is worth carrying `unpunctuated ∧ no_end` as an **early-warning pair** (cheap,
already computed) and confirming it on the next reviewed source before relying on it — but density
on the finished clip is the direct measurement and is what Fix 1 gates on.

---

## Fix 2 — merges of more than two blocks, and merging backwards (implemented)

Markers on a block's score: `+` join the next block, `++` join the next two (a thought across
three), `-` before the score join the preceding block. `++` was chosen over `+2`: it extends `+`
visually, needs no digit that could blur into the score, and reads as "keep going". A forward `+`
on block *i* and a backward `-` on *i+1* name the **same** edge `(i, i+1)` and merge once. A merge
whose span exceeds `max_duration` is reported to the reviewer by block number and the blocks are
kept separate — never silently trimmed.

This matters because the reviewer's manual joins are frequent, which is the same signal Fix 3
quantifies: **12 of 30 PXL selections needed joining**, and 20 of the 23 shipped clips are
`human_merged`.

---

## Fix 3 — clips that end on a complete sentence but an incomplete thought (report only)

Clips 6 and 10 end with `end_snap_reason: sentence` — snap found a terminal mark and stopped,
correct by its own rules — yet the thought continues. The snap is not changed. The question is
whether **block segmentation** cuts too early. Numbers below; no code change in Fix 3.

### 1. Block duration vs the 90s ceiling

| source | blocks | median | mean | max | ≥90s | <18 | 18–30 | 30–40 | 40–50 | 50–70 | 70–90 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| PXL interview | 120 | **22.0s** | 23.1s | 45.2s | 0 | 0 | 112 | 6 | 2 | 0 | 0 |
| lecture B | 75 | **22.2s** | 36.3s | 109.6s | 1 | 0 | 48 | 4 | 1 | 14 | 7 |

Interview blocks cluster hard at **18–30s — 24–25% of the 90s ceiling**; 112 of 120 PXL blocks are
under 30s and none reach 46s. There is enormous unused head-room. Lecture B has a long-monologue
tail (21 blocks ≥50s) but the same 22s median: the short-block cluster is not interview-specific.

### 2. How often a boundary is a sentence-end where the speaker kept going

A boundary is `sentence` only when the previous line ended in terminal punctuation **and** the gap
was **not** longer than `min_pause_for_phrase_end` (pause is checked first) — i.e. the speaker
punctuated and kept talking.

| source | boundaries | sentence (kept going) | pause (real stop) | speaker_turn |
|---|---|---|---|---|
| PXL interview | 445 | **390 (88%)** | 46 (10%) | 9 (2%) |
| lecture B | 326 | **296 (91%)** | 30 (9%) | — |

**~9 of every 10 block boundaries are a sentence-end the speaker talked straight through.** Only
~1 in 10 is a real pause. Segmentation is overwhelmingly cutting mid-flow at punctuation — exactly
the clips-6-and-10 defect, at scale.

### 3. What changes if segmentation prefers to continue to 40–50s

Estimate on the existing transcripts (no R0): greedily extend a block while it is under 40s **and**
the boundary to the next block is a `sentence` boundary (speaker kept going — never cross a real
pause or speaker turn) **and** the combined span stays ≤ 50s.

| source | blocks before → after | soft joins | median before → after | in 40–50s band before → after | still <18s |
|---|---|---|---|---|---|
| PXL interview | 120 → **71** | 49 | 22.0s → **41.3s** | 2 → **45** | 0 → 0 |
| lecture B | 75 → **58** | 17 | 22.2s → **41.2s** | 1 → **9** | 0 → 0 |

Preferring continuation across soft boundaries would **roughly halve the block count**, move the
median from ~22s to **~41s**, and land most blocks in the 40–50s band — without crossing any real
pause and without producing sub-floor blocks. That is close to what the reviewer did by hand (12 of
30 joined). The lever is narrow and safe: only `sentence`-reason boundaries are crossed, only up to
a 50s target, well under the 90s ceiling.

### Recommendation to decide on

The data supports a segmentation preference toward 40–50s that continues across sentence-end
boundaries where the speaker kept going, capped at a soft target (~50s) and never crossing a
`pause`/`speaker_turn` boundary. It would remove most of the manual joining and the
"complete-sentence, incomplete-thought" endings. It does **not** replace Fix 2 (the reviewer still
needs explicit joins for the cases the heuristic won't reach) nor Fix 1 (a longer target makes the
dead-air check more important, not less). Decision pending; no segmentation change in this commit.

---

## Follow-up — segmentation now runs to a target length (implemented)

The segmentation change the audit above recommended is now in `candidate_blocks`
(`block_target_sec: 40`): a **soft** boundary (sentence-terminal mark with no pause behind it)
no longer closes a block until it has reached the target; a **hard** boundary (pause >
`min_pause_for_phrase_end`, paragraph, speaker turn) still closes it always; and a soft boundary
also closes early if continuing to the next boundary would exceed `max_duration`. Short-merge and
over-long-split are unchanged.

### Before → after, both cached sources

BEFORE = old behaviour (close at every boundary, i.e. `block_target_sec=0`); AFTER = `40`.

| source | count | median | mean | max | bands `<18 / 18-30 / 30-40 / 40-50 / 50-70 / 70-90` |
|---|---|---|---|---|---|
| PXL interview — before | 119 | 22.0s | 23.3s | 45.2s | 0 / 110 / 7 / 2 / 0 / 0 |
| PXL interview — **after** | **63** | **42.6s** | 43.0s | 73.9s | 0 / 8 / 10 / 32 / 12 / 1 |
| lecture B — before | 75 | 22.2s | 36.3s | 109.6s | 0 / 48 / 4 / 1 / 14 / 7 |
| lecture B — **after** | **54** | **43.8s** | 50.0s | 109.6s | 0 / 13 / 4 / 13 / 13 / 10 |

Boundary-reason breakdown (what closed each block):
- PXL: sentence `103 → 37`, pause `14 → 24`, speaker_turn `2 → 2` — soft closures more than halve;
  blocks now end predominantly on real pauses, not on mid-flow full stops.
- lecture B: sentence `56 → 28`, pause `19 → 26`.

The aggregate prediction from the audit **holds**: PXL block count roughly halves (119 → 63) and the
median moves from 22s to ~43s, with the mass landing in the 40-50s band.

### Against the reference — did the reviewer's twelve hand-merges collapse into single blocks?

Re-exported PXL blocks (old kept-block numbering, 113 kept — matches the review). A pair is
"covered" when a single new block spans it:

`44+45`, `59+60`, `80+81` covered → **3 of 12** (strict: one new block spans the whole pair;
4 of 12 by the looser test of both halves sharing a new block).

**Reported plainly: few.** The distribution moved as predicted, but the change does **not**
reproduce the reviewer's specific joins, for two reasons:
- **Phase misalignment (most pairs).** Accumulation is greedy from the previous hard boundary, so
  the ~40s budget fills at a point that need not line up with the reviewer's chosen pair. `23+24`,
  `84+85`, `94+95`, `98+99`, `102+103` are all *contiguous* (0.00s gap — a soft boundary) yet land
  on opposite sides of a new block edge, because the block boundary fell exactly between them. The
  policy targets a *length*, not a *thought*; where it lands is incidental to the pair.
- **Hard pause inside a pair (`65+66`, gap 2.10s > 1.5s).** The reviewer merged across a real pause;
  this change never crosses a hard boundary by design, so that pair is uncoverable here.

Conclusion: the target-length policy does what the *aggregate* evidence predicted — it halves the
block count and centres durations near 40s, which should reduce how *often* the reviewer must merge.
It does not, and cannot on its own, land the *specific* joins: those remain the job of the manual
`+`/`++`/`-` markers (Fix 2). The two are complementary — this lowers the volume of manual joining,
the markers handle the exact pairs and the across-a-pause cases.
