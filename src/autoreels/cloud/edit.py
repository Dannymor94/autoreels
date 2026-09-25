"""Deterministic sub-clip editing for the manual/edit path (Parts 2-3).

Judgement stays in the review markers (s:/e:); given the transcript words everything here is
deterministic. Sentence bounds shape the overall [start, end] span; filler removal then cuts the
span into an ordered list of models.Segment windows (gaps = removed filler / shortened pauses).
"""
from __future__ import annotations

from autoreels.core.models import Segment

_TERM = ".?!…"
_CLAUSE_PUNCT = ",.?!…—–:;"      # a standalone filler may sit against one of these
_STRIP = "—–.,!?…\"'»«()[]:;- \t"


def _clean(word: str) -> str:
    """Lowercase token stripped of surrounding punctuation/dashes (matches select._first_word_clean)."""
    return word.strip().strip(_STRIP).lower()


def words_in_span(words, start: float, end: float) -> list:
    """Words whose start falls in [start, end) — same convention as subtitles.words_in_window."""
    return [w for w in words if start <= w.t0 < end]


def _ends_terminal(word) -> bool:
    tok = word.word.rstrip("»\"')]")
    return bool(tok) and tok[-1] in _TERM


def split_sentences(words: list) -> list[list]:
    """Split words into sentences at terminal punctuation (.?!…), continuous across the input.

    Each sentence is a non-empty list of Word. The SAME split is used at review export and at
    apply, so a review's s:/e: index exactly the sentences the reviewer counted (numbering runs
    continuously across a merge — pass the words of the whole merged span).
    """
    out: list[list] = []
    cur: list = []
    for w in words:
        cur.append(w)
        if _ends_terminal(w):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _filler_token_set(filler_words) -> set[str]:
    """Every individual word appearing in the filler list (so multi-word 'как бы' → {'как','бы'})."""
    return {_clean(tok) for phrase in filler_words for tok in phrase.split() if _clean(tok)}


def _pure_wind_down(sentence: list, fillers: set[str], wd_norm: set[str]) -> bool:
    """True if the sentence is nothing but fillers, or (fillers dropped) equals a wind-down phrase."""
    toks = [_clean(w.word) for w in sentence]
    meaningful = [t for t in toks if t and t not in fillers]
    return not meaningful or " ".join(meaningful) in wd_norm


def default_end_sentence(sentences: list[list], wind_down_phrases, filler_words) -> int:
    """0-based index of the LAST sentence to keep: drop trailing PURE wind-down sentences only.

    Conservative on purpose — it never drops real content, only trailing sentences that are nothing
    but fillers or a listed wind-down phrase ('да', 'вот', 'как-то так'). A trailing fragment that
    lacks terminal punctuation (speech cut mid-thought) is left for the snap stage to resolve, not
    collapsed here. Never drops below the first sentence."""
    fillers = _filler_token_set(filler_words)
    wd_norm = set()
    for p in wind_down_phrases:
        toks = [_clean(t) for t in p.split()]
        wd_norm.add(" ".join(t for t in toks if t and t not in fillers))
    j = len(sentences) - 1
    while j > 0 and _pure_wind_down(sentences[j], fillers, wd_norm):
        j -= 1
    return j


def sentence_bounds(words: list, start: float, end: float, *, s: int | None = None,
                    e: int | None = None, wind_down_phrases=(), filler_words=()) -> tuple[float, float, bool, str]:
    """Resolve [start, end] to sentence edges. Returns (new_start, new_end, explicit_start, note).

    Explicit s/e (a human choice) win and bypass the defaults for that edge; out-of-range values
    are clamped and noted. Defaults: start is left unchanged (the dangling-start repair owns the
    default start); end drops trailing pure wind-down sentences (default tight ending).
    """
    sents = split_sentences(words_in_span(words, start, end))
    if not sents:
        return start, end, s is not None, ""
    new_start, new_end = start, end
    notes: list[str] = []

    if s is not None:
        i = max(1, min(s, len(sents))) - 1
        new_start = sents[i][0].t0
        if s != i + 1:
            notes.append(f"s:{s}→{i + 1} (clamped)")
    if e is not None:
        j = max(1, min(e, len(sents))) - 1
        new_end = sents[j][-1].t1
        if e != j + 1:
            notes.append(f"e:{e}→{j + 1} (clamped)")
    else:
        j = default_end_sentence(sents, wind_down_phrases, filler_words)
        if j < len(sents) - 1:
            new_end = sents[j][-1].t1
            notes.append(f"end −{len(sents) - 1 - j} wind-down sentence(s)")
    return new_start, new_end, s is not None, "; ".join(notes)


