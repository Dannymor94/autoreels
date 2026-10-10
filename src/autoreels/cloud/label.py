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
    stop_after_failed_windows: int = 2   # consecutive provider failures → stop, mark the rest for --retry
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


def word_before(words: list, first):
    """The word --apply treats as spoken before `first` (_check_first_subtitle_word): the last word
    in transcript order whose start is earlier. Whisper sometimes inserts a hallucinated sentence
    out of time order (IMG_6848 1653 s: «Возможно, вы не понимаете…» with 20 ms words): in the
    review it looks like a finished sentence before a block, while the real previous word is the
    middle of a sentence («…любит себя,»)."""
    prev = None
    for w in words:
        if w.t0 < first.t0 - 1e-4:
            prev = w
    return prev


def _continues(first, prev) -> bool:
    """Same rule as --apply: a lowercase first word after a word that ends no sentence."""
    from autoreels.cloud.snap import _is_sentence_end
    text = first.word.strip(".,!?…;: ")
    return bool(prev is not None and text and not text[0].isupper() and not _is_sentence_end(prev.word))


_QUESTION_WORDS = frozenset("что как почему зачем где когда кто какой какая какое какие каким куда откуда "
                            "сколько чем чего кого кому отчего".split())
_LEAD = frozenset("а и но ну так вот да".split())


def is_open_question(words) -> bool:
    """A sentence asking something the clip would have to answer: ends with «?» and starts with a
    question word («Что это такое?», «А как же быть?»). A tag question closing a thought
    («…его сын, правильно?», accepted by the owner in IMG_6848) is not one (10h59 r05, M36)."""
    if not words or not words[-1].word.rstrip("»\"')").endswith("?"):
        return False
    toks = [norm_word(w.word) for w in words]
    toks = [t for t in toks if t]
    while toks and toks[0] in _LEAD:
        toks = toks[1:]
    return bool(toks) and toks[0] in _QUESTION_WORDS


def check_clip(clip: dict, win: Sequence[WBlock], words: list,
               p: LabelParams = LabelParams(), *, require_text: bool = True) -> Checked:
    """Map one proposed clip to a review line and list what breaks the owner's rules.
    require_text=False (checking an edited draft): a missing title/caption is the owner's choice."""
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
    if is_open_question(end.words):
        probs.append(f"end {end.sid} is an open question («{end.text[-60:]}») — the answer is not in the clip")
    before = order[a - 1] if a > 0 else group[0].prev
    spoken_before = word_before(words, start.words[0])
    if a == 0 and before is not None and not before.complete:
        probs.append(f"start {start.sid} continues an unfinished sentence before it (…→) — "
                     "the clip starts mid-sentence")
    elif _continues(start.words[0], spoken_before):
        probs.append(f"start {start.sid} continues the sentence «…{spoken_before.word} "
                     f"{start.words[0].word}» — the clip starts mid-sentence")
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
        if require_text:
            probs.append("title is missing")
    elif len(title) > p.title_max_chars:
        probs.append(f"title is {len(title)} characters — at most {p.title_max_chars}")
    caption = _clean_text(clip.get("caption"))
    if not caption and require_text:
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
                 log: Callable[[str], None] = print, occupied: set[int] | None = None) -> LabelResult:
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

    occupied = set(occupied or ())          # blocks already used by lines of an existing draft

    def taken(ch: Checked) -> bool:
        return bool(set(ch.blocks) & occupied) or any(set(ch.blocks) & set(a.blocks) for a in accepted)

    provider_fails = 0                      # consecutive windows lost to the providers
    for wi, win in enumerate(wins):
        label = f"{win[0].seq}–{win[-1].seq}" if len(win) > 1 else f"{win[0].seq}"
        if provider_fails >= p.stop_after_failed_windows:
            # Free tiers run out for hours (Groq hourly/daily quota, OpenRouter 50 requests a day):
            # every further window would wait out the whole budget and fail. Stop asking; the
            # owner runs `arl label … --retry` later for exactly these windows.
            failed.append(f"# blocks {label}: no answer (stopped: providers exhausted — arl label --retry later)")
            res.windows_failed += 1
            continue
        msgs = base + [{"role": "user", "content": render_window(win, p)}]
        ans, raw, err = _ask(provider, msgs)
        res.requests += 1
        provider_fails = provider_fails + 1 if err is not None else 0
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
        if ans is not None or n_ok:
            log(f"  блоки {label}: клипов {n_ok}" + (f", с замечаниями {n_bad}" if n_bad else "")
                + (f", отложено до следующего окна {len(pending)}" if pending else "")
                + (" (взяты отложенные из прошлого окна)" if ans is None else ""))
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


