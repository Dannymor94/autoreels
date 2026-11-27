"""POSIX child-process supervision for isolated, trusted fixture adapters.

No shell, HTTP, process discovery, remote execution or arbitrary user command.
Only signal the newly created child group while its leader remains unreaped.
Controller death, escaped descendants and uncertain cleanup need reconciliation;
never infer a safe restart from a timeout or exit code alone.
"""
from __future__ import annotations

import math
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Sequence


@dataclass(frozen=True)
class Result:
    status: Literal["success", "failed", "cancelled", "timeout", "uncertain"]
    returncode: int


def _exited(proc: subprocess.Popen) -> bool:
    # Observe without reaping: retain the PID/session identity until the
    # last group signal has been sent. Requires POSIX waitid support.
    info = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    return info is not None and info.si_pid == proc.pid


def _signal_owned_group(proc: subprocess.Popen, sig: int):
    # The caller has not reaped the child. Never signal a PGID obtained
    # from a file, an old attempt or an untrusted request.
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass


def _group_absent(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def supervise(
    argv: Sequence[str], *, cwd: Path, timeout_sec: float,
    stop_requested: Callable[[], bool], grace_sec: float = 0.5,
    poll_sec: float = 0.05,
) -> Result:
    """Run a trusted foreground child and observe it at bounded intervals.

    stop_requested may also renew a coordinator lease. Exceptions stop the
    owned group and propagate, never publish a successful result. Child
    stdout/stderr are inherited (no unbounded pipe buffer). A nonempty
    process group after leader reaping is conservatively uncertain.
    """
    if os.name != "posix" or not all(hasattr(os, x) for x in
                                   ("waitid", "WNOWAIT", "killpg", "P_PID")):
        raise RuntimeError("POSIX waitid process supervision unavailable")
    if (not argv or isinstance(argv, (str, bytes))
            or any(not isinstance(x, str) or "\0" in x for x in argv)):
        raise ValueError("trusted argv required")
    if (not cwd.is_absolute() or cwd != cwd.resolve() or not cwd.is_dir()
            or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v)
                   for v in (timeout_sec, grace_sec, poll_sec))
            or timeout_sec <= 0 or not 0 <= grace_sec <= 5 or not 0 < poll_sec <= 0.25):
        raise ValueError("invalid supervision bounds")
    if stop_requested():
        # No process started; distinguish this from a child exit.
        return Result("cancelled", -1)
    proc = subprocess.Popen(
        list(argv), cwd=cwd, stdin=subprocess.DEVNULL,
        start_new_session=True, shell=False, close_fds=True,
    )
    deadline = time.monotonic() + timeout_sec

    def stop_group() -> int:
        _signal_owned_group(proc, signal.SIGTERM)
        end = time.monotonic() + grace_sec
        while time.monotonic() < end:
            time.sleep(min(poll_sec, max(0.0, end - time.monotonic())))
        # Even if the leader exited, it is still unreaped; descendants that
        # ignored TERM receive KILL. Never send another signal after wait().
        _signal_owned_group(proc, signal.SIGKILL)
        return proc.wait(timeout=5)

    reason = None
    try:
        while True:
            if stop_requested():
                reason = "cancelled"
                break
            if time.monotonic() >= deadline:
                reason = "timeout"
                break
            if _exited(proc):
                break
            time.sleep(poll_sec)
    except BaseException:
        stop_group()
        raise
    if reason is None:
        rc = proc.wait(timeout=5)
        status = "success" if rc == 0 else "failed"
    else:
        rc = stop_group()
        status = reason
    # No destructive signal after reaping: a reused group must never be
    # killed. If descendants/zombies remain, fail closed for reconciliation.
    if not _group_absent(proc.pid):
        return Result("uncertain", rc)
    return Result(status, rc)
