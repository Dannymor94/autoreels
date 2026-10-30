"""M188: per-clip and per-source quality metrics for a gate. Pure functions — no file I/O
except load_gate. Mirrors the pipeline's own rules so the yardstick and the conveyor agree."""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any


# ── shots helper (copied logic from tools/measure_shots.py; that file is not touched) ─────────

def _shots(r: dict) -> list[tuple[float, float, float | None, bool, bool]]:
    """Return (a, z, src, in_cold_open, is_last) for every shot in one reel."""
    segs = (
        ([dict(r["cold_open"], _co=True)] if r.get("cold_open") else []) +
        (r.get("segments") or [{"start": r["start"], "end": r["end"], "shot": "wide"}])
    )
    t, bounds, co_end, spans = 0.0, [0.0], 0.0, []
    for s in segs:
        dur = s["end"] - s["start"]
        if dur <= 1e-6:
            continue
        if t > 1e-6:
            bounds.append(t)
        for c0, c1 in s.get("close_intervals") or []:
            for e in (c0, c1):
                if 1e-3 < e < dur - 1e-3:
                    bounds.append(t + e)
        spans.append((t, s["start"]))
        t += dur
        if s.get("_co"):
            co_end = t
    b = sorted({round(x, 4) for x in bounds}) + [t]
    out = []
    for i, (a, z) in enumerate(zip(b, b[1:])):
        src = next((s0 + (a - t0) for t0, s0 in reversed(spans) if t0 <= a + 1e-6), None)
        out.append((a, z, src, z <= co_end + 1e-6, i == len(b) - 2))
    return out


# ── body helper ──────────────────────────────────────────────────────────────

def _body(r: dict) -> list[dict]:
    """Segments of the body (no cold_open)."""
    segs = r.get("segments")
    if segs:
        return segs
    return [{"start": r["start"], "end": r["end"], "shot": "wide",
             "window_cut": False, "close_intervals": []}]


def _norm_word(w: str) -> str:
    return "".join(c if c.isalnum() else "" for c in w.lower().replace("ё", "е").replace("-", " "))


def _stems_of(text: str) -> set[str]:
    """5-char prefix stems for words of 5+ letters (same as postcopy._stems)."""
    return {w[:5] for w in (_norm_word(x) for x in (text or "").split()) if len(w) >= 5}


# ── score_clip ────────────────────────────────────────────────────────────────

