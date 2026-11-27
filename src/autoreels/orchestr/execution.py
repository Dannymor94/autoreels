"""Internal executor contract. No public API, processes, filesystem or network.

The caller supplies a trusted coordinator clock and a SQLite connection. Real
worker authentication, preflight, process/output locks and artifact validation
must be implemented by the adapter before enabling real execution.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
OpaqueId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]
Kind = Literal["desktop", "remote", "mobile"]
Status = Literal["queued", "running", "cancelling", "reconcile", "success", "empty", "failed", "cancelled"]
ACTIVE = ("queued", "running", "cancelling", "reconcile")
MAX_LEASE_MS = 60_000
MAX_ATTEMPTS = 2


class Conflict(RuntimeError):
    """No mutation performed; caller must reload or reconcile."""


class Request(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    job_id: OpaqueId
    target_id: OpaqueId
    target_kind: Kind
    plan_sha256: Digest
    config_sha256: Digest
    output_key: Digest


class Job(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    request: Request
    status: Status = "queued"
    revision: int = 0
    fence: int = 0
    worker_id: OpaqueId | None = None
    expires_ms: int | None = None
    cancel_requested: bool = False
    artifact_sha256: Digest | None = None


def _change(job: Job, **fields) -> Job:
    # Validate the resulting value, rather than trusting model_copy(update=...).
    return Job.model_validate({**job.model_dump(), **fields, "revision": job.revision + 1})


def _time(now: int, ttl: int | None = None):
    if type(now) is not int or not 0 <= now <= 2**63 - 1 - MAX_LEASE_MS:
        raise ValueError("invalid coordinator time")
    if ttl is not None and (type(ttl) is not int or not 1 <= ttl <= MAX_LEASE_MS):
        raise ValueError("invalid lease duration")


def _live(job: Job, worker_id: str, fence: int, now: int):
    _time(now)
    if (job.status not in ("running", "cancelling") or job.worker_id != worker_id
            or type(fence) is not int or job.fence != fence
            or job.expires_ms is None or now >= job.expires_ms):
        raise Conflict("lease is not current")


def claim(job: Job, target_id: str, worker_id: str, now: int, ttl: int) -> Job:
    _time(now, ttl)
    if worker_id is None:
        raise ValueError("worker identity required")
    if job.status != "queued" or target_id != job.request.target_id or job.fence >= MAX_ATTEMPTS:
        raise Conflict("job cannot be claimed")
    return _change(job, status="running", worker_id=worker_id, fence=job.fence + 1,
                   expires_ms=now + ttl)


def renew(job: Job, worker_id: str, fence: int, now: int, ttl: int) -> Job:
    _time(now, ttl)
    _live(job, worker_id, fence, now)
    if now + ttl <= job.expires_ms:
        raise Conflict("renewal must extend the lease")
    return _change(job, expires_ms=now + ttl)


def cancel(job: Job) -> Job:
    if job.status == "queued":
        return _change(job, status="cancelled", cancel_requested=True)
    if job.status == "running":
        return _change(job, status="cancelling", cancel_requested=True)
    if job.status == "reconcile" and not job.cancel_requested:
        return _change(job, cancel_requested=True)
    if job.cancel_requested and job.status in ("cancelled", "cancelling", "reconcile"):
        return job
    raise Conflict("job already finished")


def expire(job: Job, now: int) -> Job:
    _time(now)
    if job.status not in ("running", "cancelling") or job.expires_ms is None or now < job.expires_ms:
        raise Conflict("lease has not expired")
    # Keep output reservation and fence. Never infer that a process stopped.
    return _change(job, status="reconcile", expires_ms=None)


def finish(job: Job, worker_id: str, fence: int, now: int,
           outcome: Literal["success", "empty", "failed", "cancelled"],
           artifact_sha256: str | None = None) -> Job:
    """Trusted adapter only, after process exit and output reconciliation."""
    _live(job, worker_id, fence, now)
    if outcome not in ("success", "empty", "failed", "cancelled"):
        raise ValueError("invalid outcome")
    if (outcome == "cancelled") != job.cancel_requested:
        raise Conflict("cancellation must be acknowledged")
    if (outcome == "success") != (artifact_sha256 is not None):
        raise ValueError("success requires a validated artifact digest; other outcomes forbid it")
    return _change(job, status=outcome, artifact_sha256=artifact_sha256,
                   worker_id=None, expires_ms=None)


def reconcile_stopped(job: Job, *, retry: bool) -> Job:
    """Trusted coordinator only AFTER confirming process exit and no accepted output.

    Not a proof of process exit by itself. The actual adapter must reconcile
    staging/output and hold the external resource lock before calling this.
    """
    if job.status != "reconcile" or type(retry) is not bool:
        raise Conflict("job not awaiting reconciliation")
    status = ("cancelled" if job.cancel_requested else
              "queued" if retry and job.fence < MAX_ATTEMPTS else "failed")
    return _change(job, status=status, worker_id=None, expires_ms=None)


def reconcile_artifact(job: Job, artifact_sha256: str) -> Job:
    """Trusted coordinator only AFTER verifying the exact artifact and process exit."""
    if job.status != "reconcile" or job.cancel_requested:
        raise Conflict("artifact cannot be accepted")
    if artifact_sha256 is None:
        raise ValueError("validated artifact digest required")
    return _change(job, status="success", artifact_sha256=artifact_sha256,
                   worker_id=None, expires_ms=None)


class Ledger:
    """Durable CAS and output reservation, scoped to one authoritative DB.

    No DB path or connection is created here. This table is only exercised
    with isolated synthetic fixtures until the real adapter is approved.
    """
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        if conn.in_transaction:
            raise ValueError("ledger needs a dedicated idle connection")
        with self._tx():
            conn.execute("""
                CREATE TABLE IF NOT EXISTS execution_jobs_v1 (
                    job_id TEXT PRIMARY KEY,
                    target_id TEXT NOT NULL,
                    output_key TEXT NOT NULL,
                    active INTEGER NOT NULL CHECK(active IN (0,1)),
                    revision INTEGER NOT NULL,
                    payload TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS execution_output_v1
                ON execution_jobs_v1(target_id, output_key) WHERE active=1
            """)

    @contextmanager
    def _tx(self):
        if self.conn.in_transaction:
            raise ValueError("nested ledger transaction")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def get(self, job_id: str) -> Job:
        row = self.conn.execute("SELECT payload FROM execution_jobs_v1 WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise Conflict("unknown job")
        return Job.model_validate_json(row[0])

    def submit(self, request: Request) -> Job:
        with self._tx():
            row = self.conn.execute("SELECT payload FROM execution_jobs_v1 WHERE job_id=?",
                                    (request.job_id,)).fetchone()
            if row is not None:
                job = Job.model_validate_json(row[0])
                if job.request != request:
                    raise Conflict("identifier already bound to another request")
                return job
            job = Job(request=request)
            try:
                self.conn.execute("INSERT INTO execution_jobs_v1 VALUES(?,?,?,?,?,?)",
                                  (request.job_id, request.target_id, request.output_key,
                                   1, job.revision, job.model_dump_json()))
            except sqlite3.IntegrityError:
                raise Conflict("output already reserved") from None
            return job

    def apply(self, job_id: str, revision: int, transition, *args, **kwargs) -> Job:
        # Internal trusted transition functions only, never dispatch a client string.
        if transition not in (claim, renew, cancel, expire, finish, reconcile_stopped, reconcile_artifact):
            raise ValueError("unknown transition")
        with self._tx():
            current = self.get(job_id)
            if type(revision) is not int or current.revision != revision:
                raise Conflict("stale revision")
            job = transition(current, *args, **kwargs)
            if job == current:
                return current
            self.conn.execute(
                "UPDATE execution_jobs_v1 SET active=?,revision=?,payload=? WHERE job_id=?",
                (int(job.status in ACTIVE), job.revision, job.model_dump_json(), job_id),
            )
            return job
