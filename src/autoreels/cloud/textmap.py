"""M208: the map's passport and topics without a model.

The thoughts of a map (cloud/thoughtmap.py) are already cut by code — runs of 1–4 sentences at pauses — and their
voice energy and the similar places are measured by code. A model gave only the PASSPORT (role, strength 1–5, standalone,
refers, summary) and the TOPICS. Owner, 2026-11-02: deterministic mechanics, no paid API. Here both by rules:

- role: question («?»), example («например», «однажды», «помню», «был случай» …), metaphor («как будто», «словно»,
  «представьте» …), conclusion («поэтому», «итак», «в итоге», «получается» …), explanation («потому что», «то есть»,
  «дело в том» …), aside (fewer than 3 content words), otherwise thesis — the first marker found in this order wins;
- strength 1–5: a raw score — short sentences (median ≤ 12 words), a contrast («не …, а …»), a generalization
  («всегда», «никогда», «главное», «самое» …), the voice's energy, the role — then by rank within the source: 5 for the
  top 10 %, 4 the next 20 %, 3 the next 30 %, 2 the next 25 %, 1 the rest (PUNCH_SHARES); an aside is 1;
- standalone: the first sentence opens as a reel may open (the start rules of autocut: no reference back, no verb
  without a subject); refers — the previous thought when not standalone;
- summary: the thought's sentence with the most of its content words, fillers dropped, ≤ 160 characters;
- topics: TextTiling over lemmas — the cohesion of the thoughts before and after each gap; the deepest valleys are the
  topic borders, about one topic per 8 thoughts (3 … 15), none shorter than 3 thoughts.

Pure: a map dict in, a new map dict out (`passport: rules`); the cut, the times, the voice and `similar` stay."""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Sequence

_WORD = re.compile(r"[а-яёa-z0-9-]+", re.IGNORECASE)
_SENT = re.compile(r"(?<=[.!?…])\s+")
_CONTENT = frozenset({"NOUN", "ADJF", "ADJS", "COMP", "VERB", "INFN", "PRTF", "PRTS", "GRND", "NUMR", "ADVB"})
_STOP = frozenset("это вот так как что там тут уже еще ещё очень просто ну да нет вообще быть есть был была было были "
                  "который которая которое которые свой своя свое своё весь вся всё все тот та то те этот эта эти "
                  "такой такая такое такие себя мочь сказать говорить делать".split())
# the order is the precedence: the first role whose marker is in the thought wins
_ROLE_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("example", ("например", "однажды", "помню", "был случай", "как-то раз", "вот у меня", "у меня была",
                 "у меня был", "приходит ко мне", "пришла ко мне", "пришёл ко мне", "пришел ко мне", "история")),
    ("metaphor", ("как будто", "словно", "будто", "представьте", "представь", "это как", "как если бы")),
    ("conclusion", ("поэтому", "итак", "в итоге", "получается", "в общем", "в результате", "вывод", "таким образом",
                    "и вот поэтому", "значит,")),
    ("explanation", ("потому что", "так как", "то есть", "дело в том", "это значит", "это потому", "из-за того")),
)
_GENERAL = ("всегда", "никогда", "главное", "самое", "каждый", "любой", "никто", "все люди", "на самом деле",
            "важно", "нельзя", "нужно")
# not «как бы», «значит», «то есть»: they carry meaning too («как бы вы ни …», «это значит …»)
_FILLERS = ("в общем", "в принципе", "собственно", "буквально", "просто", "вот", "ну", "короче", "понимаете",
            "смотрите", "знаете", "кстати", "типа")

_morph_cache: list = []


def _morph():
    if not _morph_cache:
        try:
            import pymorphy3
            _morph_cache.append(pymorphy3.MorphAnalyzer())
        except Exception:  # noqa: BLE001 — no package: words as they are, every word counts as content
            _morph_cache.append(None)
    return _morph_cache[0]


def _lemmas(text: str) -> list[str]:
    m = _morph()
    out = []
    for w in _WORD.findall(text.lower().replace("ё", "е")):
        if len(w) < 3 or w in _STOP:
            continue
        if m is None:
            out.append(w)
            continue
        p = m.parse(w)[0]
        if p.tag.POS in _CONTENT and p.normal_form not in _STOP:
            out.append(p.normal_form)
    return out


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text or "") if s.strip()]


def _has(text: str, marker: str) -> bool:
    return re.search(r"(?<![а-яё])" + re.escape(marker) + r"(?![а-яё])", text) is not None


def rule_role(text: str) -> str:
    low = " " + (text or "").lower().replace("ё", "е") + " "
    sents = _sentences(text)
    if sents and sents[-1].rstrip("»\"') ").endswith("?"):
        return "question"
    for role, markers in _ROLE_MARKERS:
        if any(_has(low, m.replace("ё", "е")) for m in markers):
            return role
    if len(_lemmas(text)) < 3:
        return "aside"
    return "thesis"