# ── an existing draft: re-check it with the current code, or retry its unanswered windows ─────

_NO_ANSWER_RE = re.compile(r"^# blocks (\d+)(?:–(\d+))?: no answer")


def entry_to_clip(entry, wblocks: Sequence[WBlock], words: list) -> tuple[dict | None, list[WBlock], str]:
    """A parsed review line → (labeller JSON, its block group, why it cannot be checked)."""
    by_seq = {wb.seq: wb for wb in wblocks}
    if entry.merge_back:
        return None, [], "joins the previous block ('-') — not checked"
    if entry.beats:
        return None, [], "beat lines ('>') — not checked"
    group = [by_seq.get(entry.seq + i) for i in range(entry.merge_fwd + 1)]
    if any(g is None for g in group):
        return None, [], "block number outside the review"
    merged = merge_group_sentences([g.block for g in group], words)
    pos: dict[int, int] = {}
    for k, ms in enumerate(merged, 1):
        for w in ms:
            pos.setdefault(id(w), k)
    ids: dict[int, list[str]] = {}
    for g in group:
        for s in g.sents:
            ids.setdefault(pos.get(id(s.words[0]), 0), []).append(s.sid)
    n = len(merged)
    s_num = entry.s or 1
    e_num = entry.e or n
    if s_num not in ids or e_num not in ids:
        return None, group, f"s:{s_num}/e:{e_num} outside 1–{n}"
    keys: dict[str, list[str]] = {}
    for num, ws in entry.k:
        if num in ids:
            keys.setdefault(ids[num][-1], []).extend(w.rstrip("*") for w in ws)
    clip = {"blocks": [g.seq for g in group], "start": ids[s_num][0], "end": ids[e_num][-1],
            "cut": [ids[x][0] for x in entry.x if x in ids], "close": [ids[c][-1] for c in entry.c if c in ids],
            "keys": keys, "title": entry.title or "", "caption": entry.description or "",
            "score": entry.score if entry.score is not None else 80}
    return clip, group, ""


def check_draft(text: str, wblocks: Sequence[WBlock], words: list, p: LabelParams = LabelParams()
                ) -> tuple[str, list[tuple[int, list[str]]]]:
    """Re-check every review line of a draft (a draft written by an older version, or edited by the
    owner). A line that breaks a rule is commented out as '#! <line>  ← reasons'; everything else
    is kept byte for byte. Returns (new text, [(block, reasons)])."""
    from autoreels.cloud.blocks import parse_compact_answer
    out, flagged = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or not line[0].isdigit():
            out.append(raw)
            continue
        _, entries, errors, _ = parse_compact_answer(line + "\n")
        if errors or not entries:
            reasons = [m for _, m in errors] or ["not a review line"]
        else:
            clip, group, why = entry_to_clip(entries[0], wblocks, words)
            if clip is None and why.endswith("not checked"):
                out.append(raw)            # '-' joins and beat orders: left to the owner as written
                continue
            reasons = [why] if clip is None else check_clip(clip, group, words, p, require_text=False).problems
        if reasons:
            out.append(f"#! {line}  ← " + "; ".join(reasons))
            flagged.append((entries[0].seq if entries else 0, reasons))
        else:
            out.append(raw)
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), flagged


def unanswered_windows(text: str) -> list[tuple[int, int]]:
    """(first, last) block of every '# blocks a–b: no answer' line of a draft."""
    out = []
    for line in text.splitlines():
        m = _NO_ANSWER_RE.match(line.strip())
        if m:
            a = int(m.group(1))
            out.append((a, int(m.group(2) or a)))
    return out


def used_blocks(text: str) -> set[int]:
    """Blocks taken by the review lines of a draft (a line N with '+'/'++' takes N..N+2)."""
    from autoreels.cloud.blocks import parse_compact_answer
    _, entries, _, _ = parse_compact_answer(text)
    used: set[int] = set()
    for e in entries:
        lo = e.seq - (1 if e.merge_back else 0)
        used.update(range(lo, e.seq + e.merge_fwd + 1))
    return used


