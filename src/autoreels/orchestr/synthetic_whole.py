"""Separate opt-in whole-source fixture, using the existing immutable editor store."""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing, contextmanager
from itertools import combinations
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from autoreels.core.models import Crop, Manifest, SetupProfile
from . import editor_revisions as revisions
from .longform_review import LongformReview, build_review, synthetic_sentences
from .synthetic_cut import CutPreview, _projection
from .synthetic_editor import _MAX_REVISION, _path
from .whole_source import propose_whole_source

_PROJECT = "synthetic-whole-v1"
_DURATION_MS = 20000


class WholeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    op_id: str
    base_revision: int
    base_plan_sha256: str
    clip_uid: str
    candidate_plan_sha256: str
    removed: list[int]
    navigation: Literal["undo","redo"] | None = None


class WholeView(BaseModel):
    enabled: bool
    review: LongformReview | None
    revision: int
    plan_sha256: str
    clip_uid: str
    current_removed: list[int]
    plans: list[CutPreview]
    undo: CutPreview | None
    redo: CutPreview | None


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fixture():
    sentences = synthetic_sentences()
    words = [w for sentence in sentences for w in sentence]
    # Generated timing evidence, not an ASR or speech-analysis result.
    smap = {"words":[{"idx":i,"t0":w.t0,"t1":w.t1,
                       "audible_start":w.t0,"audible_end":w.t1}
                      for i,w in enumerate(words)],"boundaries":[]}
    review = build_review(sentences,_DURATION_MS)
    choices, plans = {}, []
    # Only three interior sentences in this fixture; not a production
    # enumeration algorithm. All removals require explicit confirmation.
    for size in range(4):
        for removed in combinations(range(2,5),size):
            proposal = propose_whole_source(sentences,words=words,smap=smap,
                source_duration_ms=_DURATION_MS,review_sha256=review.review_sha256,
                confirmed=removed)
            manifest = Manifest(source="DEMO.mp4",source_sha256="c"*64,
                duration_preset="whole-source",run_key=_PROJECT,
                setup=SetupProfile(setup_id="whole-demo",crop=Crop(x=0,y=0,w=96,h=160),
                                   frame=[96,160],scale=[96,160]),reels=[proposal.reel])
            raw = manifest.model_dump_json().encode("utf-8")
            choices[removed]=raw
            kept=tuple(i for i in range(1,6) if i not in removed)
            plans.append(_projection(proposal.reel.effective_segments(),removed,kept,raw))
    return review, choices, plans


def _initial(store,choices):
    return store.import_initial(_PROJECT,choices[()],expected_sha256=_sha(choices[()]))


def _checked(store,choices):
    head=store.current(_PROJECT)
    history=store.selection_history(_PROJECT)
    if len(history)!=head.number or head.number>_MAX_REVISION:
        raise revisions.Conflict("incomplete whole-source history")
    for op in history:
        if (op.project_id!=_PROJECT or op.selection_key!=op.removed
                or op.removed not in choices
                or _sha(choices[op.removed])!=op.candidate_plan_sha256):
            raise revisions.Conflict("invalid whole-source history")
    undo,redo=store.fixture_stacks(history,_sha(choices[()]))
    key,digest=undo[-1]
    if head.plan_bytes!=choices[key] or head.plan_sha256!=digest:
        raise revisions.Conflict("invalid whole-source head")
    return head,key,undo,redo


def _view(store,review,choices,plans):
    with store.conn:
        store.conn.execute("BEGIN")
        head,key,undo,redo=_checked(store,choices)
        def target(entry):
            return next(p for p in plans if p.plan_sha256==entry[1])
        return WholeView(enabled=True,review=review,revision=head.number,
            plan_sha256=head.plan_sha256,clip_uid=dict(head.clip_uids)["r01"],
            current_removed=list(key),plans=plans,
            undo=target(undo[-2]) if len(undo)>1 else None,
            redo=target(redo[-1]) if redo else None)


@contextmanager
def _read_store(root,choices):
    path=_path(root)
    if path.exists():
        with closing(sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=5)) as conn:
            store=revisions.Store(conn,initialize=False)
            if store.has_project(_PROJECT):
                yield store
                return
    with closing(sqlite3.connect(":memory:")) as conn:
        store=revisions.Store(conn)
        _initial(store,choices)
        yield store


def view(root: Path,enabled: bool) -> WholeView:
    if not enabled:
        return WholeView(enabled=False,review=None,revision=0,plan_sha256="",
            clip_uid="",current_removed=[],plans=[],undo=None,redo=None)
    try:
        review,choices,plans=fixture()
        with _read_store(root,choices) as store:
            return _view(store,review,choices,plans)
    except (OSError,ValueError,sqlite3.Error,revisions.Conflict):
        raise HTTPException(503,"whole-source fixture unavailable") from None


def command(root: Path,enabled: bool,body: WholeCommand) -> WholeView:
    if not enabled:
        raise HTTPException(409,"synthetic editor disabled")
    try:
        review,choices,plans=fixture()
        op=revisions.FixtureSelection(action="select-fixture",project_id=_PROJECT,
             **{**body.model_dump(),"removed":tuple(body.removed)})
        if op.selection_key not in choices or _sha(choices[op.selection_key])!=op.candidate_plan_sha256:
            raise revisions.Conflict("whole-source candidate unavailable")
        with closing(sqlite3.connect(_path(root),timeout=5)) as conn:
            store=revisions.Store(conn)
            _initial(store,choices)
            _checked(store,choices)
            store.select_fixture(op,choices=choices,max_revision=_MAX_REVISION)
            return _view(store,review,choices,plans)
    except revisions.Conflict:
        raise HTTPException(409,"whole-source revision conflict") from None
    except ValueError:
        raise HTTPException(422,"invalid whole-source selection") from None
    except (OSError,sqlite3.Error):
        raise HTTPException(503,"whole-source fixture unavailable") from None


def snapshot(root: Path,revision: int,digest: str) -> revisions.Revision:
    """Trusted offline read; exact current saved plan, no editor writes."""
    _,choices,_=fixture()
    with _read_store(root,choices) as store, store.conn:
        store.conn.execute("BEGIN")
        head,*_=_checked(store,choices)
        if head.number!=revision or head.plan_sha256!=digest:
            raise revisions.Conflict("whole-source revision changed")
        return head
