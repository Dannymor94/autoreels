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
    # M65: interesting, hooky reels
    loop: bool = True                 # open on a question the clip answers (from anywhere in the source)
    loop_max_sec: float = 20.0        # … a question unit at most this long
    prune: bool = True                # drop the weakest middle thoughts down to target_sec (+ prune_slack)
    prune_slack: float = 8.0
    hook_min_sec: float = 1.5         # a hook shorter than this is a fragment
    speed_slow_rate: float = 2.3      # words/s below this → @speed_slow
    speed_slow: float = 1.08
    speed_mid_rate: float = 2.6       # … below this → @speed_mid
    speed_mid: float = 1.05


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
    hooks: list[str] = field(default_factory=list)      # M61: all hook candidates, best first
    speed: float | None = None                          # M65: @speed by the clip's speech rate
    hook_texts: dict = field(default_factory=dict)      # M65: hook ref → (text, feature score) for ranking

    def line(self, label: str) -> str:
        sp = f"@{self.speed:g}" if self.speed else ""
        parts = [f"M{label} {self.score}{sp}", self.pieces]
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


_CONTRAST = ("на самом деле", "но ", "однако", "а вот", "парадокс", "наоборот", "вместо того", "не потому")
_STRONG = ("никогда", "всегда", "главное", "главная", "секрет", "ошибк", "важно", "самое", "страх", "боль",
           "любов", "счасть", "правд", "смерт", "деньг")
_YOU = ("вы", "вам", "вас", "ваш", "ваша", "ваше", "ваши", "ты", "тебе", "тебя", "твой", "твоя", "твоё", "твои")
_WEAK_START = ("и", "а", "это", "поэтому", "вот", "ну", "так", "то", "тоже", "потом", "тогда", "он", "она", "они")


def hook_score(text: str, sec: float, unit: dict | None = None) -> float:
    """M65: how likely a sentence makes a viewer stay (deterministic): a question, a contrast, a
    number, «вы», strong words, the voice's energy and the thought's strength; a sentence that leans
    back («И…», «Это…», «Поэтому…») or is a fragment scores low."""
    t = " " + " ".join((text or "").lower().replace("ё", "е").split()) + " "
    words = [w.strip(".,!?;:…—–«»\"'()") for w in t.split()]
    s = 0.0
    if t.rstrip().endswith("?"):
        s += 3.0
    if any(m in t for m in _CONTRAST):
        s += 2.0
    if any(ch.isdigit() for ch in t):
        s += 1.5
    if any(w in _YOU for w in words):
        s += 1.0
    if any(m in t for m in _STRONG):
        s += 1.0
    if words and words[0] in _WEAK_START and not t.rstrip().endswith("?"):
        s -= 2.0                          # «А вы знаете…?» is a fine opening; «И это так.» is not
    if 2.5 <= sec <= 6.0:
        s += 1.0
    elif sec < 1.5:
        s -= 2.0
    if unit:
        s += float((unit.get("voice") or {}).get("energy") or 50.0) / 50.0 + 0.5 * int(unit.get("punch") or 0)
    return round(s, 2)


def _sent_rows(sentences, refs):
    """sentences(refs) rows → (ref, sec, nwords, complete, text) (text optional in older callers)."""
    for row in sentences(refs):
        ref, sec, nwords, complete = row[:4]
        yield ref, sec, nwords, complete, (row[4] if len(row) > 4 else "")


def _hook_cands(clip: Sequence[dict], sentences, p: AutoParams) -> list[tuple[str, float, str]]:
    """(ref, score, text) of every hook candidate, best first: finished sentences of hook length of the
    clip's thoughts. When a question opens the clip (the loop), its own sentences are left out — the
    cold open then teases the answer instead of repeating the question."""
    skip = clip[0]["id"] if clip and clip[0].get("role") == "question" and len(clip) > 1 else None
    out = []
    for u in clip:
        if u["id"] == skip or int(u.get("punch") or 0) < p.min_punch:
            continue
        for ref, sec, nwords, complete, text in _sent_rows(sentences, u["refs"]):
            if complete and nwords >= p.hook_min_words and p.hook_min_sec <= sec <= p.hook_max_sec:
                bonus = 1.0 if u.get("role") in HOOK_ROLES else 0.0
                out.append((ref, hook_score(text, sec, u) + bonus, text))
    return sorted(out, key=lambda x: -x[1])


