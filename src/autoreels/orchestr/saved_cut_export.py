"""Trusted offline adapter for exporting a saved synthetic editor revision.

Not registered with HTTP, live job queues or remote targets. Only the exact
bundled preview and generated soundtrack/image assets are accepted. The synthetic
editor database keeps its original placeholder source identity; a separate
staged manifest binds the actual media bytes, with an explicit receipt.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from autoreels.core.models import Manifest
from . import editor_revisions as revisions, staged_executor, synthetic_cut
from .pathguard import safe_path
from .synthetic_editor import _MAX_REVISION, _path
from .synthetic_soundtrack import TRACKS
from .synthetic_image import IMAGE, IMAGE_NAME

PREVIEW_SHA256 = "c87ea2fffefd6d17905ec71cef3ad94659ff1fbee110fb670aab2ac1e43d3848"
_STEM = "SYNTHETIC_CUT"


@dataclass(frozen=True)
class PreparedCut:
    editor_revision: int
    editor_plan_sha256: str
    staged_plan_sha256: str
    preview_sha256: str
    staged_source_sha256: str
    bound: staged_executor.BoundStaged


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _snapshot(editor_root: Path, revision: int, digest: str) -> revisions.Revision:
    fixture = synthetic_cut._fixture()
    path = _path(editor_root)

    def verify(store):
        with store.conn:
            store.conn.execute("BEGIN")
            head = store.current(synthetic_cut._PROJECT)
            history = store.selection_history(synthetic_cut._PROJECT)
            if (head.number != revision or head.plan_sha256 != digest
                    or len(history) != head.number or head.number > _MAX_REVISION):
                raise revisions.Conflict("saved editor revision changed")
            if history:
                candidate = synthetic_cut._selection(fixture, history[-1])
                expected = fixture[3][history[-1].selection_key]
                if candidate.plan_sha256 != digest:
                    raise revisions.Conflict("saved candidate changed")
            else:
                expected = fixture[3][()]
            undo, _ = store.fixture_stacks(history, _digest(fixture[3][()]))
            if (head.plan_bytes != expected or undo[-1][1] != digest
                    or dict(head.clip_uids).keys() != {"r01"}):
                raise revisions.Conflict("invalid saved synthetic revision")
            return head

    if path.exists():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
            store = revisions.Store(conn, initialize=False)
            if store.has_project(synthetic_cut._PROJECT):
                return verify(store)
    with closing(sqlite3.connect(":memory:")) as conn:
        store = revisions.Store(conn)
        synthetic_cut._initial(store, fixture[3])
        return verify(store)


def _read_fixed(root: Path, name: str, expected: str) -> bytes:
    path = root / name
    if not safe_path(root, path) or not path.is_file() or path.stat().st_size > 64_000:
        raise ValueError("bundled synthetic asset unavailable")
    raw = path.read_bytes()
    if _digest(raw) != expected:
        raise ValueError("bundled synthetic asset changed")
    return raw


def prepare_saved_cut(editor_root: Path, workspace: Path, public_dir: Path, *,
                      revision: int, plan_sha256: str, job_id: str,
                      ffmpeg: str = "ffmpeg") -> PreparedCut:
    """Stage an exact current snapshot in a fresh, trusted isolated workspace.

    The caller supplies pre-staged fixture config. Never writes the editor DB,
    modifies the original preview, changes temporal/crop/audio edits, or
    overwrites any existing stage files. Partial stages are not reused.
    The existing 3-second preview is video-only; add a silent AAC stream
    without re-encoding its video. No synthetic speech or substitute footage.
    """
    for root in (editor_root, workspace, public_dir):
        if not root.is_absolute() or not root.is_dir() or root.resolve() != root:
            raise ValueError("canonical trusted directories required")
    if workspace == editor_root or workspace.is_relative_to(editor_root) or editor_root.is_relative_to(workspace):
        raise ValueError("separate isolated export workspace required")
    head = _snapshot(editor_root, revision, plan_sha256)
    manifest = head.manifest()
    if (manifest.source != _STEM + ".mp4" or manifest.source_sha256 != "b" * 64
            or manifest.source_path or len(manifest.reels) != 1
            or manifest.reels[0].id != "r01"):
        raise ValueError("not a supported synthetic editor manifest")
    preview = _read_fixed(public_dir, "synthetic-editor-preview.mp4", PREVIEW_SHA256)
    track = manifest.reels[0].background_track
    asset_raw = None
    if track is not None:
        if track.asset not in TRACKS:
            raise ValueError("unsupported synthetic soundtrack")
        asset_raw = _read_fixed(public_dir, f"synthetic-soundtrack-{TRACKS.index(track.asset)+1}.wav",
                                track.asset.sha256)

    layer = manifest.reels[0].graphic_layer
    image = layer.image if layer is not None else None
    image_raw = None
    if image is not None:
        if image != IMAGE:
            raise ValueError("unsupported synthetic graphic image")
        image_raw = _read_fixed(public_dir, IMAGE_NAME, image.sha256)

    # All media paths are derived from fixed selectors. The trusted executor
    # owns the workspace exclusively; this is not hostile-local-user isolation.
    source = workspace / "inputs" / manifest.source
    plan = workspace / "reviews" / (_STEM + ".review.json")
    original = workspace / "preview-original.mp4"
    receipt = workspace / "editor-export.json"
    assets = workspace / "assets"
    output = workspace / "reels-out"
    for path in (source, plan, original, receipt, assets, output):
        if not safe_path(workspace, path) or path.exists():
            raise ValueError("export workspace already used or blocked")
    for folder in (source.parent, plan.parent):
        if not safe_path(workspace, folder):
            raise ValueError("blocked staging directory")
        folder.mkdir(exist_ok=True)
    with original.open("xb") as handle:
        handle.write(preview)
    binary = shutil.which(ffmpeg)
    if not binary:
        raise ValueError("FFmpeg unavailable")
    subprocess.run([binary, "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                    "-i", str(original), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
                    "-t", "3", "-movflags", "+faststart", str(source)],
                   check=True, capture_output=True, timeout=20)
    if _digest(original.read_bytes()) != PREVIEW_SHA256:
        raise ValueError("staged preview changed")
    source_digest = _digest(source.read_bytes())
    staged = manifest.model_copy(update={"source_sha256": source_digest})
    raw = staged.model_dump_json().encode("utf-8")
    if Manifest.model_validate_json(raw).model_copy(update={"source_sha256": manifest.source_sha256}) != manifest:
        raise ValueError("staging changed the edit plan")
    with plan.open("xb") as handle:
        handle.write(raw)
    if track is not None or image is not None:
        assets.mkdir()
    if track is not None:
        with (assets / (track.asset.sha256 + ".wav")).open("xb") as handle:
            handle.write(asset_raw)
    if image is not None:
        with (assets / (image.sha256 + ".png")).open("xb") as handle:
            handle.write(image_raw)
    bound = staged_executor.bind(workspace, job_id=job_id, target_id="synthetic-desktop",
                                 stem=_STEM, clip="r01", gate="ui-editor-export")
    if bound.request.plan_sha256 != _digest(raw):
        raise ValueError("staged plan binding changed")
    result = PreparedCut(revision, head.plan_sha256, bound.request.plan_sha256,
                         PREVIEW_SHA256, source_digest, bound)
    # This receipt links editor and render hashes, not an export approval.
    with receipt.open("x", encoding="utf-8") as handle:
        json.dump({"editor_revision": revision, "editor_plan_sha256": head.plan_sha256,
                   "staged_plan_sha256": result.staged_plan_sha256,
                   "preview_sha256": PREVIEW_SHA256, "staged_source_sha256": source_digest,
                   "audio_binding": "silent-aac-v1", "config_sha256": bound.request.config_sha256},
                  handle, sort_keys=True)
    return result
