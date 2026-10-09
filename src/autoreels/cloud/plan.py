"""Manual-path render plan — docs/REEL_SPEC.md §1–§4 as ONE pure function.

Why this module exists: on the human path a dozen stages (snap, padding, dangling repair, end
repair, filler cuts, seam refinement, tail air, two-shot passes …) each moved clip boundaries by
Whisper times, and each one's fix broke another. The reviewer's line already says exactly which
sentences play, in which order, which one is the hook and which ones get the close shot. This
module turns that into the final plan in one place:

* windows  = runs of consecutive played sentences; cut points come from the speech map
  (audible start/end of the boundary WORDS), never from Whisper times or time-based membership;
* shots    = cold open close; body starts wide; every seam flips; c: sentences close — nothing else;
* ending   = last word audible end + end_air_sec, never into the next speech onset;
* subtitles = exactly the words of the played sentences.

No ffmpeg, no config objects, no manifest I/O — numbers in, numbers out. Callers inject the speech
map (a dict as stored in transcripts/<stem>.speechmap.json) and, optionally, a next-speech-onset
function so render-time checks and the plan agree on what "next speech" is.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from autoreels.core.models import Segment, Word, make_segment

_EPS = 1e-3
_SUB_MARGIN = 0.05   # subtitle starts stay this far inside their window (> half a frame at 10+ fps)


@dataclass(frozen=True)
class ManualPlanParams:
    """Numbers from config (r0.yaml / render.yaml). Defaults mirror the shipped config."""

    seam_pad_sec: float = 0.04        # air kept at an internal seam, inside the silence between words
    end_air_sec: float = 0.30         # air after the last word (REEL_SPEC §4)
    onset_margin_sec: float = 0.06    # never closer than this to the next speech onset
    hook_replay_min_pos: float = 0.5  # hook replays in the body only from this body fraction on
    accent_min_sec: float = 3.0       # a close shot after a seam lasts at least this long …
    accent_max_sec: float = 8.0       # … and at most this long, then the window goes back to wide


@dataclass
class PlannedWindow:
    sentences: list[int]              # 1-based sentence numbers, in play order
    start: float                      # source seconds
    end: float
    shot: str                         # base shot of the window: "wide" | "close"
    close_intervals: list[list[float]] = field(default_factory=list)  # window-relative
    cold_open: bool = False

    @property
    def last_shot(self) -> str:
        if self.shot == "close":
            return "close"
        if self.close_intervals and self.close_intervals[-1][1] >= (self.end - self.start) - _EPS:
            return "close"
        return "wide"

    def segment(self) -> Segment:
        return make_segment(self.start, self.end).model_copy(update={
            "shot": self.shot, "close_intervals": [list(ci) for ci in self.close_intervals]})


@dataclass
class ManualPlan:
    windows: list[PlannedWindow]      # output order; the cold open (if any) first
    subtitles: list[Word]
    last_word: Word
    last_audible_end: float
    next_onset: float | None
    hook: int | None
    hook_replayed: bool | None
    warnings: list[str] = field(default_factory=list)

    @property
    def cold_open(self) -> PlannedWindow | None:
        return self.windows[0] if self.windows and self.windows[0].cold_open else None

    @property
    def body(self) -> list[PlannedWindow]:
        return [w for w in self.windows if not w.cold_open]

    @property
    def end(self) -> float:
        return self.body[-1].end

    @property
    def start(self) -> float:
        return self.body[0].start

    def shot_sequence(self) -> list[tuple[str, list[int]]]:
        """Shots in output order as (shot, sentences) — the format of the golden plan files."""
        out: list[tuple[str, list[int]]] = []
        for w in self.windows:
            out.extend(_window_shot_runs(w, self._sent_bounds.get(id(w), {})))
        return out

    # filled by build_manual_plan: per window {sentence: (rel_start, rel_end)}
    _sent_bounds: dict = field(default_factory=dict, repr=False)
    _times: "SpeechTimes | None" = field(default=None, repr=False)

    def describe(self, sentences: Sequence[Sequence[Word]]) -> list[str]:
        """Human-readable plan (printed at --apply so the plan is checked BEFORE any render)."""
        lines = []
        for w in self.windows:
            first = sentences[w.sentences[0] - 1]
            last = sentences[w.sentences[-1] - 1]
            tag = "cold open" if w.cold_open else "window"
            lines.append(
                f"{tag:9} s{_fmt_nums(w.sentences)}  {w.start:.3f}–{w.end:.3f}  "
                f"«{_txt(first)[:48]}» … «{_txt(last)[-48:]}»"
            )
        lines.append("shots     " + " → ".join(f"{s}[{_fmt_nums(n)}]" for s, n in self.shot_sequence()))
        air = self.end - self.last_audible_end
        lines.append(f"end       {self.end:.3f}  last word «{self.last_word.word}» audible end "
                     f"{self.last_audible_end:.3f}  air {air:.3f}s"
                     + (f"  next speech {self.next_onset:.3f}" if self.next_onset is not None else ""))
        if self.hook is not None:
            lines.append(f"hook      s{self.hook} replayed in body: {'yes' if self.hook_replayed else 'no'}")
        return lines


def _fmt_nums(nums: Sequence[int]) -> str:
    nums = list(nums)
    if not nums:
        return ""
    if len(nums) > 1 and nums == list(range(nums[0], nums[-1] + 1)):
        return f"{nums[0]}-{nums[-1]}"
    return ",".join(str(n) for n in nums)


def _txt(words: Sequence[Word]) -> str:
    return " ".join(w.word for w in words)


def _window_shot_runs(w: PlannedWindow, bounds: dict) -> list[tuple[str, list[int]]]:
    """Split a window's sentences into runs of equal shot (for shot_sequence). A sentence that a
    shot change splits (≥ 1 s or 30 % on each side) is listed in both runs, in time order."""
    runs: list[tuple[str, list[int]]] = []

    def put(shot, n):
        if runs and runs[-1][0] == shot:
            if runs[-1][1][-1] != n:
                runs[-1][1].append(n)
        else:
            runs.append((shot, [n]))

    for n in w.sentences:
        if w.shot == "close" or not bounds:
            put(w.shot, n)
            continue
        rs, re_ = bounds[n]
        ln = max(re_ - rs, 1e-6)
        cov = [(max(a, rs), min(b, re_)) for a, b in w.close_intervals if min(b, re_) > max(a, rs)]
        c_len = sum(b - a for a, b in cov)
        thr = min(1.0, 0.3 * ln)
        if c_len >= thr and ln - c_len >= thr:
            first_close = cov[0][0] <= rs + _EPS
            for shot in (("close", "wide") if first_close else ("wide", "close")):
                put(shot, n)
        else:
            put("close" if c_len > ln / 2 else "wide", n)
    return runs


_STOPS = set("тдкгпбцч")


def _ends_with_stop(word: str) -> bool:
    letters = [c for c in word.lower() if c.isalpha() and c not in "ьъ"]
    return bool(letters) and letters[-1] in _STOPS


class SpeechTimes:
    """Audible word times from the speech map, keyed like the rest of the code (round(t0*1000)).

    Falls back to Whisper t0/t1 when a word is missing from the map or its audible span is empty.
    Neighbours come from the full (credit-stripped) transcript word list, by position.

    Adjacent words whose map spans OVERLAP (Whisper stretched one word over the next) are resolved
    by the energy track (smap["intervals"]): the map snaps one of the two edges to an energy edge,
    and the silence touching that edge is the real gap between the words (see `pair`).
    """

    _NEAR = 0.10     # an energy silence at most this far from the overlap zone resolves it
    _TAIL_TOUCH = 0.01   # energy interval may start this close after the aligned word end
    _TAIL_MAX = 0.30     # a word's sound running on at most this long past its aligned end is its tail
    _CLOSURE_MAX = 0.12  # silence before a final stop's release burst …
    _BURST_MAX = 0.15    # … and the burst itself
    _ONSET_BACK = 0.04   # untranscribed speech glued to a word onset gives this much back to the word

    def __init__(self, words: Sequence[Word], smap: dict | None, align: dict | None = None):
        self._words = list(words)
        self._pos = {round(w.t0 * 1000): i for i, w in enumerate(self._words)}
        self._smap = {}
        self._gaps: list[tuple[float, float]] = []
        if smap:
            for e in smap.get("words", []):
                self._smap[round(e["t0"] * 1000)] = e
            iv = sorted(smap.get("intervals") or [])
            self._gaps = [(iv[i][1], iv[i + 1][0]) for i in range(len(iv) - 1) if iv[i + 1][0] > iv[i][1]]
        self._gap_starts = [g[0] for g in self._gaps]
        self._iv = (smap or {}).get("intervals") or []
        # Forced alignment (local/align.py, transcripts/<stem>.align.json): word times from the
        # AUDIO plus untranscribed speech (fillers, «ммм», «ну») — preferred over the map when present.
        self._al: dict[int, tuple[float, float]] = {}
        self._untr: list[tuple[float, float]] = []
        if align:
            for e in align.get("words", []):
                if e.get("start") is not None and e.get("end") is not None and e["end"] > e["start"]:
                    self._al[round(e["t0"] * 1000)] = (float(e["start"]), float(e["end"]))
            self._untr = sorted((float(a), float(b)) for a, b in align.get("untranscribed", []) if b > a)
            self._absorb_word_tails()
            self._trim_untranscribed_before_onsets()
        self._untr_starts = [u[0] for u in self._untr]

    @property
    def aligned(self) -> bool:
        return bool(self._al)

    def _absorb_word_tails(self) -> None:
        """CTC alignment closes a word a little early (its last frames go to "blank"): the word
        really lasts until its sound stops. The aligned end is extended
          1. to the end of the energy interval it falls in, and then
          2. over one short sound after a short silence (a final stop's release burst, the
             «-ое» of «главное» after a dip),
        as long as the whole tail stays within _TAIL_MAX of the aligned end and before the next
        aligned word. Untranscribed speech the extension covers is dropped."""
        iv = sorted(tuple(x) for x in self._iv)
        starts = [a for a, _ in iv]
        keys = [round(w.t0 * 1000) for w in self._words]
        for n, k in enumerate(keys):
            if k not in self._al:
                continue
            s0, e0 = self._al[k]
            nxt = next((self._al[kk][0] for kk in keys[n + 1:n + 4] if kk in self._al), None)
            cap = e0 + self._TAIL_MAX if nxt is None else min(e0 + self._TAIL_MAX, nxt)
            j = bisect.bisect_right(starts, e0 + self._TAIL_TOUCH) - 1
            new_end, nj = e0, j + 1
            if j >= 0 and iv[j][1] > e0:                 # the aligned end lies inside a sound
                if iv[j][1] - e0 > self._TAIL_MAX:         # it runs on into the next speech
                    continue
                new_end = iv[j][1] if nxt is None else min(iv[j][1], nxt)
            if 0 <= nj < len(iv):                          # one short sound after a short silence
                ga, gb = iv[nj]
                if ga - new_end <= self._CLOSURE_MAX and gb - ga <= self._BURST_MAX and gb <= cap:
                    new_end = gb
            if new_end > e0:
                self._al[k] = (s0, new_end)
                self._untr = [(ua, ub) for ua, ub in self._untr if not (ua >= e0 - 1e-6 and ub <= new_end + 1e-6)]
                self._untr = [((new_end if ua < new_end <= ub and ua >= e0 - 1e-6 else ua), ub)
                              for ua, ub in self._untr]

    def _trim_untranscribed_before_onsets(self) -> None:
        """CTC places a word onset a frame or two late; untranscribed speech glued to an onset
        gives those frames back to the word, so a window start keeps the word's first sound."""
        if not self._untr:
            return
        onsets = sorted(a for a, _ in self._al.values())
        out = []
        for a, b in self._untr:
            i = bisect.bisect_left(onsets, b - 0.01)
            if i < len(onsets) and abs(onsets[i] - b) <= 0.01:
                b = b - self._ONSET_BACK
            if b - a >= 0.05:
                out.append((a, b))
        self._untr = out

    def audible(self, w: Word) -> tuple[float, float]:
        k = round(w.t0 * 1000)
        if k in self._al:
            return self._al[k]
        e = self._smap.get(k)
        if e is not None:
            a, b = e.get("audible_start", w.t0), e.get("audible_end", w.t1)
            if b > a:
                return a, b
        return w.t0, max(w.t1, w.t0)

    def untranscribed_between(self, t0: float, t1: float) -> list[tuple[float, float]]:
        """Untranscribed speech spans overlapping (t0, t1)."""
        if not self._untr or t1 <= t0:
            return []
        i = bisect.bisect_left(self._untr_starts, t0) - 1
        out = []
        for a, b in self._untr[max(0, i):]:
            if a >= t1:
                break
            if b > t0:
                out.append((a, b))
        return out

    def prev(self, w: Word) -> Word | None:
        i = self._pos.get(round(w.t0 * 1000))
        return self._words[i - 1] if i is not None and i > 0 else None

    def next(self, w: Word) -> Word | None:
        i = self._pos.get(round(w.t0 * 1000))
        return self._words[i + 1] if i is not None and i + 1 < len(self._words) else None

    def pair(self, left: Word, right: Word) -> tuple[float, float]:
        """(audible end of `left`, audible start of `right`) for two ADJACENT words.

        Map spans that do not overlap are returned as they are. Overlapping spans (Whisper stretched
        one word over the other) are resolved by the energy track: the silence inside the two-word
        span that lies closest to the overlap zone [right onset, left end], at most _NEAR away, is
        the real gap between the words. With no such silence the speech is continuous and the
        overlap stays (callers then cut at the right word's onset — the only place left).
        """
        as_l, ae_l = self.audible(left)
        as_r, ae_r = self.audible(right)
        if as_r >= ae_l or not self._gaps:
            return ae_l, as_r
        if round(left.t0 * 1000) in self._al and round(right.t0 * 1000) in self._al:
            return ae_l, as_r                     # aligned to the audio: no guessing from energy
        lo = bisect.bisect_right(self._gap_starts, as_l)
        best, best_d = None, None
        for gs, ge in self._gaps[lo:]:
            if gs >= ae_r:
                break
            if ge >= ae_r:
                continue
            # distance from the silence to the overlap zone (0 = touches or lies inside it)
            d = max(0.0, as_r - ge, gs - ae_l)
            if d <= self._NEAR and (best_d is None or d < best_d):
                best, best_d = (gs, ge), d
        return best if best is not None else (ae_l, as_r)

    def span(self, w: Word) -> tuple[float, float]:
        """Audible span of `w` with both neighbour overlaps resolved by `pair`."""
        a, b = self.audible(w)
        p, n = self.prev(w), self.next(w)
        if p is not None:
            a = self.pair(p, w)[1]
        if n is not None:
            b = self.pair(w, n)[0]
        return a, b

    def word_cut_by(self, t: float, tol: float = _EPS) -> Word | None:
        """The word a cut at source time `t` would split, or None.

        A cut is fine in the zone between two adjacent words (their silence, or — in continuous
        speech with no silence — anywhere in their overlap). Anything else strictly inside a word's
        audible span splits that word.
        """
        for w in self._words:
            if w.t0 > t + 2.0:
                break
            if w.t1 < t - 2.0:
                continue
            a, b = self.span(w)
            if not (a + tol < t < b - tol):
                continue
            p, n = self.prev(w), self.next(w)
            zones = []
            if p is not None:
                zones.append(sorted(self.pair(p, w)))
            if n is not None:
                zones.append(sorted(self.pair(w, n)))
            if any(z0 - tol <= t <= z1 + tol for z0, z1 in zones):
                continue
            return w
        return None


