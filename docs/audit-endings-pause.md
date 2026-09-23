# Audit: do post-clip pauses explain "abruptly cut" complaints?

Source: `PXL_20260729_085910095_34f06abf`  
Manifest: 14 reels, `selection_source: human`  
Transcript: 4 680 words, 0.0 – 2 859 s  
Date: 2026-09-23

---

## 1. Per-reel measurement

Each row: the end time of the last subtitle word, the start of the next source word, the gap between
them, the snap reason recorded in the manifest, whether `e:` was explicit in the review, and the
last six subtitle words.

| ID  | last_word_end | next_word_start | gap   | snap_reason               | e: | last 6 words |
|-----|--------------|-----------------|-------|---------------------------|----|--------------|
| r01 | 595.370      | 595.870         | 0.50s | sentence                  | Y  | ты кого-то любил, и тебя любили. |
| r02 | 679.913      | 680.373         | 0.46s | sentence                  | Y  | твоего состояния, такие же люди притягиваются. |
| r03 | 1016.233     | 1016.273        | 0.04s | sentence                  | Y  | нет предела, как я говорю, спокойствия. |
| r04 | 1183.163     | 1183.883        | 0.72s | sentence                  | Y  | себе, так как я занимаюсь хатха-йогой. |
| r05 | 1220.493     | 1221.093        | 0.60s | before_host_turn          | Y  | проблема тишины и покоя не наступает. |
| r06 | 1537.662     | 1538.842        | 1.18s | before_host_turn          | Y  | он и куда ему нужно идти. |
| r07 | 1722.136     | 1722.676        | 0.54s | sentence                  | Y  | точно, четко объясняет суть моего метода. |
| r08 | 1961.092     | 1962.012        | 0.92s | sentence                  | Y  | — это просто сигнал в теле. |
| r09 | 2057.232     | 2057.712        | 0.48s | —                         | Y  | этим. Действительно, тогда по-настоящему вы меняетесь. |
| r10 | 2158.195     | 2158.295        | 0.10s | before_host_turn          | Y  | Природа ваша — это ваше тело. |
| r11 | 2466.779     | 2466.899        | 0.12s | sentence                  | Y  | людей, кроме той группы, которая наша. |
| r12 | 2537.140     | 2537.640        | 0.50s | sentence_trimmed_hanging  | Y  | зайдет, а что-то вам не зайдет. |
| r13 | 2659.721     | 2659.761        | 0.04s | sentence                  | Y  | Тогда реализация идет более естественным образом. |
| r14 | 2747.621     | 2771.722        | 24.1s | sentence                  | —  | мировоззрением, то вы нужны именно такие. |

All 14 reels had explicit `e:` in the review except r14.

---

## 2. Transcript gap distribution

Whisper assigns many word timestamps as flush (t1 of word N = t0 of word N+1). The "gap" is
therefore meaningless for the majority of sentence boundaries. What matters is when Whisper
itself opened a non-zero interval — that is the signal that its own segmentation detected a pause.

| threshold | sentence-end gaps ≥ threshold | share |
|-----------|------------------------------|-------|
| ≥ 0.10 s  | 153 / 442                    | 34.6% |
| ≥ 0.30 s  | 136 / 442                    | 30.8% |
| ≥ 0.60 s  | 112 / 442                    | 25.3% |
| ≥ 1.00 s  | 73 / 442                     | 16.5% |
| ≥ 1.50 s  | 45 / 442                     | 10.2% |

442 sentence-terminal words found. Median gap: 0.000 s (flush majority). Mean: 0.547 s (the tail
of genuine pauses pulls the average up). Speaker turns account for most gaps ≥ 1 s.

A 0.6 s rule would have 112 qualifying "stop" points across the 2 859 s source — roughly one every
25 seconds of content. Coverage is adequate for a rule; the speaker does genuinely stop.

---

## 3. Correlation with reviewer complaints

Reviewer verdict: **abrupt endings** — r03, r07, r08, r10. **Stream without arc** — r11, r12, r13.
**Junk** — r05.

### Small-gap group (gap < 0.2 s): r03, r10, r11, r13

All four are in the complained set. For all four, the speaker continues within 0.04 – 0.12 s —
Whisper's timestamps show no breath; the audio is still going. These are clear cases where the
rule "end at a sentence terminal" fired, but the speaker had not stopped.

