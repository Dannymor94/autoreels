"""Auto-labelling (`arl label`): a free LLM drafts the review lines, deterministic code checks them.

Why: labelling a 40-minute source by hand (or pasting the export into a chat) is the slowest step of
the manual path. The LLM proposes clips; it never decides alone (invariant 1):
  * it sees the review sentences of a few consecutive blocks with stable ids "B.S" (block B,
    sentence S as numbered in the review export) and the export's own markers (…→ unfinished
    text, ↗ voice stays up, ⏸ pauses);
  * it answers JSON: blocks, start/end ids, cuts, close shots, key words, title, caption, score;
  * code maps the ids to the review numbering (continuous across a `+` merge, a block's
    unfinished last sentence joined with the next block's first — edit.merge_group_sentences),
    checks the owner's rules (REEL_SPEC §1.7 start by voice, §4.5 end by voice, unfinished text,
    length, ids that exist, key words that are in their sentence) and asks once for a repair;
  * what still fails is written as a "#!" comment line with the reasons, an unanswered window as
    "# blocks …: no answer" — never dropped silently (invariant 11).
The output is a DRAFT review file: the owner edits it and applies it with --labeler auto.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Sequence

from autoreels.cloud.edit import _ends_terminal, merge_group_sentences, split_sentences, words_in_span
from autoreels.cloud.snap import is_complete_sentence


@dataclass(frozen=True)
class LabelParams:
    window_blocks: int = 4        # blocks per LLM request (Groq free tier: 6000 tokens/min)
    min_sec: float = 20.0         # played speech of a clip
    max_sec: float = 90.0
    max_clip_blocks: int = 3      # a review line merges at most 3 blocks ('++')
    title_max_chars: int = 60
    repair_rounds: int = 1
    pause_show_sec: float = 0.3
    pause_strong_sec: float = 1.5


@dataclass
class Sent:
    sid: str                      # "B.S"
    words: list
    complete: bool
    open_tone: bool
    pause_after: float | None     # gap to the next word of the transcript

    @property
    def dur(self) -> float:
        return max(0.0, self.words[-1].t1 - self.words[0].t0)

    @property
    def text(self) -> str:
        return " ".join(w.word for w in self.words)


@dataclass
class WBlock:
    seq: int                      # review number 1..N
    block: object                 # CandidateBlock
    sents: list[Sent]
    prev: Sent | None = None      # the transcript sentence just before the block (may be unfinished)


def norm_word(w: str) -> str:
    """The k: matching rule of --apply: case-insensitive, ё→е, punctuation stripped."""
    return w.lower().replace("ё", "е").strip(".,!?;:—–-\"'«»()[]…")


def build_wblocks(kept: Sequence, words: list, tone: Callable | None = None,
                  seqs: Sequence[int] | None = None) -> list[WBlock]:
    """Review sentences of every kept block, split exactly like the review export.
    `seqs`: review numbers of `kept` (default 1..N — the whole kept list)."""
    index = {id(w): i for i, w in enumerate(words)}
    out: list[WBlock] = []
    for seq, b in zip(seqs or range(1, len(kept) + 1), kept):
        sents = split_sentences(words_in_span(words, b.start, b.end))
        items: list[Sent] = []
        for k, s in enumerate(sents, 1):
            complete = is_complete_sentence(s)
            t = tone(s[-1]) if (tone is not None and complete) else None
            i = index.get(id(s[-1]))
            gap = (words[i + 1].t0 - s[-1].t1) if (i is not None and i + 1 < len(words)) else None
            items.append(Sent(f"{seq}.{k}", s, complete, bool(t and t[0] == "open"), gap))
        out.append(WBlock(seq, b, items, _prev_sentence(words, index, items[0].words[0], tone)
                          if items else None))
    return out


def _prev_sentence(words: list, index: dict, first, tone) -> Sent | None:
    """The words since the last sentence end before `first` (an unfinished tail stays unfinished)."""
    i = index.get(id(first))
    if not i:
        return None
    j = i - 1
    while j > 0 and not _ends_terminal(words[j - 1]):
        j -= 1
    ws = words[j:i]
    complete = is_complete_sentence(ws)
    t = tone(ws[-1]) if (tone is not None and complete) else None
    return Sent("prev", ws, complete, bool(t and t[0] == "open"), first.t0 - ws[-1].t1)



def windows(wblocks: Sequence[WBlock], size: int, max_clip_blocks: int = 3) -> list[list[WBlock]]:
    """Overlapping request windows: step = size − max_clip_blocks + 1, so every run of up to
    max_clip_blocks consecutive blocks lies whole inside at least one window (a thought spanning
    blocks is never seen cut in half only)."""
    size = max(1, size)
    step = max(1, size - max(1, max_clip_blocks) + 1)
    out: list[list[WBlock]] = []
    i = 0
    while i < len(wblocks):
        out.append(list(wblocks[i:i + size]))
        if i + size >= len(wblocks):
            break
        i += step
    return out


def render_window(win: Sequence[WBlock], p: LabelParams = LabelParams()) -> str:
    """The user message: one sentence per line, id first, then the export's markers."""
    lines: list[str] = []
    prev = win[0].prev if win else None
    if prev is not None:
        tail = " ".join(w.word for w in prev.words[-8:])
        mark = " …→" if not prev.complete else (" ↗" if prev.open_tone else "")
        lines.append(f"(sentence before block {win[0].seq}: «…{tail}»{mark})")
    for wb in win:
        lines.append(f"BLOCK {wb.seq} · {wb.block.end - wb.block.start:.1f} s")
        for s in wb.sents:
            mark = "" if s.complete else " …→"
            tail = " ↗" if s.open_tone else ""
            if s.pause_after is not None and s.pause_after >= p.pause_show_sec:
                tail += f" {'⏸⏸' if s.pause_after >= p.pause_strong_sec else '⏸'}{s.pause_after:.1f}"
            lines.append(f"{s.sid}{mark} ({s.dur:.1f}s) {s.text}{tail}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_answer(text: str) -> dict | None:
    """The JSON object of a model answer (reasoning tags and code fences removed), or None."""
    if not text:
        return None
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    t = re.sub(r"```(?:json)?", "", t)
    start = t.find("{")
    while start != -1:
        depth = 0
        for j in range(start, len(t)):
            if t[j] == "{":
                depth += 1
            elif t[j] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(t[start:j + 1])
                    except ValueError:
                        break
                    return obj if isinstance(obj, dict) and isinstance(obj.get("clips"), list) else None
        start = t.find("{", start + 1)
    return None


@dataclass
class Checked:
    line: str | None              # compact review line (None when the clip cannot be written at all)
    problems: list[str] = field(default_factory=list)
    blocks: tuple[int, ...] = ()
    played_sec: float = 0.0
    preview: str = ""


def _sid(x) -> str:
    return str(x).strip().rstrip(".")


def _clean_text(s, limit: int | None = None) -> str:
    s = " ".join(str(s or "").replace("|", "—").split())
    return s[:limit].rstrip() if limit else s


def check_clip(clip: dict, win: Sequence[WBlock], words: list,
               p: LabelParams = LabelParams()) -> Checked:
    """Map one proposed clip to a review line and list what breaks the owner's rules."""
    probs: list[str] = []
    by_seq = {wb.seq: wb for wb in win}
    try:
        blocks = [int(b) for b in clip.get("blocks") or []]
    except (TypeError, ValueError):
        return Checked(None, ["'blocks' must be a list of block numbers"])
    if not blocks:
        return Checked(None, ["'blocks' is empty"])
    if any(b not in by_seq for b in blocks):
        return Checked(None, [f"blocks {blocks}: only blocks {sorted(by_seq)} are in this request"])
    if blocks != list(range(blocks[0], blocks[0] + len(blocks))):
        return Checked(None, [f"blocks {blocks} are not consecutive"])
    if len(blocks) > p.max_clip_blocks:
        return Checked(None, [f"a clip joins at most {p.max_clip_blocks} blocks, got {len(blocks)}"])
    group = [by_seq[b] for b in blocks]
    order = [s for wb in group for s in wb.sents]
    pos = {s.sid: i for i, s in enumerate(order)}
    sid_start, sid_end = _sid(clip.get("start", "")), _sid(clip.get("end", ""))
    for name, sid in (("start", sid_start), ("end", sid_end)):
        if sid not in pos:
            return Checked(None, [f"{name} {sid or '(missing)'} is not a sentence of blocks {blocks}"])
    a, z = pos[sid_start], pos[sid_end]
    if a > z:
        return Checked(None, [f"start {sid_start} comes after end {sid_end}"])

    # review numbering of the merged group (continuous, junction sentences joined)
    merged = merge_group_sentences([wb.block for wb in group], words)
    mpos: dict[int, int] = {}
    for k, ms in enumerate(merged, 1):
        for w in ms:
            mpos.setdefault(id(w), k)
    num = {s.sid: mpos.get(id(s.words[0])) for s in order}
    if any(v is None for v in num.values()):
        return Checked(None, ["internal: a sentence is missing from the merged numbering"])

    # A block's unfinished last sentence and the next block's first are ONE review sentence:
    # cutting either part cuts both.
    cut_nums: set[int] = set()
    for c in clip.get("cut") or []:
        c = _sid(c)
        if c not in pos or not (a < pos[c] < z):
            probs.append(f"cut {c} is not strictly inside {sid_start}…{sid_end}")
            continue
        if num[c] in (num[sid_start], num[sid_end]):
            probs.append(f"cut {c} is joined with the start/end sentence across the block border")
            continue
        cut_nums.add(num[c])
    played = [s for s in order[a:z + 1] if num[s.sid] not in cut_nums]
    kept_nums = {num[s.sid] for s in played}
    end, start = order[z], order[a]
    if not end.complete:
        probs.append(f"end {end.sid} is unfinished in the text (…→)")
    if end.open_tone:
        probs.append(f"end {end.sid}: the voice stays up (↗) — the thought goes on there")
    before = order[a - 1] if a > 0 else group[0].prev
    if a == 0 and before is not None and not before.complete:
        probs.append(f"start {start.sid} continues an unfinished sentence before it (…→) — "
                     "the clip starts mid-sentence")
    elif before is not None and before.open_tone:
        probs.append(f"start {start.sid} comes right after a sentence ending with the voice up (↗) — "
                     "the clip joins mid-thought")
    played_sec = sum(s.dur for s in played)
    if not (p.min_sec <= played_sec <= p.max_sec):
        probs.append(f"length {played_sec:.0f} s of speech — keep it within {p.min_sec:.0f}–{p.max_sec:.0f} s")

    played_ids = {s.sid for s in played}
    close: list[int] = []
    for c in clip.get("close") or []:
        c = _sid(c)
        if c not in played_ids:
            probs.append(f"close {c} is not a played sentence")
        elif num[c] not in close:
            close.append(num[c])
    keys: list[tuple[int, str]] = []
    kraw = clip.get("keys") or {}
    if isinstance(kraw, dict):
        for c, word in kraw.items():
            c = _sid(c)
            ws = word if isinstance(word, list) else [word]
            for wd in ws:
                wn = norm_word(str(wd))
                if c not in played_ids:
                    probs.append(f"key «{wd}» on {c}: not a played sentence")
                    continue
                sent = next(s for s in played if s.sid == c)
                if not wn or wn not in {norm_word(w.word) for w in sent.words}:
                    probs.append(f"key «{wd}» is not a word of {c}")
                    continue
                keys.append((num[c], wn))
    title = _clean_text(clip.get("title"))
    if not title:
        probs.append("title is missing")
    elif len(title) > p.title_max_chars:
        probs.append(f"title is {len(title)} characters — at most {p.title_max_chars}")
    caption = _clean_text(clip.get("caption"))
    if not caption:
        probs.append("caption is missing")
    try:
        score = int(clip.get("score", 80))
    except (TypeError, ValueError):
        score = 80
    score = min(100, max(60, score))

    merge = {1: "", 2: "+", 3: "++"}[len(blocks)]
    parts = [f"{blocks[0]} {score}{merge}", f"s:{num[start.sid]}", f"e:{num[end.sid]}"]
    xs = sorted(cut_nums)
    if xs:
        parts.append("x:" + ",".join(map(str, xs)))
    if close:
        parts.append("c:" + ",".join(map(str, sorted(close))))
    if keys:
        kd: dict[int, list[str]] = {}
        for n, wd in keys:
            if wd not in kd.setdefault(n, []):
                kd[n].append(wd)
        parts.append("k:" + ";".join(f"{n}={','.join(v)}" for n, v in sorted(kd.items())))
    if title:
        parts.append(f"t: {_clean_text(title, p.title_max_chars)}")
    if caption:
        parts.append(f"d: {caption}")
    first = " ".join(w.word for w in played[0].words[:6])
    last = " ".join(w.word for w in played[-1].words[-6:])
    return Checked(" | ".join(parts), probs, tuple(blocks), played_sec, f"«{first} … {last}»")


@dataclass
class LabelResult:
    lines: list[str]
    clips_ok: int = 0
    clips_flagged: int = 0
    windows_failed: int = 0
    requests: int = 0


def _ask(provider, messages: list[dict]) -> tuple[dict | None, str, str | None]:
    """(parsed answer, raw text, provider error)."""
    try:
        raw = provider.complete(messages, temperature=0.0)
    except Exception as exc:  # noqa: BLE001 — ProviderError and transport errors: report, go on
        return None, "", f"{type(exc).__name__}: {exc}"
    return parse_answer(raw), raw, None


def _check_all(clips: list, win, words, p) -> list[Checked]:
    out: list[Checked] = []
    used: set[int] = set()
    for c in clips:
        ch = check_clip(c if isinstance(c, dict) else {}, win, words, p=p)
        if ch.blocks and used & set(ch.blocks):
            ch.problems.append(f"blocks {list(ch.blocks)} overlap another clip of this answer")
        used |= set(ch.blocks)
        out.append(ch)
    return out


def _repair_message(checked: list[Checked]) -> str:
    rows = [f"clip {i}: " + "; ".join(ch.problems) for i, ch in enumerate(checked, 1) if ch.problems]
    return ("These clips break the rules:\n" + "\n".join(rows) +
            "\nReturn the corrected JSON with ALL clips (unchanged ones too). Drop a clip you cannot fix.")


def label_source(wblocks: Sequence[WBlock], words: list, provider, *, system: str,
                 fewshot: Sequence[dict] = (), p: LabelParams = LabelParams(),
                 log: Callable[[str], None] = print) -> LabelResult:
    """Draft review lines for every block, window by window (windows overlap).

    A clip that touches the last block of its window and could still grow is DEFERRED: the next
    window sees those blocks with more context after them. If the next window proposes nothing
    over those blocks, the deferred clip is taken. A clip overlapping an accepted one is dropped.
    """
    res = LabelResult([])
    base = [{"role": "system", "content": system}] + list(fewshot)
    wins = windows(wblocks, p.window_blocks, p.max_clip_blocks)
    accepted: list[Checked] = []          # clean clips
    flagged: list[Checked] = []           # failed the checks after the repair round
    failed: list[str] = []
    pending: list[Checked] = []

    def taken(ch: Checked) -> bool:
        return any(set(ch.blocks) & set(a.blocks) for a in accepted)

    for wi, win in enumerate(wins):
        label = f"{win[0].seq}–{win[-1].seq}" if len(win) > 1 else f"{win[0].seq}"
        msgs = base + [{"role": "user", "content": render_window(win, p)}]
        ans, raw, err = _ask(provider, msgs)
        res.requests += 1
        if ans is None and err is None:
            msgs = msgs + [{"role": "assistant", "content": raw},
                           {"role": "user", "content": 'Answer with ONLY the JSON object {"clips": [...]}.'}]
            ans, raw, err = _ask(provider, msgs)
            res.requests += 1
        checked: list[Checked] = []
        if ans is None:
            why = err or "no valid JSON after a retry"
            failed.append(f"# blocks {label}: no answer ({why})")
            res.windows_failed += 1
            log(f"  блоки {label}: нет ответа ({why})")
        else:
            checked = _check_all(ans["clips"], win, words, p)
            rounds = 0
            while any(ch.problems for ch in checked) and rounds < p.repair_rounds:
                rounds += 1
                msgs = msgs + [{"role": "assistant", "content": raw},
                               {"role": "user", "content": _repair_message(checked)}]
                ans2, raw2, err2 = _ask(provider, msgs)
                res.requests += 1
                if ans2 is None:
                    break
                ans, raw = ans2, raw2
                checked = _check_all(ans["clips"], win, words, p)
        nxt = wins[wi + 1] if wi + 1 < len(wins) else None
        nxt_first = nxt[0].seq if nxt else None
        new_pending: list[Checked] = []
        n_ok = n_bad = 0
        for ch in checked:
            if ch.problems or ch.line is None:
                if ch.blocks and taken(ch):
                    continue
                flagged.append(ch)
                n_bad += 1
                continue
            grows = (nxt is not None and ch.blocks[-1] == win[-1].seq
                     and len(ch.blocks) < p.max_clip_blocks and ch.blocks[0] >= nxt_first)
            if grows:
                new_pending.append(ch)
            elif not taken(ch):
                accepted.append(ch)
                n_ok += 1
        for ch in pending:                 # deferred from the previous window
            if not taken(ch):
                accepted.append(ch)
                n_ok += 1
        pending = new_pending
        log(f"  блоки {label}: клипов {n_ok}" + (f", с замечаниями {n_bad}" if n_bad else "")
            + (f", отложено до следующего окна {len(pending)}" if pending else ""))
    for ch in pending:
        if not taken(ch):
            accepted.append(ch)
    flagged = [f for f in flagged if not (f.blocks and taken(f))]
    rows: list[tuple[int, int, list[str]]] = []
    for ch in accepted:
        rows.append((ch.blocks[0], 0, [ch.line, f"#   {ch.played_sec:.0f} s: {ch.preview}"]))
    for ch in flagged:
        rows.append((ch.blocks[0] if ch.blocks else 10**9, 1,
                     [f"#! {ch.line or '(clip not written)'}  ← " + "; ".join(ch.problems)]))
    for k, line in enumerate(failed):
        m = re.match(r"# blocks (\d+)", line)
        rows.append((int(m.group(1)) if m else 10**9, 2, [line]))
    seen: set[str] = set()
    for _, _, lines in sorted(rows, key=lambda r: (r[0], r[1])):
        if lines[0] in seen:
            continue
        seen.add(lines[0])
        res.lines.extend(lines)
    res.clips_ok = len(accepted)
    res.clips_flagged = len({f.line or id(f) for f in flagged})
    return res


def render_file(result: LabelResult, *, source_ref: str, n_blocks: int, filter_removed: int,
                fingerprint: str, model: str, date: str, review_ref: str) -> str:
    ref = f'"{review_ref}"' if " " in review_ref else review_ref
    head = [
        "# AutoReels block review — DRAFT by arl label",
        f"# source: {source_ref}",
        f"# blocks: {n_blocks}  |  filter_removed: {filter_removed}",
        f"# fingerprint: {fingerprint}",
        "# format: compact",
        f"# labeler: auto ({model}, {date}). Every line is a proposal: check it, edit, delete.",
        f"#   plan only:  arl blocks --apply {ref} --labeler auto",
        f"#   install:    arl blocks --apply {ref} --labeler auto --install",
        "# '#!' lines failed the checks after a repair round — fix them or leave them commented out.",
        "",
    ]
    return "\n".join(head + result.lines) + "\n"
