"""M50: montage — one clip from pieces of different blocks of a source (docs/REEL_SPEC.md §8).

A review line plays sentences of ONE block group. A montage line names pieces anywhere in the
source and the plan joins them, so a good reel can be built from a lecture that never says it in
one stretch:

    M 85 | 13.2-6 41.1-4 | h:41.3 | c:13.4 | k:41.2=слово | o:41.2@года=3 ГОДА | f:0 | t: Заголовок | d: Подпись

* `M` (optionally with a label: `M2`) and a score (0–100, `@1.1` speed allowed, no merge markers);
* pieces `B.S-E` / `B.S` — block B of the review numbering, its sentences S..E in that block's own
  numbering (the [k] the review shows). Pieces play in the order written, which must be the source
  order (stage 1); two pieces never share a sentence;
* `h:B.N` (`!`/`-` as on a review line) — cold open from any block; `c:B.N,…` close shot;
  `k:B.N=word,…;B.N=…` keywords; `f:0|1`; `t:` title; `d:` caption — as on a review line;
* `o:B.N=Текст; B.N@слово=Текст` (M55) — a callout: the text in big letters for a moment, from the
  start of sentence B.N (or from the word `слово` in it). Ends at `|` or at the end of the line.

The line starts with a letter, so every existing reader of review lines (apply, arl label --check,
the review sheet) skips it. This module only parses and maps a line to the plan's terms: one
sentence list (each block used once, in source order), the played sentences, and the sentences
that start a new piece (`breaks`: the plan cuts there and keeps a natural pause). How the seams
feel is reported by `seam_report` — never fixed by code (a manual choice is not revised).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Sequence

_LINE_RE = re.compile(r"^M(\d*)\s+(\S+)\s*(.*)$")
_PIECE_RE = re.compile(r"^(\d+)\.(\d+)(?:-(\d+))?$")
_REF_RE = re.compile(r"^(\d+)\.(\d+)$")


@dataclass(frozen=True)
class Piece:
    block: int
    s: int
    e: int

    def __str__(self) -> str:
        return f"{self.block}.{self.s}" + (f"-{self.e}" if self.e != self.s else "")


@dataclass
class MontageEntry:
    label: str
    lineno: int
    raw: str
    score: int
    speed: float | None
    pieces: tuple[Piece, ...]
    hook: tuple[int, int] | None = None
    hook_keep: bool = False
    hook_remove: bool = False
    close: tuple[tuple[int, int], ...] = ()
    keys: tuple[tuple[tuple[int, int], tuple[str, ...]], ...] = ()
    filler: bool | None = None
    title: str | None = None
    description: str | None = None
    callouts: tuple[tuple[tuple[int, int], str | None, str], ...] = ()   # (B.N, word or None, text)


def _parse_callouts(val: str) -> tuple[list[tuple[tuple[int, int], str | None, str]], list[str]]:
    """`B.N=Текст; B.N@слово=Текст` → [((B, N), word|None, text)], errors."""
    out, bad = [], []
    for part in val.split(";"):
        part = part.strip()
        if not part:
            continue
        ref_s, eq, text = part.partition("=")
        ref_s, _, word = ref_s.partition("@")
        r = _ref(ref_s)
        text = text.strip()
        if r is None or not eq or not text:
            bad.append(f"o:{part} — expected o:B.N=text or o:B.N@word=text")
        else:
            out.append((r, word.strip().lower() or None, text))
    return out, bad


def is_montage_line(line: str) -> bool:
    s = line.strip()
    return bool(_LINE_RE.match(s))


def _ref(tok: str) -> tuple[int, int] | None:
    m = _REF_RE.match(tok.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_montage(text: str) -> tuple[list[MontageEntry], list[tuple[int, str]]]:
    """Every montage line of a draft → entries; malformed ones → (line number, message)."""
    from autoreels.cloud.blocks import _parse_score_markers
    entries: list[MontageEntry] = []
    errors: list[tuple[int, str]] = []
    labels: set[str] = set()
    auto = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        m = _LINE_RE.match(line)
        if not m:
            continue
        auto += 1
        label = f"M{m.group(1) or auto}"
        if label in labels:
            errors.append((lineno, f"{label}: label used twice"))
            continue
        labels.add(label)
        score, fwd, back, speed, err = _parse_score_markers(m.group(2))
        if err or score is None:
            errors.append((lineno, f"{label}: {err or 'no score'}"))
            continue
        if fwd or back:
            errors.append((lineno, f"{label}: merge markers (+/-) mean nothing on a montage line"))
            continue
        rest = m.group(3)
        description = title = None
        md = re.search(r"(?:^|[|\s])d:\s*(.*)$", rest)
        if md:
            description = md.group(1).strip() or None
            rest = rest[:md.start()].rstrip("| \t")      # the separator left by d: removal
        mt = re.search(r"(?:^|[|\s])t:\s*(.*)$", rest)
        if mt:
            title = mt.group(1).strip() or None
            rest = rest[:mt.start()]
        e = MontageEntry(label=label, lineno=lineno, raw=line, score=score, speed=speed, pieces=(),
                         title=title, description=description)
        pieces: list[Piece] = []
        bad: list[str] = []
        mo = re.search(r"(?:^|[|\s])o:\s*([^|]*)", rest)
        if mo:
            co, cbad = _parse_callouts(mo.group(1))
            e.callouts = tuple(co)
            bad.extend(cbad)
            rest = rest[:mo.start()] + " " + rest[mo.end():]
        for tok in rest.replace("|", " ").split():
            pm = _PIECE_RE.match(tok)
            if pm:
                b, s0 = int(pm.group(1)), int(pm.group(2))
                s1 = int(pm.group(3)) if pm.group(3) else s0
                if s1 < s0:
                    bad.append(f"piece {tok}: end before start")
                else:
                    pieces.append(Piece(b, s0, s1))
                continue
            key, _, val = tok.partition(":")
            if key == "h" and val:
                mode = val[-1] if val[-1] in "!-" else ""
                r = _ref(val[:-1] if mode else val)
                if r is None:
                    bad.append(f"h:{val} — expected h:B.N")
                else:
                    e.hook, e.hook_keep, e.hook_remove = r, mode == "!", mode == "-"
            elif key == "c" and val:
                refs = [_ref(x) for x in val.split(",") if x]
                if any(r is None for r in refs):
                    bad.append(f"c:{val} — expected c:B.N,B.N")
                else:
                    e.close = tuple(refs)
            elif key == "k" and val:
                ks = []
                for part in val.split(";"):
                    ref_s, _, words = part.partition("=")
                    r = _ref(ref_s)
                    ws = tuple(w.strip().lower() for w in words.split(",") if w.strip())
                    if r is None or not ws:
                        bad.append(f"k:{part} — expected k:B.N=word,…")
                    else:
                        ks.append((r, ws))
                e.keys = tuple(ks)
            elif key == "f" and val in ("0", "1"):
                e.filler = val == "1"
            else:
                bad.append(f"unrecognised «{tok}»")
        if not pieces:
            bad.append("no pieces (B.S-E)")
        if bad:
            errors.extend((lineno, f"{label}: {b}") for b in bad)
            continue
        e.pieces = tuple(pieces)
        entries.append(e)
    return entries, errors


@dataclass
class MontageBuild:
    sentences: list                     # one numbering: the used blocks' sentences, source order
    play: list[int]                     # played sentence numbers, piece order
    breaks: list[int]                   # sentence numbers starting pieces 2…n
    pieces: list[tuple[int, int]]       # (first, last) sentence number of each piece
    hook: int | None = None
    close: list[int] = field(default_factory=list)
    keys: list[tuple[int, tuple[str, ...]]] = field(default_factory=list)
    callouts: list[tuple[int, str | None, str]] = field(default_factory=list)   # (sentence no, word, text)
    errors: list[str] = field(default_factory=list)


def build_montage(entry: MontageEntry, blocks: dict, block_sentences: Callable[[object], list]) -> MontageBuild:
    """Map a montage line to one sentence numbering. `blocks`: review number → block (the blocks
    apply may use); `block_sentences(block)` → that block's sentences in the review numbering."""
    out = MontageBuild(sentences=[], play=[], breaks=[], pieces=[])
    used = {p.block for p in entry.pieces} | ({entry.hook[0]} if entry.hook else set())
    missing = sorted(b for b in used if b not in blocks)
    if missing:
        out.errors.append(f"block {', '.join(map(str, missing))} is not in the review numbering "
                          f"(1-{max(blocks) if blocks else 0}, filtered blocks excluded)")
        return out
    offset: dict[int, int] = {}
    count: dict[int, int] = {}
    for b in sorted(used):
        offset[b] = len(out.sentences)
        sents = block_sentences(blocks[b])
        count[b] = len(sents)
        out.sentences.extend(sents)

    def glob(b: int, n: int, what: str) -> int | None:
        if b not in offset:
            out.errors.append(f"{what} {b}.{n}: block {b} has no piece in this montage")
            return None
        if not 1 <= n <= count[b]:
            out.errors.append(f"{what} {b}.{n}: block {b} has sentences 1-{count[b]}")
            return None
        return offset[b] + n

    seen: set[int] = set()
    for p in entry.pieces:
        a, z = glob(p.block, p.s, "piece"), glob(p.block, p.e, "piece")
        if a is None or z is None:
            continue
        rng = list(range(a, z + 1))
        if seen & set(rng):
            out.errors.append(f"piece {p} repeats a sentence of an earlier piece")
            continue
        if out.pieces:
            prev_last = out.sentences[out.pieces[-1][1] - 1]
            if out.sentences[a - 1][0].t0 <= prev_last[-1].t0:
                out.errors.append(f"piece {p} plays before the piece written ahead of it in the source — "
                                  f"pieces go in source order (the hook h: can come from anywhere)")
                continue
            out.breaks.append(a)
        seen.update(rng)
        out.pieces.append((a, z))
        out.play.extend(rng)
    if entry.hook:
        out.hook = glob(*entry.hook, "h:")
    for r in entry.close:
        g = glob(*r, "c:")
        if g is not None:
            out.close.append(g)
    for r, ws in entry.keys:
        g = glob(*r, "k:")
        if g is not None:
            out.keys.append((g, ws))
    for r, word, text in entry.callouts:
        g = glob(*r, "o:")
        if g is None:
            continue
        if g not in out.play:
            out.errors.append(f"o:{r[0]}.{r[1]} — the sentence is not played in this montage")
        elif word and not any(_norm(w.word) == word for w in out.sentences[g - 1]):
            out.errors.append(f"o:{r[0]}.{r[1]}@{word} — no such word in the sentence")
        else:
            out.callouts.append((g, word, text))
    return out


