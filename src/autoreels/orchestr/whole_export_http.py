"""Explicit one-shot LOCAL synthetic export. No production or private proxy launch."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from . import execution, synthetic_whole, synthetic_whole_export as exporter
from .pathguard import safe_path
from .pipeline_gateway import _staged_file_identity
from .settings import Settings

_JOB="whole-export"
_RESERVATION=".whole-export-reserved"
_LEDGER="whole-jobs.sqlite"
_OUTPUT="reels-out/DEMO/_gate/ui-whole-export/r01.mp4"


class ExportCommand(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    revision: int
    plan_sha256: str


class ExportView(BaseModel):
    enabled: bool
    status: Literal["disabled","ready","reserved","queued","running","cancelling","reconcile",
                    "success","empty","failed","cancelled","blocked"]
    editor_revision: int | None
    editor_plan_sha256: str | None
    artifact_sha256: str | None


def _state(status,body=None,digest=None):
    return ExportView(enabled=status!="disabled",status=status,
        editor_revision=body.revision if body is not None else None,
        editor_plan_sha256=body.plan_sha256 if body is not None else None,
        artifact_sha256=digest)


def _workspace(s: Settings) -> Path | None:
    root=s.synthetic_export_workspace
    if root is None or not s.synthetic_editor or s.private_origin is not None:
        return None
    if (not root.is_absolute() or not root.is_dir() or root.resolve()!=root
            or root==s.root or root.is_relative_to(s.root) or s.root.is_relative_to(root)):
        raise ValueError("isolated workspace unavailable")
    for path in (root/_RESERVATION,root/_RESERVATION/"request.json",root/_LEDGER,
                 *(root/(_LEDGER+suffix) for suffix in ("-wal","-shm","-journal")),root/_OUTPUT):
        if not safe_path(root,path):
            raise ValueError("blocked workspace path")
    return root


def _read(root):
    marker=root/_RESERVATION
    if not marker.exists():
        if any((root/p).exists() for p in (_LEDGER,"whole-export.json","inputs/DEMO.mp4",
                                           "reviews/DEMO.review.json","reels-out")):
            return _state("blocked")
        return _state("ready")
    if not marker.is_dir():
        return _state("blocked")
    record=marker/"request.json"
    if not record.exists():
        return _state("reserved")
    if not record.is_file() or record.stat().st_size>4096:
        return _state("blocked")
    body=ExportCommand.model_validate_json(record.read_bytes())
    db=root/_LEDGER
    if not db.exists():
        return _state("reserved",body)
    if not db.is_file():
        return _state("blocked",body)
    with closing(sqlite3.connect(db.as_uri()+"?mode=ro",uri=True,timeout=5)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_jobs_v1'").fetchone():
            return _state("reserved",body)
        row=conn.execute("SELECT payload FROM execution_jobs_v1 WHERE job_id=?",(_JOB,)).fetchone()
    if row is None:
        return _state("reserved",body)
    job=execution.Job.model_validate_json(row[0])
    if job.status=="success":
        receipt=root/"whole-export.json"
        if not safe_path(root,receipt) or not receipt.is_file() or receipt.stat().st_size>4096:
            return _state("blocked",body)
        info=json.loads(receipt.read_text(encoding="utf-8"))
        if (info["editor_revision"]!=body.revision or info["editor_plan_sha256"]!=body.plan_sha256
                or info["plan_sha256"]!=job.request.plan_sha256
                or info["config_sha256"]!=job.request.config_sha256
                or _staged_file_identity(root,root/_OUTPUT)[0]!=job.artifact_sha256):
            return _state("blocked",body)
        return _state("success",body,job.artifact_sha256)
    return _state(job.status,body)


def view(s: Settings) -> ExportView:
    try:
        root=_workspace(s)
        return _state("disabled") if root is None else _read(root)
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error,execution.Conflict):
        return _state("blocked")


def command(s: Settings,body: ExportCommand) -> ExportView:
    # Explicit trusted local config only. No path, argv, target or media supplied by HTTP.
    if not (0<=body.revision<=100 and re.fullmatch(r"[0-9a-f]{64}",body.plan_sha256)):
        raise HTTPException(422,"invalid export revision")
    current=view(s)
    if current.status=="disabled":
        raise HTTPException(409,"synthetic export disabled")
    if current.status!="ready":
        if (current.editor_revision,current.editor_plan_sha256)==(body.revision,body.plan_sha256):
            return current
        raise HTTPException(409,"export workspace already reserved or blocked")
    try:
        root=_workspace(s)
        synthetic_whole.snapshot(s.root,body.revision,body.plan_sha256)
        # Preflight the fixed trusted config before consuming the single reservation.
        for name in ("r0.yaml","render.yaml","render.local.yaml","subtitles.yaml"):
            _staged_file_identity(root,root/"config"/name)
        (root/_RESERVATION).mkdir(mode=0o700)
    except (OSError,ValueError,sqlite3.Error,execution.Conflict,synthetic_whole.revisions.Conflict):
        raise HTTPException(409,"export workspace or saved revision unavailable") from None
    try:
        with (root/_RESERVATION/"request.json").open("x",encoding="utf-8") as handle:
            handle.write(body.model_dump_json())
        prepared=exporter.prepare(s.root,root,revision=body.revision,digest=body.plan_sha256,job_id=_JOB)
        with closing(sqlite3.connect(root/_LEDGER,timeout=5)) as db:
            ledger=execution.Ledger(db)
            exporter.execute_prepared(prepared,ledger,worker_id="local-ui")
        return _read(root)
    except Exception:
        # A partial or interrupted stage stays reserved, never retried implicitly.
        raise HTTPException(503,"synthetic export interrupted; inspect reserved workspace") from None


def artifact(s: Settings) -> Path:
    if view(s).status!="success":
        raise HTTPException(404,"validated synthetic export unavailable")
    return _workspace(s)/_OUTPUT