def _hooks(clip: Sequence[dict], sentences, p: AutoParams) -> list[str]:
    """Hook candidates, best first (M61: the check falls back to the next one when the plan skips one)."""
    return [r for r, _, _ in _hook_cands(clip, sentences, p)]


def _hook(clip, sentences, p) -> str | None:
    h = _hooks(clip, sentences, p)
    return h[0] if h else None


def _loop_question(clip: list[dict], units: Sequence[dict], by_id: dict, p: AutoParams,
                   taken: set[int]) -> dict | None:
    """M65: a question the clip answers — one a chosen thought leans on, else one of the clip's topic
    (or «similar» to its seed); short, standalone enough, not used elsewhere."""
    ids = {u["id"] for u in clip}
    leaned = {i for u in clip for i in leans_on(u, by_id)}
    topics = {u.get("topic") for u in clip}
    sims = {i for u in clip for i, _ in (u.get("similar") or [])}
    best, best_s = None, 0.0
    for q in units:
        if (q.get("role") != "question" or q["id"] in ids or q["id"] in taken or not eligible(q, p)
                or _dur(q) > p.loop_max_sec):
            continue
        s = 3.0 * (q["id"] in leaned) + 1.5 * (q.get("topic") in topics) + 1.0 * (q["id"] in sims)
        if s <= 0:
            continue
        s += 0.5 * int(q.get("punch") or 0)
        if s > best_s:
            best, best_s = q, s
    return best


def _prune(clip: list[dict], by_id: dict, p: AutoParams) -> tuple[list[dict], list[int]]:
    """M65: drop the weakest middle thoughts (not the opener, not the payoff, nothing another chosen
    thought leans on) while the clip is longer than target_sec + prune_slack and stays ≥ min_sec."""
    dropped: list[int] = []
    while sum(_dur(u) for u in clip) > p.target_sec + p.prune_slack and len(clip) > 2:
        needed = {i for u in clip for i in leans_on(u, by_id)}
        middle = [u for u in clip[1:-1] if u["id"] not in needed]
        if not middle:
            break
        weak = min(middle, key=lambda u: (int(u.get("punch") or 0),
                                          float((u.get("voice") or {}).get("energy") or 50.0)))
        if sum(_dur(u) for u in clip) - _dur(weak) < p.min_sec:
            break
        clip = [u for u in clip if u is not weak]
        dropped.append(weak["id"])
    return clip, dropped


def _speed(clip: Sequence[dict], p: AutoParams) -> float | None:
    """M65: @speed by the clip's speech rate (map voice.rate, words/s, weighted by duration)."""
    rated = [(float((u.get("voice") or {}).get("rate") or 0.0), _dur(u)) for u in clip]
    tot = sum(d for r, d in rated if r > 0)
    if tot <= 0:
        return None
    rate = sum(r * d for r, d in rated if r > 0) / tot
    if rate < p.speed_slow_rate:
        return p.speed_slow
    if rate < p.speed_mid_rate:
        return p.speed_mid
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
        extra_notes: list[str] = []
        if p.loop and clip[0].get("role") != "question":
            taken = {i for o in out for i in o.units}
            q = _loop_question(clip, units, by_id, p, taken)
            if q is not None and sum(_dur(u) for u in clip) + _dur(q) <= p.max_sec \
                    and _pieces([q] + clip) <= p.max_pieces + 1:
                clip = [q] + clip
                extra_notes.append(f"вопрос-петля: #{q['id']} «{q.get('summary') or ''}» открывает, ответ — в конце")
        if p.prune:
            clip, dropped = _prune(clip, by_id, p)
            if dropped:
                extra_notes.append("убраны слабые мысли из середины: " + ", ".join(f"#{i}" for i in dropped))
        ids = [u["id"] for u in clip]
        if any(len(set(ids) & set(o.units)) > p.overlap_max * min(len(ids), len(o.units))
               or ids[-1] == o.units[-1] for o in out):
            continue                      # M61: nor two clips with the same payoff (IMG_6848 M1/M4)
        used_seeds.update(i for i in ids if by_id[i].get("role") in STORY)
        secs = sum(_dur(u) for u in clip)
        roles = [u.get("role") for u in clip]
        punch = sum(int(u.get("punch") or 0) for u in clip) / len(clip)
        energy = sum(float((u.get("voice") or {}).get("energy") or 50.0) for u in clip) / len(clip)
        cover = 5 * bool(set(roles) & set(OPENERS)) + 5 * bool(set(roles) & set(MIDDLE)) + 5 * ("conclusion" in roles)
        loop = clip[0].get("role") == "question" and clip[-1].get("role") in PAYOFFS
        over = max(0.0, secs - p.target_sec)
        score = 15 * punch + 0.15 * energy + cover - 4 * (_pieces(clip) - 1) + 10 * loop - 0.2 * over
        opener = next((u for u in clip if u.get("role") in OPENERS), clip[0])
        payoff = next((u for u in reversed(clip) if u.get("role") in PAYOFFS), clip[-1])
        notes = [f"#{u['id']} {u.get('role')}★{u.get('punch')} {u['refs']} — {u.get('summary') or ''}" for u in clip]
        notes += extra_notes
        cands = _hook_cands(clip, sentences, p) if sentences else []
        if clip[0].get("role") == "question" and clip[0]["t0"] > min(u["t0"] for u in clip):
            notes.append("вопрос из более позднего места открывает клип (вопрос-петля)")
        out.append(Proposal(
            units=ids, pieces=" ".join(u["refs"] for u in clip),
            hook=cands[0][0] if cands else None, hooks=[r for r, _, _ in cands],
            hook_texts={r: (t, sc) for r, sc, t in cands}, speed=_speed(clip, p),
            title=_clean(opener.get("summary")), caption=_clean(payoff.get("summary") if payoff is not opener else ""),
            score=max(40, min(95, round(score))), seconds=round(secs, 1), notes=notes))
    out.sort(key=lambda o: -o.score)
    return out[:p.clips]


