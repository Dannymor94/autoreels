"""M123: the scenarist — a strong model reads the whole numbered text of a talk and writes the clips itself (what each
is about, where its question or hook is, where it lands), as review lines; the code checks every line with the same
rules as the automatic path and keeps only what passes (invariant 1: the model proposes, the code decides).

Owner (m122): «везде какая-то проблема со сценарием» — the map-based builder sees one line per thought, never the text,
so it cannot tell whether a clip asks, develops and lands (M1 of m122: an answer to a question the viewer never hears).
"""
from __future__ import annotations

import re
from typing import Callable, Sequence

from autoreels.cloud.autocut import (AutoParams, Proposal, _clean, _hook_cands, rhythm_pieces, rhythm_why)

SCENARIO_SYSTEM = (
    "You are the editor of short vertical videos (reels) cut from a long Russian talk. You get the whole talk as "
    "numbered sentences «B.k [seconds] text». Write the best reels it holds. A reel is a small story a viewer who heard "
    "NOTHING else understands and wants to watch to the end: it makes its subject clear from its first sentence (when "
    "a passage answers a question, the question comes with it), develops one thought and lands on a sentence that "
    "concludes it. Prefer concrete examples, vivid images, a surprising turn; the speaker uses many fillers («ну», "
    "«вот», «как бы», «то есть», «значит») — prefer sentences with few, and never open or close a reel on a sentence "
    "that is mostly fillers. You may take sentences from different "
    "places when they tell one story (a question from later may open it, a conclusion from elsewhere may close it), "
    "but {jumps}. Use whole sentences only, in the numbering given. Each reel lasts {min_s}–{max_s} seconds (sum of "
    "the seconds of its sentences). Reels do not share sentences. A teaser h: is one striking finished sentence from "
    "the second half of the reel, replayed at its start — it must make sense heard cold. Write up to {n} reels, best "
    "first; fewer is fine, a weak reel is worse than none. Be brief: one line per reel, nothing else, every line "
    "starting with «M |»:\n"
    "M | <sentences in play order, e.g. 14.2-5 15.1-3> | h:<B.k> | t: <the subject in at most 6 Russian words from the "
    "reel> | why: <at most 15 Russian words: what it asks or promises → how it develops → how it lands>"
)

# M123b (m123: Sonnet wrote «1 | 30.4-30.7 | …» — numbers instead of «M», ranges with the block repeated): a reel line
# is any line whose first field is «M», «M3», «3», «3.» or «3)» (markdown backticks/stars around it allowed)
REEL_LINE = re.compile(r"^\s*[`*]*\s*(?:M\s*\d*|\d+)\s*[.)]?\s*[`*]*\s*\|")


def jumps_rule(p: AutoParams) -> str:
    if not p.rhythm:
        return "keep jumps few"
    return (f"no more than {p.max_jumps} jumps (a gap of more than {p.jump_sec:g} s in the talk, or going back), "
            f"and after a jump stay at least {p.settle_far_sec:g} s in the new place (the last piece may be shorter)")


def numbered_text(rows: Sequence[tuple[str, float, str]]) -> str:
    """[(B.k, seconds, text)] → «B.k [3.2] text» lines."""
    return "\n".join(f"{ref} [{sec:.1f}] {text}" for ref, sec, text in rows)


def expand_refs(field: str) -> list[str] | None:
    """«14.2-5 15.1» → [14.2, 14.3, 14.4, 14.5, 15.1]; None when a piece is not «B.k» or «B.k-m»."""
    out: list[str] = []
    for piece in field.replace(",", " ").replace("–", "-").split():
        m = re.fullmatch(r"(\w+)\.(\d+)(?:-(?:(\w+)\.)?(\d+))?", piece)
        if not m or (m.group(3) and m.group(3) != m.group(1)):
            return None                   # «14.5-15.2» crosses blocks: the size of 14 is unknown here
        a, z = int(m.group(2)), int(m.group(4) or m.group(2))
        if z < a:
            return None
        out += [f"{m.group(1)}.{k}" for k in range(a, z + 1)]
    return out


def compress_refs(refs: Sequence[str]) -> str:
    """[14.2, 14.3, 14.4, 15.1] → «14.2-4 15.1» (runs of one block in play order)."""
    out: list[str] = []
    run: list[tuple[str, int]] = []

    def flush() -> None:
        if run:
            b, a, z = run[0][0], run[0][1], run[-1][1]
            out.append(f"{b}.{a}" + (f"-{z}" if z > a else ""))
    for r in refs:
        b, _, k = r.rpartition(".")
        if run and run[-1][0] == b and run[-1][1] + 1 == int(k):
            run.append((b, int(k)))
        else:
            flush()
            run = [(b, int(k))]
    flush()
    return " ".join(out)


def parse_scenarios(raw: str, known: set[str]) -> tuple[list[dict], list[str]]:
    """The model's lines → [{refs, hook, title, why}] and the reasons lines were dropped (invariant 2: every sentence
    is one of the talk's; a line with an unknown or repeated sentence goes whole)."""
    out, bad, used = [], [], set()
    for ln in (raw or "").splitlines():
        ln = ln.strip().strip("`")
        if not REEL_LINE.match(ln):
            continue
        ln = ln.strip("*").strip()
        parts = [x.strip() for x in ln.split("|")]
        refs = expand_refs(parts[1]) if len(parts) > 1 else None
        if not refs:
            bad.append(f"не разобрать фразы: {ln[:80]}")
            continue
        unknown = [r for r in refs if r not in known]
        if unknown:
            bad.append(f"нет таких фраз {', '.join(unknown[:3])}: {parts[1][:60]}")
            continue
        if len(set(refs)) != len(refs) or set(refs) & used:
            bad.append(f"фраза повторяется или уже в другом ролике: {parts[1][:60]}")
            continue
        sc = {"refs": refs, "hook": None, "title": "", "why": ""}
        for f in parts[2:]:
            if f.startswith("h:"):
                h = f[2:].strip().rstrip("!")
                sc["hook"] = h if h in refs else None
            elif f.startswith("t:"):
                sc["title"] = f[2:].strip()
            elif f.startswith("why:"):
                sc["why"] = f[4:].strip()
        used.update(refs)
        out.append(sc)
    return out, bad


