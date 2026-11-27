"""UI-202A: durable synthetic-only job coordinator; no pipeline side effects."""
import logging
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from threading import Event
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, model_validator

from .pathguard import safe_path
from .render_targets import TargetKind

Outcome = Literal["success", "empty", "failed"]
JobStatus = Literal["queued", "running", "success", "empty", "failed", "cancelled"]
Stage = Literal["queued", "prepare", "plan", "simulate_render", "done", "cancelled"]
MAX_JOBS = 100
_DB_NAME = ".ui-synthetic-jobs.sqlite3"
log = logging.getLogger(__name__)


class JobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["create", "cancel"]
    target_kind: TargetKind | None
    outcome: Outcome | None

    @model_validator(mode="after")
    def check_fields(self):
        if self.action == "create":
            if self.target_kind is None or self.outcome is None:
                raise ValueError("create requires explicit target and synthetic outcome")
        elif self.target_kind is not None or self.outcome is not None:
            raise ValueError("cancel must not specify target or outcome")
        return self


class SyntheticJob(BaseModel):
    job_id: str
    target_kind: TargetKind
    outcome: Outcome
    status: JobStatus
    stage: Stage
    progress: int
    revision: int


class JobInventory(BaseModel):
    enabled: bool
    jobs: list[SyntheticJob]


def _path(root: Path) -> Path:
    path = root / _DB_NAME
    for candidate in (path, *(path.with_name(path.name + s) for s in ("-journal", "-wal", "-shm"))):
        if not safe_path(root, candidate) or (candidate.exists() and not candidate.is_file()):
            raise HTTPException(409, "synthetic job storage unavailable")
    return path


def _connect(path: Path, write: bool):
    conn = sqlite3.connect(path if write else path.as_uri() + "?mode=ro", uri=not write, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _transaction(path: Path):
    with closing(_connect(path, True)) as conn:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    seq INTEGER PRIMARY KEY,
                    job_id TEXT UNIQUE NOT NULL,
                    target_kind TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    revision INTEGER NOT NULL
                )
            """)
            yield conn


def _rows(conn):
    return [SyntheticJob.model_validate(dict(row)) for row in conn.execute(
        "SELECT * FROM jobs ORDER BY seq DESC LIMIT ?", (MAX_JOBS,)
    )]


def inventory(root: Path, enabled: bool) -> JobInventory:
    if not enabled:
        return JobInventory(enabled=False, jobs=[])
    try:
        path = _path(root)
        if not path.exists():
            return JobInventory(enabled=True, jobs=[])
        with closing(_connect(path, False)) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone():
                return JobInventory(enabled=True, jobs=[])
            return JobInventory(enabled=True, jobs=_rows(conn))
    except (sqlite3.Error, OSError, ValueError):
        raise HTTPException(503, "synthetic job storage unavailable") from None


def command(root: Path, enabled: bool, job_id: str, body: JobCommand) -> SyntheticJob:
    if not enabled:
        raise HTTPException(409, "synthetic jobs disabled")
    try:
        if str(UUID(job_id)) != job_id:
            raise ValueError
    except ValueError:
        raise HTTPException(422, "invalid job identifier") from None
    try:
        path = _path(root)
        if body.action == "cancel" and not path.exists():
            raise HTTPException(404, "job not found")
        with _transaction(path) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if body.action == "create":
                if row is not None:
                    if row["target_kind"] != body.target_kind or row["outcome"] != body.outcome:
                        raise HTTPException(409, "job identifier already bound")
                else:
                    if conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] >= MAX_JOBS:
                        raise HTTPException(409, "synthetic job history limit reached")
                    conn.execute(
                        "INSERT INTO jobs(job_id,target_kind,outcome,status,stage,progress,revision) "
                        "VALUES(?,?,?,'queued','queued',0,0)",
                        (job_id, body.target_kind, body.outcome),
                    )
            else:
                if row is None:
                    raise HTTPException(404, "job not found")
                if row["status"] in ("queued", "running"):
                    conn.execute(
                        "UPDATE jobs SET status='cancelled',stage='cancelled',revision=revision+1 WHERE job_id=?",
                        (job_id,),
                    )
                elif row["status"] != "cancelled":
                    raise HTTPException(409, "job already finished")
            return SyntheticJob.model_validate(dict(conn.execute(
                "SELECT * FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()))
    except (sqlite3.Error, OSError, ValueError):
        raise HTTPException(503, "synthetic job storage unavailable") from None


def advance(root: Path) -> bool:
    """One atomic simulated checkpoint; safe to resume with a fresh process.

    No operation escapes this transaction, hence no external lease or replay
    side effect. A real executor MUST have fencing and a separate output lock.
    """
    path = _path(root)
    if not path.exists():
        return False
    with _transaction(path) as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status IN ('queued','running') "
            "ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, seq LIMIT 1"
        ).fetchone()
        if row is None:
            return False
        job = SyntheticJob.model_validate(dict(row))
        if job.status == "queued":
            status, stage, progress = "running", "prepare", 25
        elif job.stage == "prepare":
            status, stage, progress = "running", "plan", 60
        elif job.stage == "plan":
            if job.outcome == "empty":
                status, stage, progress = "empty", "done", 100
            else:
                status, stage, progress = "running", "simulate_render", 85
        elif job.stage == "simulate_render":
            status, stage, progress = job.outcome, "done", 100
        else:
            raise ValueError("invalid synthetic checkpoint")
        conn.execute(
            "UPDATE jobs SET status=?,stage=?,progress=?,revision=revision+1 WHERE job_id=?",
            (status, stage, progress, job.job_id),
        )
        return True


def run_worker(root: Path, stop: Event):
    reported = False
    while not stop.wait(1.0):
        try:
            advance(root)
            reported = False
        except (sqlite3.Error, OSError, ValueError, HTTPException):
            if not reported:
                log.warning("synthetic job worker blocked by storage error")
                reported = True
