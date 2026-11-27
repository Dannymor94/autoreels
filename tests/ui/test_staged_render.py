"""UI-204A: existing CLI render entry point, isolated bytes + mocked encoder."""
import hashlib
import shutil
from pathlib import Path

import pytest
import yaml

from autoreels import __main__ as cli
from autoreels.core.models import Crop, Manifest, Reel, SetupProfile
from autoreels.orchestr import pipeline_gateway as gateway


def digest(data):
    return hashlib.sha256(data).hexdigest()


def stage(root):
    for folder in ("config", "inputs", "reviews"):
        (root / folder).mkdir()
    repo = Path(__file__).resolve().parents[2]
    for name in ("render.yaml", "subtitles.yaml", "r0.yaml"):
        shutil.copyfile(repo / "config" / name, root / "config" / name)
    (root / "config" / "render.local.yaml").write_text(yaml.safe_dump({
        "role": "both", "speech_map": False, "music": {"enabled": False},
    }))
    source = root / "inputs" / "DEMO.mp4"
    source.write_bytes(b"synthetic-source")
    manifest = Manifest(
        source=source.name, source_sha256=digest(source.read_bytes()),
        duration_preset="shorts", run_key="synthetic",
        setup=SetupProfile(setup_id="s", crop=Crop(x=0, y=0, w=1080, h=1920),
                           frame=[1080, 1920], scale=[1080, 1920]),
        reels=[Reel(id=id, start=0.0, end=2.0, score=80, hook="h",
                    title="t", description="d") for id in ("r01", "r02")],
    )
    path = root / "reviews" / "DEMO.review.json"
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    return source, path


def test_staged_adapter_reuses_cli_and_preserves_source(monkeypatch, tmp_path):
    source, plan = stage(tmp_path)
    before = plan.read_bytes()
    calls = []

    def fail(*args, **kwargs):
        pytest.fail("unexpected side effect or external dependency")

    monkeypatch.setattr(cli, "_git_pull", fail)
    monkeypatch.setattr(cli, "_archive_video", fail)
    monkeypatch.setattr(cli, "_manifest_calibration_desync", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_resolve_cached_transcript", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_resolve_music_track", lambda *a, **k: None)
    monkeypatch.setattr(cli, "resolve_ffmpeg", lambda *a, **k: "synthetic-ffmpeg")
    def preflight(profile, encoder, cfg, **kwargs):
        assert profile == "h264" and encoder == "libx264"
        assert kwargs["fallback"] is False
        return profile, encoder
    monkeypatch.setattr(cli, "_preflight_encoder", preflight)
    monkeypatch.setattr(cli, "_stage_two_shot_auto", lambda *a, **k: None)
    def render(manifest, **kwargs):
        assert [r.id for r in manifest.reels] == ["r02"]
        assert kwargs["profile"] == "h264" and kwargs["encoder"] == "libx264"
        out = kwargs["out_dir"] / "r02.mp4"
        out.parent.mkdir(parents=True)
        out.write_bytes(b"synthetic-output")
        calls.append(out)
        return [out]
    monkeypatch.setattr(cli, "render_crop", render)
    result, sha = gateway.render_staged_clip(
        tmp_path, stem="DEMO", clip="r02", gate="ui-test",
        plan_sha256=digest(before), run_render=cli.cmd_render,
    )
    assert result == tmp_path / "reels-out" / "DEMO" / "_gate" / "ui-test" / "r02.mp4"
    assert sha == digest(b"synthetic-output")
    assert calls == [result]
    assert source.read_bytes() == b"synthetic-source" and plan.read_bytes() == before
    assert not (tmp_path / "inputs-archive").exists()
    assert not (result.parent / "r01.mp4").exists()
    with pytest.raises(ValueError, match="gate"):
        gateway.render_staged_clip(tmp_path, stem="DEMO", clip="r02", gate="ui-test",
                                   plan_sha256=digest(before), run_render=fail)


def test_staged_adapter_rejects_stale_or_missing_inputs(tmp_path):
    source, plan = stage(tmp_path)
    before = plan.read_bytes()
    def fail(**kwargs):
        pytest.fail("render must not be called")
    args = dict(stem="DEMO", clip="r01", gate="ui-test",
                plan_sha256=digest(before), run_render=fail)
    with pytest.raises(ValueError, match="stale plan"):
        gateway.render_staged_clip(tmp_path, **{**args, "plan_sha256":"a"*64})
    with pytest.raises(ValueError, match="unsupported"):
        gateway.render_staged_clip(tmp_path, **{**args, "clip":"r99"})
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="source mismatch"):
        gateway.render_staged_clip(tmp_path, **args)
    assert not (tmp_path / "reels-out").exists()


def test_staged_adapter_does_not_accept_missing_or_wrong_result(tmp_path):
    _, plan = stage(tmp_path)
    args = dict(stem="DEMO", clip="r01", gate="ui-test",
                plan_sha256=digest(plan.read_bytes()))
    for output in ([], [tmp_path / "unrelated.mp4"]):
        with pytest.raises(RuntimeError, match="exact clip"):
            gateway.render_staged_clip(tmp_path, **args, run_render=lambda **k: output)