def _norm(word: str) -> str:
    return "".join(c for c in word.lower() if c.isalnum() or c in "%-")


_NUM_RE = re.compile(r"\d")


def callout_times(build: MontageBuild, subtitles: Sequence, *, numbers: bool = False,
                  numbers_max: int = 3, gap_sec: float = 8.0) -> list[dict]:
    """Callouts of a built montage as [{"t": source seconds, "text": …}], in time order.

    Explicit `o:` callouts start at their sentence (or its word). Times come from the clip's own
    subtitle words (the plan's aligned words) — the first one at/after the sentence start, or the
    matching word — falling back to the transcript time. `numbers=True` adds a callout for every
    played word with a digit (with the next word when it is a short word: «3 года», «80%»), at
    most `numbers_max`, never within `gap_sec` of another callout."""
    subs = sorted(subtitles, key=lambda w: w.t0)

    def at(sent, word):
        lo, hi = sent[0].t0 - 0.5, sent[-1].t1 + 0.5
        cands = [w for w in subs if lo <= w.t0 <= hi]
        if word:
            for w in cands:
                if _norm(w.word) == word:
                    return w.t0
            for w in sent:
                if _norm(w.word) == word:
                    return w.t0
        for w in cands:
            if w.t0 >= sent[0].t0 - 0.3:
                return w.t0
        return sent[0].t0

    out = [{"t": round(at(build.sentences[g - 1], word), 3), "text": text} for g, word, text in build.callouts]
    if numbers:
        added = 0
        played = [w for g in build.play for w in build.sentences[g - 1]]
        for i, w in enumerate(played):
            if added >= numbers_max:
                break
            if not _NUM_RE.search(w.word):
                continue
            t = at([w], _norm(w.word))
            if any(abs(t - c["t"]) < gap_sec for c in out):
                continue
            text = w.word.strip(".,!?;:…—–")
            nxt = played[i + 1].word.strip(".,!?;:…—–") if i + 1 < len(played) else ""
            if nxt.isalpha() and len(nxt) <= 10 and not text.endswith("%"):
                text = f"{text} {nxt}"
            out.append({"t": round(t, 3), "text": text})
            added += 1
    return sorted(out, key=lambda c: c["t"])


