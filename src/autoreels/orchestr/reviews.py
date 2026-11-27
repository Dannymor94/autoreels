"""Local technical reviews. Never writes legacy draft/export/learning decisions."""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from . import pipeline_gateway

Verdict = Literal["keep", "fix", "drop"]
_SHA = r"^[0-9a-f]{64}$"
_ID = r"^[0-9a-f-]{36}$"
_CHUNK = 1024 * 1024


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=_ID)
    artifact_sha256: str = Field(pattern=_SHA)
    base_revision: str | None
    verdict: Verdict
    comment: str = Field(max_length=2000)
    position_s: float | None = Field(ge=0, allow_inf_nan=False)


class ReviewEvent(BaseModel):
    request_id: str
    artifact_sha256: str
    verdict: Verdict
    comment: str
    position_s: float | None
    created_at: str


class LegacyReview(BaseModel):
    gate: str
    verdict: str
    comment: str
    date: str


class ReviewState(BaseModel):
    artifact_sha256: str
    current: ReviewEvent | None
    history: list[ReviewEvent]
    legacy: list[LegacyReview]


def _signature(st):
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def _open_hashed(path: Path):
    """Hash the opened regular file, not just its name or render.json fingerprint."""
    handle = None
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise HTTPException(404, "not a regular video file")
        handle = path.open("rb")
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise HTTPException(404, "not a regular video file")
        h = hashlib.sha256()
        for block in iter(lambda: handle.read(_CHUNK), b""):
            h.update(block)
        if _signature(before) != _signature(os.fstat(handle.fileno())):
            raise HTTPException(409, "video changed while reading")
        if _signature(before) != _signature(path.stat()):
            raise HTTPException(409, "video replaced while reading")
        handle.seek(0)
        return handle, h.hexdigest(), before
    except BaseException as exc:
        if handle is not None:
            handle.close()
        if isinstance(exc, OSError):
            raise HTTPException(409, "video unavailable or changed") from exc
        raise


def artifact_hash(path: Path) -> str:
    handle, digest, _ = _open_hashed(path)
    with handle:
        return digest


def versioned_media(path: Path, expected: str, request: Request):
    """Serve the opened, verified bytes. Single HTTP byte range for browser seeking.

    Existing unversioned playback remains on FileResponse. No copies or new media
    files are produced. A midstream mutation aborts instead of silently switching.
    Local review is not an authenticated remote service.
    """
    handle, digest, st = _open_hashed(path)
    size = st.st_size
    try:
        if digest != expected:
            raise HTTPException(409, "review video changed")
        start, end, status = 0, size - 1, 200
        headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-store",
                   "ETag": '"' + digest + '"'}
        raw = request.headers.get("range")
        if raw and request.headers.get("if-range", headers["ETag"]) == headers["ETag"]:
            match = re.fullmatch(r"bytes=(\d{0,20})-(\d{0,20})", raw)
            if match and size and (match[1] or match[2]):
                if not match[1]:
                    start = max(0, size - int(match[2]))
                else:
                    start = int(match[1])
                    if match[2]:
                        end = min(end, int(match[2]))
            if not match or not size or not (match[1] or match[2]) or start > end:
                raise HTTPException(416, "unsupported byte range",
                                    headers={"Content-Range": f"bytes */{size}"})
            status = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        length = max(0, end - start + 1)
        headers["Content-Length"] = str(length)
        handle.seek(start)

        def chunks():
            remaining = length
            try:
                while remaining:
                    data = handle.read(min(_CHUNK, remaining))
                    if not data or _signature(st) != _signature(os.fstat(handle.fileno())):
                        raise OSError("review video changed during streaming")
                    remaining -= len(data)
                    yield data
            finally:
                handle.close()

        return StreamingResponse(chunks(), status_code=status, media_type="video/mp4",
                                 headers=headers, background=BackgroundTask(handle.close))
    except BaseException:
        handle.close()
        raise


def _db_path(root: Path) -> Path:
    reviews = root / "reviews"
    folder = reviews / "ui"
    path = folder / "technical_reviews.sqlite3"
    if any(p.is_symlink() for p in (reviews, folder, path)):
        raise HTTPException(409, "review storage cannot be a symlink")
    return path