def punch_raw(text: str, role: str, energy) -> float:
    """The strength before ranking: short sentences, a contrast, a generalization, the voice's energy, the role."""
    low = (text or "").lower().replace("ё", "е")
    sents = _sentences(text) or [text or ""]
    lens = sorted(len(_WORD.findall(s)) for s in sents)
    s = 0.0
    s += lens[len(lens) // 2] <= 12
    s += re.search(r"(?<![а-я])не\s[^.!?]{1,60}?,\s*а\s", low) is not None
    s += any(_has(low, g) for g in _GENERAL)
    if isinstance(energy, (int, float)):
        s += (float(energy) - 50.0) / 25.0
    s += 0.5 if role in ("conclusion", "thesis", "question", "metaphor") else 0.0
    return s - (3.0 if role == "aside" else 0.0)


# the strength by rank within the source — the share of thoughts with 5, 4, 3, 2 (the rest 1); seed_punch 4 = the top 30 %
PUNCH_SHARES = (0.10, 0.20, 0.30, 0.25)


def rank_punch(raws: Sequence[float], roles: Sequence[str]) -> list[int]:
    n = len(raws)
    order = sorted(range(n), key=lambda i: (-raws[i], i))
    out = [1] * n
    edges, acc = [], 0.0
    for share in PUNCH_SHARES:
        acc += share
        edges.append(round(acc * n))
    for rank, i in enumerate(order):
        out[i] = 5 - next((k for k, e in enumerate(edges) if rank < e), len(edges))
    return [1 if roles[i] == "aside" else max(1, out[i]) for i in range(n)]


def rule_standalone(text: str) -> bool:
    from autoreels.cloud.autocut import back_reference
    first = (_sentences(text) or [""])[0]
    if back_reference(first):
        return False
    try:
        from autoreels.cloud.clipcheck import start_morph
        return start_morph(first.split()) is None
    except Exception:  # noqa: BLE001 — no pymorphy3: the lexical rule alone
        return True


def rule_summary(text: str, limit: int = 160) -> str:
    sents = _sentences(text) or [text or ""]
    best = max(sents, key=lambda s: (len(set(_lemmas(s))), -sents.index(s)))
    s = " " + best + " "
    for f in _FILLERS:
        s = re.sub(r"(?i)(?<=[\s,—])" + re.escape(f) + r"(?=[\s,.!?—])", "", s)
    s = re.sub(r"\s*,\s*(,\s*)+", ", ", s)
    s = re.sub(r"\s+", " ", s).strip(" ,—")
    s = s[:1].upper() + s[1:]
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


def _cos(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    num = sum(a[k] * b[k] for k in a.keys() & b.keys())
    return num / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


def rule_topics(texts: Sequence[str], *, per_topic: int = 8, min_len: int = 3, window: int = 3,
                lo: int = 3, hi: int = 15) -> list[int]:
    """TextTiling: topic ids 1..T, contiguous, one per thought."""
    n = len(texts)
    if n == 0:
        return []
    want = max(lo, min(hi, round(n / per_topic))) if n >= lo * min_len else 1
    bags = [Counter(_lemmas(t)) for t in texts]
    gaps = []                                 # gap i = between thought i-1 and i
    for i in range(1, n):
        left = sum((bags[j] for j in range(max(0, i - window), i)), Counter())
        right = sum((bags[j] for j in range(i, min(n, i + window))), Counter())
        gaps.append((i, _cos(left, right)))
    sims = [s for _, s in gaps]
    depth = []
    for k, (i, s) in enumerate(gaps):
        lpeak = max(sims[:k + 1])
        rpeak = max(sims[k:])
        depth.append((lpeak - s) + (rpeak - s))
    order = sorted(range(len(gaps)), key=lambda k: (-depth[k], gaps[k][0]))
    cuts: list[int] = []
    for k in order:
        if len(cuts) >= want - 1:
            break
        i = gaps[k][0]
        if i < min_len or n - i < min_len or any(abs(i - c) < min_len for c in cuts):
            continue
        cuts.append(i)
    cuts.sort()
    out, tid, nxt = [], 1, 0
    for i in range(n):
        if nxt < len(cuts) and i == cuts[nxt]:
            tid += 1
            nxt += 1
        out.append(tid)
    return out


def apply_rules(the_map: dict) -> dict:
    """A copy of the map with the passport and the topics by rules (`passport: rules`)."""
    units = [dict(u) for u in the_map.get("units") or []]
    prev_id = None
    raws = []
    for u in units:
        text = str(u.get("text") or "")
        role = rule_role(text)
        standalone = rule_standalone(text)
        raws.append(punch_raw(text, role, (u.get("voice") or {}).get("energy")))
        u.update(role=role, standalone=standalone, refers=None if standalone else prev_id, summary=rule_summary(text))
        u.pop("missing", None)
        prev_id = u.get("id")
    for u, pn in zip(units, rank_punch(raws, [u["role"] for u in units])):
        u["punch"] = pn
    tids = rule_topics([str(u.get("text") or "") for u in units])
    for u, t in zip(units, tids):
        u["topic"] = t
    topics = []
    for t in sorted(set(tids)):
        mem = [u for u in units if u["topic"] == t]
        bag = Counter(l for u in mem for l in _lemmas(str(u.get("text") or "")))
        name = ", ".join(w for w, _ in bag.most_common(3)) or f"тема {t}"
        topics.append({"id": t, "name": name, "units": [u["id"] for u in mem]})
    return {**the_map, "units": units, "topics": topics, "passport": "rules"}
