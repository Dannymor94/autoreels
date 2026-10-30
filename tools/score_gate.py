"""M188/M191: one table per gate. Usage:
    python tools/score_gate.py <gate> [--compare <gate2>] [--ref <ref_gate>] [--stems a,b]
Reads reviews/, manifests/, transcripts/, config/r0.yaml, reviews/verdicts.jsonl.
Writes reels-out/_score/<gate>.json (and <gate2>.json for --compare).
--ref: show which ref_gate clips a gate finds (and which it misses).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from autoreels.cloud.gatescore import coverage, load_gate, score_clip, summarize, verdicts
from autoreels.core.config import load_r0_config


# ── helpers ───────────────────────────────────────────────────────────────────

def _cfg_dict(cfg) -> dict:
    return {
        "short_shot_sec": cfg.short_shot_sec,
        "context_min_words": cfg.autocut.context_min_words,
    }


def _load_verdicts(root: Path) -> list[dict]:
    p = root / "reviews" / "verdicts.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _load_owner_reels(root: Path, stem: str) -> list[dict] | None:
    p = root / "manifests" / f"{stem}.json"
    if not p.exists():
        return None
    m = json.loads(p.read_text(encoding="utf-8"))
    if m.get("selection_source") != "human":
        return None
    return m.get("reels") or []


def _score_gate(root: Path, gate: str, stems_filter: list[str] | None = None) -> dict:
    """Score all review files for a gate. Returns full results dict."""
    cfg = load_r0_config(root / "config" / "r0.yaml")
    c = _cfg_dict(cfg)
    gate_data = load_gate(root, gate)

    if stems_filter:
        gate_data = {s: v for s, v in gate_data.items() if s in stems_filter}

    v_rows = _load_verdicts(root)

    per_stem: dict[str, dict] = {}
    for stem, data in sorted(gate_data.items()):
        map_ = data["map"]
        prosody = data["prosody"]
        clips = [score_clip(r, map_, prosody, c) for r in data["reels"]]

        owner_reels = _load_owner_reels(root, stem)
        cov = coverage(owner_reels, [r for r in data["reels"]]) if owner_reels is not None else None

        per_stem[stem] = {
            "clips": clips,
            "summary": summarize(clips),
            "coverage": cov,
        }

    all_clips = [cl for s in per_stem.values() for cl in s["clips"]]
    total_summary = summarize(all_clips)

    # aggregate coverage
    total_found = total_owner = 0
    for s in per_stem.values():
        cov = s.get("coverage")
        if cov is not None:
            total_found += cov["found"]
            total_owner += cov["total"]
    total_cov = {"found": total_found, "total": total_owner} if total_owner else None

    v_data = verdicts(v_rows, gate)

    # worst clips: score by number of problems
    def _problem_score(c):
        return (
            bool(c.get("start_backref"))
            + bool(c.get("start_short"))
            + (c.get("end_tone") == "open")
            + (not c.get("close_role"))
            + (c.get("topics", 1) > 1)
            + c.get("short_shots", 0)
        )

    all_clips_with_stem = [
        (stem, cl)
        for stem, s in per_stem.items()
        for cl in s["clips"]
    ]
    worst = sorted(all_clips_with_stem, key=lambda x: -_problem_score(x[1]))[:5]

    return {
        "gate": gate,
        "per_stem": per_stem,
        "total": total_summary,
        "coverage": total_cov,
        "verdicts": v_data,
        "worst": [
            {
                "stem": stem,
                "id": cl["id"],
                "problems": _problem_score(cl),
                "reasons": _explain(cl),
            }
            for stem, cl in worst
        ],
    }


def _explain(c: dict) -> list[str]:
    reasons = []
    if c.get("start_backref"):
        reasons.append(f"ссылка_назад({c['start_backref']})")
    if c.get("start_short"):
        reasons.append("обрывок")
    if c.get("end_tone") == "open":
        reasons.append("конец_открытый")
    if not c.get("close_role"):
        reasons.append("нет_вывода")
    if c.get("topics", 1) > 1:
        reasons.append(f"тем={c['topics']}")
    if c.get("short_shots"):
        reasons.append(f"кор_планов={c['short_shots']}")
    return reasons


# ── table printing ────────────────────────────────────────────────────────────

_COLS = [
    ("клипов", "n", "d"),
    ("дл.мед", "dur_median", ".1f"),
    ("крючок%", "hook_pct", ".0f"),
    ("ссылка%", "start_backref_pct", ".0f"),
    ("обрывок%", "start_short_pct", ".0f"),
    ("конец→%", "end_open_pct", ".0f"),
    ("без тона%", "end_none_pct", ".0f"),
    ("стыков/мин", "seams_per_min", ".1f"),
    ("вырезов/мин", "cuts_per_min", ".1f"),
    ("скачков↩", "back_jumps", "d"),
    ("кор.план", "short_shots", "d"),
    ("вспышек", "slivers", "d"),
    ("откр%", "open_role_pct", ".0f"),
    ("вывод%", "close_role_pct", ".0f"),
    ("1тема%", "one_topic_pct", ".0f"),
    ("замыкание%", "closure_pct", ".0f"),
]


def _fmt(val, fmt):
    if val is None:
        return "—"
    if fmt == "d":
        return str(int(val))
    return format(val, fmt)


def _print_table(rows: list[tuple[str, dict, str | None]]):
    """rows: list of (label, summary_dict, coverage_str|None)"""
    headers = [c[0] for c in _COLS] + ["покрытие"]
    widths = [max(len(h), 5) for h in headers]

    # compute widths
    data_rows = []
    for label, s, cov_str in rows:
        vals = [_fmt(s.get(k), f) for _, k, f in _COLS] + [cov_str or "—"]
        data_rows.append((label, vals))
        for i, v in enumerate(vals):
            widths[i] = max(widths[i], len(v))
    label_w = max(len(r[0]) for r in data_rows) + 1

    # header
    header_line = " ".join(h.rjust(widths[i]) for i, h in enumerate(headers))
    print(f"{'источник'.ljust(label_w)}  {header_line}")
    print("-" * (label_w + 2 + len(header_line)))

    for label, vals in data_rows:
        row = " ".join(v.rjust(widths[i]) for i, v in enumerate(vals))
        print(f"{label.ljust(label_w)}  {row}")


def _cov_str(cov: dict | None) -> str:
    if cov is None:
        return "нет разметки"
    return f"{cov['found']}/{cov['total']}"


def _print_result(result: dict, label: str = ""):
    gate = result["gate"]
    print(f"\n=== Гейт {gate}{' ' + label if label else ''} ===\n")

    rows = []
    for stem, s_data in sorted(result["per_stem"].items()):
        sm = s_data["summary"]
        cov = s_data.get("coverage")
        rows.append((stem, sm, _cov_str(cov)))

    total = result["total"]
    total_cov = result.get("coverage")
    rows.append(("ИТОГО", total, _cov_str(total_cov)))
    _print_table(rows)

    print()
    print("Топ-5 предупреждений:")
    for kind, cnt in (result["total"].get("top_warnings") or []):
        print(f"  {cnt:3d}  {kind}")

    vd = result["verdicts"]
    print(f"\nОценки гейта {gate}: {vd['gate_rows']} строк из {vd['total_rows']} в verdicts.jsonl")
    if vd["by_verdict"]:
        print("  по решению:", dict(vd["by_verdict"]))
    if vd["by_reason"]:
        top = sorted(vd["by_reason"].items(), key=lambda x: -x[1])[:5]
        print("  топ причин:", dict(top))

    print("\nХудшие 5 клипов:")
    for w in result["worst"]:
        print(f"  {w['stem']} {w['id']}: {', '.join(w['reasons']) or 'нет'}")


def _diff_row(label: str, s1: dict, s2: dict) -> tuple[str, list[str], list[str], list[str]]:
    """Return label, vals1, vals2, diffs for comparison table."""
    v1 = [_fmt(s1.get(k), f) for _, k, f in _COLS]
    v2 = [_fmt(s2.get(k), f) for _, k, f in _COLS]
    diff = []
    for (_, k, f), a, b in zip(_COLS, v1, v2):
        try:
            d = float(b.replace("—", "0")) - float(a.replace("—", "0"))
            diff.append(f"{d:+.1f}" if "." in f else f"{int(d):+d}")
        except ValueError:
            diff.append("—")
    return label, v1, v2, diff


def _load_ref_reels(root: Path, stem: str, ref_gate: str) -> list[dict] | None:
    """Load reels from a ref gate review file for a stem, or None if missing."""
    p = root / "reviews" / f"{stem}_{ref_gate}.review.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8")).get("reels") or []


def _score_ref(root: Path, main_result: dict, ref_gate: str, cfg: dict) -> dict:
    """For each stem: how many ref clips does the main gate find?"""
    from autoreels.cloud.gatescore import coverage as _cov, score_clip, summarize

    per_stem: dict[str, dict] = {}
    missed_clips: list[dict] = []
    total_found = total_ref = 0

    for stem, s_data in sorted(main_result["per_stem"].items()):
        ref_reels = _load_ref_reels(root, stem, ref_gate)
        gate_reels = [r for r in _get_reels(root, stem, main_result["gate"])]

        if ref_reels is None:
            per_stem[stem] = {"found": None, "total": None}
            continue

        cov = _cov(ref_reels, gate_reels)
        per_stem[stem] = {"found": cov["found"], "total": cov["total"]}
        total_found += cov["found"]
        total_ref += cov["total"]

        # collect missed clips with their score_clip data
        map_ = s_data["clips"][0]["units"] and s_data  # just use already-loaded map
        # reload map/prosody via load_gate for ref clips
        from autoreels.cloud.gatescore import load_gate as _lg
        ref_data = _lg(root, ref_gate)
        ref_stem_data = ref_data.get(stem, {})
        ref_map = ref_stem_data.get("map", {})
        ref_prosody = ref_stem_data.get("prosody", {})

        for oi in cov["missed"]:
            r = ref_reels[oi]
            clip = score_clip(r, ref_map, ref_prosody, cfg)
            best_gi, best_frac = cov["best"][oi]
            best_id = gate_reels[best_gi]["id"] if best_gi is not None else None
            missed_clips.append({
                "stem": stem,
                "id": r.get("id"),
                "title": r.get("title_overlay") or r.get("title") or "",
                "dur": clip["dur"],
                "best_gate_id": best_id,
                "best_frac": best_frac,
                "units": clip["units"],
                "problems": _explain(clip),
            })

    return {
        "ref_gate": ref_gate,
        "per_stem": per_stem,
        "total": {"found": total_found, "total": total_ref},
        "missed_clips": missed_clips,
    }


def _get_reels(root: Path, stem: str, gate: str) -> list[dict]:
    p = root / "reviews" / f"{stem}_{gate}.review.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("reels") or []


def _print_ref(ref_result: dict, main_gate: str):
    ref_gate = ref_result["ref_gate"]
    total = ref_result["total"]
    print(f"\n=== Эталон {ref_gate} в {main_gate}: найдено {total['found']} из {total['total']} ===\n")

    rows = [(stem, d.get("found"), d.get("total")) for stem, d in sorted(ref_result["per_stem"].items())]
    lw = max(len(s) for s, _, _ in rows)
    for stem, found, tot in rows:
        if found is None:
            print(f"  {stem:{lw}}  нет файла {ref_gate}")
        else:
            print(f"  {stem:{lw}}  {found}/{tot}")

    print(f"\nПотерянные клипы эталона:")
    for m in ref_result["missed_clips"]:
        roles = "→".join(
            f"{u.get('role','?')}({u.get('punch','?')})" for u in m["units"]
        ) or "нет мыслей"
        best_str = f"{m['best_gate_id']} {int(m['best_frac']*100)}%" if m["best_gate_id"] else "нет перекрытия"
        problems = ", ".join(m["problems"]) or "нет"
        dur_s = f"{m['dur']:.0f}с"
        print(f"  {m['stem']} {m['id']} «{m['title']}» {dur_s} | лучшее: {best_str} | роли: {roles} | {problems}")


def _print_comparison(r1: dict, r2: dict):
    headers = [c[0] for c in _COLS]
    g1, g2 = r1["gate"], r2["gate"]
    s1, s2 = r1["total"], r2["total"]
    label1, v1, v2, diff = _diff_row("ИТОГО", s1, s2)

    widths = [max(len(h), len(a), len(b), len(d)) for h, a, b, d in
              zip(headers, v1, v2, diff)]

    print(f"\n=== Сравнение {g1} vs {g2} ===\n")
    hdr = " ".join(h.rjust(w) for h, w in zip(headers, widths))
    print(f"{'':12}  {hdr}")
    print("-" * (14 + len(hdr)))
    print(f"{g1:12}  " + " ".join(a.rjust(w) for a, w in zip(v1, widths)))
    print(f"{g2:12}  " + " ".join(b.rjust(w) for b, w in zip(v2, widths)))
    print(f"{'разница':12}  " + " ".join(d.rjust(w) for d, w in zip(diff, widths)))


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("gate")
    ap.add_argument("--compare", metavar="GATE2")
    ap.add_argument("--ref", metavar="REF_GATE")
    ap.add_argument("--stems", metavar="a,b")
    args = ap.parse_args()

    root = _REPO
    out_dir = root / "reels-out" / "_score"
    out_dir.mkdir(parents=True, exist_ok=True)

    stems = args.stems.split(",") if args.stems else None

    cfg = _cfg_dict(load_r0_config(root / "config" / "r0.yaml"))

    def _ensure(gate: str) -> dict:
        out_path = out_dir / f"{gate}.json"
        if out_path.exists():
            result = json.loads(out_path.read_text(encoding="utf-8"))
            if not stems:
                return result
        result = _score_gate(root, gate, stems)
        if not stems:
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    r1 = _ensure(args.gate)
    _print_result(r1)

    if args.compare:
        r2 = _ensure(args.compare)
        _print_result(r2)
        _print_comparison(r1, r2)

    if args.ref:
        r_ref = _ensure(args.ref)
        ref_result = _score_ref(root, r1, args.ref, cfg)
        _print_ref(ref_result, args.gate)
        # persist ref section into gate json
        out_path = out_dir / f"{args.gate}.json"
        if out_path.exists():
            stored = json.loads(out_path.read_text(encoding="utf-8"))
        else:
            stored = r1
        stored["ref"] = {
            "gate": args.ref,
            "per_stem": ref_result["per_stem"],
            "total": ref_result["total"],
            "missed": ref_result["missed_clips"],
        }
        out_path.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
