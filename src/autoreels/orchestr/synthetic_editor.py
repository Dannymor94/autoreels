"""Opt-in fixed synthetic subtitle editor. Never reads owner plans or media."""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from autoreels.core.models import Crop, Manifest, Reel, SetupProfile, Word
from . import editor_revisions as revisions
from .pathguard import safe_path

_PROJECT = "synthetic-editor-v1"
_DB = ".ui-synthetic-editor.sqlite3"
_MAX_REVISION = 100


class DemoWord(BaseModel):
    index: int
    word: str
    start: float
    end: float


class DemoEdit(BaseModel):
    revision: int
    action: Literal["edit", "undo", "redo"]
    word_index: int
    before: str
    after: str


class DemoEditorView(BaseModel):
    enabled: bool
    revision: int
    plan_sha256: str
    clip_uid: str
    words: list[DemoWord]
    history: list[DemoEdit]
    undo: DemoEdit | None
    redo: DemoEdit | None


class DemoCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["edit", "undo", "redo"]
    op_id: str
    base_revision: int
    base_plan_sha256: str
    clip_uid: str
    word_index: int
    expected_text: str
    replacement: str


def _initial(store: revisions.Store):
    m = Manifest(source="SYNTHETIC_EDITOR.mp4", source_sha256="a"*64,
        duration_preset="shorts", run_key="synthetic-editor-v1",
        setup=SetupProfile(setup_id="demo", crop=Crop(x=0,y=0,w=360,h=640),
                           frame=[360,640], scale=[360,640]),
        reels=[Reel(id="r01", start=0, end=3, score=80, hook="demo",
                    title="demo", description="demo",
                    subtitles=[Word(word="Превет", t0=0.1, t1=0.8),
                               Word(word="дорогие", t0=1.0, t1=1.6),
                               Word(word="друзья!", t0=1.8, t1=2.8)])])
    raw = m.model_dump_json().encode("utf-8")
    return store.import_initial(_PROJECT, raw, expected_sha256=hashlib.sha256(raw).hexdigest())


def _path(root: Path) -> Path:
    path = root / _DB
    if not root.is_dir():
        raise HTTPException(409, "synthetic editor root unavailable")
    for candidate in (path, *(path.with_name(path.name+s) for s in ("-journal","-wal","-shm"))):
        if not safe_path(root, candidate) or (candidate.exists() and not candidate.is_file()):
            raise HTTPException(409, "synthetic editor storage unavailable")
    return path


def _event(number: int, op: revisions.Correction) -> DemoEdit:
    return DemoEdit(revision=number, action=op.action, word_index=op.word_index,
                    before=op.expected_text, after=op.replacement)


def _view(store: revisions.Store) -> DemoEditorView:
    # Single SQLite read snapshot, including head and history.
    with store.conn:
        store.conn.execute("BEGIN")
        head = store.current(_PROJECT)
        history = store.history(_PROJECT)
        if len(history) != head.number or head.number > _MAX_REVISION:
            raise revisions.Conflict("incomplete synthetic history")
        undo, redo = store.stacks(history)
        numbered = {op.op_id: n for n, op in enumerate(history, 1)}
        words = head.manifest().reels[0].subtitles
        return DemoEditorView(enabled=True, revision=head.number, plan_sha256=head.plan_sha256,
            clip_uid=dict(head.clip_uids)["r01"],
            words=[DemoWord(index=i, word=w.word, start=w.t0, end=w.t1) for i,w in enumerate(words)],
            history=[_event(n,op) for n,op in reversed(list(enumerate(history,1)))],
            undo=_event(numbered[undo[-1].op_id],undo[-1]) if undo else None,
            redo=_event(numbered[redo[-1].op_id],redo[-1]) if redo else None)


def view(root: Path, enabled: bool) -> DemoEditorView:
    if not enabled:
        return DemoEditorView(enabled=False, revision=0, plan_sha256="", clip_uid="",
                              words=[], history=[], undo=None, redo=None)
    try:
        path = _path(root)
        if path.exists():
            with closing(sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, timeout=5)) as conn:
                store = revisions.Store(conn, initialize=False)
                if store.has_project(_PROJECT):
                    return _view(store)
        with closing(sqlite3.connect(":memory:")) as conn:
            store = revisions.Store(conn)
            _initial(store)
            return _view(store)
    except (sqlite3.Error, OSError, ValueError, revisions.Conflict):
        raise HTTPException(503, "synthetic editor storage unavailable") from None


def command(root: Path, enabled: bool, body: DemoCommand) -> DemoEditorView:
    if not enabled:
        raise HTTPException(409, "synthetic editor disabled")
    try:
        op = revisions.Correction(project_id=_PROJECT, **body.model_dump())
    except ValueError:
        raise HTTPException(422, "invalid synthetic editor operation") from None
    try:
        path = _path(root)
        with closing(sqlite3.connect(path, timeout=5)) as conn:
            store = revisions.Store(conn)
            _initial(store)
            store.correct(op, max_revision=_MAX_REVISION)
            # Exact retry is idempotent in the store; return current head, not
            # an older snapshot that might roll back the displayed UI.
            return _view(store)
    except revisions.Conflict:
        raise HTTPException(409, "synthetic editor revision conflict") from None
    except ValueError:
        raise HTTPException(422, "invalid synthetic editor operation") from None
    except (sqlite3.Error, OSError):
        raise HTTPException(503, "synthetic editor storage unavailable") from None