def retry_draft(text: str, wblocks: Sequence[WBlock], words: list, provider, *, system: str,
                fewshot: Sequence[dict] = (), p: LabelParams = LabelParams(),
                log: Callable[[str], None] = print) -> tuple[str, int, int]:
    """Ask again for the windows a draft marks '# blocks a–b: no answer'; new clips never overlap
    the draft's lines. Returns (new text, windows answered now, windows still unanswered)."""
    by_seq = {wb.seq: wb for wb in wblocks}
    lines = text.splitlines()
    done = still = 0
    for a, z in unanswered_windows(text):
        win = [by_seq[i] for i in range(a, z + 1) if i in by_seq]
        if not win:
            continue
        sub = label_source(win, words, provider, system=system, fewshot=fewshot,
                           p=LabelParams(**{**p.__dict__, "window_blocks": len(win)}),
                           log=log, occupied=used_blocks("\n".join(lines)))
        label = f"{a}–{z}" if z != a else f"{a}"
        if sub.windows_failed:
            still += 1
            continue
        done += 1
        new = sub.lines or [f"# blocks {label}: no clip (retry)"]
        idx = next(i for i, l in enumerate(lines) if _NO_ANSWER_RE.match(l.strip())
                   and l.strip().startswith(f"# blocks {label}:"))
        lines[idx:idx + 1] = new
    return "\n".join(lines) + "\n", done, still


# ── the owner's review of rendered clips (review sheet → decisions → draft) ──────────────────
#
# arl review-sheet shows every rendered clip next to its review line; the owner marks each clip
# ok / drop / fix + a note and downloads a decisions file:
#     # stem: <stem>
#     # review: reviews/<stem>_auto.txt
#     r01 | line 3 | ok
#     r02 | line 5 | fix | конец раньше, на «…»
# arl review-apply writes the verdicts into the draft (drop → the line commented out, fix → a «✎»
# note above the line); with --redo the LLM reworks each «✎» line under the same checks as a new
# draft. Code places every verdict on the line by its block number; nothing is lost silently.

_DECISION_RE = re.compile(r"^\s*(r\d+)\s*\|\s*line\s+(\d+)\s*\|\s*(ok|drop|fix)\s*(?:\|\s*(.*))?$", re.IGNORECASE)
_FIX_RE = re.compile(r"^# ✎ владелец \((r\d+)([^)]*)\):\s*(.*)$")


@dataclass
class Decision:
    reel: str
    seq: int
    verdict: str          # ok | drop | fix
    note: str = ""


def parse_decisions(text: str) -> tuple[dict[str, str], list[Decision], list[str]]:
    """(header fields, decisions, errors) of a decisions file. A 'fix' without a note is an error:
    there is nothing to rework by."""
    head: dict[str, str] = {}
    out: list[Decision] = []
    errors: list[str] = []
    seen: dict[int, str] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            m = re.match(r"#\s*(\w+):\s*(.*)$", line)
            if m:
                head[m.group(1).lower()] = m.group(2).strip()
            continue
        m = _DECISION_RE.match(line)
        if not m:
            errors.append(f"строка {n}: не понял «{line[:60]}»")
            continue
        d = Decision(m.group(1).lower(), int(m.group(2)), m.group(3).lower(), (m.group(4) or "").strip())
        if d.verdict == "fix" and not d.note:
            errors.append(f"строка {n}: {d.reel} — «fix» без замечания")
            continue
        if d.seq in seen:
            errors.append(f"строка {n}: строка черновика {d.seq} уже решена ({seen[d.seq]})")
            continue
        seen[d.seq] = d.reel
        out.append(d)
    return head, out, errors


@dataclass
class ClipLine:
    seq: int                      # the anchor review line (earliest scored line of the group)
    raw: str
    blocks: tuple[int, ...]
    t0: float                     # source span of the group's blocks
    t1: float
    preview: str = ""             # the draft's '#   NN s: text' line under it
    marks: tuple[str, ...] = ()   # the owner's marks of earlier rounds above it


def clip_lines(review_text: str, wblocks: Sequence[WBlock]) -> list[ClipLine]:
    """The review lines that become clips, in clip order, with the source span of their block group
    — the same groups --apply builds (blocks.resolve_merge_groups; the anchor is the earliest scored
    line of a group)."""
    from autoreels.cloud.blocks import parse_compact_answer, resolve_merge_groups
    text_lines = review_text.splitlines()
    raw_by_seq: dict[int, str] = {}
    prev_by_seq: dict[int, str] = {}
    marks_by_seq: dict[int, tuple[str, ...]] = {}
    for i, raw in enumerate(text_lines):
        s = raw.strip()
        if s[:1].isdigit() and int(s.split()[0]) not in raw_by_seq:
            q = int(s.split()[0])
            raw_by_seq[q] = s
            nxt = text_lines[i + 1] if i + 1 < len(text_lines) else ""
            if nxt.startswith("#   "):
                prev_by_seq[q] = nxt[4:].strip()
            marks_by_seq[q] = tuple(reversed(_marks_above(text_lines, i)))
    _, entries, _, _ = parse_compact_answer(review_text)
    by_seq = {wb.seq: wb for wb in wblocks}
    groups, _ = resolve_merge_groups(list(entries), {q: wb.block for q, wb in by_seq.items()}, float("inf"))
    scored = {e.seq for e in entries if e.score is not None}
    out: list[ClipLine] = []
    for g in groups:
        anchor = next((q for q in g if q in scored), None)
        if anchor is None:
            continue
        out.append(ClipLine(anchor, raw_by_seq.get(anchor, ""), tuple(g),
                            by_seq[g[0]].block.start, by_seq[g[-1]].block.end,
                            prev_by_seq.get(anchor, ""), marks_by_seq.get(anchor, ())))
    return out


