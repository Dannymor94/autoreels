"""Isolated editor identity and atomic subtitle correction regressions."""
import hashlib
import sqlite3
from contextlib import closing

import pytest

from autoreels.core.models import Crop, Manifest, Reel, SetupProfile, Word, make_cold_open_segment
from autoreels.orchestr import editor_revisions as e


def fixture():
    reel = Reel(id="r01", start=0.0, end=3.0, score=80, hook="h",
                title="test", description="test",
                cold_open=make_cold_open_segment(0.0, 1.0),
                subtitles=[Word(word="Превет", t0=0.1, t1=0.8, emph=True),
                           Word(word="мир", t0=1.1, t1=1.5)])
    other = reel.model_copy(update={"id": "r02", "cold_open": None})
    return Manifest(source="DEMO.mp4", source_sha256="a"*64, source_hash_scheme="partial-p1",
        duration_preset="shorts", run_key="fixture",
        setup=SetupProfile(setup_id="s", crop=Crop(x=0,y=0,w=360,h=640),
                           frame=[360,640], scale=[360,640]), reels=[reel,other])


def initial(store, manifest=None, project="demo"):
    m = manifest if manifest is not None else fixture()
    raw = m.model_dump_json().encode()
    return store.import_initial(project, raw, expected_sha256=hashlib.sha256(raw).hexdigest())


def operation(base, **changes):
    values = dict(op_id="op1", project_id=base.project_id, clip_uid=dict(base.clip_uids)["r01"],
                  base_revision=base.number, base_plan_sha256=base.plan_sha256,
                  word_index=0, expected_text="Превет", replacement="Привет")
    return e.Correction.model_validate({**values, **changes})


def test_stable_ids_correction_preserves_audio_and_reopens(tmp_path):
    db = tmp_path / "edit.sqlite"
    with closing(sqlite3.connect(db)) as c:
        store = e.Store(c)
        base = initial(store)
        op = operation(base)
        changed = store.correct(op)
        assert changed.number == 1 and changed.plan_sha256 != base.plan_sha256
        assert changed.clip_uids == base.clip_uids
        before, after = base.manifest(), changed.manifest()
        # Entire manifest identical except the chosen text value.
        words = list(before.reels[0].subtitles)
        words[0] = words[0].model_copy(update={"word":"Привет"})
        expected = before.model_copy(update={"reels":[before.reels[0].model_copy(update={"subtitles":words}), before.reels[1]]})
        assert after == expected
        assert store.correct(op) == changed
        assert initial(store) == changed
        with pytest.raises(e.Conflict, match="stale"):
            store.correct(operation(base, op_id="stale"))
        with pytest.raises(e.Conflict, match="already bound"):
            store.correct(operation(base, replacement="Другое"))
        assert store.current("demo") == changed
    with closing(sqlite3.connect(db)) as c:
        store = e.Store(c)
        assert store.current("demo") == changed
        # Explicit inverse correction; a new revision, never history deletion.
        undo = operation(changed, op_id="undo1", expected_text="Привет", replacement="Превет")
        restored = store.correct(undo)
        assert restored.number == 2 and restored.manifest() == before
        assert restored.clip_uids == base.clip_uids
        assert store.correct(op) == changed  # exact historical retry, not rollback of current
        assert store.current("demo") == restored


def test_import_rejects_ambiguous_migration(tmp_path):
    with closing(sqlite3.connect(tmp_path/"edit.sqlite")) as c:
        store = e.Store(c)
        original = initial(store)
        with pytest.raises(e.Conflict, match="already has"):
            initial(store, project="same-source")
        m = fixture()
        with pytest.raises(e.Conflict, match="another initial"):
            initial(store, m.model_copy(update={"run_key":"changed"}))
        with pytest.raises(e.Conflict, match="ambiguous"):
            initial(store, m.model_copy(update={"source_sha256":"b"*64,"reels":[m.reels[0],m.reels[0]]}), project="duplicate")
        with pytest.raises(e.Conflict, match="digest"):
            store.import_initial("bad", original.plan_bytes, expected_sha256="f"*64)
        assert store.current("demo") == original
        with pytest.raises(e.Conflict):
            store.current("duplicate")


def test_invalid_correction_never_advances_head(tmp_path):
    with closing(sqlite3.connect(tmp_path/"edit.sqlite")) as c:
        store = e.Store(c)
        base = initial(store)
        for kwargs, error in [
            ({"replacement":"два слова"}, ValueError),
            ({"replacement":"Превет"}, ValueError),
            ({"word_index":99}, e.Conflict),
            ({"expected_text":"не то"}, e.Conflict),
            ({"clip_uid":"f"*64}, e.Conflict),
            ({"base_plan_sha256":"f"*64}, e.Conflict),
        ]:
            with pytest.raises(error):
                store.correct(operation(base, **kwargs))
            assert store.current("demo") == base
        assert store.correct(operation(base)).number == 1


def test_undo_redo_stack_and_branch_invalidation(tmp_path):
    with closing(sqlite3.connect(tmp_path/"edit.sqlite")) as c:
        store = e.Store(c)
        base = initial(store)
        first = store.correct(operation(base))
        second = store.correct(operation(first, op_id="two", word_index=1,
                                        expected_text="мир", replacement="Мир"))
        with pytest.raises(e.Conflict, match="target changed"):
            store.correct(operation(second, op_id="wrong", action="undo",
                                    expected_text="Привет", replacement="Превет"))
        third = store.correct(operation(second, op_id="undo2", action="undo", word_index=1,
                                       expected_text="Мир", replacement="мир"))
        fourth = store.correct(operation(third, op_id="undo1", action="undo",
                                        expected_text="Привет", replacement="Превет"))
        assert fourth.manifest() == base.manifest()
        fifth = store.correct(operation(fourth, op_id="redo1", action="redo"))
        assert fifth.manifest() == first.manifest()
        sixth = store.correct(operation(fifth, op_id="branch", expected_text="Привет", replacement="Здравствуй"))
        assert store.stacks(store.history("demo"))[1] == []
        with pytest.raises(e.Conflict, match="no matching"):
            store.correct(operation(sixth, op_id="redo2", action="redo", word_index=1,
                                    expected_text="мир", replacement="Мир"))
        assert store.current("demo") == sixth
