"""M56: the auto-editor — montage lines proposed from the map of a source (cloud/thoughtmap.py).

The map already says, for every thought (unit) of the lecture, what it does (role), how strong it is
(punch 1–5), whether it stands alone or leans on an earlier thought (refers — the «сноска»), its
topic, how alive the voice is (energy) and where the same thought is said again (similar). This
module turns that into reels, deterministically (the LLM only described the units; invariant 1):

1. SEEDS: strong units (punch ≥ seed_punch) with a story role — thesis, conclusion, example,
   metaphor, question.
2. CLIP around a seed: the seed and every unit it leans on (refers, transitively); then units of the
   same topic — and the seed's «similar» units said elsewhere — by score (punch, voice energy, a
   role the story still lacks: an opener, an example, a payoff), each with what it leans on, while
   the clip fits max_sec and has at most max_pieces pieces. Kept only when it reaches min_sec and
   has an opener (thesis or question) or a payoff (conclusion).
3. ORDER: a question opens the clip (M59 allows it to come from anywhere — the «вопрос-петля»);
   the rest plays in source order (a unit always after the one it leans on). Pieces are the units'
   review references; adjacent ones join without a seam (M58).
4. HOOK: the shortest-sounding finished sentence (≤ hook_max_sec, ≥ hook_min_words) of the strongest
   payoff/question/metaphor unit of the clip → h: (the plan replays it in context or not, §2).
5. Plate t: = the opener's summary; caption d: = the payoff's summary (the LLM's words).
6. Clips sharing more than overlap_max of their units with a better clip are dropped; the best
   `clips` are kept. Every line is a proposal for the owner — the montage checks run at --apply.

Pure: the map's units and a sentence lookup in, proposals out.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

STORY = ("thesis", "conclusion", "example", "metaphor", "question")
OPENERS = ("thesis", "question")
PAYOFFS = ("conclusion",)
MIDDLE = ("example", "metaphor", "explanation")
HOOK_ROLES = ("conclusion", "question", "metaphor", "thesis")


@dataclass(frozen=True)
class AutoParams:
    clips: int = 5
    min_sec: float = 30.0
    target_sec: float = 60.0
    max_sec: float = 90.0
    max_pieces: int = 4
    min_punch: int = 3                # a unit weaker than this is never used
    seed_punch: int = 4               # a clip grows only around a unit at least this strong
    hook_max_sec: float = 6.0
    hook_min_words: int = 4
    overlap_max: float = 0.5
    use_filtered: bool = False        # take units of filtered blocks (head/tail/promo, x-refs)


@dataclass
class Proposal:
    units: list[int]                  # play order
    pieces: str                       # "13.2-5 14.1 41.3-4"
    hook: str | None
    title: str
    caption: str
    score: int
    seconds: float
    notes: list[str] = field(default_factory=list)

    def line(self, label: str) -> str:
        parts = [f"M{label} {self.score}", self.pieces]
        if self.hook:
            parts.append(f"h:{self.hook}")
        if self.title:
            parts.append(f"t: {self.title}")
        out = " | ".join(parts)
        if self.caption:
            out += f" | d: {self.caption}"
        return out


def _dur(u: dict) -> float:
    return float(u["t1"]) - float(u["t0"])


def eligible(u: dict, p: AutoParams) -> bool:
    if u.get("missing") or not u.get("refs") or u.get("role") in (None, "aside"):
        return False
    if u.get("filtered") and not p.use_filtered:
        return False
    return int(u.get("punch") or 0) >= p.min_punch


def leans_on(u: dict, by_id: dict) -> list[int]:
    """The chain of earlier units u leans on (refers, transitively), nearest first."""
    out, seen, cur = [], {u["id"]}, u
    while not cur.get("standalone", True) and cur.get("refers") in by_id and cur["refers"] not in seen:
        cur = by_id[cur["refers"]]
        seen.add(cur["id"])
        out.append(cur["id"])
    return out


def _pieces(units: Sequence[dict]) -> int:
    """Pieces after M58 joins: a unit right after the previous one in the source joins it."""
    n, prev = 0, None
    for u in units:
        if prev is None or u["id"] != prev["id"] + 1:
            n += 1
        prev = u
    return n


def _order(units: list[dict]) -> list[dict]:
    q = [u for u in units if u.get("role") == "question"]
    first = q[:1]
    rest = sorted((u for u in units if u not in first), key=lambda u: u["t0"])
    return first + rest


def _unit_score(u: dict, have: set[str]) -> float:
    s = 2.0 * int(u.get("punch") or 0) + float((u.get("voice") or {}).get("energy") or 50.0) / 25.0
    role = u.get("role")
    if role in OPENERS and not have & set(OPENERS):
        s += 2.0
    if role in PAYOFFS and "conclusion" not in have:
        s += 2.0
    if role in MIDDLE and not have & set(MIDDLE):
        s += 1.5
    return s


def build_clip(seed: dict, units: Sequence[dict], by_id: dict, p: AutoParams) -> list[dict] | None:
    chosen: dict[int, dict] = {}

    def add(u: dict) -> bool:
        group = [u] + [by_id[i] for i in leans_on(u, by_id)]
        if any(not eligible(g, p) and g["id"] not in chosen for g in group[1:]):
            # an earlier unit it leans on is unusable (filler / missing): this one cannot stand
            return False
        new = {g["id"]: g for g in group if g["id"] not in chosen}
        trial = {**chosen, **new}
        if sum(_dur(g) for g in trial.values()) > p.max_sec or _pieces(_order(list(trial.values()))) > p.max_pieces:
            return False
        chosen.update(new)
        return True

    if not add(seed):
        return None
    sims = {i for i, _ in (seed.get("similar") or [])}
    pool = [u for u in units if eligible(u, p) and u["id"] not in chosen
            and (u.get("topic") == seed.get("topic") or u["id"] in sims)]
    while sum(_dur(g) for g in chosen.values()) < p.target_sec and pool:
        have = {g.get("role") for g in chosen.values()}
        # prefer units close to what is chosen (fewer pieces), then the score
        pool.sort(key=lambda u: -_unit_score(u, have) + min(abs(u["t0"] - g["t0"]) for g in chosen.values()) / 500.0)
        u = pool.pop(0)
        add(u)
    clip = _order(list(chosen.values()))
    roles = {u.get("role") for u in clip}
    if sum(_dur(u) for u in clip) < p.min_sec or not roles & set(OPENERS + PAYOFFS):
        return None
    if clip[-1].get("role") == "question":
        return None                                   # never end on an open question
    return clip


def _hook(clip: Sequence[dict], sentences: Callable[[str], list[tuple[str, float, int, bool]]],
          p: AutoParams) -> str | None:
    cands = sorted((u for u in clip if u.get("role") in HOOK_ROLES and int(u.get("punch") or 0) >= p.seed_punch),
                   key=lambda u: (-int(u.get("punch") or 0), HOOK_ROLES.index(u["role"]), -u["t0"]))
    for u in cands:
        best = None
        for ref, sec, nwords, complete in sentences(u["refs"]):
            if complete and nwords >= p.hook_min_words and sec <= p.hook_max_sec:
                if best is None or sec > best[1]:
                    best = (ref, sec)
        if best:
            return best[0]
    return None


def propose(units: Sequence[dict], p: AutoParams = AutoParams(),
            sentences: Callable[[str], list[tuple[str, float, int, bool]]] | None = None) -> list[Proposal]:
    """Best `p.clips` proposals. `sentences(refs)` → [(B.k, seconds, words, finished)] of a unit's
    references (for the hook); None = no hook."""
    by_id = {u["id"]: u for u in units}
    seeds = sorted((u for u in units if eligible(u, p) and u.get("role") in STORY
                    and int(u.get("punch") or 0) >= p.seed_punch),
                   key=lambda u: (-int(u["punch"]), -float((u.get("voice") or {}).get("energy") or 50.0), u["t0"]))
    out: list[Proposal] = []
    used_seeds: set[int] = set()
    for seed in seeds:
        if seed["id"] in used_seeds:
            continue
        clip = build_clip(seed, units, by_id, p)
        if clip is None:
            continue
        ids = [u["id"] for u in clip]
        if any(len(set(ids) & set(o.units)) > p.overlap_max * min(len(ids), len(o.units)) for o in out):
            continue
        used_seeds.update(i for i in ids if by_id[i].get("role") in STORY)
        secs = sum(_dur(u) for u in clip)
        roles = [u.get("role") for u in clip]
        punch = sum(int(u.get("punch") or 0) for u in clip) / len(clip)
        energy = sum(float((u.get("voice") or {}).get("energy") or 50.0) for u in clip) / len(clip)
        cover = 5 * bool(set(roles) & set(OPENERS)) + 5 * bool(set(roles) & set(MIDDLE)) + 5 * ("conclusion" in roles)
        score = 15 * punch + 0.15 * energy + cover - 4 * (_pieces(clip) - 1)
        opener = next((u for u in clip if u.get("role") in OPENERS), clip[0])
        payoff = next((u for u in reversed(clip) if u.get("role") in PAYOFFS), clip[-1])
        notes = [f"#{u['id']} {u.get('role')}★{u.get('punch')} {u['refs']} — {u.get('summary') or ''}" for u in clip]
        if clip[0].get("role") == "question" and clip[0]["t0"] > min(u["t0"] for u in clip):
            notes.append("вопрос из более позднего места открывает клип (вопрос-петля)")
        out.append(Proposal(
            units=ids, pieces=" ".join(u["refs"] for u in clip),
            hook=_hook(clip, sentences, p) if sentences else None,
            title=_clean(opener.get("summary")), caption=_clean(payoff.get("summary") if payoff is not opener else ""),
            score=max(40, min(95, round(score))), seconds=round(secs, 1), notes=notes))
    out.sort(key=lambda o: -o.score)
    return out[:p.clips]


def _clean(s) -> str:
    return " ".join(str(s or "").replace("|", " ").split())[:90]