def match_reels(reel_windows: Sequence[tuple[str, list[tuple[float, float]]]],
                lines: Sequence[ClipLine], *, min_share: float = 0.5) -> dict[str, ClipLine | None]:
    """Reel id → its review line, by where the reel plays in the source: the line whose block span
    covers the largest part of the reel (at least min_share of it), each line used once. A reel
    with no such line (the draft changed after the render) maps to None."""
    out: dict[str, ClipLine | None] = {}
    used: set[int] = set()
    for rid, wins in reel_windows:
        total = sum(max(0.0, b - a) for a, b in wins) or 1e-9
        best, best_ov = None, 0.0
        for ln in lines:
            if ln.seq in used:
                continue
            ov = sum(max(0.0, min(b, ln.t1) - max(a, ln.t0)) for a, b in wins)
            if ov > best_ov:
                best, best_ov = ln, ov
        if best is not None and best_ov / total >= min_share:
            used.add(best.seq)
            out[rid] = best
        else:
            out[rid] = None
    return out


def _line_index(lines: list[str], seq: int) -> int | None:
    for i, l in enumerate(lines):
        s = l.strip()
        if s[:1].isdigit() and s.split()[0] == str(seq):
            return i
    return None


def _marks_above(lines: list[str], i: int) -> list[str]:
    """The comment lines directly above line i (the owner's marks of earlier rounds)."""
    out = []
    j = i - 1
    while j >= 0 and lines[j].strip().startswith("# ") and ("владел" in lines[j]):
        out.append(lines[j].strip())
        j -= 1
    return out


def apply_decisions(review_text: str, decisions: list[Decision], *, date: str = "") -> tuple[str, list[str]]:
    """Write the owner's verdicts into the draft: drop → the line is commented out with the note;
    fix → the note goes above the line (for --redo or a manual edit); ok → a mark above the line.
    Applying the same decisions twice changes nothing. Returns (new text, messages)."""
    lines = review_text.splitlines()
    msgs: list[str] = []
    tag = f" {date}" if date else ""
    for d in decisions:
        i = _line_index(lines, d.seq)
        if i is None:
            msgs.append(f"{d.reel}: строки {d.seq} в черновике нет (уже убрана?) — пропущено")
            continue
        if d.verdict == "drop":
            note = f": {d.note}" if d.note else ""
            lines[i] = f"#- {lines[i].strip()}  ← убрано владельцем ({d.reel}{tag}){note}"
            msgs.append(f"{d.reel}: строка {d.seq} убрана")
            continue
        if d.verdict == "fix":
            mark = f"# ✎ владелец ({d.reel}{tag}): {d.note}"
            done = f"# ✔ переделано по замечанию владельца ({d.reel}{tag}): {d.note}"
        else:
            mark = f"# ✓ владелец ({d.reel}{tag})" + (f": {d.note}" if d.note else "")
            done = mark
        above = _marks_above(lines, i)
        if mark in above or done in above:
            continue
        lines.insert(i, mark)
        msgs.append(f"{d.reel}: строка {d.seq} — " + ("замечание записано" if d.verdict == "fix" else "ок"))
    return "\n".join(lines) + ("\n" if review_text.endswith("\n") else ""), msgs