def scenario_proposals(scens: Sequence[dict], sent: dict[str, tuple[float, float, str, bool, int]],
                       units: Sequence[dict], p: AutoParams, end_tone: Callable[[str], "str | None"] | None = None
                       ) -> tuple[list[Proposal], list[tuple[str, str]]]:
    """M123: each scenario → a Proposal the automatic path checks and polishes as its own, or a reason it goes.
    `sent` — B.k → (t0, t1, text, finished, words). Checks: length min_sec…max_sec; the jump rule (p.rhythm); the end
    finished and not «→» (trailing sentences go while the reel stays ≥ min_sec). The thoughts of the map it plays give
    `units` (partly played ones get unit_refs); the model's teaser comes first among the code's hook candidates."""
    by_ref_unit: dict[str, dict] = {}
    for u in units:
        for r in (expand_refs(u.get("refs") or "") or []):
            by_ref_unit.setdefault(r, u)
    out: list[Proposal] = []
    gone: list[tuple[str, str]] = []
    for rank, sc in enumerate(scens):
        refs = list(sc["refs"])
        label = compress_refs(refs)
        dur = lambda rs: sum(sent[r][1] - sent[r][0] for r in rs)  # noqa: E731
        notes = [f"сценарий: {sc.get('why') or '—'}"]
        if end_tone is not None and p.end_tone:
            while refs and (end_tone(refs[-1]) == "open" or not sent[refs[-1]][3]) and dur(refs[:-1]) >= p.min_sec:
                notes.append(f"конец: «{sent[refs[-1]][2][-40:]}» не законченный или «→» — убран")
                refs = refs[:-1]
            if not sent[refs[-1]][3] or end_tone(refs[-1]) == "open":
                gone.append((label, "конец не законченный или звучит «→», укоротить нельзя"))
                continue
        secs = dur(refs)
        if not p.min_sec <= secs <= p.max_sec:
            gone.append((label, f"длина {secs:.0f} с вне {p.min_sec:g}–{p.max_sec:g} с"))
            continue
        spans = [(sent[r][0], sent[r][1]) for r in refs]
        if p.rhythm:
            why, _k = rhythm_why(spans, p, sent[refs[0]][2].rstrip().endswith("?"))
            if why:
                gone.append((label, f"скачки: {why}"))
                continue
        pieces = [[refs[i] for i in pc] for pc in rhythm_pieces(spans, p.jump_sec)]
        uids: list[int] = []
        played: dict[int, list[str]] = {}
        for r in refs:
            u = by_ref_unit.get(r)
            if u is None:
                continue
            if u["id"] not in played:
                uids.append(u["id"])
                played[u["id"]] = []
            played[u["id"]].append(r)
        by_id = {u["id"]: u for u in units}
        unit_refs = {i: compress_refs(rs) for i, rs in played.items()
                     if rs != (expand_refs(by_id[i].get("refs") or "") or [])}
        pseudo = [{"id": -1 - k, "refs": compress_refs(pc), "punch": 5, "role": None} for k, pc in enumerate(pieces)]

        def rows(rf: str):
            return [(r, sent[r][1] - sent[r][0], sent[r][4], sent[r][3], sent[r][2]) for r in (expand_refs(rf) or [])]
        cands = _hook_cands(pseudo, rows, p)
        hooks = [c[0] for c in cands]
        hook_texts = {r: (t, s) for r, s, t in cands}
        h = sc.get("hook")
        if h and h in refs and refs.index(h) >= len(refs) * p.hook_teaser_pos and sent[h][3] \
                and sent[h][4] >= p.hook_min_words and p.hook_min_sec <= sent[h][1] - sent[h][0] <= p.hook_max_sec:
            hooks = [h] + [x for x in hooks if x != h]
            hook_texts.setdefault(h, (sent[h][2], 0.0))
            notes.append(f"крючок сценариста: h:{h} «{sent[h][2][:60]}»")
        close: list[str] = []
        if p.close_last:
            acc = 0.0
            for r in reversed(refs):
                if len(close) == 2 or (close and acc >= p.close_last_sec):
                    break
                close.insert(0, r)
                acc += sent[r][1] - sent[r][0]
        notes.append(f"куски: {len(pieces)}, скачков {len(pieces) - 1}, {secs:.0f} с")
        # M124: the thoughts of the map it plays, as the automatic path writes them (the measures read these lines)
        notes = [f"#{i} {by_id[i].get('role')}★{by_id[i].get('punch')} {unit_refs.get(i) or by_id[i].get('refs')} — "
                 f"{by_id[i].get('summary') or ''}" for i in uids] + notes
        payoff = by_id.get(uids[-1]) if uids else None
        out.append(Proposal(
            units=uids or [-1], pieces=" ".join(compress_refs(pc) for pc in pieces),
            hook=hooks[0] if hooks else None, hooks=hooks, hook_texts=hook_texts, speed=None,
            title=_clean(sc.get("title") or (by_id[uids[0]].get("summary") if uids else "")),
            caption=_clean((payoff or {}).get("summary") or sc.get("why") or ""),
            opener=uids[0] if uids else None, unit_refs=unit_refs, hook_keep=p.hook_teaser, close=close,
            score=max(40, 95 - rank), seconds=round(secs, 1), notes=notes))
    return out, gone