def _connect(path: Path, *, write: bool):
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=5)
    else:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _create(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY,
            request_id TEXT NOT NULL UNIQUE,
            stem TEXT NOT NULL,
            clip TEXT NOT NULL,
            variant TEXT NOT NULL,
            artifact_sha256 TEXT NOT NULL,
            base_revision TEXT,
            verdict TEXT NOT NULL,
            comment TEXT NOT NULL,
            position_s REAL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS locator ON events(stem,clip,variant,seq)")


def _events(conn, stem, clip, variant):
    return [ReviewEvent.model_validate(dict(row)) for row in conn.execute(
        "SELECT * FROM events WHERE stem=? AND clip=? AND variant=? ORDER BY seq DESC",
        (stem, clip, variant),
    )]


def _state(root, digest, events, stem, clip):
    return ReviewState(
        artifact_sha256=digest,
        current=next((e for e in events if e.artifact_sha256 == digest), None),
        history=events,
        legacy=[LegacyReview.model_validate(row) for row in
                pipeline_gateway.legacy_reviews(root, stem, clip)],
    )


def get_state(root: Path, path: Path, stem: str, clip: str, variant: str) -> ReviewState:
    digest = artifact_hash(path)
    db = _db_path(root)
    if not db.exists():
        return _state(root, digest, [], stem, clip)
    try:
        with closing(_connect(db, write=False)) as conn:
            return _state(root, digest, _events(conn, stem, clip, variant), stem, clip)
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(503, "review storage unavailable") from exc


def save(root: Path, path: Path, stem: str, clip: str, variant: str,
         body: ReviewInput) -> ReviewState:
    if artifact_hash(path) != body.artifact_sha256:
        raise HTTPException(409, "review video changed")
    db = _db_path(root)
    payload = (stem, clip, variant, body.artifact_sha256, body.base_revision,
               body.verdict, body.comment, body.position_s)
    try:
        with closing(_connect(db, write=True)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            _create(conn)
            prior = conn.execute(
                "SELECT stem,clip,variant,artifact_sha256,base_revision,verdict,comment,position_s "
                "FROM events WHERE request_id=?", (body.request_id,),
            ).fetchone()
            if prior is not None:
                if tuple(prior) != payload:
                    raise HTTPException(409, "request id already used with different data")
            else:
                current = conn.execute(
                    "SELECT request_id FROM events WHERE stem=? AND clip=? AND variant=? "
                    "AND artifact_sha256=? ORDER BY seq DESC LIMIT 1",
                    (stem, clip, variant, body.artifact_sha256),
                ).fetchone()
                if (current[0] if current else None) != body.base_revision:
                    raise HTTPException(409, "review revision changed")
                conn.execute(
                    "INSERT INTO events(request_id,stem,clip,variant,artifact_sha256,"
                    "base_revision,verdict,comment,position_s,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (body.request_id, *payload, datetime.now(timezone.utc).isoformat()),
                )
            events = _events(conn, stem, clip, variant)
        return _state(root, body.artifact_sha256, events, stem, clip)
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(503, "review storage unavailable") from exc


# UI-104: preference is not a verdict or export approval.
class ComparisonInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=_ID)
    left_sha256: str = Field(pattern=_SHA)
    right_sha256: str = Field(pattern=_SHA)
    base_revision: str | None
    winner: str
    comment: str = Field(max_length=2000)


class ComparisonEvent(BaseModel):
    request_id: str
    left_variant: str
    right_variant: str
    left_sha256: str
    right_sha256: str
    winner: str
    comment: str
    created_at: str


class ComparisonState(BaseModel):
    left_variant: str
    right_variant: str
    left_sha256: str
    right_sha256: str
    current: ComparisonEvent | None
    history: list[ComparisonEvent]


def _comparison_rows(conn, stem, clip, a, b):
    # Existing UI-103 databases have no comparisons table until first choice.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='comparisons'").fetchone():
        return []
    return [ComparisonEvent.model_validate(dict(row)) for row in conn.execute(
        "SELECT * FROM comparisons WHERE stem=? AND clip=? AND left_variant=? "
        "AND right_variant=? ORDER BY seq DESC", (stem, clip, a, b),
    )]


def _comparison_state(a, b, sha_a, sha_b, events):
    return ComparisonState(left_variant=a, right_variant=b, left_sha256=sha_a,
                           right_sha256=sha_b, history=events,
                           current=next((e for e in events if
                               (e.left_sha256, e.right_sha256) == (sha_a, sha_b)), None))


def compare(root: Path, stem: str, clip: str, left: str, right: str,
            body: ComparisonInput | None = None) -> ComparisonState:
    from .media import resolve_media_path

    if left == right:
        raise HTTPException(422, "choose two different variants")
    # Canonical ordering makes switching the UI sides the same comparison.
    a, b = sorted((left, right))
    path_a = resolve_media_path(root, stem, clip, a)
    path_b = resolve_media_path(root, stem, clip, b)
    sha_a, sha_b = artifact_hash(path_a), artifact_hash(path_b)
    db = _db_path(root)
    if body is None and not db.exists():
        return _comparison_state(a, b, sha_a, sha_b, [])
    try:
        if body is None:
            with closing(_connect(db, write=False)) as conn:
                return _comparison_state(a, b, sha_a, sha_b, _comparison_rows(conn, stem, clip, a, b))
        if body.winner not in (a, b):
            raise HTTPException(422, "winner must be one of the selected variants")
        expected = (body.left_sha256, body.right_sha256) if left == a else (body.right_sha256, body.left_sha256)
        if expected != (sha_a, sha_b):
            raise HTTPException(409, "comparison video changed")
        payload = (stem, clip, a, b, sha_a, sha_b, body.base_revision, body.winner, body.comment)
        with closing(_connect(db, write=True)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            _create(conn)
            conn.execute("""CREATE TABLE IF NOT EXISTS comparisons (
                seq INTEGER PRIMARY KEY,
                request_id TEXT NOT NULL UNIQUE,
                stem TEXT NOT NULL, clip TEXT NOT NULL,
                left_variant TEXT NOT NULL, right_variant TEXT NOT NULL,
                left_sha256 TEXT NOT NULL, right_sha256 TEXT NOT NULL,
                base_revision TEXT, winner TEXT NOT NULL, comment TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")
            prior = conn.execute(
                "SELECT stem,clip,left_variant,right_variant,left_sha256,right_sha256,"
                "base_revision,winner,comment FROM comparisons WHERE request_id=?",
                (body.request_id,),
            ).fetchone()
            if prior is not None:
                if tuple(prior) != payload:
                    raise HTTPException(409, "request id already used with different data")
            else:
                current = _comparison_state(a, b, sha_a, sha_b, _comparison_rows(conn, stem, clip, a, b)).current
                if (current.request_id if current else None) != body.base_revision:
                    raise HTTPException(409, "comparison revision changed")
                conn.execute(
                    "INSERT INTO comparisons(request_id,stem,clip,left_variant,right_variant,"
                    "left_sha256,right_sha256,base_revision,winner,comment,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (body.request_id, *payload, datetime.now(timezone.utc).isoformat()),
                )
            events = _comparison_rows(conn, stem, clip, a, b)
        return _comparison_state(a, b, sha_a, sha_b, events)
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(503, "review storage unavailable") from exc
