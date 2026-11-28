"""Internal bridge for the isolated staged fixture, never a public worker API.

No discovery, remote execution, transfer, publication or source archiving.
The trusted caller owns the isolated root, assets, process/environment and
decoder validation. This is a bounded synchronous pilot, not production
process supervision; an uncertain result retains the ledger reservation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import execution, pipeline_gateway, process_supervisor
from .pathguard import safe_path

_CONFIG_FILES = ("r0.yaml", "render.yaml", "render.local.yaml", "subtitles.yaml")


@dataclass(frozen=True)
class BoundStaged:
    root: Path
    stem: str
    clip: str
    gate: str
    request: execution.Request


def bind(root: Path, *, job_id: str, target_id: str, stem: str, clip: str, gate: str) -> BoundStaged:
    """Bind the narrow H.264 fixture to the plan and staged config byte digests.

    The config digest is fixture-specific, NOT a full production effective
    config/assets/toolchain fingerprint. The destination key is computed by
    the trusted coordinator, never taken from an HTTP client.
    """
    if not root.is_absolute() or not root.is_dir() or root != root.resolve():
        raise ValueError("canonical isolated root required")
    if not (re.fullmatch(r"[A-Za-z0-9_-]{1,64}", stem)
            and re.fullmatch(r"r[0-9]{2,6}", clip)
            and re.fullmatch(r"ui-[a-z0-9-]{1,60}", gate)):
        raise ValueError("invalid staged selector")
    config = root / "config"
    files = [
        (name, pipeline_gateway._staged_file_identity(root, config / name)[0])
        for name in _CONFIG_FILES
    ]
    plan = root / "reviews" / (stem + ".review.json")
    plan_sha = pipeline_gateway._staged_file_identity(root, plan)[0]
    from autoreels.core.models import Manifest
    from autoreels.local.assets import resolve_audio_asset, resolve_image_asset
    raw = plan.read_bytes()
    if hashlib.sha256(raw).hexdigest() != plan_sha:
        raise ValueError("staged plan changed")
    manifest = Manifest.model_validate_json(raw)
    # The CLI resolves all explicitly selected tracks; bind all of them.
    for digest, asset in sorted({r.background_track.asset.sha256:r.background_track.asset
                                for r in manifest.reels if r.background_track is not None}.items()):
        path = resolve_audio_asset(root / "assets", asset)
        if pipeline_gateway._staged_file_identity(root, path)[0] != digest:
            raise ValueError("staged asset changed")
        files.append(("asset:" + digest, digest))
    images = [r.graphic_layer.image for r in manifest.reels
              if r.graphic_layer is not None and r.graphic_layer.image is not None]
    for asset in sorted(images,key=lambda a:a.sha256):
        if asset.rights != "synthetic":
            raise ValueError("staged image must be synthetic")
        path = resolve_image_asset(root / "assets", asset)
        if pipeline_gateway._staged_file_identity(root, path)[0] != asset.sha256:
            raise ValueError("staged image changed")
        files.append(("image:" + asset.sha256, asset.sha256))
    snapshot = json.dumps(
        {"version": "fixture-v1", "profile": "h264", "encoder": "libx264",
         "archive_source": False, "pull_first": False, "fallback": False,
         "auto_recrop": False, "files": files},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")
    destination = root / "reels-out" / stem / "_gate" / gate
    if not safe_path(root, destination):
        raise ValueError("staged output unavailable")
    # Reserve the gate, not individual clip files; the gateway forbids reusing
    # a gate. Include the selected clip in the config binding below so another
    # selector cannot substitute for the original with the same request ID.
    config_sha = hashlib.sha256(snapshot + b"\0clip=" + clip.encode("ascii")).hexdigest()
    output_key = hashlib.sha256(os.fsencode(str(destination))).hexdigest()
    req = execution.Request(
        job_id=job_id, target_id=target_id, target_kind="desktop",
        plan_sha256=plan_sha, config_sha256=config_sha, output_key=output_key,
    )
    return BoundStaged(root, stem, clip, gate, req)


def _rebind(bound: BoundStaged) -> BoundStaged:
    return bind(bound.root, job_id=bound.request.job_id, target_id=bound.request.target_id,
                stem=bound.stem, clip=bound.clip, gate=bound.gate)


@contextmanager
def fixture_lock(root: Path):
    """Serialize cooperating fixture executors on POSIX; never unlink the lock.

    This is not a distributed lock, not a legacy-CLI lock and not proof that
    orphaned subprocesses died. Recovery still requires process reconciliation.
    """
    import fcntl

    path = root / ".ui-staged-executor.lock"
    if not safe_path(root, path) or (path.exists() and not path.is_file()):
        raise execution.Conflict("fixture lock unavailable")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise execution.Conflict("fixture lock unavailable") from exc
    with os.fdopen(fd, "rb+") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise execution.Conflict("fixture lock unavailable")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise execution.Conflict("fixture executor busy") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_bound(
    ledger: execution.Ledger, bound: BoundStaged, *, worker_id: str,
    clock_ms: Callable[[], int], run_render: Callable, verify: Callable[[Path], None],
) -> execution.Job:
    """Claim once, render synchronously, validate, and commit exact result.

    verify is trusted adapter code and MUST raise on any invalid artifact.
    Exceptions after claim retain an active reservation. Lease expiry never
    starts a second renderer; the caller must reconcile actual processes and
    staged outputs before retry. No progress/cancel signal or lease renewal
    yet, so only short fixtures are supported. No HTTP/launcher registration.
    """
    with fixture_lock(bound.root):
        if _rebind(bound) != bound:
            raise execution.Conflict("staged plan or config changed")
        job = ledger.get(bound.request.job_id)
        if job.request != bound.request:
            raise execution.Conflict("staged request mismatch")
        if (bound.root / "reels-out" / bound.stem / "_gate" / bound.gate).exists():
            raise execution.Conflict("staged gate already exists")
        job = ledger.apply(job.request.job_id, job.revision, execution.claim,
                           job.request.target_id, worker_id, clock_ms(), execution.MAX_LEASE_MS)
        fence = job.fence
        out, digest = pipeline_gateway.render_staged_clip(
            bound.root, stem=bound.stem, clip=bound.clip, gate=bound.gate,
            plan_sha256=job.request.plan_sha256, run_render=run_render,
        )
        initial = pipeline_gateway._staged_file_identity(bound.root, out)
        if initial[0] != digest:
            raise execution.Conflict("staged artifact changed")
        verify(out)
        if (pipeline_gateway._staged_file_identity(bound.root, out) != initial
                or _rebind(bound) != bound):
            raise execution.Conflict("staged artifact, plan or config changed")
        current = ledger.get(job.request.job_id)
        if current.status == "reconcile":
            return current
        if current.fence != fence or current.worker_id != worker_id:
            raise execution.Conflict("staged worker lost ownership")
        now = clock_ms()
        if current.expires_ms is None or now >= current.expires_ms:
            return ledger.apply(current.request.job_id, current.revision, execution.expire, now)
        if current.cancel_requested:
            # Synchronous runner and validation have returned; do not accept
            # or publish the staged bytes. Retain the file for reconciliation.
            return ledger.apply(current.request.job_id, current.revision, execution.finish,
                                worker_id, fence, now, "cancelled")
        return ledger.apply(current.request.job_id, current.revision, execution.finish,
                            worker_id, fence, now, "success", digest)



class _Interrupted(RuntimeError):
    def __init__(self, result: process_supervisor.Result):
        super().__init__("staged child did not complete successfully")
        self.result = result


def run_supervised_bound(
    ledger: execution.Ledger, bound: BoundStaged, *, worker_id: str,
    clock_ms: Callable[[], int], fixture_argv: tuple[str, ...],
    verify: Callable[[Path], None], timeout_sec: float,
) -> execution.Job:
    """Trusted fixture child command only; no client-supplied argv.

    Renew the lease and observe cancellation while the child runs. A
    confirmed stopped child with cancellation can be acknowledged; any
    uncertain, timed-out or failed run retains its reservation. The outer
    gateway verifies the selected output and source; no output promotion.
    """
    claimed_fence: int | None = None

    def run_child(**_render_args):
        nonlocal claimed_fence
        claimed_fence = ledger.get(bound.request.job_id).fence
        # The gateway constructs render kwargs, but the trusted fixture
        # command independently invokes the same fixed adapter contract.
        # This bridge is not a general CLI dispatcher.
        def check():
            current = ledger.get(bound.request.job_id)
            if (current.status not in ("running", "cancelling")
                    or current.request != bound.request or current.fence != claimed_fence
                    or current.worker_id != worker_id or current.expires_ms is None):
                raise execution.Conflict("staged worker lost ownership")
            now = clock_ms()
            if now >= current.expires_ms:
                raise execution.Conflict("staged lease expired")
            if current.cancel_requested:
                return True
            if current.expires_ms - now <= 20_000:
                ledger.apply(current.request.job_id, current.revision, execution.renew,
                             worker_id, current.fence, now, execution.MAX_LEASE_MS)
            return False

        result = process_supervisor.supervise(
            fixture_argv, cwd=bound.root, timeout_sec=timeout_sec, stop_requested=check,
        )
        if result.status != "success":
            raise _Interrupted(result)
        return [bound.root / "reels-out" / bound.stem / "_gate" / bound.gate / (bound.clip + ".mp4")]

    try:
        return run_bound(ledger, bound, worker_id=worker_id, clock_ms=clock_ms,
                         run_render=run_child, verify=verify)
    except _Interrupted as error:
        # run_bound released the cooperating lock on unwind. Reacquire it
        # before acknowledging a confirmed cancellation. No other attempt
        # can claim the still-active reservation in the interim.
        if error.result.status != "cancelled":
            raise
        with fixture_lock(bound.root):
            current = ledger.get(bound.request.job_id)
            now = clock_ms()
            if (current.status != "cancelling" or not current.cancel_requested
                    or current.request != bound.request or current.fence != claimed_fence
                    or current.worker_id != worker_id or current.expires_ms is None
                    or now >= current.expires_ms):
                raise
            return ledger.apply(current.request.job_id, current.revision, execution.finish,
                                worker_id, current.fence, now, "cancelled")



def recover_interrupted(ledger: execution.Ledger, bound: BoundStaged) -> execution.Job:
    """Quarantine the exact interrupted fixture after controller restart.

    Only the trusted coordinator calls this while holding the same fixture
    lock. No process enumeration, stored PID signal, clock comparison,
    artifact acceptance, deletion or retry. A free controller lock is not
    proof that an orphaned render child or decoder has exited.

    Recovery intentionally checks the persisted request rather than rebinding
    current files: changed/missing input or config must not prevent quarantine.
    """
    if (not bound.root.is_absolute() or not bound.root.is_dir()
            or bound.root != bound.root.resolve()):
        raise ValueError("canonical isolated root required")
    with fixture_lock(bound.root):
        current = ledger.get(bound.request.job_id)
        if current.request != bound.request:
            raise execution.Conflict("staged request mismatch")
        if current.status in ("running", "cancelling"):
            return ledger.apply(current.request.job_id, current.revision, execution.abandon)
        # Queued, terminal, or already quarantined: do not modify.
        return current