def _clean(s) -> str:
    return " ".join(str(s or "").replace("|", " ").split())[:90]



HOOK_SYSTEM = (
    "You pick the opening line (the cold open) of a short vertical video (a reel, 30–60 s) cut from a "
    "Russian talk. The first 2–3 seconds decide whether a viewer stays. Prefer a line that opens a "
    "question in the viewer's head or promises a payoff: a surprising claim, a contrast, a concrete "
    "number, a direct «вы», a strong feeling. Avoid lines that depend on what came before («Это…», "
    "«Поэтому…»), greetings and fragments. Answer only with JSON: {\"best\": <number>, \"why\": \"<at most 12 "
    "Russian words>\"}."
)


def rank_hooks(pr: "Proposal", provider, *, top: int = 6, log: Callable[[str], None] = print) -> bool:
    """M65: the LLM picks the best of the top hook candidates (invariant 1: it only ranks the
    deterministic candidates; an answer outside them is retried once, then the code's order stays).
    Returns True when the order changed."""
    import json as _json
    import re as _re
    cands = pr.hooks[:top]
    if len(cands) < 2:
        return False
    rows = [f"{i + 1}. {pr.hook_texts.get(r, ('', 0))[0]}" for i, r in enumerate(cands)]
    msg = (f"Reel: «{pr.title}». Thoughts: " + "; ".join(n.split(" — ", 1)[-1] for n in pr.notes[:6]) +
           "\nCandidates:\n" + "\n".join(rows))
    for _ in range(2):
        try:
            raw = provider.complete([{"role": "system", "content": HOOK_SYSTEM}, {"role": "user", "content": msg}],
                                    temperature=0.0)
        except Exception as exc:  # noqa: BLE001 — no model: the code's order stays
            log(f"  крючок: модель не ответила ({type(exc).__name__})")
            return False
        m = _re.search(r"\{.*\}", raw or "", _re.S)
        try:
            obj = _json.loads(m.group(0)) if m else {}
            best = int(obj.get("best"))
        except (ValueError, TypeError):
            continue
        if 1 <= best <= len(cands):
            chosen = cands[best - 1]
            why = str(obj.get("why") or "").strip()[:80]
            if chosen != pr.hooks[0]:
                pr.hooks = [chosen] + [h for h in pr.hooks if h != chosen]
                pr.hook = chosen
                pr.notes.append(f"крючок выбран моделью: h:{chosen}" + (f" — {why}" if why else ""))
                return True
            return False
    log("  крючок: ответ модели вне кандидатов — порядок кода")
    return False
