#!/usr/bin/env python3
"""Cache / workspace garbage collection (PART 2).

Usage:
    python scripts/gc.py              # inventory only (dry-run)
    python scripts/gc.py --delete     # delete / move confirmed-safe items
    python scripts/gc.py --cat 6      # one category only

Categories:
  6  transcripts/*.speechmap.json with SPEECHMAP_VERSION < current;
     plus data/cache entries that carry a speechmap_params_hash for an old version.
  7  data/cache transcript entries whose params_key does not match the current
     transcription config — but only if no manifest references that audio hash with
     the current params (otherwise the entry is still needed as a fallback).
  8  Gate/demo review copies: reviews/*gate* and scratchpad/*.review.md
     → moved to reviews/_archive/ (never deleted).

Rules:
  • Always inventory first; print per-file sizes.
  • Only categories listed above are touched; nothing else.
  • Never touch: manifests/, reels-out/, reviews/*_answer.txt, real *.review.md /
    *.review.json outside the gate/demo definition, data/cache entries referenced
    by a current-params manifest.
  • Report freed space per category.
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
    return freed if delete else 0


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
    return freed_del if delete else 0


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
    return total_bytes if move else 0


# ─── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--delete", action="store_true",
                   help="actually delete / move files (default: dry-run)")
    p.add_argument("--cat", type=int, choices=[6, 7, 8], default=None,
                   help="run only one category")
    args = p.parse_args()

    print(f"GC — {'DELETE' if args.delete else 'DRY-RUN'}  root={REPO}")
    cats = [args.cat] if args.cat else [6, 7, 8]
    total_freed = 0

    if 6 in cats:
        total_freed += run_cat6(delete=args.delete)
    if 7 in cats:
        total_freed += run_cat7(delete=args.delete)
    if 8 in cats:
        # category 8 moves not deletes, but count bytes for the report
        total_freed += run_cat8(move=args.delete)

    if args.delete:
        print(f"\nTotal freed / moved: {_fmt(total_freed)}")
    else:
        print("\n(dry-run complete — rerun with --delete to apply)")


if __name__ == "__main__":
    main()
