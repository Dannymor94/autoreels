"""M108: one lock for every heavy job of gamebox — the audiobook's synthesis and checks, llama-server use, whisper.cpp.

The owner runs an audiobook model on gamebox; it and llama-server (Qwen3-27B) share the processor and the memory
(11.6 GB per worker + all 16 threads vs ~12 GB + 8 threads), so they must never run at the same time. Both sides
take the same lock — `flock` on one file there (config/r0.yaml `heavy_lock:`). The second comer waits; nobody
kills the other's work. The audiobook's wrapper stops llama-server for its run and starts it again only when it
was running before; this side starts llama-server when it is down and stops it again when it started it.

How the lock is held from this machine: `ssh <host> flock <path> sh -c 'echo LOCKED; exec cat >/dev/null'` —
the remote `cat` lives as long as our ssh stdin is open, the lock with it. Closing stdin (release) or the death of
this process (ssh closes) ends `cat`, and flock lets go — a crash never leaves the lock taken.

`run` / `popen` / `probe` / `sleep` / `clock` — injection points for tests.
"""
from __future__ import annotations

import atexit
import contextlib
import shlex
import subprocess
import time
from typing import Callable


class HeavyLockError(RuntimeError):
    """The lock could not be taken (ssh failed, no flock there, the directory not writable)."""


class HeavyLock:
    def __init__(self, cfg, *, log: Callable[[str], None] = print, run: Callable | None = None,
                 popen: Callable | None = None, probe: Callable[[], bool] | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.cfg = cfg
        self._log = log
        self._run = run or (lambda argv: subprocess.run(argv, capture_output=True, text=True))
        self._popen = popen or (lambda argv: subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                              text=True))
        self._probe = probe
        self._sleep, self._clock = sleep, clock
        self._proc = None
        self._started_llama = False

    @property
    def held(self) -> bool:
        return self._proc is not None

    def _ssh(self, cmd: str) -> list[str]:
        return ["ssh", "-o", "ServerAliveInterval=30", self.cfg.host, cmd]

    def _mkdir(self) -> str:
        d = self.cfg.path.rsplit("/", 1)[0] or "/"
        return f"mkdir -p {shlex.quote(d)}"

    def busy(self) -> bool:
        """True when someone holds the lock right now (a non-blocking try)."""
        r = self._run(self._ssh(f"{self._mkdir()} && flock -n {shlex.quote(self.cfg.path)} true"))
        return r.returncode != 0

    def acquire(self, *, wait: bool = True, llama: bool = True) -> bool:
        """Take the lock (waiting for it when `wait`), then — for a job that talks to the model (`llama`) — make
        sure llama-server is up (start_llama). False = busy and not waiting. Taking it twice is a no-op."""
        if self.held:
            if llama:
                self._ensure_llama()
            return True
        busy = self.busy()
        if busy and not wait:
            return False
        if busy:
            self._log(f"gamebox занят (общий замок {self.cfg.path}: озвучка или другая тяжёлая задача) — жду…")
        t0 = self._clock()
        p = self._popen(self._ssh(f"{self._mkdir()} && exec flock {shlex.quote(self.cfg.path)} "
                                  f"sh -c 'echo LOCKED; exec cat >/dev/null'"))
        line = (p.stdout.readline() if p.stdout is not None else "").strip()
        if line != "LOCKED":
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass
            raise HeavyLockError(f"замок {self.cfg.host}:{self.cfg.path} не взят (ssh/flock: «{line[:120]}»)")
        self._proc = p
        waited = self._clock() - t0
        self._log(f"gamebox: замок взят" + (f" (ждал {waited:.0f} с)" if busy else ""))
        atexit.register(self.release)
        if llama:
            try:
                self._ensure_llama()
            except Exception:
                self.release()           # the model did not come up: do not keep gamebox locked for nothing
                raise
        return True

    @contextlib.contextmanager
    def hold(self, *, llama: bool = True):
        """The lock for a block of work; released at its end unless it was already held before (by this process)."""
        mine = not self.held
        self.acquire(wait=True, llama=llama)
        try:
            yield self
        finally:
            if mine:
                self.release()

    def _ensure_llama(self) -> None:
        if not getattr(self.cfg, "start_llama", False) or not getattr(self.cfg, "llama_unit", ""):
            return
        unit = shlex.quote(self.cfg.llama_unit)
        if self._run(self._ssh(f"systemctl is-active --quiet {unit}")).returncode == 0:
            return
        r = self._run(self._ssh(f"sudo -n systemctl start {unit}"))
        if r.returncode != 0:
            raise HeavyLockError(f"{self.cfg.llama_unit} не запустился: {(r.stderr or r.stdout or '')[-200:]}")
        self._started_llama = True
        self._log(f"gamebox: {self.cfg.llama_unit} запущен — жду, пока модель загрузится")
        if self._probe is None:
            return
        deadline = self._clock() + float(self.cfg.ready_timeout_sec)
        while not self._probe():
            if self._clock() > deadline:
                raise HeavyLockError(f"{self.cfg.llama_unit} не ответил за {self.cfg.ready_timeout_sec:.0f} с")
            self._sleep(5.0)
        self._log(f"gamebox: модель отвечает")

    def release(self) -> None:
        """Stop llama-server when this side started it (stop_if_started), then let the lock go."""
        if self._proc is None:
            return
        if self._started_llama and getattr(self.cfg, "stop_if_started", False):
            self._run(self._ssh(f"sudo -n systemctl stop {shlex.quote(self.cfg.llama_unit)}"))
            self._log(f"gamebox: {self.cfg.llama_unit} остановлен (его запускал autoreels)")
            self._started_llama = False
        p, self._proc = self._proc, None
        try:
            if p.stdin is not None:
                p.stdin.close()
            p.wait(timeout=15)
        except Exception:  # noqa: BLE001 — the ssh dies with us anyway, and flock lets go with it
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass
        self._log("gamebox: замок отпущен")

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False


_SHARED: dict = {}


def shared_lock(cfg, **kw) -> HeavyLock | None:
    """The one HeavyLock of this process for that host and path (None when heavy_lock.host is empty — off)."""
    if cfg is None or not getattr(cfg, "host", ""):
        return None
    key = (cfg.host, cfg.path)
    if key not in _SHARED:
        _SHARED[key] = HeavyLock(cfg, **kw)
    return _SHARED[key]