def score_clip(
    reel: dict,
    map_: dict,
    prosody: dict,
    cfg: dict,
) -> dict:
    """Compute all quality fields for one reel dict.

    cfg keys used: short_shot_sec (float), context_min_words (int).
    map_ is the transcripts/<stem>.map.json dict (or {}).
    prosody is the transcripts/<stem>.prosody.json dict (or {}).
    """
    from autoreels.cloud.autocut import back_reference
    from autoreels.local.prosody import classify

    body = _body(reel)
    speed = reel.get("speed") or 1.0
    co = reel.get("cold_open")

    # dur
    body_len = sum(s["end"] - s["start"] for s in body)
    co_len = (co["end"] - co["start"]) if co else 0.0
    dur = (co_len + body_len) / speed

    # hook
    hook = bool(co and co_len > 0)

    # seams, cuts, back_jumps
    seams = cuts = back_jumps = 0
    for prev, nxt in zip(body, body[1:]):
        if nxt.get("window_cut"):
            cuts += 1
        else:
            seams += 1
        if nxt["start"] < prev["start"]:
            back_jumps += 1

    # first_text — words in first body segment, up to first sentence-end
    first_seg = body[0]
    subs = reel.get("subtitles") or []
    first_words = [
        w for w in subs
        if first_seg["start"] - 1e-4 <= w["t0"] <= first_seg["end"] + 1e-4
    ]
    # stop at first word ending with sentence-final punctuation
    cutoff = len(first_words)
    for i, w in enumerate(first_words):
        if w["word"].rstrip()[-1:] in ".?!…":
            cutoff = i + 1
            break
    first_words = first_words[:cutoff]
    first_text = " ".join(w["word"] for w in first_words)

    # start_backref
    start_backref = back_reference(first_text)

    # start_short
    context_min = cfg.get("context_min_words", 0)
    ft_plain = [w for w in first_text.split() if w]
    is_question = first_text.rstrip().endswith("?")
    start_short = bool(
        context_min
        and len(ft_plain) < context_min
        and not is_question
        and first_text.strip()
    )

    # end_tone — last word in last body segment
    last_seg = body[-1]
    last_words = [
        w for w in subs
        if last_seg["start"] - 1e-4 <= w["t0"] <= last_seg["end"] + 1e-4
    ]
    p_words = prosody.get("words") or []
    end_tone = "none"
    if last_words:
        target_t0 = last_words[-1]["t0"]
        # find prosody entry nearest to target_t0 within 0.1s
        best = min(p_words, key=lambda e: abs(e["t0"] - target_t0), default=None)
        if best and abs(best["t0"] - target_t0) <= 0.1:
            tone = classify(best)
            end_tone = tone if tone is not None else "none"

    # short_shots, slivers
    short_shot_sec = cfg.get("short_shot_sec", 0.0)
    short_shots = slivers = 0
    for a, z, _, in_co, is_last in _shots(reel):
        if in_co or is_last:
            continue
        d = z - a
        if d < 0.2:
            slivers += 1
        elif short_shot_sec and d < short_shot_sec:
            short_shots += 1

    # warnings — group by prefix (up to first ":", "(", "—", trimmed to 40 chars)
    warnings: dict[str, int] = {}
    for w in reel.get("warnings") or []:
        import re
        prefix = re.split(r"[:(—]", w)[0].strip()[:40]
        warnings[prefix] = warnings.get(prefix, 0) + 1

    # units from map
    units_raw = (map_ or {}).get("units") or []
    # compute out_time for each body segment (cumulative from 0)
    seg_out_times = []
    t = 0.0
    for s in body:
        seg_out_times.append(t)
        t += s["end"] - s["start"]

    def _overlap(u_t0, u_t1, seg):
        o = min(u_t1, seg["end"]) - max(u_t0, seg["start"])
        return max(0.0, o)

    matched_units = []  # (first_out_time, unit_dict)
    for u in units_raw:
        u_t0, u_t1 = u.get("t0", 0.0), u.get("t1", 0.0)
        u_len = u_t1 - u_t0
        if u_len <= 0:
            continue
        total_overlap = sum(_overlap(u_t0, u_t1, s) for s in body)
        if total_overlap / u_len < 0.5:
            continue
        # find first segment that overlaps this unit
        first_out = None
        for i, s in enumerate(body):
            if _overlap(u_t0, u_t1, s) > 0:
                first_out = seg_out_times[i]
                break
        matched_units.append((first_out or 0.0, u))

    matched_units.sort(key=lambda x: x[0])
    units = [u for _, u in matched_units]

    # open_role, close_role
    open_role = any(u.get("role") in ("question", "thesis") for u in units[:2])
    close_role = any(u.get("role") == "conclusion" for u in units[-2:])

    # closure
    closure: int | None = None
    if len(units) >= 2:
        stems_first = _stems_of(units[0].get("text", ""))
        stems_last = _stems_of(units[-1].get("text", ""))
        closure = len(stems_first & stems_last)

    # topics
    topics = len({u.get("topic") for u in units if u.get("topic") is not None})

    # punch_mean
    punches = [u.get("punch") for u in units if u.get("punch") is not None]
    punch_mean = statistics.mean(punches) if punches else None

    return {
        "id": reel.get("id"),
        "dur": dur,
        "hook": hook,
        "seams": seams,
        "cuts": cuts,
        "back_jumps": back_jumps,
        "first_text": first_text,
        "start_backref": start_backref,
        "start_short": start_short,
        "end_tone": end_tone,
        "short_shots": short_shots,
        "slivers": slivers,
        "warnings": warnings,
        "units": units,
        "open_role": open_role,
        "close_role": close_role,
        "closure": closure,
        "topics": topics,
        "punch_mean": punch_mean,
    }


# ── summarize ─────────────────────────────────────────────────────────────────

def summarize(clips: list[dict]) -> dict:
    """Aggregate per-clip dicts into per-source/per-gate summary."""
    n = len(clips)
    if not n:
        return {"n": 0}

    durs = [c["dur"] for c in clips]
    total_dur_min = sum(durs) / 60.0

    def pct(key, val=None):
        if val is None:
            return round(100.0 * sum(1 for c in clips if c.get(key)) / n, 1)
        return round(100.0 * sum(1 for c in clips if c.get(key) == val) / n, 1)

    # per-minute rates need total rendered duration
    total_rendered_min = total_dur_min or 1e-9
    seams_per_min = round(sum(c["seams"] for c in clips) / total_rendered_min, 2)
    cuts_per_min = round(sum(c["cuts"] for c in clips) / total_rendered_min, 2)

    # top-5 warning kinds
    all_warnings: dict[str, int] = {}
    for c in clips:
        for k, v in (c.get("warnings") or {}).items():
            all_warnings[k] = all_warnings.get(k, 0) + v
    top_warnings = sorted(all_warnings.items(), key=lambda x: -x[1])[:5]

    return {
        "n": n,
        "dur_median": round(statistics.median(durs), 2),
        "dur_min": round(min(durs), 2),
        "dur_max": round(max(durs), 2),
        "hook_pct": pct("hook"),
        "start_backref_pct": round(100.0 * sum(1 for c in clips if c.get("start_backref")) / n, 1),
        "start_short_pct": pct("start_short"),
        "end_open_pct": pct("end_tone", "open"),
        "end_none_pct": pct("end_tone", "none"),
        "open_role_pct": pct("open_role"),
        "close_role_pct": pct("close_role"),
        "one_topic_pct": round(100.0 * sum(1 for c in clips if c.get("topics") == 1) / n, 1),
        "closure_pct": round(100.0 * sum(1 for c in clips if (c.get("closure") or 0) >= 1) / n, 1),
        "seams_per_min": seams_per_min,
        "cuts_per_min": cuts_per_min,
        "back_jumps": sum(c["back_jumps"] for c in clips),
        "short_shots": sum(c["short_shots"] for c in clips),
        "slivers": sum(c["slivers"] for c in clips),
        "top_warnings": top_warnings,
    }