def _boundary(times: SpeechTimes, left: Word, right: Word) -> float:
    """Cut point between two ADJACENT words: middle of the silence; if they overlap with no
    silence, the right word's onset (never inside the right word)."""
    ae_l, as_r = times.pair(left, right)
    return (ae_l + as_r) / 2 if as_r > ae_l else as_r


def _cut_between(left_end: float, right_start: float) -> float:
    return (left_end + right_start) / 2 if right_start > left_end else right_start


def _speech_before(times: SpeechTimes, first: Word) -> tuple[float | None, float]:
    """(end of the speech heard right before `first`, onset of `first`). Speech = the previous
    word or any untranscribed speech (fillers) between them."""
    prev = times.prev(first)
    if prev is not None:
        left, as_f = times.pair(prev, first)
    else:
        left, as_f = None, times.audible(first)[0]
    lo = left if left is not None else as_f - 5.0
    for a, b in times.untranscribed_between(lo, as_f):
        left = min(b, as_f) if left is None else max(left, min(b, as_f))
    return left, as_f


def _speech_after(times: SpeechTimes, last: Word) -> tuple[float, float | None]:
    """(end of `last`, onset of the next speech: next word or untranscribed speech)."""
    nxt = times.next(last)
    if nxt is not None:
        ae_l, right = times.pair(last, nxt)
    else:
        ae_l, right = times.audible(last)[1], None
    hi = right if right is not None else ae_l + 5.0
    for a, b in times.untranscribed_between(ae_l, hi):
        a = max(a, ae_l)
        right = a if right is None else min(right, a)
    return ae_l, right


