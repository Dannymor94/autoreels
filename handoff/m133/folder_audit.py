#!/usr/bin/env python3
"""M133: read-only inventory of the project folder -> markdown on stdout.

Reads only: no writes, no deletes, no hashing of videos, no arl calls.
Run from the project root:  python3 handoff/m133/folder_audit.py > handoff/m133/folder_audit.md
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip() or ".")
NOW = time.time()
SKIP_WALK = {".git", ".venv", "node_modules"}


def sh(*args: str) -> str:
    r = subprocess.run(list(args), cwd=ROOT, capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    tot = 0
    for dp, dn, fn in os.walk(p):
        dn[:] = [d for d in dn if d not in SKIP_WALK]
        for f in fn:
            try:
                tot += (Path(dp) / f).lstat().st_size
            except OSError:
                pass
    return tot


def hs(n: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


def age_days(p: Path) -> float:
    return (NOW - p.stat().st_mtime) / 86400


def section(t: str) -> None:
    print(f"\n## {t}\n")


def main() -> int:
    print(f"# Folder audit — {ROOT.name} — {time.strftime('%Y-%m-%d %H:%M')}")

    section("1. git")
    print("```")
    print(sh("git", "status", "-sb", "--untracked-files=normal"))
    print("--- HEAD vs origin/main:", sh("git", "rev-list", "--left-right", "--count", "HEAD...origin/main"))
    print("--- stash:\n" + (sh("git", "stash", "list") or "(none)"))
    print("--- local branches:\n" + sh("git", "branch", "-vv"))
    print("--- worktrees:\n" + sh("git", "worktree", "list"))
    print("```")

    section("2. Sizes of top-level folders")
    rows = []
    for p in sorted(ROOT.iterdir()):
        if p.name in {".git"}:
            continue
        if p.is_dir():
            rows.append((size(p), p.name))
    print("| folder | size |\n|---|---|")
    for s, n in sorted(rows, reverse=True):
        print(f"| {n} | {hs(s)} |")

    section("3. Largest files (outside .git/.venv)")
    big = []
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in SKIP_WALK]
        for f in fn:
            fp = Path(dp) / f
            if "__pycache__" in dp:
                continue
            try:
                big.append((fp.lstat().st_size, fp))
            except OSError:
                pass
    print("| size | file | age, days |\n|---|---|---|")
    for s, fp in sorted(big, reverse=True)[:20]:
        print(f"| {hs(s)} | {fp.relative_to(ROOT)} | {age_days(fp):.0f} |")

    section("4. Leftovers: temp / partial / lock files")
    pat = re.compile(r"(\.tmp|\.partial|\.part|\.lock|~|\.bak|\.orig|\.rej)$|^\.~|^tmp", re.I)
    hits = [fp for _, fp in big if pat.search(fp.name)]
    for fp in hits[:60]:
        print(f"- {fp.relative_to(ROOT)} ({hs(fp.stat().st_size)}, {age_days(fp):.0f} d)")
    print(f"\ntotal: {len(hits)}" if hits else "none")

    section("5. reels-out per source")
    ro = ROOT / "reels-out"
    if ro.is_dir():
        print("| source | clips (mp4) | size | _gate dirs | _gate size | oldest gate, days |\n|---|---|---|---|---|---|")
        for d in sorted(p for p in ro.iterdir() if p.is_dir()):
            mp4 = [f for f in d.glob("*.mp4")]
            gate = d / "_gate"
            gdirs = [g for g in gate.iterdir() if g.is_dir()] if gate.is_dir() else []
            gsize = size(gate) if gate.is_dir() else 0
            old = max((age_days(g) for g in gdirs), default=0)
            print(f"| {d.name} | {len(mp4)} | {hs(size(d))} | {len(gdirs)} | {hs(gsize)} | {old:.0f} |")
        loose = [f.name for f in ro.iterdir() if f.is_file()]
        if loose:
            print(f"\nloose files in reels-out/: {loose[:20]}")

    section("6. manifests")
    man = ROOT / "manifests"
    sidecar = re.compile(r"\.(blocks|discarded|failed_chunks|blocks\.[a-z_]+)\.json$")
    srcs_dirs = [ROOT / "inputs", ROOT / "inputs-archive"]
    names_on_disk = {f.name for d in srcs_dirs if d.is_dir() for f in d.rglob("*") if f.is_file()}
    print("| manifest | status | selection | reels | source file found by name in inputs*/ | tracked in git |\n|---|---|---|---|---|---|")
    tracked = set(sh("git", "ls-files", "manifests").splitlines())
    for f in sorted(man.glob("*.json")) if man.is_dir() else []:
        if sidecar.search(f.name):
            continue
        try:
            d = json.loads(f.read_text())
        except Exception as e:  # noqa: BLE001 — report, don't stop
            print(f"| {f.name} | UNREADABLE: {e} | | | | |")
            continue
        if not isinstance(d, dict):
            print(f"| {f.name} | not a manifest (list) | | | | |")
            continue
        src = d.get("source", "?")
        reels = d.get("reels") or d.get("segments") or []
        sel = d.get("selection_source") or {r.get("selection_source") for r in reels if isinstance(r, dict)} or "?"
        print(f"| {f.name} | {d.get('status','?')} | {sel} | {len(reels)} | {'yes' if Path(str(src)).name in names_on_disk else 'NO (outside inputs*/?)'} | {'yes' if f'manifests/{f.name}' in tracked else 'NO'} |")
    sc = [f.name for f in man.glob("*.json") if sidecar.search(f.name)] if man.is_dir() else []
    print(f"\nsidecars: {len(sc)}")

    section("7. reviews/ by kind")
    rv = ROOT / "reviews"
    kinds = defaultdict(list)
    rules = [
        ("owner answer *_answer.txt", re.compile(r"_answer\.txt$")),
        ("autocut draft *_auto_*.txt", re.compile(r"_auto_.*\.txt$")),
        ("gate copy *_mNN.review.json", re.compile(r"_m\d+[a-z]?\.review\.json$")),
        ("manifest copy *.review.json", re.compile(r"\.review\.json$")),
        ("backup (before/bak/orig)", re.compile(r"(before|\.bak|\.orig)", re.I)),
        ("other .txt", re.compile(r"\.txt$")),
    ]
    for f in sorted(rv.rglob("*")) if rv.is_dir() else []:
        if not f.is_file():
            continue
        for k, r in rules:
            if r.search(f.name):
                kinds[k].append(f)
                break
        else:
            kinds["other"].append(f)
    print("| kind | count | size | newest, days |\n|---|---|---|---|")
    for k, fs in kinds.items():
        print(f"| {k} | {len(fs)} | {hs(sum(x.stat().st_size for x in fs))} | {min(age_days(x) for x in fs):.0f} |")
    for k in ("other", "other .txt", "backup (before/bak/orig)"):
        if kinds.get(k):
            print(f"\n{k}: " + ", ".join(x.name for x in kinds[k][:40]))

    section("8. transcripts/ — stems without a manifest")
    tr = ROOT / "transcripts"
    mstems = {f.name.split(".")[0] for f in man.glob("*.json")} if man.is_dir() else set()
    tstems = Counter()
    for f in tr.glob("*") if tr.is_dir() else []:
        if f.is_file():
            tstems[f.name.split(".")[0]] += 1
    orphan = sorted(s for s in tstems if s not in mstems)
    print(f"stems: {len(tstems)}, without manifest: {len(orphan)} (normal for sources analysed by arl map/autocut only)")
    for s in orphan[:40]:
        print(f"- {s} ({tstems[s]} files)")

    section("9. data/")
    dd = ROOT / "data"
    if dd.is_dir():
        print("| path | files | size |\n|---|---|---|")
        for p in sorted(dd.iterdir()):
            n = sum(1 for _ in p.rglob("*")) if p.is_dir() else 1
            print(f"| {p.relative_to(ROOT)} | {n} | {hs(size(p))} |")
        cache = dd / "cache"
        if cache.is_dir():
            print("\ndata/cache/:")
            for p in sorted(cache.iterdir()):
                n = sum(1 for _ in p.rglob("*")) if p.is_dir() else 1
                print(f"- {p.name}: {n} files, {hs(size(p))}")
    print("\nYuNet model present:", (dd / "models" / "face_detection_yunet_2023mar.onnx").is_file())

    section("10. Local config and caches")
    loc = ROOT / "config" / "render.local.yaml"
    print("render.local.yaml:", "present" if loc.is_file() else "MISSING")
    if loc.is_file():
        for line in loc.read_text().splitlines():
            if re.match(r"\s*(role|ffmpeg|encoder|codec)\b", line):
                print("  ", line.strip())
    print(".env present:", (ROOT / ".env").is_file(), "(contents not read)")
    pyc = sum(size(Path(dp)) for dp, dn, fn in os.walk(ROOT) if Path(dp).name == "__pycache__" and ".venv" not in dp)
    print("__pycache__ outside .venv:", hs(pyc), "| .pytest_cache:", hs(size(ROOT / ".pytest_cache")) if (ROOT / ".pytest_cache").exists() else "-")

    section("11. handoff/ (local, gitignored)")
    ho = ROOT / "handoff"
    if ho.is_dir():
        ds = sorted(p for p in ho.iterdir() if p.is_dir())
        print(f"folders: {len(ds)}, size {hs(size(ho))}; largest:")
        for s, p in sorted(((size(p), p) for p in ds), reverse=True)[:8]:
            print(f"- {p.name}: {hs(s)}")

    section("12. export/")
    ex = ROOT / "export"
    if ex.is_dir():
        for p in sorted(ex.iterdir()):
            print(f"- {p.name}: {hs(size(p))}")
    else:
        print("none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
