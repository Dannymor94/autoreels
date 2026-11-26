"""Read-only project catalog; a legacy stem is not a verified source identity."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from autoreels.core.models import Manifest

from . import pipeline_gateway


def _children(root: Path, folder: str, *, files: bool, suffix: str = "") -> list[Path]:
    directory = root / folder
    if directory.is_symlink() or not directory.is_dir():
        return []
    try:
        return sorted(
            p for p in directory.iterdir()
            if not p.is_symlink() and (p.is_file() if files else p.is_dir())
            and (not suffix or p.suffix.lower() == suffix)
        )
    except OSError:
        return []


def _stem(value: object) -> str:
    if not isinstance(value, str) or not value:
        return ""
    # Provenance only: never follow paths stored in manifests or history.
    name = Path(value.replace("\\", "/")).stem
    return name if name not in ("", ".", "..") else ""


def list_projects(root: Path, rendered: list[dict]) -> list[dict]:
    """Project rows derived from local evidence; never creates or modifies files.

    Keep old output locators; ambiguity disables review from the catalog.
    Missing video alone is not proof of failure or zero harvest. A render row is
    evidence of files available for review, not proof of validity or approval.
    """
    inputs = defaultdict(list)
    for folder in ("inputs", "inputs-archive"):
        for p in _children(root, folder, files=True, suffix=".mp4"):
            inputs[p.stem].append(p)

    renders = {item["stem"]: item for item in rendered}
    output_dirs = {p.name for p in _children(root, "reels-out", files=False)}
    runs = defaultdict(list)
    for rec in pipeline_gateway.catalog_history(root):
        stem = _stem(rec.get("source"))
        if stem:
            runs[stem].append(rec)

    known = set(inputs) | set(renders) | output_dirs | set(runs)
    manifests = {}
    broken = set()
    for path in _children(root, "manifests", files=True, suffix=".json"):
        try:
            manifest = Manifest.model_validate_json(path.read_bytes())
        except (ValueError, OSError):
            # Sidecars also end in .json; only report a bad file when an
            # independent project locator identifies it. Do not invent rows.
            if path.stem in known:
                broken.add(path.stem)
            continue
        manifests[path.stem] = manifest

    rows = []
    for stem in sorted(known | set(manifests)):
        m = manifests.get(stem)
        latest = runs[stem][0] if runs[stem] else {}
        outcome = latest.get("outcome")
        hashes = {
            rec["sha256"] for rec in runs[stem]
            if isinstance(rec.get("sha256"), str) and rec["sha256"]
        }
        if m is not None and m.source_sha256:
            hashes.add(m.source_sha256)
        historical_path = latest.get("source_path")
        # A previous in-place run with the same basename is not necessarily
        # the file now in inputs. Do not silently attribute its status.
        uncertain_input = (
            len(inputs[stem]) == 1
            and inputs[stem][0].parent.name == "inputs"
            and isinstance(historical_path, str) and bool(historical_path)
            and historical_path != str(inputs[stem][0])
        )
        ambiguous = (
            len(inputs[stem]) > 1 or len(hashes) > 1 or uncertain_input
            or (m is not None and _stem(m.source) != stem)
            or (root / "reels-out" / stem).is_symlink()
        )
        render = renders.get(stem)
        if ambiguous:
            status, detail = "unknown", "ambiguous"
        elif outcome == "failed" or (m is not None and m.status.value == "failed"):
            status, detail = "failed", "run_failed"
        elif outcome == "skipped":
            status, detail = "unknown", "run_skipped"
        elif outcome == "zero-harvest" and type(latest.get("reel_count")) is int and latest["reel_count"] == 0:
            status, detail = ("unknown", "conflicting_evidence") if render or (m is not None and m.reels) else ("empty", "zero_harvest")
        elif stem in broken:
            status, detail = "unknown", "invalid_manifest"
        elif render:
            status, detail = "ready", "render_present"
        elif m is not None:
            status, detail = "draft", "manifest_present"
        elif latest or stem in output_dirs or any(p.parent.name == "inputs-archive" for p in inputs[stem]):
            status, detail = "unknown", "insufficient_evidence"
        elif inputs[stem]:
            status, detail = "unprocessed", "input_present"
        else:
            status, detail = "unknown", "insufficient_evidence"

        can_review = bool(render) and not ambiguous
        row = dict(render) if render else dict(
            stem=stem, display_name=None, clip_count=0, variant_names=[],
            poster_clip=None, poster_variant="",
        )
        # Do not advertise a preview or a count linked to an ambiguous source.
        if ambiguous:
            row.update(display_name=None, clip_count=0, variant_names=[], poster_clip=None, poster_variant="")
        row.update(status=status, detail=detail, can_review=can_review)
        rows.append(row)
    return rows
