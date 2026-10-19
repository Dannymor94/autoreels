"""M108: one lock for every heavy job of gamebox (the audiobook, llama-server use, whisper.cpp); M109: arl dictate."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from autoreels.core.config import HeavyLockConfig
from autoreels.core.heavy_lock import HeavyLock, HeavyLockError, shared_lock

CFG = HeavyLockConfig(host="gamebox", path="/mnt/data/locks/heavy.lock", ready_timeout_sec=60)


class FakeProc:
    def __init__(self, first_line="LOCKED\n"):
        self.stdout = SimpleNamespace(readline=lambda: first_line)
        self.stdin = SimpleNamespace(closed=False, close=lambda: setattr(self.stdin, "closed", True))
        self.killed = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


class Remote:
    """ssh answers by the command text: busy lock, the unit's state."""

    def __init__(self, busy=False, active=True, start_rc=0):
        self.busy, self.active, self.start_rc, self.calls = busy, active, start_rc, []

    def __call__(self, argv):
        cmd = argv[-1]
        self.calls.append(cmd)
        rc = 0
        if "flock -n" in cmd:
            rc = 1 if self.busy else 0
        elif "is-active --quiet" in cmd:
            rc = 0 if self.active else 3
        elif "systemctl start" in cmd:
            rc = self.start_rc
        return SimpleNamespace(returncode=rc, stdout="", stderr="")


def _lock(remote, procs=None, probes=(True,), logs=None):
    procs = procs if procs is not None else []
    seq = list(probes)

    def popen(argv):
        procs.append(argv)
        return FakeProc()
    clock = iter(range(0, 10_000, 5))
    return HeavyLock(CFG, run=remote, popen=popen, probe=lambda: seq.pop(0) if seq else True,
                     sleep=lambda s: None, clock=lambda: next(clock), log=(logs.append if logs is not None else print))


def test_the_lock_is_held_by_a_remote_flock_and_starts_llama_only_when_it_was_down():
    remote, procs, logs = Remote(busy=False, active=False), [], []
    lk = _lock(remote, procs, probes=(False, False, True), logs=logs)
    assert lk.acquire() is True and lk.held
    (argv,) = procs
    assert argv[:4] == ["ssh", "-o", "ServerAliveInterval=30", "gamebox"]
    assert "exec flock /mnt/data/locks/heavy.lock sh -c 'echo LOCKED; exec cat >/dev/null'" in argv[-1]
    assert "mkdir -p /mnt/data/locks" in argv[-1]
    assert any("sudo -n systemctl start llama-server" in c for c in remote.calls)
    assert "gamebox: модель отвечает" in logs
    lk.acquire()                                               # twice: nothing new
    assert len(procs) == 1
    lk.release()
    assert any("sudo -n systemctl stop llama-server" in c for c in remote.calls)   # it started it — it stops it
    assert not lk.held and logs[-1] == "gamebox: замок отпущен"


def test_a_running_model_is_left_running_and_a_busy_lock_is_waited_for():
    remote, logs = Remote(busy=True, active=True), []
    lk = _lock(remote, logs=logs)
    assert lk.acquire(wait=False) is False and not lk.held                  # the reserve never waits
    assert lk.acquire(wait=True) is True
    assert any("gamebox занят" in m and "жду" in m for m in logs)
    assert not any("systemctl start" in c for c in remote.calls)
    lk.release()
    assert not any("systemctl stop" in c for c in remote.calls)            # not ours — not stopped


def test_whisper_takes_the_lock_without_the_model_and_failures_are_loud():
    remote = Remote(busy=False, active=False)
    lk = _lock(remote)
    with lk.hold(llama=False):
        assert lk.held
        with lk.hold(llama=False):                                         # nested: the outer one releases
            pass
        assert lk.held
    assert not lk.held and not any("systemctl" in c for c in remote.calls)
    bad = HeavyLock(CFG, run=Remote(), popen=lambda argv: FakeProc("flock: cannot open lock file"),
                    log=lambda m: None)
    with pytest.raises(HeavyLockError, match="не взят"):
        bad.acquire()
    stuck_remote = Remote(active=False)
    stuck = _lock(stuck_remote, probes=[False] * 100, logs=[])
    with pytest.raises(HeavyLockError, match="не ответил"):
        stuck.acquire()
    assert not stuck.held and any("systemctl stop" in c for c in stuck_remote.calls)   # let go, model stopped
    assert shared_lock(HeavyLockConfig(host="")) is None and shared_lock(None) is None