def test_legacy_render_archive_default_unchanged():
    import inspect
    assert inspect.signature(cli.cmd_render).parameters["archive_source"].default is True


def test_staged_media_hashing_streams_source_and_result(tmp_path, monkeypatch):
    source, plan = stage(tmp_path)
    # The source spans more than two hashing chunks. Do not read any MP4
    # into a single bytes object in the gateway.
    source.write_bytes(b"0123456789" * 250_000)
    expected_source = digest(source.read_bytes())
    manifest = Manifest.model_validate_json(plan.read_bytes())
    plan.write_text(manifest.model_copy(update={"source_sha256":expected_source}).model_dump_json())
    plan_sha = digest(plan.read_bytes())
    original = Path.read_bytes

    def forbid_media_read(self):
        if self.suffix == ".mp4":
            pytest.fail("whole-file media read")
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", forbid_media_read)

    def fake(**kwargs):
        out = tmp_path / "reels-out/DEMO/_gate/ui-stream/r01.mp4"
        out.parent.mkdir(parents=True)
        out.write_bytes(b"out" * 800_000)
        return [out]

    out, sha = gateway.render_staged_clip(tmp_path, stem="DEMO", clip="r01",
        gate="ui-stream", plan_sha256=plan_sha, run_render=fake)
    assert sha == digest(b"out" * 800_000)
    assert gateway._staged_file_identity(tmp_path, source)[0] == expected_source
    assert out.stat().st_size == 2_400_000


def test_staged_input_replacement_and_empty_artifact_rejected(tmp_path):
    source, plan = stage(tmp_path)
    plan_sha = digest(plan.read_bytes())

    def replace_same_bytes(**kwargs):
        data = source.read_bytes()
        new = source.with_suffix(".tmp")
        new.write_bytes(data)
        new.replace(source)
        out = tmp_path / "reels-out/DEMO/_gate/ui-replaced/r01.mp4"
        out.parent.mkdir(parents=True)
        out.write_bytes(b"out")
        return [out]

    with pytest.raises(RuntimeError, match="staged input changed"):
        gateway.render_staged_clip(tmp_path, stem="DEMO", clip="r01",
            gate="ui-replaced", plan_sha256=plan_sha, run_render=replace_same_bytes)

    def empty(**kwargs):
        out = tmp_path / "reels-out/DEMO/_gate/ui-empty/r01.mp4"
        out.parent.mkdir(parents=True)
        out.touch()
        return [out]

    with pytest.raises(RuntimeError, match="empty bytes"):
        gateway.render_staged_clip(tmp_path, stem="DEMO", clip="r01",
            gate="ui-empty", plan_sha256=plan_sha, run_render=empty)


def test_bound_executor_rejects_config_drift_before_claim(tmp_path):
    pytest.importorskip("fcntl")
    import sqlite3
    from contextlib import closing
    from autoreels.orchestr import execution, staged_executor
    _, plan = stage(tmp_path)
    bound = staged_executor.bind(tmp_path, job_id="j1", target_id="local",
                                 stem="DEMO", clip="r01", gate="ui-bind")
    assert bound.request.plan_sha256 == digest(plan.read_bytes())
    with closing(sqlite3.connect(tmp_path / "jobs.sqlite")) as c:
        ledger = execution.Ledger(c)
        job = ledger.submit(bound.request)
        (tmp_path / "config" / "render.local.yaml").write_text("role: both\n")
        with pytest.raises(execution.Conflict, match="config changed"):
            staged_executor.run_bound(ledger, bound, worker_id="w", clock_ms=lambda: 0,
                run_render=lambda **k: pytest.fail("unexpected render"), verify=lambda p: None)
        assert ledger.get("j1") == job


def test_bound_executor_validation_and_expiry_hold_reservation(tmp_path):
    pytest.importorskip("fcntl")
    import sqlite3
    from contextlib import closing
    from autoreels.orchestr import execution, staged_executor
    stage(tmp_path)
    bound = staged_executor.bind(tmp_path, job_id="j1", target_id="local",
                                 stem="DEMO", clip="r01", gate="ui-bound")
    def fake(**kwargs):
        out = tmp_path / "reels-out/DEMO/_gate/ui-bound/r01.mp4"
        out.parent.mkdir(parents=True)
        out.write_bytes(b"synthetic-output")
        return [out]
    def fail(_):
        raise ValueError("not decodable")
    with closing(sqlite3.connect(tmp_path / "jobs.sqlite")) as c:
        ledger = execution.Ledger(c)
        ledger.submit(bound.request)
        with pytest.raises(ValueError, match="not decodable"):
            staged_executor.run_bound(ledger, bound, worker_id="w", clock_ms=lambda:0,
                                      run_render=fake, verify=fail)
        j = ledger.get("j1")
        assert j.status == "running" and j.artifact_sha256 is None
        j = ledger.apply("j1", j.revision, execution.expire, execution.MAX_LEASE_MS)
        assert j.status == "reconcile"
        conflicting = staged_executor.bind(tmp_path, job_id="j2", target_id="local",
                                           stem="DEMO", clip="r02", gate="ui-bound")
        with pytest.raises(execution.Conflict, match="reserved"):
            ledger.submit(conflicting.request)
        with pytest.raises(execution.Conflict):
            staged_executor.run_bound(ledger, bound, worker_id="w2", clock_ms=lambda:60001,
                                      run_render=lambda **k: pytest.fail("duplicate"), verify=lambda p:None)


