"""M172: which reels of two review.json differ in their played pieces. Usage: compare_reels.py OLD NEW
Prints a line per reel (id, pieces old → new) and the last line `changed: 1,4,…` (1-based reel numbers for --reels)."""
import json, sys

def pieces(r):
    segs = r.get("segments") or [{"start": r["start"], "end": r["end"]}]
    co = r.get("cold_open")
    out = ([f"h{co['start']:.2f}-{co['end']:.2f}"] if co else []) + [f"{s['start']:.2f}-{s['end']:.2f}" for s in segs]
    return out

old = json.load(open(sys.argv[1]))["reels"]
new = json.load(open(sys.argv[2]))["reels"]
changed = []
for i, (a, b) in enumerate(zip(old, new), 1):
    pa, pb = pieces(a), pieces(b)
    mark = "  " if pa == pb else "≠ "
    if pa != pb:
        changed.append(str(i))
    print(f"{mark}{i:02d} {b.get('id')}: {' '.join(pa)}" + ("" if pa == pb else f"\n      → {' '.join(pb)}"))
if len(old) != len(new):
    print(f"число клипов: {len(old)} → {len(new)}")
print("changed: " + ",".join(changed))