@dataclass(frozen=True)
class SeamParams:
    piece_min_sec: float = 6.0
    seams_per_min_max: float = 3.0
    pace_ratio_max: float = 1.35
    seam_jump_warn: float = 3.0
    loudness_diff_db: float = 4.0
    pitch_diff_st: float = 3.0
    side_sec: float = 4.0


def _alnum(word) -> bool:
    return any(c.isalnum() for c in word.word)


def seam_report(plan, build: MontageBuild, entry: MontageEntry, params: SeamParams = SeamParams(), *,
                tone: Callable | None = None, jump: Callable[[float, float], float] | None = None,
                weak_start_words=frozenset(), voice: Callable | None = None,
                marks: list | None = None) -> tuple[list[str], list[str]]:
    """(plan lines, warnings) about the seams between pieces — what makes a montage feel smooth or
    jumpy: piece length, seams per minute, the pause heard at a seam, the picture jump (arl motion),
    the speech rate on both sides, a piece that ends with the voice up (↗: the seam sounds like an
    interruption) or starts on a word pointing back («И», «Это» — to something that was skipped),
    and — with `voice` ((a, b) → object with level_db, pitch_st; local/voice.meter) — loudness and
    pitch of the last / first side_sec of played speech on each side.
    Reported only; the montage is built exactly as written."""
    times = plan._times
    sents = build.sentences
    lines: list[str] = []
    warns: list[str] = []
    played = set()
    for w in plan.body:
        played.update(w.sentences)

    def span(a: int, z: int) -> tuple[float, float]:
        ws = [x for n in range(a, z + 1) if n in played for x in sents[n - 1]]
        if not ws:
            return 0.0, 0.0
        return times.audible(ws[0])[0], times.audible(ws[-1])[1]

    def pace(a: int, z: int) -> float | None:
        ws = [x for n in range(a, z + 1) if n in played for x in sents[n - 1] if _alnum(x)]
        t0, t1 = span(a, z)
        return len(ws) / (t1 - t0) if ws and t1 - t0 > 1.0 else None

    total = sum(w.played for w in plan.body)
    n_seams = len(build.pieces) - 1
    lines.append(f"montage {entry.label}: {len(build.pieces)} pieces "
                 f"{' '.join(str(p) for p in entry.pieces)}, {n_seams} seam(s), {total:.1f}s")
    allowed = params.seams_per_min_max * total / 60.0
    if n_seams > max(1.0, allowed) + 1e-9:
        warns.append(f"{n_seams} seams in {total:.0f}s — more than {params.seams_per_min_max:g} per minute: "
                     f"the clip may feel like constant jumping")
    weak = frozenset(weak_start_words)
    paces = [pace(a, z) for a, z in build.pieces]
    for k, (a, z) in enumerate(build.pieces):
        t0, t1 = span(a, z)
        if t1 - t0 < params.piece_min_sec:
            warns.append(f"piece {entry.pieces[k]} is {t1 - t0:.1f}s (< {params.piece_min_sec:g}s): "
                         f"too short to settle into")
    for k in range(1, len(build.pieces)):
        pa, pb = entry.pieces[k - 1], entry.pieces[k]
        b0 = build.pieces[k][0]
        wb = next((i for i, w in enumerate(plan.body) if w.sentences and w.sentences[0] == b0), None)
        if wb is None or wb == 0:
            lines.append(f"seam {k}  {pa}→{pb}  played through (no silence between them)")
            continue
        left, right = plan.body[wb - 1], plan.body[wb]
        last = sents[left.sentences[-1] - 1][-1]
        first = sents[right.sentences[0] - 1][0]
        heard = (left.end - times.audible(last)[1]) + (times.audible(first)[0] - right.start)
        parts = [f"skips {right.start - left.end:.1f}s", f"pause {heard:.2f}s"]
        name = f"seam {k} ({pa}→{pb})"
        gap = right.start - left.end
        ru = [f"пропущено {gap:.0f} с" if gap >= 0 else f"назад на {-gap:.0f} с", f"пауза {heard:.2f} с"]
        ru_w: list[str] = []
        if jump is not None:
            j = jump(left.end, right.start)
            parts.append(f"picture jump {j:.1f}×")
            ru.append(f"скачок картинки {j:.1f}×")
            if j > params.seam_jump_warn:
                ru_w.append(f"картинка скачет: {j:.1f}× обычного движения — поза или свет другие")
                warns.append(f"{name}: picture jump {j:.1f}× typical motion (> {params.seam_jump_warn:g}) — "
                             f"pose or light differs; the shot change only partly hides it")
        p0, p1 = paces[k - 1], paces[k]
        if p0 and p1:
            parts.append(f"pace {p0:.1f}→{p1:.1f} w/s")
            ru.append(f"темп {p0:.1f}→{p1:.1f} сл/с")
            if max(p0, p1) / min(p0, p1) > params.pace_ratio_max:
                ru_w.append(f"темп речи меняется: {p0:.1f} → {p1:.1f} слов/с")
                warns.append(f"{name}: speech rate {p0:.1f} → {p1:.1f} words/s — the voice changes tempo at the seam")
        if voice is not None:
            va = voice(max(left.start, left.end - params.side_sec), left.end)
            vb = voice(right.start, min(right.end, right.start + params.side_sec))
            if va.level_db is not None and vb.level_db is not None:
                d = vb.level_db - va.level_db
                parts.append(f"loudness {va.level_db:.0f}→{vb.level_db:.0f} dB")
                ru.append(f"громкость {d:+.1f} дБ")
                if abs(d) > params.loudness_diff_db:
                    ru_w.append(f"голос {'громче' if d > 0 else 'тише'} на {abs(d):.1f} дБ — слышно")
                    warns.append(f"{name}: the voice gets {'louder' if d > 0 else 'quieter'} by {abs(d):.1f} dB "
                                 f"(> {params.loudness_diff_db:g}) — the jump is heard")
            if va.pitch_st is not None and vb.pitch_st is not None:
                d = vb.pitch_st - va.pitch_st
                parts.append(f"pitch {va.pitch_st:+.1f}→{vb.pitch_st:+.1f} st")
                ru.append(f"высота голоса {d:+.1f} пт")
                if abs(d) > params.pitch_diff_st:
                    ru_w.append(f"голос {'выше' if d > 0 else 'ниже'} на {abs(d):.1f} полутона — другое настроение")
                    warns.append(f"{name}: the voice sits {'higher' if d > 0 else 'lower'} by {abs(d):.1f} semitones "
                                 f"(> {params.pitch_diff_st:g}) — a different mood on each side")
        t = tone(last) if tone is not None else None
        if t is not None:
            parts.append(f"end {t[0]}")
            ru.append({"final": "фраза закончена", "open": "голос вверх ↗", "unsure": "интонация неясна"}.get(t[0], t[0]))
        lines.append(f"seam {k}  {pa}→{pb}  " + ", ".join(parts))
        if tone is not None:
            if t is not None and t[0] == "open":
                warns.append(f"{name}: piece {pa} ends with the voice up ({t[1]}) on «{last.word}» — "
                             f"the seam sounds like the speaker was cut off")
                ru_w.append(f"кусок кончается с голосом вверх на «{last.word}» — звучит как перебили")
        w0 = first.word.strip()
        if w0 and (w0[0].islower() or w0.strip(".,!?;:—–-«»\"'()…").lower() in weak):
            warns.append(f"{name}: piece {pb} starts on «{w0}» — it points back to what was skipped")
            ru_w.append(f"кусок начинается на «{w0}» — отсылает к пропущенному")
        if marks is not None:     # M53: for the review sheet — where in the clip to look, and why
            marks.append({"t": round(right.start, 3), "kind": "seam",
                          "text": f"стык {k} ({pa}→{pb}): " + ", ".join(ru), "warn": ru_w})
    return lines, warns