def test_fixture_lock_serializes_cooperating_executor(tmp_path):
    import sys
    from autoreels.orchestr import execution, staged_executor
    if sys.platform == "win32":
        pytest.skip("fixture lock POSIX only")
    with staged_executor.fixture_lock(tmp_path):
        with pytest.raises(execution.Conflict, match="busy"):
            with staged_executor.fixture_lock(tmp_path):
                pytest.fail("second lock acquired")
    with staged_executor.fixture_lock(tmp_path):
        assert (tmp_path / ".ui-staged-executor.lock").is_file()


@pytest.mark.parametrize("cancel", [True, False])
def test_bound_executor_does_not_accept_cancelled_or_expired_result(tmp_path, cancel):
    pytest.importorskip("fcntl")
    import sqlite3
    from contextlib import closing
    from autoreels.orchestr import execution, staged_executor
    stage(tmp_path)
    bound = staged_executor.bind(tmp_path, job_id="j1", target_id="local",
                                 stem="DEMO", clip="r01", gate="ui-final")
    now = [0]
    with closing(sqlite3.connect(tmp_path / "jobs.sqlite")) as c:
        ledger = execution.Ledger(c)
        ledger.submit(bound.request)
        def fake(**kwargs):
            out = tmp_path / "reels-out/DEMO/_gate/ui-final/r01.mp4"
            out.parent.mkdir(parents=True)
            out.write_bytes(b"synthetic-output")
            return [out]
        def verify(_):
            if cancel:
                current = ledger.get("j1")
                ledger.apply("j1", current.revision, execution.cancel)
            else:
                now[0] = execution.MAX_LEASE_MS
        j = staged_executor.run_bound(ledger, bound, worker_id="w",
                    clock_ms=lambda:now[0], run_render=fake, verify=verify)
        assert j.status == ("cancelled" if cancel else "reconcile")
        assert j.artifact_sha256 is None
        assert (tmp_path / "reels-out/DEMO/_gate/ui-final/r01.mp4").is_file()



def test_restart_quarantines_after_actual_controller_crash(tmp_path):
    pytest.importorskip("fcntl")
    import sqlite3
    import subprocess
    import sys
    from contextlib import closing
    from autoreels.orchestr import execution, staged_executor

    source, plan = stage(tmp_path)
    bound = staged_executor.bind(tmp_path, job_id="crash", target_id="local",
                                 stem="DEMO", clip="r01", gate="ui-crash")
    db = tmp_path / "crash.sqlite"
    with closing(sqlite3.connect(db)) as c:
        queued = execution.Ledger(c).submit(bound.request)
    # A real child controller exits without finally handlers after claiming.
    # An interrupted output is deliberately left in the gate. No owner media.
    code = """
import os, sqlite3, sys
from pathlib import Path
from autoreels.orchestr import execution, staged_executor
root = Path(sys.argv[1])
ledger = execution.Ledger(sqlite3.connect(root / "crash.sqlite"))
with staged_executor.fixture_lock(root):
    j = ledger.get("crash")
    ledger.apply("crash", j.revision, execution.claim, "local", "old-worker", 900000, 60000)
    out = root / "reels-out/DEMO/_gate/ui-crash/r01.mp4"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"partial-output")
    os._exit(37)
"""
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)],
                            check=False, timeout=10)
    assert result.returncode == 37
    # Config/source drift must not make the recovery itself fail.
    (tmp_path / "config/render.local.yaml").write_text("role: both\n")
    partial = tmp_path / "reels-out/DEMO/_gate/ui-crash/r01.mp4"
    with closing(sqlite3.connect(db)) as c:
        ledger = execution.Ledger(c)
        interrupted = ledger.get("crash")
        assert interrupted.status == "running" and interrupted.revision > queued.revision
        with staged_executor.fixture_lock(tmp_path):
            with pytest.raises(execution.Conflict, match="busy"):
                staged_executor.recover_interrupted(ledger, bound)
        recovered = staged_executor.recover_interrupted(ledger, bound)
        assert recovered.status == "reconcile"
        assert recovered.request == bound.request and recovered.fence == interrupted.fence
        assert recovered.artifact_sha256 is None
        assert staged_executor.recover_interrupted(ledger, bound) == recovered
        with pytest.raises(execution.Conflict, match="reserved"):
            ledger.submit(bound.request.model_copy(update={"job_id":"duplicate"}))
        with pytest.raises(execution.Conflict):
            ledger.apply("crash", recovered.revision, execution.finish,
                         "old-worker", recovered.fence, 1, "success", "d"*64)
    assert partial.read_bytes() == b"partial-output"
    assert source.read_bytes() == b"synthetic-source"
    assert plan.is_file()
