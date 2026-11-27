"""Real, short, generated child processes; no owner data or service."""
import os
import sys
import time

import pytest

from autoreels.orchestr.process_supervisor import supervise

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "waitid") or not hasattr(os, "WNOWAIT"),
    reason="POSIX waitid supervision required",
)


def test_child_exit_and_failure(tmp_path):
    for code, status in ((0, "success"), (7, "failed")):
        result = supervise([sys.executable, "-c", f"raise SystemExit({code})"],
                           cwd=tmp_path, timeout_sec=5, stop_requested=lambda: False)
        assert result.status == status and result.returncode == code


def test_pre_cancel_never_starts(tmp_path):
    result = supervise([sys.executable, "-c", "open('started','w').close()"],
                       cwd=tmp_path, timeout_sec=5, stop_requested=lambda: True)
    assert result.status == "cancelled"
    assert not (tmp_path / "started").exists()


@pytest.mark.parametrize("cancel", [True, False])
def test_stop_uncooperative_process(tmp_path, cancel):
    code = ("import signal,time,pathlib;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "pathlib.Path('ready').touch();time.sleep(30)")
    ready = tmp_path / "ready"
    start = time.monotonic()
    result = supervise([sys.executable, "-c", code], cwd=tmp_path,
                       timeout_sec=3 if not cancel else 5,
                       stop_requested=lambda: cancel and ready.exists(),
                       grace_sec=0.1, poll_sec=0.025)
    assert ready.exists()
    assert result.status == ("cancelled" if cancel else "timeout")
    assert result.returncode == -9
    assert time.monotonic() - start < 7


def test_callback_exception_stops_child(tmp_path):
    ready = tmp_path / "ready"
    def check():
        if ready.exists():
            raise RuntimeError("lease lost")
        return False
    with pytest.raises(RuntimeError, match="lease lost"):
        supervise([sys.executable, "-c", "import pathlib,time;pathlib.Path('ready').touch();time.sleep(30)"],
                  cwd=tmp_path, timeout_sec=5, stop_requested=check, grace_sec=0.1)
    assert ready.exists()


def test_exited_leader_with_live_descendant_never_success(tmp_path):
    # Descendant exits by itself; the supervisor must not accept the
    # leader's zero status while the owned group still exists.
    code = ("import subprocess,sys;"
            "subprocess.Popen([sys.executable,'-c','import time;time.sleep(0.8)']);")
    result = supervise([sys.executable, "-c", code], cwd=tmp_path,
                       timeout_sec=5, stop_requested=lambda: False)
    assert result.status == "uncertain"