def test_build_pool_waits_for_the_lock_before_asking_the_local_model(monkeypatch):
    from autoreels.cloud import providers as P
    from autoreels.core import heavy_lock as H
    order = []
    fake = SimpleNamespace(held=False, acquire=lambda wait=True, llama=True: order.append(("lock", wait)) or True)
    monkeypatch.setattr(H, "shared_lock", lambda cfg, **kw: fake)
    monkeypatch.setenv("LOCAL_LLM_URL", "http://gamebox:8081/v1")
    monkeypatch.setattr(P, "probe_provider", lambda url, **kw: order.append(("probe", url)) or 200)
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    r0 = SimpleNamespace(model="m", openrouter_model="o", local_llm=None, heavy_lock=CFG)
    P.build_pool(r0, local="only")
    assert order[0] == ("lock", True) and order[1][0] == "probe"
    order.clear()
    pool = P.build_pool(r0, local="last")
    assert order and order[0][0] == "probe"                                  # the reserve: no waiting at build
    reserve = [m.provider for m in pool._members if m.reserve]
    assert len(reserve) == 1
    busy = SimpleNamespace(held=False, acquire=lambda wait=True, llama=True: False)
    wrapped = P._LockedLocal(SimpleNamespace(name="Local", complete=lambda *a, **k: "ok"), busy)
    with pytest.raises(P.ProviderTimeout) as e:
        wrapped.complete([{"role": "user", "content": "x"}])
    assert e.value.is_connect_error
    free = SimpleNamespace(held=False, acquire=lambda wait=True, llama=True: True)
    assert P._LockedLocal(SimpleNamespace(name="Local", complete=lambda *a, **k: "ok"), free).complete([]) == "ok"
    assert all(isinstance(r, P._LockedLocal) for r in reserve)


def test_whisper_cpp_on_gamebox_runs_inside_the_lock(tmp_path):
    from autoreels.cloud.transcribe import WhisperCppBackend
    from autoreels.core.config import WhisperCppParams
    seen = []

    class Lock:
        held = False

        def hold(self, llama=True):
            import contextlib

            @contextlib.contextmanager
            def cm():
                seen.append(("in", llama))
                try:
                    yield
                finally:
                    seen.append(("out", llama))
            return cm()

    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"x")

    def run(argv):
        seen.append(argv[0])
        if argv[0] == "scp" and str(argv[-1]).endswith(".json"):
            (tmp_path / "x").write_text("")
    be = WhisperCppBackend(WhisperCppParams(), run=run, lock=Lock())
    with pytest.raises(Exception):
        be.transcribe(audio)                                 # no JSON came back — but the order is what we check
    assert seen[0] == ("in", False) and seen[-1] == ("out", False) and "ssh" in seen
    seen.clear()
    local = WhisperCppBackend(WhisperCppParams(host=""), run=run, lock=Lock())
    with pytest.raises(Exception):
        local.transcribe(audio)
    assert ("in", False) not in seen                         # on this machine: no gamebox lock


def _root(tmp_path):
    import shutil
    from tests.test_montage import _source
    from tests.test_render import ROOT
    _source(tmp_path)
    for name in ("render.yaml", "transcribe.yaml"):
        shutil.copy(ROOT / "config" / name, tmp_path / "config" / name)


def test_dictate_asks_for_the_file_writes_the_text_next_to_it(tmp_path, capsys):
    from autoreels import __main__ as cli
    from autoreels.core.models import Transcript, Word
    _root(tmp_path)
    rec_dir = tmp_path / "Voice Memos"
    rec_dir.mkdir()
    rec = rec_dir / "Запись 1.m4a"
    rec.write_bytes(b"audio")

    class Backend:
        no_chunking = True
        calls = 0

        def transcribe(self, path, language=None):
            Backend.calls += 1
            return Transcript(language="ru", words=[Word(word="Привет,", t0=0.0, t1=0.4), Word(word="мир.", t0=0.4, t1=0.9)])

        def describe(self):
            return {"provider": "whispercpp", "model": "t", "prompt_hash": ""}
    answers = iter([str(tmp_path / "нет.m4a"), str(rec).replace(" ", "\\ ")])          # macOS drag-and-drop
    rc = cli.cmd_dictate(None, root=tmp_path, cache_dir=str(tmp_path / "cache"), ask=lambda q: next(answers),
                         backend=Backend(), copy=False)
    out = capsys.readouterr().out
    assert rc == 0 and "нет такого файла" in out
    txt = rec_dir / "Запись 1.txt"
    assert txt.is_file() and "Привет, мир." in txt.read_text(encoding="utf-8")
    assert "готово: 2 слов" in out
    rc = cli.cmd_dictate([str(rec)], root=tmp_path, cache_dir=str(tmp_path / "cache"), backend=Backend(), copy=False)
    assert rc == 0 and Backend.calls == 1                    # the same file again: from the cache
    assert cli._clean_media_path("'/a b/c.m4a'") == cli.Path("/a b/c.m4a") and cli._clean_media_path("  ") is None


def test_dictate_without_gamebox_offers_groq_and_gamebox_status(tmp_path, capsys):
    from autoreels import __main__ as cli
    _root(tmp_path)
    rec = tmp_path / "r.m4a"
    rec.write_bytes(b"audio")
    down = lambda argv: SimpleNamespace(returncode=255, stdout="", stderr="")           # noqa: E731
    rc = cli.cmd_dictate([str(rec)], root=tmp_path, ask=lambda q: "n", run=down, copy=False)
    assert rc == 1 and "не отвечает" in capsys.readouterr().out
    cfgp = tmp_path / "config" / "r0.yaml"
    assert "heavy_lock:" in cfgp.read_text(encoding="utf-8")
    remote = Remote(busy=True)

    def run(argv):
        if "is-active" in argv[-1] and "--quiet" not in argv[-1]:
            return SimpleNamespace(returncode=0, stdout="active\n21\n", stderr="")
        return remote(argv)
    assert cli.cmd_gamebox("status", root=tmp_path, run=run) == 0
    out = capsys.readouterr().out
    assert "замок ЗАНЯТ" in out and "llama-server: active" in out and "свободно памяти: 21 ГБ" in out
