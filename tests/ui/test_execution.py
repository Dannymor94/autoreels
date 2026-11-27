"""Pure contract + durable SQLite proof; no external worker or media."""
import sqlite3
from contextlib import closing

import pytest
from pydantic import ValidationError

from autoreels.orchestr import execution as e


def request(job_id="job1", target="mac1", output="a"):
    return e.Request(job_id=job_id, target_id=target, target_kind="desktop",
                     plan_sha256="b"*64, config_sha256="c"*64, output_key=output*64)


def test_request_binding_and_output_reservation(tmp_path):
    with closing(sqlite3.connect(tmp_path/"ledger.sqlite")) as c:
        ledger = e.Ledger(c)
        r = request()
        j = ledger.submit(r)
        assert ledger.submit(r) == j
        with pytest.raises(e.Conflict):
            ledger.submit(request(target="other"))
        with pytest.raises(e.Conflict):
            ledger.submit(request("job2"))
        with pytest.raises(e.Conflict):
            ledger.apply(j.request.job_id, j.revision, e.claim, "other", "worker1", 0, 100)
        assert ledger.get("job1") == j
        with pytest.raises(ValidationError):
            e.Request.model_validate({**r.model_dump(), "command":"ffmpeg"})
        other = ledger.submit(request("job3", "other"))
        assert other.request.target_id == "other"


def test_expiry_restart_fence_and_reconciliation(tmp_path):
    db = tmp_path/"ledger.sqlite"
    with closing(sqlite3.connect(db)) as c:
        ledger = e.Ledger(c)
        j = ledger.submit(request())
        j = ledger.apply("job1", j.revision, e.claim, "mac1", "worker1", 100, 50)
        assert j.fence == 1
        with pytest.raises(e.Conflict):
            ledger.apply("job1", j.revision, e.finish, "worker1", 1, 150, "success", "d"*64)
        with pytest.raises(e.Conflict):
            ledger.apply("job1", j.revision, e.expire, 149)
        j = ledger.apply("job1", j.revision, e.expire, 150)
        assert j.status == "reconcile"
    with closing(sqlite3.connect(db)) as c:
        ledger = e.Ledger(c)
        assert ledger.get("job1") == j
        for operation, args in [(e.claim, ("mac1","worker2",151,50)),
                                (e.finish, ("worker1",1,151,"success","d"*64))]:
            with pytest.raises(e.Conflict):
                ledger.apply("job1", j.revision, operation, *args)
        with pytest.raises(e.Conflict):
            ledger.submit(request("job2"))
        j = ledger.apply("job1", j.revision, e.reconcile_stopped, retry=True)
        j = ledger.apply("job1", j.revision, e.claim, "mac1","worker2",152,50)
        assert j.fence == 2 and j.request.target_id == "mac1"
        with pytest.raises(e.Conflict):
            ledger.apply("job1", j.revision, e.finish, "worker1",1,153,"success","d"*64)
        with pytest.raises(e.Conflict):
            ledger.apply("job1", j.revision-1, e.cancel)
        with pytest.raises(ValueError):
            ledger.apply("job1", j.revision, e.finish,"worker2",2,153,"success")
        assert ledger.get("job1") == j
        j = ledger.apply("job1", j.revision, e.finish,"worker2",2,153,"success","d"*64)
        assert j.status == "success" and j.artifact_sha256 == "d"*64
        assert ledger.submit(request("job2")).status == "queued"


def test_cancel_does_not_release_until_ack_or_reconciliation(tmp_path):
    with closing(sqlite3.connect(tmp_path/"ledger.sqlite")) as c:
        ledger = e.Ledger(c)
        j = ledger.submit(request())
        j = ledger.apply("job1", j.revision,e.claim,"mac1","worker1",0,10)
        j = ledger.apply("job1", j.revision,e.cancel)
        assert j.status == "cancelling"
        assert ledger.apply("job1", j.revision,e.cancel) == j
        with pytest.raises(e.Conflict):
            ledger.submit(request("job2"))
        with pytest.raises(e.Conflict):
            ledger.apply("job1",j.revision,e.finish,"worker1",1,1,"success","d"*64)
        j = ledger.apply("job1",j.revision,e.expire,10)
        with pytest.raises(e.Conflict):
            ledger.apply("job1",j.revision,e.reconcile_artifact,"d"*64)
        j = ledger.apply("job1",j.revision,e.reconcile_stopped,retry=True)
        assert j.status == "cancelled"
        assert ledger.submit(request("job2")).status == "queued"


def test_renewal_bounded_retries_and_existing_artifact():
    j = e.claim(e.Job(request=request()),"mac1","worker1",10,10)
    j = e.renew(j,"worker1",1,11,20)
    with pytest.raises(e.Conflict):
        e.expire(j,20)
    j = e.expire(j,31)
    with pytest.raises(ValueError):
        e.reconcile_artifact(j,None)
    done = e.reconcile_artifact(j,"d"*64)
    assert done.status == "success" and done.artifact_sha256 == "d"*64
    j = e.reconcile_stopped(j,retry=True)
    j = e.claim(j,"mac1","worker2",32,10)
    j = e.expire(j,42)
    assert e.reconcile_stopped(j,retry=True).status == "failed"
    with pytest.raises(ValueError):
        e.claim(e.Job(request=request()),"mac1","worker1",0,e.MAX_LEASE_MS+1)


def test_claim_requires_worker_identity():
    with pytest.raises(ValueError):
        e.claim(e.Job(request=request()),"mac1",None,0,10)



def test_abandon_fences_restart_without_clock_or_releasing_reservation(tmp_path):
    with closing(sqlite3.connect(tmp_path/"ledger.sqlite")) as c:
        ledger = e.Ledger(c)
        j = ledger.submit(request())
        j = ledger.apply("job1", j.revision, e.claim, "mac1", "worker1", 900_000, 60_000)
        j = ledger.apply("job1", j.revision, e.cancel)
        recovered = ledger.apply("job1", j.revision, e.abandon)
        assert recovered.status == "reconcile"
        assert recovered.expires_ms is None and recovered.cancel_requested
        assert recovered.fence == j.fence and recovered.worker_id == j.worker_id
        assert recovered.request == j.request
        assert ledger.apply("job1", recovered.revision, e.abandon) == recovered
        with pytest.raises(e.Conflict):
            ledger.apply("job1", recovered.revision, e.finish,
                         "worker1", recovered.fence, 1, "cancelled")
        with pytest.raises(e.Conflict):
            ledger.submit(request("job2"))
        with pytest.raises(e.Conflict):
            ledger.apply("job1", recovered.revision, e.claim, "mac1", "worker2", 1, 10)