# --------------------------------------------------------------------------- filler removal

def _boundary_before(ws: list, i: int, pause_sec: float) -> bool:
    """Clause edge to the LEFT of word i: block start, previous token ends with clause punctuation,
    or a pause ≥ pause_sec precedes it."""
    if i == 0:
        return True
    if ws[i - 1].word.strip()[-1:] in _CLAUSE_PUNCT:
        return True
    return ws[i].t0 - ws[i - 1].t1 >= pause_sec


def _boundary_after(ws: list, j: int, pause_sec: float) -> bool:
    """Clause edge to the RIGHT of word j: block end, this token ends with clause punctuation, or a
    pause ≥ pause_sec follows it."""
    if j == len(ws) - 1:
        return True
    if ws[j].word.strip()[-1:] in _CLAUSE_PUNCT:
        return True
    return ws[j + 1].t0 - ws[j].t1 >= pause_sec


def _apply_cuts(start: float, end: float, cuts: list[tuple[float, float]],
                budget: float) -> tuple[list[Segment], float, int]:
    """Clip/merge cut intervals, accept left-to-right up to `budget` seconds removed, return the
    kept-window complement as Segments. Fewer than 2 segments → caller keeps a single span."""
    norm = sorted((max(a, start), min(b, end)) for a, b in cuts)
    merged: list[list[float]] = []
    for a, b in norm:
        if b - a <= 1e-3:
            continue
        if merged and a <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    accepted: list[list[float]] = []
    removed = 0.0
    for a, b in merged:
        d = b - a
        if removed + d > budget + 1e-6:
            continue                          # past the cap → skip (deterministic: earliest kept)
        accepted.append([a, b])
        removed += d
    if not accepted:
        return [], 0.0, 0
    segs: list[Segment] = []
    cur = start
    for a, b in accepted:
        if a > cur + 1e-3:
            segs.append(Segment(start=cur, end=a))
        cur = b
    if end > cur + 1e-3:
        segs.append(Segment(start=cur, end=end))
    return segs, removed, len(accepted)


def remove_fillers(words: list, start: float, end: float, *, filler_words, pause_shorten_sec: float,
                   pause_residual_sec: float, max_removed_share: float) -> tuple[list[Segment], float, int]:
    """Cut standalone fillers, immediate word repetitions and over-long pauses out of [start, end].

    Returns (segments, removed_sec, cut_count). Rules:
      - a filler phrase is cut only when it stands at a clause edge on BOTH sides (block edge,
        adjacent punctuation, or a pause ≥ pause_shorten_sec) — never mid-phrase where dropping it
        changes meaning; the filler and the silence up to the next word go;
      - an immediate repetition ("я я") drops the first occurrence up to the second's start;
      - a pause longer than pause_shorten_sec is shortened to pause_residual_sec (not removed
        entirely — speech keeps breathing).
    Total removal is capped at max_removed_share·span; cuts past the cap are skipped. Empty or a
    single kept window → [] (the caller keeps the reel as one span).
    """
    span = end - start
    ws = words_in_span(words, start, end)
    n = len(ws)
    if n < 2 or span <= 0:
        return [], 0.0, 0
    clean = [_clean(w.word) for w in ws]
    phrases = [tuple(_clean(t) for t in p.split()) for p in filler_words]
    phrases = [p for p in phrases if all(p)]
    cuts: list[tuple[float, float]] = []

    # 1. standalone filler phrases at clause edges
    # i == 0 is skipped: the clip's opening word is the first word of its first sentence (chosen by
    # s:N or the default start) — never cut it, even if it reads as a filler.
    i = 1
    while i < n:
        hit = 0
        for ph in phrases:
            L = len(ph)
            if L and tuple(clean[i:i + L]) == ph and _boundary_before(ws, i, pause_shorten_sec) \
                    and _boundary_after(ws, i + L - 1, pause_shorten_sec):
                hit = L
                break
        if hit:
            b = ws[i + hit].t0 if i + hit < n else ws[i + hit - 1].t1
            cuts.append((ws[i].t0, b))
            i += hit
        else:
            i += 1

    # 2. immediate word repetitions — drop the first occurrence
    for k in range(n - 1):
        if clean[k] and clean[k] == clean[k + 1]:
            cuts.append((ws[k].t0, ws[k + 1].t0))

    # 3. over-long pauses — shorten to the residual
    for k in range(n - 1):
        if ws[k + 1].t0 - ws[k].t1 > pause_shorten_sec:
            cuts.append((ws[k].t1 + pause_residual_sec, ws[k + 1].t0))

    return _apply_cuts(start, end, cuts, max_removed_share * span)


