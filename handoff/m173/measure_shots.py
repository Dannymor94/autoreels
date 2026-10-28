"""M173: shots of every clip of a review.json as rendered — from its segments (cold open first; a shot changes at every
segment and at every wide/close edge inside one). Usage: measure_shots.py REVIEW.json [REVIEW2.json …]
Per clip with a short shot: out time, length, where. Totals: slivers (< 0.2 s — one to a few frames) and short shots
(< 2.0 s), the cold open and the last shot not counted; plus the plan's «short shot» warnings when present."""
import json, sys

def shots(r):
    segs = ([dict(r["cold_open"], _co=True)] if r.get("cold_open") else []) + \
           (r.get("segments") or [{"start": r["start"], "end": r["end"], "shot": "wide"}])
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
    b = sorted(set(round(x, 4) for x in bounds)) + [t]
    out = []
    for i, (a, z) in enumerate(zip(b, b[1:])):
        src = next((s0 + (a - t0) for t0, s0 in reversed(spans) if t0 <= a + 1e-6), None)
        out.append((a, z, src, z <= co_end + 1e-6, i == len(b) - 2))
    return out

tot_sl = tot_sh = 0
for path in sys.argv[1:]:
    reels = json.load(open(path))["reels"]
    n_sl = n_sh = 0
    print(f"== {path}")
    for i, r in enumerate(reels, 1):
        bad = []
        for a, z, src, in_co, last in shots(r):
            d = z - a
            if in_co or last or d >= 2.0:
                continue
            kind = "SLIVER" if d < 0.2 else "short"
            n_sl += kind == "SLIVER"; n_sh += kind == "short"
            bad.append(f"{kind} {d:.2f}s @out {a:.2f} (src {src:.2f})")
        ww = [w for w in (r.get("warnings") or []) if w.startswith("short shot")]
        if bad or ww:
            print(f"  {i:02d} {r['id']}: " + "; ".join(bad))
            for w in ww:
                print(f"       ! {w}")
    print(f"  итого: SLIVER {n_sl}, short {n_sh}")
    tot_sl += n_sl; tot_sh += n_sh
print(f"ВСЕГО: SLIVER {tot_sl}, short {tot_sh}")
