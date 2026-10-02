#!/usr/bin/env python3
"""Workspace garbage collection — categories 1–8.

Usage:
    python scripts/gc.py              # inventory (dry-run, all categories)
    python scripts/gc.py --delete     # apply all categories
    python scripts/gc.py --cat 3      # one category only

Categories:
  1  reels-out/<stem>/_gate/<name>/ for every name except m18_final.
  2  reels-out/_stage_a_snips/ and reels-out/_stage_a_snips_v2/.
  3  *.tmp.mp4 under reels-out/.
  4  *.render.lock files not held by any live process.
  5  Project temp folders/files in /tmp (gate_frames, m16_e2e*, ff_err_*,
     ass_proof, manifest_backup*, feature_audit*, m16_rerun*, taskA_dry*, etc.).
  6  transcripts/*.speechmap.json whose stored version < current SPEECHMAP_VERSION.
  7  data/cache transcript entries with a non-current params_key, unless a manifest
     still references that source_sha256 + old pkey (protected as fallback).
  8  Gate/demo review copies: reviews/*gate* and scratchpad/*.review.md
     → moved to reviews/_archive/ (never deleted, only archived).

Never touched:
  reels-out/<stem>/r*.mp4 and their sidecars, manifests/, reviews/*_answer.txt,
  real *.review.md / *.review.json, data/cache entries current-pkey manifests need,
  worktrees (../autoreels-*), transcripts (except category 6).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def _fmt(n_bytes: int) -> str:
    if n_bytes < 1024:
        return f"{n_bytes} B"
    if n_bytes < 1024 ** 2:
        return f"{n_bytes / 1024:.1f} KB"
    return f"{n_bytes / 1024 ** 2:.1f} MB"


def _dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


# ─── category 1: non-m18_final gate directories ───────────────────────────────

def _cat1_inventory() -> list[Path]:
    """reels-out/<stem>/_gate/<name>/ for every name != m18_final."""
    dirs: list[Path] = []
    ro = REPO / "reels-out"
    if not ro.exists():
        return dirs
    for gate_dir in sorted(ro.rglob("_gate")):
        if not gate_dir.is_dir():
            continue
        for child in sorted(gate_dir.iterdir()):
            if child.is_dir() and child.name != "m18_final":
                dirs.append(child)
    return dirs


def run_cat1(*, delete: bool) -> int:
    dirs = _cat1_inventory()
    sizes = {d: _dir_size(d) for d in dirs}
    total = sum(sizes.values())
    print(f"\n[1] Non-m18_final gate directories: {len(dirs)} dir(s), {_fmt(total)}")
    if not dirs:
        print("  nothing to do")
        return 0
    for d in dirs:
        rel = d.relative_to(REPO)
        print(f"  {rel}/  ({_fmt(sizes[d])})")
    if delete:
        for d in dirs:
            shutil.rmtree(d)
        print(f"  → removed {len(dirs)} dir(s), freed {_fmt(total)}")
    else:
        print("  (dry-run: pass --delete to remove)")
    return total


# ─── category 2: _stage_a_snips directories ───────────────────────────────────

def _cat2_inventory() -> list[Path]:
    ro = REPO / "reels-out"
    names = ("_stage_a_snips", "_stage_a_snips_v2")
    return [ro / n for n in names if (ro / n).is_dir()]


def run_cat2(*, delete: bool) -> int:
    dirs = _cat2_inventory()
    sizes = {d: _dir_size(d) for d in dirs}
    total = sum(sizes.values())
    print(f"\n[2] _stage_a_snips directories: {len(dirs)} dir(s), {_fmt(total)}")
    if not dirs:
        print("  nothing to do")
        return 0
    for d in dirs:
        print(f"  reels-out/{d.name}/  ({_fmt(sizes[d])})")
    if delete:
        for d in dirs:
            shutil.rmtree(d)
        print(f"  → removed {len(dirs)} dir(s), freed {_fmt(total)}")
    else:
        print("  (dry-run: pass --delete to remove)")
    return total


# ─── category 3: *.tmp.mp4 under reels-out/ ───────────────────────────────────

def _cat3_inventory() -> list[Path]:
    ro = REPO / "reels-out"
    if not ro.exists():
        return []
    return sorted(ro.rglob("*.tmp.mp4"))


def run_cat3(*, delete: bool) -> int:
    files = _cat3_inventory()
    total = sum(f.stat().st_size for f in files)
    print(f"\n[3] Temp render files (*.tmp.mp4): {len(files)} file(s), {_fmt(total)}")
    if not files:
        print("  nothing to do")
        return 0
    for f in files:
        print(f"  {f.relative_to(REPO)}  ({_fmt(f.stat().st_size)})")
    if delete:
        for f in files:
            f.unlink()
        print(f"  → deleted {len(files)} file(s), freed {_fmt(total)}")
    else:
        print("  (dry-run: pass --delete to remove)")
    return total


# ─── category 4: stale .render.lock files ─────────────────────────────────────

def _lock_is_held(path: Path) -> bool:
    """Return True if the lock file is currently held by a live process."""
    try:
        import fcntl
        with open(path) as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fh, fcntl.LOCK_UN)
                return False  # acquired → not held
            except OSError:
                return True   # blocked → held
    except Exception:
        return False  # can't open / no fcntl → treat as stale


def _cat4_inventory() -> tuple[list[Path], list[Path]]:
    """Return (stale_locks, held_locks)."""
    ro = REPO / "reels-out"
    stale, held = [], []
    if not ro.exists():
        return stale, held
    for f in sorted(ro.rglob(".render.lock")):
        (held if _lock_is_held(f) else stale).append(f)
    return stale, held


def run_cat4(*, delete: bool) -> int:
    stale, held = _cat4_inventory()
    total = sum(f.stat().st_size for f in stale)
    print(f"\n[4] Stale .render.lock files: {len(stale)} stale, {len(held)} held")
    if held:
        for f in held:
            print(f"  ⚠ HELD (render running?): {f.relative_to(REPO)}")
    if not stale:
        print("  nothing to do")
        return 0
    for f in stale:
        print(f"  {f.relative_to(REPO)}  ({_fmt(f.stat().st_size)})")
    if delete:
        for f in stale:
            f.unlink()
        print(f"  → deleted {len(stale)} lock(s)")
    else:
        print("  (dry-run: pass --delete to remove stale locks)")
    return total


# ─── category 5: project temp items in /tmp ───────────────────────────────────

# Patterns matched by name (exact or prefix) — safe project-owned temp items.
_TMP_PATTERNS = (
    "gate_frames",
    "taskA_dry",
    "m16_e2e",
    "m16_rerun",
    "m17_",
    "m18_",
    "ff_err_",
    "ass_proof",
    "manifest_backup",
    "feature_audit_",
    "arl_tmp_",
)


def _cat5_inventory() -> list[Path]:
    tmp = Path("/private/tmp") if Path("/private/tmp").exists() else Path("/tmp")
    found: list[Path] = []
    try:
        for entry in sorted(tmp.iterdir()):
            name = entry.name
            if any(name == pat or name.startswith(pat) for pat in _TMP_PATTERNS):
                found.append(entry)
    except PermissionError:
        pass
    return found


def run_cat5(*, delete: bool) -> int:
    items = _cat5_inventory()
    sizes = {}
    for p in items:
        try:
            sizes[p] = _dir_size(p) if p.is_dir() else p.stat().st_size
        except OSError:
            sizes[p] = 0
    total = sum(sizes.values())
    print(f"\n[5] Project temp items in /tmp: {len(items)} item(s), {_fmt(total)}")
    if not items:
        print("  nothing to do")
        return 0
    for p in items:
        kind = "dir" if p.is_dir() else "file"
        print(f"  /tmp/{p.name}  ({kind}, {_fmt(sizes[p])})")
    if delete:
        for p in items:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        print(f"  → removed {len(items)} item(s), freed {_fmt(total)}")
    else:
        print("  (dry-run: pass --delete to remove)")
    return total


# ─── category 6: stale speechmap files ────────────────────────────────────────

def _cat6_inventory() -> list[Path]:
    """speechmap.json files whose stored 'version' < current SPEECHMAP_VERSION."""
    from autoreels.cloud.speechmap import SPEECHMAP_VERSION
    import json

    stale: list[Path] = []
    tr_dir = REPO / "transcripts"
    if not tr_dir.exists():
        return stale
    for f in sorted(tr_dir.glob("*.speechmap.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("version") != SPEECHMAP_VERSION:
                stale.append(f)
        except Exception:
            pass  # unreadable → leave alone
    return stale


def run_cat6(*, delete: bool) -> int:
    from autoreels.cloud.speechmap import SPEECHMAP_VERSION
    stale = _cat6_inventory()
    freed = sum(f.stat().st_size for f in stale)
    print(f"\n[6] Stale speechmap files (current version={SPEECHMAP_VERSION}): {len(stale)} file(s), {_fmt(freed)}")
    if not stale:
        print("  nothing to do")
        return 0
    for f in stale:
        import json
        ver = json.loads(f.read_text(encoding="utf-8")).get("version", "?")
        print(f"  {f.name}  (version={ver}, {_fmt(f.stat().st_size)})")
    if delete:
        for f in stale:
            f.unlink()
        print(f"  → deleted {len(stale)} file(s), freed {_fmt(freed)}")
    else:
        print("  (dry-run: pass --delete to remove)")
    return freed


# ─── category 7: stale transcript cache entries ────────────────────────────────

def _current_pkey() -> str:
    from autoreels.core.config import load_transcribe_config
    from autoreels.cloud.transcribe import params_key, _backend_meta, get_backend
    tcfg = load_transcribe_config(REPO / "config" / "transcribe.yaml")
    return params_key(_backend_meta(get_backend(tcfg)))


def _manifest_refs() -> set[tuple[str, str]]:
    """Set of (source_sha256, params_key) pairs that appear in any manifest."""
    from autoreels.core.models import Manifest
    refs: set[tuple[str, str]] = set()
    mdir = REPO / "manifests"
    if not mdir.exists():
        return refs
    sidecar_suffixes = (".blocks.json", ".discarded.json", ".failed_chunks.json")
    for mf in mdir.glob("*.json"):
        if any(mf.name.endswith(s) for s in sidecar_suffixes):
            continue
        try:
            m = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
            if m.source_sha256 and m.transcript_params_key:
                refs.add((m.source_sha256, m.transcript_params_key))
        except Exception:
            pass
    return refs


def _cat7_inventory(current_pkey: str, manifest_refs: set[tuple[str, str]]) -> tuple[list[Path], list[Path]]:
    """Return (deletable, protected).

    A stale-pkey transcript is deletable if no manifest's transcript_params_key equals
    its stale pkey for the same source_sha256.  Protection is determined by the
    source_sha256 stored INSIDE the transcript JSON (most reliable), with a fallback
    to checking whether the stale pkey appears in any manifest at all.
    """
    import json as _json

    stale_pkeys_in_manifests = {pkey for _, pkey in manifest_refs if pkey != current_pkey}

    cache = REPO / "data" / "cache"
    deletable: list[Path] = []
    protected: list[Path] = []
    if not cache.exists():
        return deletable, protected
    for f in sorted(cache.glob("*.transcript.json")):
        parts = f.stem.split(".")
        if len(parts) < 2:
            continue  # no-pkey legacy — separate concern, leave alone
        file_pkey = parts[1]
        if file_pkey == current_pkey:
            continue  # current — keep
        if file_pkey == "transcript":
            continue  # no-pkey legacy — leave alone
        # Stale pkey: check if any manifest still references this transcript via its
        # stored source_sha256 + this pkey.
        try:
            inner = _json.loads(f.read_bytes())
            inner_sha = inner.get("source_sha256", "")
        except Exception:
            inner_sha = ""
        # Protected when: (a) the inner source_sha256 + this stale pkey is in manifest refs,
        # OR (b) no inner sha but this pkey appears somewhere in manifests (conservative).
        if inner_sha:
            if (inner_sha, file_pkey) in manifest_refs:
                protected.append(f)
            else:
                deletable.append(f)
        else:
            # Legacy transcript without source_sha256: protect if pkey used by any manifest
            if file_pkey in stale_pkeys_in_manifests:
                protected.append(f)
            else:
                deletable.append(f)
    return deletable, protected


def run_cat7(*, delete: bool) -> int:
    current_pkey = _current_pkey()
    manifest_refs = _manifest_refs()
    deletable, protected = _cat7_inventory(current_pkey, manifest_refs)
    freed_del = sum(f.stat().st_size for f in deletable)
    freed_prot = sum(f.stat().st_size for f in protected)
    print(f"\n[7] Stale transcript cache (current pkey={current_pkey}): "
          f"{len(deletable)} deletable ({_fmt(freed_del)}), "
          f"{len(protected)} protected ({_fmt(freed_prot)})")
    if deletable:
        print("  Deletable (no manifest references this audio hash with any params):")
        for f in deletable:
            pkey = f.stem.split(".")[1]
            print(f"    {f.name}  (pkey={pkey}, {_fmt(f.stat().st_size)})")
    if protected:
        print("  Protected (manifest still references this audio hash — keeping):")
        for f in protected:
            pkey = f.stem.split(".")[1]
            print(f"    {f.name}  (pkey={pkey}, {_fmt(f.stat().st_size)})  ← KEEP")
    if not deletable and not protected:
        print("  nothing to do")
        return 0
    if delete and deletable:
        for f in deletable:
            f.unlink()
        print(f"  → deleted {len(deletable)} file(s), freed {_fmt(freed_del)}")
    elif not delete:
        print("  (dry-run: pass --delete to remove deletable entries)")
    return freed_del


# ─── category 8: gate/demo review copies ─────────────────────────────────────

def _cat8_inventory() -> list[Path]:
    """Gate/demo review files that should be archived, not left at top level."""
    candidates: list[Path] = []

    # reviews/*gate* (any extension, case-insensitive)
    reviews_dir = REPO / "reviews"
    if reviews_dir.exists():
        for f in sorted(reviews_dir.iterdir()):
            if f.is_file() and "gate" in f.name.lower() and not f.name.startswith("_"):
                candidates.append(f)

    # scratchpad/*.review.md
    scratch_dir = REPO / "scratchpad"
    if scratch_dir.exists():
        for f in sorted(scratch_dir.glob("*.review.md")):
            candidates.append(f)

    return candidates


def run_cat8(*, move: bool) -> int:
    candidates = _cat8_inventory()
    total_bytes = sum(f.stat().st_size for f in candidates)
    print(f"\n[8] Gate/demo review copies to archive: {len(candidates)} file(s), {_fmt(total_bytes)}")
    if not candidates:
        print("  nothing to do")
        return 0
    archive_dir = REPO / "reviews" / "_archive"
    for f in candidates:
        print(f"  {f.relative_to(REPO)}  ({_fmt(f.stat().st_size)})"
              f"  → reviews/_archive/{f.name}")
    if move:
        archive_dir.mkdir(parents=True, exist_ok=True)
        moved = 0
        for f in candidates:
            dest = archive_dir / f.name
            if dest.exists():
                print(f"  ⚠ {f.name}: already in _archive — skipping")
                continue
            shutil.move(str(f), dest)
            moved += 1
        print(f"  → moved {moved} file(s) to reviews/_archive/")
    else:
        print("  (dry-run: pass --delete to move to reviews/_archive/)")
    return total_bytes


# ─── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--delete", action="store_true",
                   help="actually delete / move files (default: dry-run)")
    p.add_argument("--cat", type=int, choices=list(range(1, 9)), default=None,
                   help="run only one category (1–8)")
    args = p.parse_args()

    print(f"GC — {'DELETE' if args.delete else 'DRY-RUN'}  root={REPO}")
    cats = [args.cat] if args.cat else list(range(1, 9))

    # Each runner returns bytes actually freed (delete mode) or bytes inventoried (dry-run).
    # We always pass the delete flag; dry-run functions still return their inventory size.
    runners = {
        1: lambda: run_cat1(delete=args.delete),
        2: lambda: run_cat2(delete=args.delete),
        3: lambda: run_cat3(delete=args.delete),
        4: lambda: run_cat4(delete=args.delete),
        5: lambda: run_cat5(delete=args.delete),
        6: lambda: run_cat6(delete=args.delete),
        7: lambda: run_cat7(delete=args.delete),
        8: lambda: run_cat8(move=args.delete),
    }
    total = sum(runners[c]() for c in cats)

    label = "freed / moved" if args.delete else "would free"
    print(f"\nTotal {label}: {_fmt(total)}")
    if not args.delete:
        print("(dry-run — rerun with --delete to apply)")


if __name__ == "__main__":
    main()
