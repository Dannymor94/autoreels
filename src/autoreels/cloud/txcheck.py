"""M57: a check of a transcript for Whisper inventions and holes (G5a: on IMG_6848 the Groq transcript
had «Субтитры создавал DimaTorzok» and «каждый из них влияет на результат по-своему» five times where
the speaker said something else, and ~1000 words fewer than a local Whisper).

Three signs, each only a pointer for the owner's ear — the code changes nothing:

* known  — phrases Whisper is known to invent from film subtitles («субтитры создавал», «продолжение
           следует», «спасибо за просмотр» …; config r0.yaml tx_check.known);
* repeat — the same run of `repeat_words`+ words in places at least `repeat_far_sec` apart (a speaker
           rarely repeats six words verbatim minutes later; Whisper repeats its inventions);
* sparse — sound without words: windows where the speech map hears at least `sparse_min_speech_sec`
           of speech but the transcript has fewer than `sparse_max_rate` words per second of it.

Pure: words (t0/t1/word) and the speech map's intervals in, a report dict out.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

KNOWN = (
    "субтитры создавал", "субтитры сделал", "субтитры делал", "субтитры подготовил", "редактор субтитров",
    "корректор а.", "продолжение следует", "спасибо за просмотр", "спасибо за внимание друзья",
    "подписывайтесь на канал", "ставьте лайки", "dimatorzok", "игорь негода",
)


@dataclass(frozen=True)
class TxCheckParams:
    repeat_words: int = 6
    repeat_far_sec: float = 60.0
    sparse_win_sec: float = 10.0
    sparse_min_speech_sec: float = 6.0
    sparse_max_rate: float = 0.8
    known: tuple[str, ...] = field(default=KNOWN)
    on_speech_sec: float = 2.0        # M60: speech heard around a flagged place → «на речи»
    sparse_suspicious_sec: float = 60.0   # M60: this much «sound without words» makes a transcript suspicious


def _norm(w: str) -> str:
    return "".join(c for c in w.lower().replace("ё", "е") if c.isalnum() or c == ".")


def _tokens(words) -> list[tuple[str, float]]:
    out = []
    for w in words:
        n = _norm(w.word).strip(".")
        if n:
            out.append((n, float(w.t0)))
    return out


def known_phrases(words, patterns: Sequence[str]) -> list[dict]:
    """Every place a known invention appears: {"t", "text"}."""
    toks = _tokens(words)
    text_tokens = [t for t, _ in toks]
    hits = []
    for pat in patterns:
        p = [_norm(x).strip(".") for x in pat.split()]
        p = [x for x in p if x]
        if not p:
            continue
        n = len(p)
        for i in range(len(text_tokens) - n + 1):
            window = text_tokens[i:i + n]
            if window[:-1] == p[:-1] and window[-1].startswith(p[-1]):
                hits.append({"t": round(toks[i][1], 2), "text": " ".join(w.word for w in _slice(words, toks, i, n + 2))})
    out: list[dict] = []
    for h in sorted(hits, key=lambda h: h["t"]):
        if not out or h["t"] - out[-1]["t"] > 3.0:              # one place, however many patterns match it
            out.append(h)
    return out


def _slice(words, toks, i, n):
    """The original words of token positions i..i+n (for display)."""
    t0 = toks[i][1]
    t1 = toks[min(i + n, len(toks)) - 1][1]
    return [w for w in words if t0 <= w.t0 <= t1]


def repeats(words, *, n: int = 6, far_sec: float = 60.0) -> list[dict]:
    """Runs of n+ identical words heard at least far_sec apart: {"text", "times"} — the run grown to
    its full length, every place it occurs (each place counted once)."""
    toks = _tokens(words)
    seq = [t for t, _ in toks]
    pos: dict[tuple, list[int]] = {}
    for i in range(len(seq) - n + 1):
        pos.setdefault(tuple(seq[i:i + n]), []).append(i)
    out: list[dict] = []
    covered: set[int] = set()
    for key, idx in pos.items():
        if len(idx) < 2 or idx[0] in covered:
            continue
        far = [idx[0]]
        for i in idx[1:]:
            if toks[i][1] - toks[far[-1]][1] >= far_sec:
                far.append(i)
        if len(far) < 2:
            continue
        # grow the run while every occurrence continues the same way
        ln = n
        while all(j + ln < len(seq) for j in far) and len({seq[j + ln] for j in far}) == 1:
            ln += 1
        for j in far:
            covered.update(range(j, j + ln))
        out.append({"text": " ".join(seq[far[0]:far[0] + ln]), "words": ln,
                    "times": [round(toks[j][1], 2) for j in far]})
    return sorted(out, key=lambda r: (-len(r["times"]), -r["words"], r["times"][0]))


def _speech_bins(intervals, end: float, bin_sec: float = 0.5) -> list[float]:
    """Seconds of speech in each bin_sec bin of [0, end)."""
    n = int(end / bin_sec) + 1
    bins = [0.0] * n
    for x, y in intervals:
        x, y = max(0.0, float(x)), min(float(y), end)
        k = int(x / bin_sec)
        while x < y and k < n:
            edge = min(y, (k + 1) * bin_sec)
            bins[k] += edge - x
            x = edge
            k += 1
    return bins


def sparse(words, intervals: Sequence[Sequence[float]], *, win: float = 10.0, min_speech: float = 6.0,
           max_rate: float = 0.8, end: float | None = None) -> list[dict]:
    """Stretches where the speech map hears speech but the transcript has few words:
    {"a", "b", "speech_sec", "words"} (overlapping windows merged)."""
    import bisect
    if not intervals:
        return []
    end = end if end is not None else max(float(b) for _, b in intervals)
    bin_sec = 0.5
    bins = _speech_bins(intervals, end, bin_sec)
    acc = [0.0]
    for v in bins:
        acc.append(acc[-1] + v)

    def speech(a, b):
        return acc[min(len(bins), int(round(b / bin_sec)))] - acc[min(len(bins), int(round(a / bin_sec)))]
    starts = sorted(float(w.t0) for w in words)

    def nwords(a, b):
        return bisect.bisect_left(starts, b) - bisect.bisect_left(starts, a)
    hot: list[list[float]] = []
    t, step = 0.0, win / 2
    while t < end:
        a, b = t, min(t + win, end)
        sp = speech(a, b)
        if sp >= min_speech and nwords(a, b) / sp < max_rate:
            if hot and a <= hot[-1][1]:
                hot[-1][1] = b
            else:
                hot.append([a, b])
        t += step
    return [{"a": round(a, 1), "b": round(b, 1), "speech_sec": round(speech(a, b), 1), "words": nwords(a, b)}
            for a, b in hot]


def check(words, intervals: Sequence[Sequence[float]] | None = None, p: TxCheckParams = TxCheckParams()) -> dict:
    """The report of one transcript: known / repeat / sparse lists and their counts."""
    rep = repeats(words, n=p.repeat_words, far_sec=p.repeat_far_sec)
    kn = known_phrases(words, p.known)
    sp = sparse(words, intervals or [], win=p.sparse_win_sec, min_speech=p.sparse_min_speech_sec,
                max_rate=p.sparse_max_rate)
    sparse_sec = round(sum(s["b"] - s["a"] for s in sp), 1)
    has_map = intervals is not None and len(intervals) > 0
    if has_map:
        # M60: an invention in silence (Whisper fills pauses with «Продолжение следует…») only leaks into
        # a clip that plays that pause; one ON speech hides what was said. Seconds of speech heard in
        # [t − 1, t + 4] decide (≥ on_speech_sec → on speech).
        end = max(float(b) for _, b in intervals)
        bins = _speech_bins(intervals, end + 5.0)
        acc = [0.0]
        for v in bins:
            acc.append(acc[-1] + v)

        def heard(t):
            i0 = min(len(bins), max(0, int((t - 1.0) / 0.5)))
            i1 = min(len(bins), max(i0, int((t + 4.0) / 0.5)))
            return acc[i1] - acc[i0]
        for h in kn:
            h["on_speech"] = heard(h["t"]) >= p.on_speech_sec
        for r in rep:
            r["on_speech"] = [heard(t) >= p.on_speech_sec for t in r["times"]]
    serious = [h for h in kn if h.get("on_speech", True)] + [r for r in rep if any(r.get("on_speech", [True]))]
    return {"words": len(words), "known": kn, "repeat": rep, "sparse": sp, "sparse_sec": sparse_sec,
            "speech_map": has_map, "serious": len(serious),
            "suspicious": bool(serious or sparse_sec >= p.sparse_suspicious_sec)}


def hit_times(report: dict) -> list[tuple[float, str]]:
    """(source second, short note) for every known / repeat place — for clip warnings."""
    out = [(h["t"], f"известная выдумка Whisper «{h['text']}»") for h in report.get("known", [])]
    for r in report.get("repeat", []):
        for t in r["times"]:
            out.append((t, f"фраза повторяется в {len(r['times'])} местах «{r['text']}» — возможна выдумка Whisper"))
    return sorted(out)


# ── M62: prompt leaks and a comparison of two transcripts ──────────────────────────────────────

def prompt_patterns(prompt: str, n: int = 5) -> list[str]:
    """Every run of n words of each prompt sentence (the whole sentence if shorter): Groq's
    initial_prompt leaks into the text in pieces («результат по-своему», «каждый из них влияет …»)."""
    import re as _re
    out: list[str] = []
    for sent in _re.split(r"(?<=[.!?])\s+", (prompt or "").strip()):
        toks = [t for t in (_norm(x).strip(".") for x in sent.split()) if t]
        if not toks:
            continue
        if len(toks) <= n:
            out.append(" ".join(toks))
        else:
            out += [" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)]
    return list(dict.fromkeys(out))


_TERMINAL = (".", "!", "?", "…")


def _sent_ends(words) -> float:
    """Sentence-ending marks per 100 words (punctuation the sentence split relies on)."""
    if not words:
        return 0.0
    ends = sum(1 for w in words if w.word.rstrip().endswith((".", "!", "?", "…")))
    return round(100.0 * ends / len(words), 1)


def compare_words(ref, other, *, show: int = 8) -> dict:
    """Two transcripts of one audio, word by word (case, ё and punctuation folded): matched words,
    words only in one of them, the share that differs (of the reference) and the longest
    disagreements with their times. M111: `sent_agree` — on the matched words, how many sentence ends
    of `ref` the other one has too (recall) and how many of its own are also in `ref` (precision)."""
    import difflib
    a = [(_norm(w.word).strip("."), w) for w in ref]
    b = [(_norm(w.word).strip("."), w) for w in other]
    a = [x for x in a if x[0]]
    b = [x for x in b if x[0]]
    sm = difflib.SequenceMatcher(None, [x[0] for x in a], [x[0] for x in b], autojunk=False)
    matched, only_a, only_b, spans = 0, 0, 0, []
    ends_ref = ends_other = ends_both = 0          # M111: sentence ends on the matched words
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            matched += i2 - i1
            for k in range(i2 - i1):
                er = a[i1 + k][1].word.rstrip().endswith(_TERMINAL)
                eo = b[j1 + k][1].word.rstrip().endswith(_TERMINAL)
                ends_ref += er
                ends_other += eo
                ends_both += er and eo
            continue
        only_a += i2 - i1
        only_b += j2 - j1
        t = a[i1][1].t0 if i1 < i2 else (b[j1][1].t0 if j1 < j2 else 0.0)
        spans.append({"t": round(t, 1), "kind": tag, "size": max(i2 - i1, j2 - j1),
                      "ref": " ".join(w.word for _, w in a[i1:i2])[:120],
                      "other": " ".join(w.word for _, w in b[j1:j2])[:120]})
    spans.sort(key=lambda s: -s["size"])
    return {"ref_words": len(a), "other_words": len(b), "matched": matched, "only_ref": only_a,
            "only_other": only_b, "differ": round(100.0 * (only_a + only_b) / max(1, len(a)), 1),
            "ref_sent_ends": _sent_ends(ref), "other_sent_ends": _sent_ends(other),
            "sent_agree": {"ref": ends_ref, "other": ends_other, "both": ends_both,
                           "recall": round(100.0 * ends_both / ends_ref, 1) if ends_ref else 0.0,
                           "precision": round(100.0 * ends_both / ends_other, 1) if ends_other else 0.0},
            "longest": spans[:show]}


# ── M64c: Groq's punctuation onto the local words ──────────────────────────────────────────────


def transfer_punctuation(target, ref) -> tuple[list, int]:
    """Sentence ends of `ref` (Groq: 13 per 100 words) onto the same words of `target` (whisper.cpp:
    9 per 100 — sentences too long to end a clip on). Words are matched in order (case, ё and
    punctuation folded); where a matched ref word ends a sentence and the target word does not, the
    target word gets the same mark and the next target word a capital letter. Words, times and
    everything outside the matched runs stay as they are (an invented Groq stretch matches nothing).
    Returns (words, marks added)."""
    import difflib
    a = [(_norm(w.word).strip("."), i) for i, w in enumerate(target)]
    b = [(_norm(w.word).strip("."), j) for j, w in enumerate(ref)]
    a = [x for x in a if x[0]]
    b = [x for x in b if x[0]]
    sm = difflib.SequenceMatcher(None, [x[0] for x in a], [x[0] for x in b], autojunk=False)
    out = list(target)
    added = 0
    cap: set[int] = set()
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            continue
        for k in range(i2 - i1):
            ti, rj = a[i1 + k][1], b[j1 + k][1]
            rw, tw = ref[rj].word.rstrip(), out[ti].word.rstrip()
            mark = next((m for m in _TERMINAL if rw.endswith(m)), None)
            if mark and not tw.endswith(_TERMINAL):
                out[ti] = out[ti].model_copy(update={"word": tw.rstrip(",;:—–-") + mark})
                added += 1
                cap.add(ti + 1)
    for ti in cap:
        if ti < len(out):
            w = out[ti].word
            lead = len(w) - len(w.lstrip("«\"'("))
            if lead < len(w) and w[lead].islower():
                out[ti] = out[ti].model_copy(update={"word": w[:lead] + w[lead].upper() + w[lead + 1:]})
    return out, added