# --------------------------------------------------------------------------- manual sentence exclusion

def exclude_sentences(
    words: list, reel_start: float, reel_end: float,
    exclude_1based, all_sents: list,
) -> tuple[list, float, float, list[int], list[int], str]:
    """Cut specific sentences (1-based in all_sents) out of [reel_start, reel_end].

    Sentences outside [reel_start, reel_end] are returned as out_of_span and ignored.
    Leading/trailing excluded sentences collapse into a bound movement rather than a zero-length
    window.

    Returns (segs, new_start, new_end, applied_1based, out_of_span_1based, note).
    segs is empty when only bounds moved (no interior gaps needed).
    new_end < new_start signals "everything excluded" (caller must refuse and skip the reel).
    """
    eps = 1e-3
    in_span_set = {
        k for k, s in enumerate(all_sents)
        if s and s[0].t0 >= reel_start - eps and s[-1].t1 <= reel_end + eps
    }
    applied_0: list[int] = []
    out_of_span_1: list[int] = []
    for n1 in sorted({int(n) for n in exclude_1based}):
        k = n1 - 1
        if k < 0 or k >= len(all_sents) or k not in in_span_set:
            out_of_span_1.append(n1)
        else:
            applied_0.append(k)
    if not applied_0:
        return [], reel_start, reel_end, [], out_of_span_1, ""
    applied_set = set(applied_0)
    if applied_set >= in_span_set:  # everything excluded — sentinel
        return [], reel_start, reel_start - 1.0, [k + 1 for k in sorted(applied_set)], out_of_span_1, "all excluded"
    in_span_sorted = sorted(in_span_set)
    first_kept = next(k for k in in_span_sorted if k not in applied_set)
    last_kept = next(k for k in reversed(in_span_sorted) if k not in applied_set)
    head_ex = [k for k in in_span_sorted if k < first_kept]
    tail_ex = [k for k in in_span_sorted if k > last_kept]
    notes: list[str] = []
    new_start = all_sents[first_kept][0].t0 if head_ex else reel_start
    new_end = all_sents[last_kept][-1].t1 if tail_ex else reel_end
    if head_ex:
        notes.append(f"x:{','.join(str(k+1) for k in head_ex)} → s:{first_kept+1}")
    if tail_ex:
        notes.append(f"x:{','.join(str(k+1) for k in tail_ex)} → e:{last_kept+1}")
    # Middle gaps: build merged cut intervals for consecutive excluded sentences
    cuts: list[tuple[float, float]] = []
    cut_start: float | None = None
    cut_end: float | None = None
    for k in in_span_sorted:
        if k == first_kept or k == last_kept:
            if cut_start is not None:
                cuts.append((cut_start, cut_end))   # type: ignore[arg-type]
                cut_start = cut_end = None
            continue
        if k < first_kept or k > last_kept:
            continue
        s = all_sents[k]
        if k in applied_set:
            if cut_start is None:
                cut_start = s[0].t0
            cut_end = s[-1].t1
        else:
            if cut_start is not None:
                cuts.append((cut_start, cut_end))   # type: ignore[arg-type]
                cut_start = cut_end = None
    if cut_start is not None:
        cuts.append((cut_start, cut_end))            # type: ignore[arg-type]
    if not cuts:
        return [], new_start, new_end, [k + 1 for k in sorted(applied_set)], out_of_span_1, "; ".join(notes)
    segs: list[Segment] = []
    cur = new_start
    for a, b in cuts:
        if a > cur + eps:
            segs.append(Segment(start=cur, end=a))
        cur = b
    if new_end > cur + eps:
        segs.append(Segment(start=cur, end=new_end))
    return segs, new_start, new_end, [k + 1 for k in sorted(applied_set)], out_of_span_1, "; ".join(notes)
