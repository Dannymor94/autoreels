#!/usr/bin/env python3
"""M118 (замер, ничего не пишет): где автоматическая сборка теряет клипы, которые владелец выбрал сам.

    .venv/bin/python handoff/m118/owner_funnel.py

Для каждого источника с ручным выбором (manifests/<источник>.json, selection_source: human), картой мыслей
(transcripts/<источник>.map.json) и черновиком «только правила» (reviews/<источник>_auto_m118-rules.txt — arl autocut
--llm none --no-check --clips 50: всё, что код может предложить без модели) — по каждому клипу владельца:
  A. какие мысли карты он покрывает (мысль считается, если клип покрывает не меньше половины её), их роли и сила;
     есть ли «зерно» — мысль, вокруг которой autocut строит сборку (роль из STORY, сила ≥ seed_punch);
  B. короче ли клип, чем autocut.min_sec;
  C. есть ли среди кандидатов «только правила» сборка с хотя бы одной его мыслью;
  D. приняли ли его начало судьи (handoff/m118/owner_<модель>.jsonl, если есть).
В конце — воронка по всем источникам и причины потерь.
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

from autoreels.cloud.autocut import STORY, eligible, AutoParams
from autoreels.__main__ import load_r0_config


def spans_of(reel: dict) -> list[tuple[float, float]]:
    segs = reel.get("segments") or []
    return [(float(s["start"]), float(s["end"])) for s in segs] or [(float(reel["start"]), float(reel["end"]))]


def overlap(a0: float, a1: float, spans) -> float:
    return sum(max(0.0, min(a1, b1) - max(a0, b0)) for b0, b1 in spans)


def candidates(draft: Path) -> list[set[int]]:
    out, cur = [], None
    if not draft.is_file():
        return out
    for ln in draft.read_text(encoding="utf-8").splitlines():
        if ln.startswith("# --- M"):
            cur = set()
            out.append(cur)
        elif ln.startswith("# --- "):
            cur = None
        elif cur is not None:
            m = re.match(r"^#   #(\d+) ", ln)
            if m:
                cur.add(int(m.group(1)))
    return [c for c in out if c]


def judged() -> dict:
    """(stem, reel id) → {model: ok} from the owner-start benches."""
    base = Path("handoff/m118/owner_starts.jsonl")
    if not base.is_file():
        return {}
    by_msg = {}
    for ln in base.read_text(encoding="utf-8").splitlines():
        r = json.loads(ln)
        by_msg[(r["stem"], r["msg"])] = r["why"].split()[-1]
    out: dict = {}
    for f in sorted(glob.glob("handoff/m118/owner_*.jsonl")):
        name = Path(f).stem.replace("owner_", "")
        if name == "starts":
            continue
        for ln in Path(f).read_text(encoding="utf-8").splitlines():
            r = json.loads(ln)
            rid = by_msg.get((r.get("stem"), r.get("msg")))
            if rid:
                out.setdefault((r["stem"], rid), {})[name] = r.get("ok")
    return out


def main() -> int:
    r0 = load_r0_config(Path("config/r0.yaml"))
    ac = r0.autocut
    p = AutoParams(min_punch=ac.min_punch, seed_punch=ac.seed_punch, use_filtered=ac.use_filtered, min_sec=ac.min_sec)
    jd = judged()
    tot = {"клипов": 0, "с мыслями карты": 0, "с зерном": 0, "не короче min_sec": 0, "есть кандидат": 0}
    why_lost: dict = {}
    judge_tot: dict = {}
    for mp in sorted(glob.glob("manifests/*.json")):
        try:
            m = json.load(open(mp, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict) or m.get("selection_source") != "human":
            continue
        stem = Path(mp).stem
        mjson = Path("transcripts") / f"{stem}.map.json"
        draft = Path("reviews") / f"{stem}_auto_m118-rules.txt"
        if not mjson.is_file():
            print(f"\n=== {stem}: нет карты — пропущен")
            continue
        units = json.loads(mjson.read_text(encoding="utf-8")).get("units") or []
        cands = candidates(draft)
        print(f"\n=== {stem}: клипов владельца {len(m.get('reels') or [])}, мыслей в карте {len(units)}, "
              f"кандидатов «только правила» {len(cands)}" + ("" if draft.is_file() else " (нет черновика)"))
        for r in m.get("reels") or []:
            sp = spans_of(r)
            dur = sum(b - a for a, b in sp)
            us = [u for u in units if u.get("t1") and float(u["t1"]) > float(u["t0"])
                  and overlap(float(u["t0"]), float(u["t1"]), sp) >= 0.5 * (float(u["t1"]) - float(u["t0"]))]
            ids = {u["id"] for u in us}
            seed = [u for u in us if eligible(u, p) and u.get("role") in STORY and int(u.get("punch") or 0) >= p.seed_punch]
            cov = max((len(ids & c) for c in cands), default=0)
            j = jd.get((stem, r.get("id")), {})
            tot["клипов"] += 1
            tot["с мыслями карты"] += bool(us)
            tot["с зерном"] += bool(seed)
            tot["не короче min_sec"] += dur >= p.min_sec
            tot["есть кандидат"] += cov > 0
            for k, v in j.items():
                if v is not None:
                    judge_tot.setdefault(k, [0, 0])
                    judge_tot[k][0] += bool(v)
                    judge_tot[k][1] += 1
            if not us:
                reason = "клип не покрывает ни одной мысли карты целиком"
            elif cov > 0:
                reason = ""
            elif not seed:
                reason = "нет зерна (сильной мысли из STORY)"
            elif dur < p.min_sec:
                reason = f"короче min_sec ({p.min_sec:g} с)"
            else:
                reason = "зерно есть, но кандидата с его мыслями нет"
            if reason:
                why_lost[reason] = why_lost.get(reason, 0) + 1
            roles = " ".join(f"{u.get('role')}★{u.get('punch')}" for u in us) or "—"
            jtxt = " ".join(f"{k}:{'✓' if v else '✗' if v is not None else '?'}" for k, v in sorted(j.items()))
            print(f"   {r.get('id')}: {dur:5.1f} с, мысли {roles}; {'зерно' if seed else 'без зерна'}; "
                  f"{'кандидат ✓ (' + str(cov) + ' общ.)' if cov else 'кандидата нет'}"
                  + (f"; судьи начала: {jtxt}" if jtxt else "") + (f"  ← {reason}" if reason else ""))
    print("\n=== ВОРОНКА (все источники)")
    for k, v in tot.items():
        print(f"   {k:22} {v}")
    print("   причины, по которым кандидата нет:")
    for k, v in sorted(why_lost.items(), key=lambda kv: -kv[1]):
        print(f"     {v:3d} — {k}")
    for k, (a, n) in sorted(judge_tot.items()):
        print(f"   судья {k}: принял начал владельца {a} из {n} ({100 * a / max(1, n):.0f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
