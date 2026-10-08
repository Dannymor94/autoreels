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
    """Split a window's sentences into runs of equal shot (for shot_sequence)."""
    runs: list[tuple[str, list[int]]] = []
    for n in w.sentences:
        if w.shot == "close" or not bounds:
            shot = w.shot
        else:
            rs, re_ = bounds[n]
            mid = (rs + re_) / 2
            shot = "close" if any(a - _EPS <= mid <= b + _EPS for a, b in w.close_intervals) else "wide"
        if runs and runs[-1][0] == shot:
            runs[-1][1].append(n)
        else:
            runs.append((shot, [n]))
    return runs


class SpeechTimes:
    """Audible word times from the speech map, keyed like the rest of the code (round(t0*1000)).

    Falls back to Whisper t0/t1 when a word is missing from the map or its audible span is empty.
    Neighbours come from the full (credit-stripped) transcript word list, by position.

    Adjacent words whose map spans OVERLAP (Whisper stretched one word over the next) are resolved
    by the energy track (smap["intervals"]): the map snaps one of the two edges to an energy edge,
    and the silence touching that edge is the real gap between the words (see `pair`).
    """

    _NEAR = 0.10     # an energy silence at most this far from the overlap zone resolves it

    def __init__(self, words: Sequence[Word], smap: dict | None):
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

    def audible(self, w: Word) -> tuple[float, float]:
        e = self._smap.get(round(w.t0 * 1000))
        if e is not None:
            a, b = e.get("audible_start", w.t0), e.get("audible_end", w.t1)
            if b > a:
                return a, b
        return w.t0, max(w.t1, w.t0)

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


def _window_start(times: SpeechTimes, first: Word, pad: float) -> float:
    prev = times.prev(first)
    as_f = times.pair(prev, first)[1] if prev is not None else times.audible(first)[0]
    start = as_f - pad
    if prev is not None:
        start = max(start, _boundary(times, prev, first))
    return min(start, as_f)


def _window_end(times: SpeechTimes, last: Word, pad: float) -> float:
    nxt = times.next(last)
    if nxt is None:
        return times.audible(last)[1] + pad
    ae_l, as_n = times.pair(last, nxt)
    end = min(ae_l + pad, (ae_l + as_n) / 2 if as_n > ae_l else ae_l)
    return max(end, ae_l)


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
) -> ManualPlan:
    """Plan one manual clip. `sentences` is the review numbering (merge_group_sentences output);
    `play` the body sentence numbers in play order (s:..e: minus x:, or the beat order).
    """
    n_sent = len(sentences)
    play = [int(n) for n in play]
    warnings: list[str] = []
    for n in play + ([hook] if hook else []) + list(close):
        if not 1 <= n <= n_sent:
            raise ValueError(f"sentence {n} out of range 1-{n_sent}")
    if not play:
        raise ValueError("nothing to play")
    times = SpeechTimes(words, smap)
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
    nxt = times.next(last_word)
    if nxt is not None:
        ae_last, onset = times.pair(last_word, nxt)
    else:
        ae_last, onset = times.audible(last_word)[1], None
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
            w.shot = "wide" if prev_shot in (None, "close") else "close"
            if prev_shot is None:
                w.shot = "wide"
            if w.shot == "wide":
                ci: list[list[float]] = []
                for n in w.sentences:
                    if n in close_set:
                        a, b = bounds[n]
                        if ci and abs(ci[-1][1] - a) < _EPS:
                            ci[-1][1] = b
                        else:
                            ci.append([a, b])
                if len(ci) == 1 and ci[0][0] < _EPS and ci[0][1] > dur - _EPS:
                    w.shot, ci = "close", []
                w.close_intervals = ci
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