def _window_start(times: SpeechTimes, first: Word, pad: float) -> float:
    left, as_f = _speech_before(times, first)
    start = as_f - pad
    if left is not None:
        start = max(start, _cut_between(left, as_f))
    return min(start, as_f)


def _window_end(times: SpeechTimes, last: Word, pad: float) -> float:
    ae_l, right = _speech_after(times, last)
    end = ae_l + pad
    if right is not None:
        end = min(end, _cut_between(ae_l, right))
    return max(end, ae_l)


def _merge_intervals(iv: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1] + _EPS:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _accent_end(times: SpeechTimes, sentences, w: "PlannedWindow", bounds: dict,
                params: "ManualPlanParams") -> float:
    """Window-relative end of the seam accent (close shot): the end of the first sentence(s) once
    at least accent_min_sec has played; a first sentence longer than accent_max_sec is cut at a
    word boundary inside it (after a comma when there is one)."""
    lo, hi = params.accent_min_sec, params.accent_max_sec
    for n in w.sentences:
        end_n = bounds[n][1]
        if end_n < lo:
            continue
        if end_n <= hi:
            return end_n
        s_words = sentences[n - 1]
        cands = []
        for a, b in zip(s_words, s_words[1:]):
            t = _boundary(times, a, b) - w.start
            if lo <= t <= hi:
                cands.append((a.word.rstrip().endswith((",", ";", ":", "—")), t))
        if cands:
            commas = [t for c, t in cands if c]
            return commas[-1] if commas else cands[-1][1]
        return hi
    return min(hi, w.end - w.start)


