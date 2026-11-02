"""M205: the reels of each run's draft (reviews/<source>_auto_all_<tag>.txt) side by side — how many, which only in one
run, and whether «Алгоритм или эмпатия» (prew_isaev_anna, the sentences 21.1-5) is taken. Read only.
Run from the project root: .venv/bin/python handoff/m205/compare.py s205a s205b s205c"""
import re
import sys
from pathlib import Path

S7 = ("disko_beach_p1", "disko_beach_p2", "disko_beach_p3", "day_yoga_p1", "day_yoga_p2", "prew_isaev_anna",
      "prew_isaev_danny")
tags = sys.argv[1:]
root = Path.cwd()


def reels(stem: str, tag: str) -> list[tuple[str, str]] | None:
    f = root / "reviews" / f"{stem}_auto_all_{tag}.txt"
    if not f.is_file():
        return None
    out = []
    for ln in f.read_text(encoding="utf-8").splitlines():
        if re.match(r"^M\d* \d", ln):
            parts = [p.strip() for p in ln.split(" | ")]
            title = next((p[3:] for p in parts if p.startswith("t: ")), "")
            out.append((parts[1], title))
    return out


tot = {t: 0 for t in tags}
print("источник            " + "  ".join(f"{t:>7}" for t in tags))
rows = {}
for s in S7:
    rs = {t: reels(s, t) for t in tags}
    rows[s] = rs
    cells = [f"{len(rs[t]):>7}" if rs[t] is not None else "    нет" for t in tags]
    for t in tags:
        tot[t] += len(rs[t] or [])
    print(f"{s:18}  " + "  ".join(cells))
print(f"{'ИТОГО':18}  " + "  ".join(f"{tot[t]:>7}" for t in tags))
for a, b in zip(tags, tags[1:]):
    print(f"\n== {a} → {b}")
    for s in S7:
        ra, rb = rows[s][a] or [], rows[s][b] or []
        pa, pb = {p for p, _ in ra}, {p for p, _ in rb}
        for p, t in ra:
            if p not in pb:
                print(f"  {s}: − {p}  «{t}»")
        for p, t in rb:
            if p not in pa:
                print(f"  {s}: + {p}  «{t}»")
print("\n«Алгоритм или эмпатия» (prew_isaev_anna, 21.1-5):")
for t in tags:
    hit = [f"{p} «{ti}»" for p, ti in (rows["prew_isaev_anna"][t] or []) if "21.1-5" in p]
    print(f"  {t}: " + ("взят — " + "; ".join(hit) if hit else "нет"))
