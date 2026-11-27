"""Targeted UI-202A tests; no media or external executor."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from autoreels.orchestr import queue, settings
from autoreels.orchestr.app import app


@pytest.fixture()
def jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "settings", settings.Settings(root=tmp_path, synthetic_jobs=True))
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield tmp_path, client


def create(c, kind="desktop", outcome="success", job_id=None):
    job_id = job_id or str(uuid4())
    response = c.put("/api/jobs/" + job_id, json={"action":"create","target_kind":kind,"outcome":outcome})
    assert response.status_code == 200, response.text
    return response.json()


def cancel(c, job_id):
    return c.put("/api/jobs/" + job_id, json={"action":"cancel","target_kind":None,"outcome":None})


def test_disabled_and_read_only_default(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "settings", settings.Settings(root=tmp_path))
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    assert c.get("/api/jobs").json() == {"enabled":False,"jobs":[]}
    assert c.put("/api/jobs/" + str(uuid4()), json={"action":"create","target_kind":"mobile","outcome":"success"}).status_code == 409
    assert list(tmp_path.iterdir()) == []


def test_fifo_checkpoint_restart_empty_failure_no_fallback(jobs):
    root, c = jobs
    assert c.get("/api/jobs").json() == {"enabled":True,"jobs":[]}
    assert list(root.iterdir()) == []
    a = create(c,"desktop")
    b = create(c,"mobile","empty")
    d = create(c,"remote","failed")
    assert create(c,"desktop",job_id=a["job_id"]) == a
    assert c.put("/api/jobs/" + a["job_id"], json={"action":"create","target_kind":"remote","outcome":"success"}).status_code == 409
    assert queue.advance(root)
    def by_id():
        return {j["job_id"]:j for j in c.get("/api/jobs").json()["jobs"]}
    assert by_id()[a["job_id"]]["stage"] == "prepare"
    assert by_id()[b["job_id"]]["status"] == "queued"
    assert queue.advance(root)
    assert by_id()[a["job_id"]]["progress"] == 60
    for _ in range(9):
        assert queue.advance(root)
    assert not queue.advance(root)
    final = by_id()
    assert [final[j["job_id"]]["status"] for j in (a,b,d)] == ["success","empty","failed"]
    assert [final[j["job_id"]]["target_kind"] for j in (a,b,d)] == ["desktop","mobile","remote"]
    assert cancel(c,a["job_id"]).status_code == 409
    assert len(list(root.iterdir())) == 1


def test_cancel_idempotency_and_serialized_checkpoints(jobs):
    root,c = jobs
    a = create(c)
    b = create(c,"remote")
    assert cancel(c,b["job_id"]).json()["status"] == "cancelled"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: queue.advance(root), range(2))) == [True,True]
    state = next(j for j in c.get("/api/jobs").json()["jobs"] if j["job_id"] == a["job_id"])
    assert state["revision"] == 2 and state["progress"] == 60
    stopped = cancel(c,a["job_id"]).json()
    assert stopped["status"] == "cancelled" and stopped["progress"] == 60
    assert cancel(c,a["job_id"]).json() == stopped
    assert create(c,job_id=a["job_id"]) == stopped
    assert not queue.advance(root)
    assert c.put("/api/jobs/" + str(uuid4()), json={"action":"create","target_kind":"gamebox","outcome":"success"}).status_code == 422
    assert c.put("/api/jobs/" + str(uuid4()), json={"action":"create","target_kind":"desktop","outcome":"success","command":"ffmpeg"}).status_code == 422


def test_symlink_and_bounded_history(jobs, monkeypatch):
    root,c = jobs
    path = root / queue._DB_NAME
    outside = root.parent / "outside.sqlite"
    path.symlink_to(outside)
    assert c.get("/api/jobs").status_code == 409
    assert not outside.exists()
    path.unlink()
    monkeypatch.setattr(queue,"MAX_JOBS",1)
    a = create(c)
    assert c.put("/api/jobs/" + str(uuid4()), json={"action":"create","target_kind":"desktop","outcome":"success"}).status_code == 409
    assert create(c,job_id=a["job_id"]) == a