def _group_windows(play: Sequence[int]) -> list[list[int]]:
    wins: list[list[int]] = []
    for n in play:
        if wins and n == wins[-1][-1] + 1:
            wins[-1].append(n)
        else:
            wins.append([n])
    return wins


def build_manual_plan(
    sentences: Sequence[Sequence[Word]],
    play: Iterable[int],
    *,
    words: Sequence[Word],
    smap: dict | None,
    params: ManualPlanParams = ManualPlanParams(),
    hook: int | None = None,
    hook_mode: str | None = None,          # None | "!" (always replay) | "-" (never replay)
    close: Iterable[int] = (),
    next_onset: Callable[[Word], float | None] | None = None,
    source_duration: float | None = None,
    align: dict | None = None,
    tone: Callable[[Word], tuple[str, str] | None] | None = None,
) -> ManualPlan:
    """Plan one manual clip. `sentences` is the review numbering (merge_group_sentences output);
    `play` the body sentence numbers in play order (s:..e: minus x:, or the beat order).
    `tone`: word → ("final" | "open" | "unsure", description) from local/prosody.py; when given,
    an ending whose voice does not finish is reported (the reviewer's e: is never moved).
    """
    n_sent = len(sentences)
    play = [int(n) for n in play]
    warnings: list[str] = []
    for n in play + ([hook] if hook else []) + list(close):
        if not 1 <= n <= n_sent:
            raise ValueError(f"sentence {n} out of range 1-{n_sent}")
    if not play:
        raise ValueError("nothing to play")
    times = SpeechTimes(words, smap, align)
    pad = params.seam_pad_sec

    def body_windows(order: list[int], note: bool = False) -> list[PlannedWindow]:
        out: list[PlannedWindow] = []
        for run in _group_windows(order):
            first = sentences[run[0] - 1][0]
            last = sentences[run[-1] - 1][-1]
            w = PlannedWindow(sentences=list(run), start=_window_start(times, first, pad),
                              end=_window_end(times, last, pad), shot="wide")
            prev = out[-1] if out else None
            # A forward seam whose next window starts before the previous one ends has no silence
            # to cut in: the skipped sentence is a Whisper duplicate overlapping its neighbours.
            # Cutting there would replay audio — the speech is continuous, so play it through.
            if prev is not None and run[0] > prev.sentences[-1] and w.start < prev.end:
                if note:
                    skipped = list(range(prev.sentences[-1] + 1, run[0]))
                    warnings.append(
                        f"x:{_fmt_nums(skipped)} overlaps its neighbours in time (Whisper duplicate) — "
                        f"no silence to cut, played through")
                prev.sentences.extend(run)
                prev.end = max(prev.end, w.end)
                continue
            out.append(w)
        return out

    # §2 hook replay by position (in the body as it would play with the hook kept).
    hook_replayed: bool | None = None
    if hook is not None:
        if hook not in play:
            hook_replayed = False
        elif hook_mode == "!":
            hook_replayed = True
        elif hook_mode == "-":
            hook_replayed = False
        else:
            wins = body_windows(play)
            total = sum(w.end - w.start for w in wins)
            acc = 0.0
            pos = 0.0
            for w in wins:
                if hook in w.sentences:
                    hs = times.audible(sentences[hook - 1][0])[0]
                    pos = acc + max(0.0, hs - w.start)
                    break
                acc += w.end - w.start
            hook_replayed = total > 0 and pos / total >= params.hook_replay_min_pos
        if not hook_replayed and hook in play:
            play = [n for n in play if n != hook]
            if not play:
                raise ValueError("hook removal leaves nothing to play")

    body = body_windows(play, note=True)

    # §4 ending: last word audible end + air, never into the next speech.
    last_word = sentences[play[-1] - 1][-1]
    ae_last, onset = _speech_after(times, last_word)
    if next_onset is not None:            # e.g. untranscribed speech the transcript does not have
        o2 = next_onset(last_word)
        if o2 is not None:
            onset = o2 if onset is None else min(onset, o2)
    end = ae_last + params.end_air_sec
    if onset is not None:
        end = min(end, onset - params.onset_margin_sec)
    if end < ae_last:
        warnings.append(f"no room after last word «{last_word.word}» (next speech at {onset:.3f}) — "
                        f"clip ends at its audible end")
        end = ae_last
    if source_duration is not None:
        end = min(end, source_duration)
    body[-1].end = max(end, body[-1].start + _EPS)
    if tone is not None:
        warnings.extend(_ending_tone_warnings(sentences, play[-1], tone))

    windows: list[PlannedWindow] = []
    if hook is not None:
        hs = sentences[hook - 1]
        windows.append(PlannedWindow(sentences=[hook], start=_window_start(times, hs[0], pad),
                                     end=_window_end(times, hs[-1], pad), shot="close",
                                     cold_open=True))
    windows.extend(body)

    # §3 shots: cold open close; body starts wide; every seam flips; c: close; nothing else.
    close_set = set(close)
    sent_bounds: dict = {}
    prev_shot: str | None = "close" if hook is not None else None
    for w in windows:
        bounds = {}
        dur = w.end - w.start
        for i, n in enumerate(w.sentences):
            s_words = sentences[n - 1]
            rs = 0.0 if i == 0 else _boundary(times, sentences[w.sentences[i - 1] - 1][-1], s_words[0]) - w.start
            re_ = dur if i == len(w.sentences) - 1 else _boundary(times, s_words[-1], sentences[w.sentences[i + 1] - 1][0]) - w.start
            bounds[n] = (max(0.0, rs), min(dur, re_))
        sent_bounds[id(w)] = bounds
        if not w.cold_open:
            flip = "wide" if prev_shot in (None, "close") else "close"
            ci: list[list[float]] = [list(bounds[n]) for n in w.sentences if n in close_set]
            if flip == "close":
                # Seam accent: the close shot masks the seam, then the window goes back to wide.
                t = dur if dur <= params.accent_max_sec else _accent_end(times, sentences, w, bounds, params)
                ci.append([0.0, t])
            ci = _merge_intervals(ci)
            if len(ci) == 1 and ci[0][0] < _EPS and ci[0][1] > dur - _EPS:
                w.shot, w.close_intervals = "close", []
            else:
                w.shot, w.close_intervals = "wide", ci
        prev_shot = w.last_shot

    # §1/§6 subtitles: exactly the words of the played sentences, times kept inside their window.
    subs: dict[int, Word] = {}
    for w in windows:
        for n in w.sentences:
            for word in sentences[n - 1]:
                key = round(word.t0 * 1000)
                if key in subs:
                    continue
                # Keep every word start at least _SUB_MARGIN inside its window: render snaps window
                # edges to the frame grid (up to half a frame) and drops words that start outside.
                m = min(_SUB_MARGIN, (w.end - w.start) / 2)
                t0 = min(max(word.t0, w.start + m), w.end - m)
                t1 = min(max(word.t1, t0), w.end)
                subs[key] = word if (t0 == word.t0 and t1 == word.t1) else \
                    word.model_copy(update={"t0": t0, "t1": t1})
    subtitles = sorted(subs.values(), key=lambda x: x.t0)

    for n in close_set:
        if not any(n in w.sentences for w in windows):
            warnings.append(f"c:{n} is not played — ignored")

    plan = ManualPlan(windows=windows, subtitles=subtitles, last_word=last_word,
                      last_audible_end=ae_last, next_onset=onset, hook=hook,
                      hook_replayed=hook_replayed, warnings=warnings)
    plan._sent_bounds = sent_bounds
    plan._times = times
    return plan


