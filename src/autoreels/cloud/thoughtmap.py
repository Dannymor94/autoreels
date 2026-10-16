"""M54: the map of a whole source — what a reel can be built from (docs/REEL_SPEC.md §8, `arl map`).

A review block is a ~40 s cut of the timeline; a reel that uses pieces from different parts of a
lecture needs to know the whole lecture. The map, built once per source:

1. THOUGHTS (units): runs of 1–4 sentences (about 8–30 s) that end on a finished sentence, split at
   pauses. Sentences are the review numbering's (each block's own split), so every sentence of a
   kept block carries its `B.k` — a unit can be written into a montage line as it is.
2. VOICE per unit (measured, local/voice.py): speech level, median pitch and pitch range (how
   expressive), speech rate; `energy` = percentile of their combination within the source (0–100):
   where the speaker comes alive — a hook or a payoff candidate.
3. PASSPORT per unit (LLM, window by window): role in a story (question, thesis, explanation,
   example, metaphor, conclusion, address, aside), strength 1–5 (quotable?), standalone (clear
   without what came before?), refers (the earlier unit it leans on — the «сноска») and a short
   summary. Every unit gets an answer or is retried once, then marked missing (invariant 11).
4. TOPICS (LLM, one request over all summaries): 5–15 themes of the source, each unit in one.
5. SIMILAR (deterministic): character n-gram TF-IDF cosine of unit texts; for every unit the most
   similar units far away in time — pieces of one thought said in different places.

Pure: numbers and text in, a dict out (transcripts/<stem>.map.json). The CLI does the I/O.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Sequence

MAP_VERSION = 1
ROLES = ("question", "thesis", "explanation", "example", "metaphor", "conclusion", "address", "aside")
ROLE_RU = {"question": "вопрос", "thesis": "тезис", "explanation": "объяснение", "example": "пример",
           "metaphor": "образ", "conclusion": "вывод", "address": "обращение", "aside": "служебное"}


@dataclass(frozen=True)
class MapParams:
    unit_min_sec: float = 8.0         # a thought shorter than this takes the next sentence too …
    unit_max_sec: float = 30.0        # … but never grows past this
    unit_max_sents: int = 4
    pause_split_sec: float = 1.0      # a pause this long after a sentence ends a thought (once ≥ min)
    window_units: int = 20            # units per LLM request (plus 2 before as context)
    similar_min: float = 0.30         # cosine from which two units count as similar
    similar_far_sec: float = 60.0     # only units at least this far apart are listed as similar
    similar_top: int = 3


@dataclass
class Sentence:
    words: list
    a: float                          # audible start / end (source seconds)
    b: float
    ref: str | None                   # "B.k" in the review numbering, None for a filtered block
    complete: bool
    block_note: str = ""              # why the block is not in the review numbering (head, tail …)

    @property
    def text(self) -> str:
        return " ".join(w.word for w in self.words)


@dataclass
class Unit:
    id: int
    sents: list[Sentence]
    info: dict = field(default_factory=dict)

    @property
    def t0(self) -> float:
        return self.sents[0].a

    @property
    def t1(self) -> float:
        return self.sents[-1].b

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sents)


def split_units(sents: Sequence[Sentence], p: MapParams = MapParams()) -> list[Unit]:
    """Thoughts: consecutive sentences; a thought closes after a finished sentence once it lasts
    unit_min_sec and a pause of pause_split_sec follows or it has unit_max_sents sentences; it
    closes before a sentence that would take it past unit_max_sec (an unfinished thought then)."""
    units: list[Unit] = []
    cur: list[Sentence] = []
    for i, s in enumerate(sents):
        if cur and s.b - cur[0].a > p.unit_max_sec:
            units.append(Unit(len(units) + 1, cur))
            cur = []
        cur.append(s)
        dur = cur[-1].b - cur[0].a
        nxt = sents[i + 1] if i + 1 < len(sents) else None
        pause = (nxt.a - s.b) if nxt is not None else math.inf
        if s.complete and dur >= p.unit_min_sec and (pause >= p.pause_split_sec or len(cur) >= p.unit_max_sents):
            units.append(Unit(len(units) + 1, cur))
            cur = []
    if cur:
        units.append(Unit(len(units) + 1, cur))
    return units


def unit_refs(u: Unit) -> str:
    """The unit as review numbering: '13.2-5', '13.6-8 14.1-2', or '' (filtered blocks)."""
    out: list[str] = []
    cur_b, a, z = None, None, None
    for s in u.sents:
        if s.ref is None:
            continue
        b, k = s.ref.split(".")
        if b == cur_b and int(k) == z + 1:
            z = int(k)
            continue
        if cur_b is not None:
            out.append(f"{cur_b}.{a}" + (f"-{z}" if z != a else ""))
        cur_b, a, z = b, int(k), int(k)
    if cur_b is not None:
        out.append(f"{cur_b}.{a}" + (f"-{z}" if z != a else ""))
    return " ".join(out)


# ── voice ────────────────────────────────────────────────────────────────────────────────────

def voice_scores(units: Sequence[Unit], measure: Callable[[float, float], dict] | None) -> None:
    """unit.info["voice"] = level_db, pitch_st, range_st, rate (words/s), energy (percentile 0–100 of
    z(level) + z(range) + z(rate) within the source; None when the audio was not measured)."""
    for u in units:
        v = dict(measure(u.t0, u.t1)) if measure is not None else {"level_db": None, "pitch_st": None,
                                                                     "range_st": None}
        n = sum(1 for s in u.sents for w in s.words if any(c.isalnum() for c in w.word))
        v["rate"] = round(n / (u.t1 - u.t0), 2) if u.t1 - u.t0 > 0.5 else None
        u.info["voice"] = v

    def z(key: str) -> dict[int, float]:
        vals = [(u.id, u.info["voice"][key]) for u in units if u.info["voice"].get(key) is not None]
        if len(vals) < 3:
            return {}
        xs = [x for _, x in vals]
        m = sum(xs) / len(xs)
        sd = math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs)) or 1.0
        return {i: (x - m) / sd for i, x in vals}

    zs = [z("level_db"), z("range_st"), z("rate")]
    if not zs[0] and not zs[1]:
        for u in units:
            u.info["voice"]["energy"] = None
        return
    combo = {u.id: sum(d.get(u.id, 0.0) for d in zs) for u in units}
    order = sorted(combo.values())
    for u in units:
        rank = sum(1 for x in order if x < combo[u.id])
        u.info["voice"]["energy"] = round(100.0 * rank / max(1, len(order) - 1))


# ── similarity ───────────────────────────────────────────────────────────────────────────────

def _ngrams(text: str, n: int = 4) -> Counter:
    out: Counter = Counter()
    for w in re.findall(r"[а-яёa-z0-9]+", text.lower().replace("ё", "е")):
        if len(w) < 4:
            continue
        w = f" {w} "
        out.update(w[i:i + n] for i in range(len(w) - n + 1))
    return out


def similar_units(units: Sequence[Unit], p: MapParams = MapParams()) -> None:
    """unit.info["similar"] = [[id, cosine], …]: the most similar units at least similar_far_sec away
    (TF-IDF of character 4-grams of the words — Russian endings change, the stems stay)."""
    grams = [_ngrams(u.text + " " + str(u.info.get("summary") or "")) for u in units]
    df: Counter = Counter()
    for g in grams:
        df.update(g.keys())
    n = len(units)
    vecs = []
    for g in grams:
        v = {k: c * math.log((1 + n) / (1 + df[k])) for k, c in g.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({k: x / norm for k, x in v.items()})
    for i, u in enumerate(units):
        cands = []
        for j, o in enumerate(units):
            if i == j or abs(o.t0 - u.t0) < p.similar_far_sec:
                continue
            a, b = (vecs[i], vecs[j]) if len(vecs[i]) < len(vecs[j]) else (vecs[j], vecs[i])
            sim = sum(x * b.get(k, 0.0) for k, x in a.items())
            if sim >= p.similar_min:
                cands.append((round(sim, 2), o.id))
        u.info["similar"] = [[i2, s] for s, i2 in sorted(cands, reverse=True)[:p.similar_top]]


# ── LLM: passports and topics ────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict | None:
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
                    return obj if isinstance(obj, dict) else None
        start = t.find("{", start + 1)
    return None


def _window_text(units: Sequence[Unit], ctx: Sequence[Unit]) -> str:
    lines = []
    if ctx:
        lines.append("Context (already described, do not describe again):")
        lines += [f"#{u.id} [{_mmss(u.t0)}] {u.text}" for u in ctx]
        lines.append("")
    lines.append("Describe EVERY one of these units:")
    lines += [f"#{u.id} [{_mmss(u.t0)}] {u.text}" for u in units]
    return "\n".join(lines)


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _valid_passport(e: dict, ids: set[int], uid: int) -> dict | None:
    role = str(e.get("role", "")).strip().lower()
    if role not in ROLES:
        return None
    try:
        punch = int(e.get("punch"))
    except (TypeError, ValueError):
        return None
    if not 1 <= punch <= 5:
        return None
    ref = e.get("refers")
    if isinstance(ref, str) and ref.strip().lstrip("#").isdigit():
        ref = int(ref.strip().lstrip("#"))
    if not isinstance(ref, int) or ref not in ids or ref >= uid:
        ref = None
    summary = str(e.get("summary") or "").strip()[:160]
    return {"role": role, "punch": punch, "standalone": bool(e.get("standalone", True)),
            "refers": ref, "summary": summary}


def describe_units(units: Sequence[Unit], provider, *, system: str, p: MapParams = MapParams(),
                   log: Callable[[str], None] = print, known: dict | None = None) -> tuple[int, int]:
    """Passports window by window; unanswered units asked once more, then marked missing.
    `known` (M66): passports already described (a previous, incomplete map) — only the others are asked.
    Returns (described, missing)."""
    ids = {u.id for u in units}
    by_id = {u.id: u for u in units}

    def ask(batch: Sequence[Unit]) -> dict[int, dict]:
        first = units.index(batch[0])
        ctx = units[max(0, first - 2):first]
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": _window_text(batch, ctx)}]
        try:
            raw = provider.complete(msgs, temperature=0.0)
        except Exception as exc:  # noqa: BLE001 — provider down: the units stay unanswered
            log(f"  окно #{batch[0].id}–#{batch[-1].id}: нет ответа ({type(exc).__name__}: {exc})")
            return {}
        obj = _parse_json(raw) or {}
        got: dict[int, dict] = {}
        for e in obj.get("units") or []:
            if not isinstance(e, dict):
                continue
            try:
                uid = int(str(e.get("id", "")).lstrip("#"))
            except ValueError:
                continue
            if uid in {b.id for b in batch}:
                v = _valid_passport(e, ids, uid)
                if v is not None:
                    got[uid] = v
        return got

    done: dict[int, dict] = {uid: v for uid, v in (known or {}).items() if uid in ids}
    todo = [u for u in units if u.id not in done]
    for k in range(0, len(todo), p.window_units):
        batch = list(todo[k:k + p.window_units])
        done.update(ask(batch))
        log(f"  мысли #{batch[0].id}–#{batch[-1].id}: описано {sum(1 for b in batch if b.id in done)} из {len(batch)}")
    missing = [u for u in units if u.id not in done]
    for k in range(0, len(missing), p.window_units):
        done.update(ask(missing[k:k + p.window_units]))
    n_missing = 0
    for u in units:
        if u.id in done:
            u.info.update(done[u.id])
        else:
            u.info.update({"role": None, "punch": None, "standalone": None, "refers": None, "summary": "",
                           "missing": True})
            n_missing += 1
    return len(units) - n_missing, n_missing


def topic_units(units: Sequence[Unit], provider, *, system: str,
                log: Callable[[str], None] = print) -> list[dict]:
    """5–15 topics of the source from the unit summaries; unit.info["topic"] = topic id (0 = other).
    Units the answer leaves out go to topic 0; an id in two topics stays in the first."""
    rows = [f"#{u.id} [{_mmss(u.t0)}] {u.info.get('summary') or u.text[:120]}" for u in units]
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": "TOPICS of the whole source. Units:\n" + "\n".join(rows)}]
    try:
        obj = _parse_json(provider.complete(msgs, temperature=0.0)) or {}
    except Exception as exc:  # noqa: BLE001
        log(f"  темы: нет ответа ({type(exc).__name__}: {exc})")
        obj = {}
    ids = {u.id for u in units}
    topics: list[dict] = []
    seen: set[int] = set()
    for t in obj.get("topics") or []:
        if not isinstance(t, dict) or not str(t.get("name") or "").strip():
            continue
        members = []
        for x in t.get("units") or []:
            try:
                uid = int(str(x).lstrip("#"))
            except ValueError:
                continue
            if uid in ids and uid not in seen:
                members.append(uid)
                seen.add(uid)
        if members:
            topics.append({"id": len(topics) + 1, "name": str(t["name"]).strip()[:60], "units": members})
    rest = [u.id for u in units if u.id not in seen]
    if rest:
        topics.append({"id": 0, "name": "прочее", "units": rest})
    tid = {uid: t["id"] for t in topics for uid in t["units"]}
    for u in units:
        u.info["topic"] = tid.get(u.id, 0)
    log(f"  темы: {sum(1 for t in topics if t['id'])}, без темы {len(rest)} мыслей")
    return topics


def build_map(units: Sequence[Unit], *, stem: str, source_sha256: str, topics: Sequence[dict] = (),
              model: str = "") -> dict:
    return {
        "version": MAP_VERSION, "stem": stem, "source_sha256": source_sha256, "model": model,
        "topics": list(topics),
        "units": [{"id": u.id, "t0": round(u.t0, 3), "t1": round(u.t1, 3), "refs": unit_refs(u),
                   "filtered": next((s.block_note for s in u.sents if s.block_note), ""),
                   "text": u.text, **u.info} for u in units],
    }