# ── coverage ──────────────────────────────────────────────────────────────────

def coverage(owner_reels: list[dict], gate_reels: list[dict]) -> dict:
    """How many owner clips are found in gate_reels.

    A clip is 'found' when a gate reel's body windows overlap with the owner's body windows
    by >= 50% of the shorter clip's total body length.  Each gate reel counts at most once.

    Returns keys: found, total, matched, missed, best.
    - matched: list of [owner_idx, gate_idx, frac] for found pairs
    - missed:  list of owner_idx not found
    - best:    for every owner_idx, [gate_idx, frac] of the gate clip with highest overlap
               (even below 50%); [None, 0.0] if no gate clip overlaps at all
    """
    def _body_len(r):
        return sum(s["end"] - s["start"] for s in _body(r))

    def _overlap_len(r1, r2):
        total = 0.0
        for s1 in _body(r1):
            for s2 in _body(r2):
                total += max(0.0, min(s1["end"], s2["end"]) - max(s1["start"], s2["start"]))
        return total

    n_owner = len(owner_reels)

    # All (owner_idx, gate_idx, frac) pairs — even below 0.5
    all_pairs: list[tuple[float, int, int]] = []
    for oi, ow in enumerate(owner_reels):
        ow_len = _body_len(ow)
        for gi, gr in enumerate(gate_reels):
            gr_len = _body_len(gr)
            shorter = min(ow_len, gr_len)
            if shorter <= 0:
                continue
            ov = _overlap_len(ow, gr)
            frac = ov / shorter
            all_pairs.append((frac, oi, gi))

    # best per owner (highest frac regardless of threshold)
    best: list[list] = [[None, 0.0] for _ in range(n_owner)]
    for frac, oi, gi in all_pairs:
        if frac > best[oi][1]:
            best[oi] = [gi, round(frac, 4)]

    # greedy match: only pairs >= 0.5, each gate clip at most once
    candidates = sorted(
        ((frac, oi, gi) for frac, oi, gi in all_pairs if frac >= 0.5),
        reverse=True,
    )
    used_gate: set[int] = set()
    found_owner: set[int] = set()
    matched: list[list] = []
    for frac, oi, gi in candidates:
        if gi in used_gate or oi in found_owner:
            continue
        used_gate.add(gi)
        found_owner.add(oi)
        matched.append([oi, gi, round(frac, 4)])

    missed = [oi for oi in range(n_owner) if oi not in found_owner]

    return {
        "found": len(found_owner),
        "total": n_owner,
        "matched": matched,
        "missed": missed,
        "best": best,
    }


# ── verdicts ──────────────────────────────────────────────────────────────────

def verdicts(rows: list[dict], gate: str) -> dict:
    """Aggregate verdicts.jsonl rows for the given gate."""
    gate_rows = [r for r in rows if r.get("gate") == gate]
    by_verdict: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    for r in gate_rows:
        v = r.get("verdict")
        if v:
            by_verdict[v] = by_verdict.get(v, 0) + 1
        for reason in r.get("reasons") or []:
            by_reason[reason] = by_reason.get(reason, 0) + 1
    return {
        "total_rows": len(rows),
        "gate_rows": len(gate_rows),
        "by_verdict": by_verdict,
        "by_reason": by_reason,
    }


# ── load_gate ─────────────────────────────────────────────────────────────────

def load_gate(root: str | Path, gate: str) -> dict[str, list[dict]]:
    """Load all reviews/<stem>_<gate>.review.json files.  Returns {stem: [reel, ...]}.

    Also loads map and prosody for each stem when present.
    """
    root = Path(root)
    result: dict[str, dict] = {}
    for path in sorted((root / "reviews").glob(f"*_{gate}.review.json")):
        stem = path.name.replace(f"_{gate}.review.json", "")
        review = json.loads(path.read_text(encoding="utf-8"))
        map_path = root / "transcripts" / f"{stem}.map.json"
        prosody_path = root / "transcripts" / f"{stem}.prosody.json"
        result[stem] = {
            "reels": review.get("reels") or [],
            "map": json.loads(map_path.read_text(encoding="utf-8")) if map_path.exists() else {},
            "prosody": json.loads(prosody_path.read_text(encoding="utf-8")) if prosody_path.exists() else {},
        }
    return result