Context after clip end:

- **r03** (0.04 s): ends on "нет предела, как я говорю, спокойствия." → 0.04 s → "стараемся
  еще в более его естественное состояние войти…" — a clause completing the thought.
- **r10** (0.10 s): ends on "Природа ваша — это ваше тело." → 0.10 s → "Вы же в теле
  находитесь, правильно?" — a rhetorical question that IS the continuation of the statement.
  `snap_reason: before_host_turn` is wrong here — the "host" timestamp is the guest completing
  his own point with a question.
- **r11** (0.12 s): ends on "людей, кроме той группы, которая наша." → 0.12 s → "Мы обычно
  выбираем какие-то ретритные центры." — still mid-description.
- **r13** (0.04 s): ends on "Тогда реализация идет более естественным образом." → 0.04 s →
  "Мы говорили, помнишь, про цветочек…" — callbacks to earlier metaphor; monologue continues.

**For this group, the correlation is clean. Gap < 0.2 s = still talking.**

### Moderate-gap group (gap 0.3–1.0 s): r07, r08, r12

These have real pauses but the reviewer still complained.

- **r07** (0.54 s, "abrupt"): ends on "точно, четко объясняет суть моего метода." → 0.54 s →
  "Там даже не метод, а объяснение самой системы психики." — the speaker immediately qualifies
  and develops the claim. The 0.54 s is a real pause, but the sentence is a tee-up, not a
  conclusion; what follows is the substance.
- **r08** (0.92 s, "abrupt"): ends on "— это просто сигнал в теле." → 0.92 s → "На самом
  деле там сидит внутри какой-то маленький ребенок…" — the "signal" formulation is followed
  by an explanation of what it signals. The pause is genuine; the thought is not finished.
- **r12** (0.50 s, "stream"): ends on "зайдет, а что-то вам не зайдет." → 0.50 s → "конечно
  же, максимальная работа с телом." — continues a list. Both the gap and the endpoint are
  similar to r01 (0.50 s, fine), but r12 lacks an opening hook that would make the list feel
  purposeful.

These cases illustrate a different problem: the sentence is grammatically terminal but
rhetorically a set-up. The gap is not the signal.

### Accepted reels with similar gaps

| ID  | gap   | next content |
|-----|-------|--------------|
| r01 | 0.50s | guest continues; but ending sentence is emotionally final ("ты кого-то любил…") |
| r02 | 0.46s | host speaks next ("как-то так. Здорово.") — natural interaction end |
| r04 | 0.72s | guest continues; ending sentence is self-contained |
| r06 | 1.18s | host speaks next — clear topic close |
| r09 | 0.48s | guest continues; but ending sentence has an arc resolution |

r02 and r06 end where the host takes over — a categorical boundary that the reviewer apparently
accepts as natural. r01 and r04 end with sentences the reviewer read as complete. r09 ends with
"вы меняетесь" — an action conclusion.

---

## 4. Does the complaint track the gap?

**Partially.** Two distinct sub-populations:

**Sub-population A — near-zero gap (< 0.15 s):** r03, r10, r11, r13 — all complained, all have
the speaker still talking within a Whisper-word-duration. A gap threshold would reliably flag
these. A rule of "do not end here unless the gap to the next word is ≥ 0.3 s" would have
extended all four.

**Sub-population B — moderate gap (0.3–1.0 s), still complained:** r07, r08, r12 — the pause
is real but the sentence is not the payoff; it is the premise of what follows. The gap is
diagnostic of a pause but not of a rhetorical endpoint. Gap alone cannot distinguish these from
accepted reels r01, r02, r09 which have similar or smaller gaps.

**The hypothesis is half-right.** For the near-zero-gap group the correlation is clean.
For the moderate-gap group it does not track — those complaints are about structure, not about
being cut off mid-breath.

---

## 5. Estimate: pause-based end rule at N = 0.6 / 1.0 / 1.5 s

Rule: "extend the clip end to the next sentence-terminal word followed by a gap of at least N
seconds, within a 60-second search window from the current end."