def redo_line(raw_line: str, note: str, wblocks: Sequence[WBlock], words: list, provider, *,
              system: str, fewshot: Sequence[dict] = (), p: LabelParams = LabelParams(),
              occupied: set[int] | None = None) -> tuple[Checked | None, list[str]]:
    """Ask the LLM to rework ONE clip by the owner's note; the same checks as a new draft, one
    repair round. The window is the clip's blocks ± one; blocks of other lines (occupied) are off
    limits. Returns (the checked clip or None, problems)."""
    from autoreels.cloud.blocks import parse_compact_answer
    _, entries, errors, _ = parse_compact_answer(raw_line + "\n")
    if errors or not entries:
        return None, ["the line does not parse"]
    clip, group, why = entry_to_clip(entries[0], wblocks, words)
    if clip is None:
        return None, [why]
    occupied = set(occupied or ()) - {g.seq for g in group}
    by_seq = {wb.seq: wb for wb in wblocks}
    lo, hi = group[0].seq, group[-1].seq
    win = [by_seq[q] for q in range(lo - 1, hi + 2) if q in by_seq and q not in occupied]
    ask = (render_window(win, p) + "\nCurrent clip, reviewed by the owner after watching it:\n"
           + json.dumps({"clips": [clip]}, ensure_ascii=False)
           + f"\nOwner's note: {note}\n"
           "Rework this clip following the note and all the rules. "
           'Return {"clips": [ ... ]} with exactly one clip.')
    msgs = [{"role": "system", "content": system}] + list(fewshot) + [{"role": "user", "content": ask}]

    def judge(ans) -> Checked:
        ch = check_clip(ans["clips"][0], win, words, p)
        if set(ch.blocks) & occupied:
            ch.problems.append("overlaps another clip of the draft (blocks "
                               + ",".join(str(b) for b in sorted(set(ch.blocks) & occupied)) + ")")
        return ch

    ans, raw, err = _ask(provider, msgs)
    if ans is None or not ans.get("clips"):
        return None, [err or "no valid answer"]
    ch = judge(ans)
    if ch.problems and p.repair_rounds:
        msgs += [{"role": "assistant", "content": raw}, {"role": "user", "content": _repair_message([ch])}]
        ans2, _raw2, _err2 = _ask(provider, msgs)
        if ans2 is not None and ans2.get("clips"):
            ch = judge(ans2)
    if ch.line is None or ch.problems:
        return None, ch.problems or ["the clip could not be written"]
    return ch, []


def redo_fixes(review_text: str, wblocks: Sequence[WBlock], words: list, provider, *, system: str,
               fewshot: Sequence[dict] = (), p: LabelParams = LabelParams(),
               log: Callable[[str], None] = print) -> tuple[str, int, int]:
    """Rework every line with a pending owner's «✎» note above it.
    Success: the line is replaced, its preview refreshed, the old line kept as '#~ было: …', the
    note becomes '# ✔ переделано …'. Failure: the note stays (a later --redo tries again) and a
    '#! правка …' line says why. Returns (text, reworked, failed)."""
    lines = review_text.splitlines()
    done = failed = 0
    i = 0
    while i < len(lines):
        m = _FIX_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue
        j = i + 1
        while j < len(lines) and lines[j].strip().startswith("# ") and "владел" in lines[j]:
            j += 1                                   # other marks of the same line
        if j >= len(lines) or not lines[j].strip()[:1].isdigit():
            i += 1
            continue
        rid, rest, note = m.group(1), m.group(2), m.group(3)
        old = lines[j].strip()
        # what follows the line: its preview, an earlier failure of this very note
        k = j + 1
        tail_keep: list[str] = []
        while k < len(lines) and lines[k].startswith("#") and not lines[k].strip()[:1].isdigit() \
                and (lines[k].startswith("#   ") or lines[k].startswith("#~ ") or lines[k].startswith("#! правка")):
            if not (lines[k].startswith("#   ") or lines[k].startswith(f"#! правка {rid}{rest}:")):
                tail_keep.append(lines[k])
            k += 1
        occupied = used_blocks("\n".join(lines[:j] + lines[j + 1:]))
        ch, probs = redo_line(old, note, wblocks, words, provider, system=system, fewshot=fewshot,
                              p=p, occupied=occupied)
        if ch is not None:
            new = [f"# ✔ переделано по замечанию владельца ({rid}{rest}): {note}", ch.line,
                   f"#   {ch.played_sec:.0f} s: {ch.preview}", f"#~ было: {old}"] + tail_keep
            done += 1
            log(f"  {rid}: переделано по замечанию")
        else:
            prev = [l for l in lines[j + 1:k] if l.startswith("#   ")]
            new = [lines[i], *lines[i + 1:j], lines[j], *prev,
                   f"#! правка {rid}{rest}: не прошла проверку — " + "; ".join(probs)] + tail_keep
            failed += 1
            log(f"  {rid}: правка не прошла проверку — " + "; ".join(probs))
        lines[i:k] = new
        i += len(new)
    return "\n".join(lines) + ("\n" if review_text.endswith("\n") else ""), done, failed
