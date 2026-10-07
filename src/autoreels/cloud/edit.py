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


def strip_credit_words(words: list, patterns: list[str]) -> list:
    """Remove Whisper credit-hallucination words from a word list.

    Scans left-to-right; any run of consecutive words whose normalised tokens match a pattern
    phrase is dropped. Normalisation: lowercase + strip _STRIP punctuation. Sentence boundaries
    are not affected — the surrounding words keep their timestamps.
    """
    if not patterns or not words:
        return words
    pat_tokens = [[_clean(t) for t in p.split()] for p in patterns]
    result: list = []
    i = 0
    while i < len(words):
        matched = False
        for ptoks in pat_tokens:
            n = len(ptoks)
            if i + n <= len(words) and [_clean(words[j].word) for j in range(i, i + n)] == ptoks:
                i += n
                matched = True
                break
        if not matched:
            result.append(words[i])
            i += 1
    return result


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


def merge_group_sentences(group_blocks, tx_words: list) -> list[list]:
    """Sentence list for a group of blocks that will be merged into one reel.

    When block[i]'s last sentence is incomplete (no terminal punctuation), it is joined
    with block[i+1]'s first sentence into one sentence — matching the reviewer's manual
    count: the export shows …→ on a sentence and the reviewer merges it with the next
    block's first sentence to get one numbered sentence at the junction.

    For a single-block group returns the plain split. For multi-block groups the junction
    sentence correctly spans the overlap boundary without re-splitting the whole merged
    span (which would consume the next block's first sentence via Whisper overlap words).
    """
    result: list[list] = []
    for b in group_blocks:
        b_sents = split_sentences(words_in_span(tx_words, b.start, b.end))
        if not b_sents:
            continue
        if result and not _ends_terminal(result[-1][-1]):
            # Incomplete last sentence of the previous block → merge with first of this one.
            result[-1] = result[-1] + b_sents[0]
            result.extend(b_sents[1:])
        else:
            result.extend(b_sents)
    return result


def sentence_bounds(words: list, start: float, end: float, *, s: int | None = None,
                    e: int | None = None, wind_down_phrases=(), filler_words=(),
                    sents: list | None = None) -> tuple[float, float, bool, str]:
    """Resolve [start, end] to sentence edges. Returns (new_start, new_end, explicit_start, note).

    Explicit s/e (a human choice) win and bypass the defaults for that edge; out-of-range values
    are clamped and noted. Defaults: start is left unchanged (the dangling-start repair owns the
    default start); end drops trailing pure wind-down sentences (default tight ending).

    sents: pre-computed sentence list (from merge_group_sentences for a merged group); when None
    the sentences are computed from words_in_span(words, start, end).
    """
    if sents is None:
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


def _refine_seams(
    segs: list[Segment],
    words: list,
    smap_words: "list | None",
    seam_pad: float,
    fps: float = 30.0,
) -> list[Segment]:
    """Refine internal seam endpoints using speech map audible word boundaries.

    A-side end  = audible_end(last kept word before cut) + seam_pad,
                  capped at audible_start(first cut word).
    B-side start = audible_start(first kept word after cut) - seam_pad,
                  floored at audible_end(last cut word).
    Gap < 2 output frames → cut in the middle. Overlapping Whisper duplicates removed first.
    """
    if not smap_words or len(segs) < 2:
        return segs
    from autoreels.cloud.snap import _dedup_overlapping_words
    frame_sec = 1.0 / fps
    smap_lk = {round(w["t0"] * 1000): w for w in smap_words}

    def _ae(w) -> float:
        e = smap_lk.get(round(w.t0 * 1000))
        return e["audible_end"] if e else w.t1

    def _as(w) -> float:
        e = smap_lk.get(round(w.t0 * 1000))
        return e["audible_start"] if e else w.t0

    ws = _dedup_overlapping_words(list(words)) if words else []
    result = list(segs)
    for i in range(len(result) - 1):
        a = result[i].end
        b = result[i + 1].start
        if a >= b - 1e-4:
            # Non-chronological beat seam (B-side start <= A-side end): refining would produce
            # a midpoint outside both segments' source spans.  Leave beat gap as-is.
            continue
        last_a    = next((w for w in reversed(ws) if w.t0 < a - 1e-4), None)
        first_cut = next((w for w in ws if w.t0 >= a - 1e-4), None)
        last_cut  = next((w for w in reversed(ws) if w.t0 < b - 1e-4), None)
        first_b   = next((w for w in ws if w.t0 >= b - 1e-4), None)
        ae_la = _ae(last_a) if last_a else a
        new_a = (ae_la + seam_pad) if last_a else a
        if first_cut:
            # Cap only when the cut word genuinely starts after the kept word ends;
            # skip the cap when they overlap (Whisper artifact) to avoid pulling
            # the seam back inside the kept word's audible span.
            cap_a = _as(first_cut)
            if cap_a >= ae_la - 1e-4:
                new_a = min(new_a, cap_a)
        ae_lc = _ae(last_cut) if last_cut else b
        new_b = (_as(first_b) - seam_pad) if first_b else b
        if last_cut:
            as_fb = _as(first_b) if first_b else b
            if ae_lc <= as_fb + 1e-4:
                new_b = max(new_b, ae_lc)
        # Push new_a past any smap word in the cut zone whose audible span still contains new_a.
        # Condition: t0 >= a (word is in or near the cut zone) OR audible_start >= ae_la-seam_pad
        # (the original threshold for deduped-away words).  OR ensures both cases are covered:
        # — deduped words with as ≥ ae_la-seam_pad (original case, kept for compatibility)
        # — cut-zone words whose as falls slightly below ae_la-seam_pad due to Whisper chunk
        #   overlap (their t0 = a exactly but as < threshold; the old check skipped them, leaving
        #   new_a inside the word's audible span).
        for _sw in smap_words:
            _as_, _ae_ = _sw.get("audible_start", 0), _sw.get("audible_end", 0)
            if (_ae_ > _as_ and (_as_ >= ae_la - seam_pad or _sw.get("t0", 0) >= a - 1e-4)
                    and _as_ < new_a < _ae_):
                new_a = _ae_ + seam_pad
        # Pull new_b before any smap word in the cut zone (audible_end <= ae_lc + seam_pad).
        ae_lc2 = ae_lc if last_cut else b
        for _sw in reversed(smap_words):
            _as_, _ae_ = _sw.get("audible_start", 0), _sw.get("audible_end", 0)
            if _ae_ > _as_ and _ae_ <= ae_lc2 + seam_pad and _as_ < new_b < _ae_:
                new_b = _as_ - seam_pad
        if new_a > new_b:
            new_a = new_b = (new_a + new_b) / 2
        elif new_b - new_a < 2 * frame_sec:
            mid = (new_a + new_b) / 2
            new_a = new_b = mid
        result[i] = result[i].model_copy(update={"end": new_a})
        result[i + 1] = result[i + 1].model_copy(update={"start": new_b})
    return result