def _ending_tone_warnings(sentences: Sequence[Sequence[Word]], last: int,
                          tone: Callable[[Word], tuple[str, str] | None]) -> list[str]:
    """REEL_SPEC §4.3: the clip should end where the VOICE ends, not only the text. An open or
    unclear final tone is reported with the nearest sentences (same numbering) that end finished."""
    r = tone(sentences[last - 1][-1])
    if r is None or r[0] == "final":
        return []
    kind, desc = r
    fin = [n for n in range(1, len(sentences) + 1)
           if n != last and (tone(sentences[n - 1][-1]) or ("",))[0] == "final"]
    near = sorted(fin, key=lambda n: (abs(n - last), n))[:3]
    alt = ", ".join(f"s{n} «{sentences[n - 1][-1].word}»" for n in sorted(near)) or "none in this block"
    what = "sounds unfinished — the speaker goes on" if kind == "open" else "intonation unclear"
    return [f"ending intonation {desc}: «{sentences[last - 1][-1].word}» {what}; "
            f"finished sentence ends nearby: {alt}"]


def load_alignment(path, source_sha256: str | None = None) -> dict | None:
    """transcripts/<stem>.align.json (local/align.py) or None when missing / for another source."""
    import json
    from pathlib import Path
    p = Path(path)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("version") != 1:
        return None
    if source_sha256 and data.get("source_sha256") and data["source_sha256"] != source_sha256:
        return None
    return data