| ID  | cur_dur | N=0.6 s new_dur (+ext) | N=1.0 s new_dur (+ext) | N=1.5 s new_dur (+ext) |
|-----|---------|------------------------|------------------------|------------------------|
| r01 | 60.4s   | 83.6s (+23.2s)         | **no pause**           | **no pause**           |
| r02 | 40.6s   | 56.8s (+16.2s)         | 56.8s (+16.2s)         | 56.8s (+16.2s)         |
| r03 | 34.4s   | 50.9s (+16.5s)         | 50.9s (+16.5s)         | **no pause**           |
| r04 | 72.2s   | 87.1s (+14.9s)         | 87.1s (+14.9s)         | **no pause**           |
| r05 | 22.0s   | **no pause**           | **no pause**           | **no pause**           |
| r06 | 64.4s   | 77.5s (+13.2s)         | 77.5s (+13.2s)         | 77.5s (+13.2s)         |
| r07 | 33.1s   | 56.5s (+23.4s)         | 56.5s (+23.4s)         | 56.5s (+23.4s)         |
| r08 | 68.5s   | 95.9s (+27.5s)         | 109.3s (+40.8s)        | **no pause**           |
| r09 | 30.1s   | 61.9s (+31.8s)         | 61.9s (+31.8s)         | 61.9s (+31.8s)         |
| r10 | 68.1s   | 80.9s (+12.8s)         | 80.9s (+12.8s)         | 80.9s (+12.8s)         |
| r11 | 52.7s   | 84.5s (+31.8s)         | 100.4s (+47.8s)        | **no pause**           |
| r12 | 35.1s   | 52.8s (+17.8s)         | 71.6s (+36.5s)         | 71.6s (+36.5s)         |
| r13 | 29.1s   | 44.7s (+15.6s)         | 72.3s (+43.3s)         | 72.3s (+43.3s)         |
| r14 | 38.7s   | 79.6s (+40.9s)         | **no pause**           | **no pause**           |

**Reels exceeding 180 s:** none at any threshold.

**Reels with no qualifying pause within 60 s:**
- N=0.6 s: 1 reel (r05)
- N=1.0 s: 3 reels (r01, r05, r14)
- N=1.5 s: 7 reels (r01, r03, r04, r05, r08, r11, r14)

**Cost summary:**

N=0.6 s extends every reel between 13 and 41 seconds. Several already-fine reels (r01, r06, r09)
would grow significantly without the reviewer having asked for it. The rule is blind to whether
the extension adds narrative value — it simply hunts for the next breath. r01 (fine at 60s) would
become 83s; r09 (fine at 30s) would become 62s; r14 (fine at 39s) would become 80s.

N=1.0 s is more selective on which pauses qualify, but the extensions are larger when a pause is
found: r11 grows from 53s to 100s, r13 from 29s to 72s. Three reels get no pause and fall back
to the current sentence-end rule.

N=1.5 s is too strict — half the reels fall back, including the three most complained about
(r03 at N=1.5 gets no pause; r08 at N=1.5 gets no pause).

---

## 6. Conclusion

**The gap hypothesis explains four of the seven complaints** (r03, r10, r11, r13 — all near-zero
gap, all still-talking). A rule requiring a minimum gap before ending would fix these without
false positives in the non-complained group (no accepted reel has gap < 0.15 s).

**Three complaints are not gap-driven** (r07, r08, r12). r07 and r08 have the sentence as a
tee-up for the punchline that follows; the punchline is what the reviewer missed. r12 is a
"stream" problem — the clip is mid-list with no arc; a longer end would not fix it.

**A pause-based end rule at N=0.6 s is technically viable** (coverage: 13/14 reels find a pause
within 60 s; no result exceeds 180 s). The cost is large across-the-board extension: every
already-accepted reel also extends by 13–41 s, many of which the reviewer had not asked to be
longer. The rule would need to be a **fallback** or **a raising floor** (only extend if the
current gap is below a threshold), not a blanket replacement.

**The root problem for r07/r08 is different in kind:** the current sentence-selection criterion
("end at the last sentence within the explicit `e:` bound") picks grammatically terminal sentences
that are rhetorically mid-thought. The fix there is either a different sentence-ranking criterion
(prefer sentences that close a thought rather than open one) or reviewer guidance to pick a
different `e:`.

**Recommended next step (if any):** implement a minimum-gap guard as a soft constraint — if the
chosen sentence end has gap < 0.15 s, scan forward for the next sentence end with gap ≥ 0.3 s
within a short window (e.g. 20 s), and prefer it. This fixes the near-zero-gap group without
inflating already-acceptable clips.
