"""Fixed synthetic cut preview using the existing audio-aware planner.

No owner project files or media reads. Only the isolated demo revision
store may be written. The map is generated evidence, not transcription.
"""
import hashlib
from itertools import permutations
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from autoreels.cloud.plan import ManualPlanParams, build_manual_plan
from autoreels.core.models import Crop, Manifest, Reel, SetupProfile, Word

from . import sentence_edit, editor_revisions as revisions
from .synthetic_editor import _path, _MAX_REVISION

_PROJECT = "synthetic-cut-v1"


class CutSentence(BaseModel):
    number: int
    text: str
    start: float
    end: float


class CutWindow(BaseModel):
    source_start: float
    source_end: float
    output_start: float
    output_end: float


class CutPreview(BaseModel):
    removed: list[int]
    order: list[int]
    duration: float
    windows: list[CutWindow]
    plan_sha256: str
    trim: list[int] | None = None


class CutSelectionEvent(BaseModel):
    revision: int
    removed: list[int]
    order: list[int] | None = None
    trim: list[int] | None = None


class CutDemoView(BaseModel):
    enabled: bool
    source_duration: float
    sentences: list[CutSentence]
    plans: list[CutPreview]
    revision: int
    plan_sha256: str
    clip_uid: str
    current_removed: list[int]
    history: list[CutSelectionEvent]


class CutCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    op_id: str
    base_revision: int
    base_plan_sha256: str
    clip_uid: str
    candidate_plan_sha256: str
    removed: list[int]
    order: list[int] | None = None
    trim: list[int] | None = None


def _key(removed, order, trim=None):
    removed, order = tuple(removed), tuple(order)
    key = removed if order == tuple(sorted(order)) else (*removed, 0, *order)
    return key if trim is None else (*key, -1, *trim)


def _projection(segments, removed, order, raw, trim=None):
    windows = []
    offset = 0.0
    for seg in segments:
        end = offset + seg.end - seg.start
        windows.append(CutWindow(source_start=seg.start, source_end=seg.end,
                                 output_start=offset, output_end=end))
        offset = end
    return CutPreview(removed=list(removed), order=list(order), duration=offset,
                      windows=windows, plan_sha256=hashlib.sha256(raw).hexdigest(),
                      trim=list(trim) if trim is not None else None)


def _fixture():
    duration = 3.0
    words = [Word(word=text, t0=float(i), t1=i+0.9)
             for i, text in enumerate(("Начало.", "Лишнее.", "Продолжение."))]
    sentences = [[w] for w in words]
    smap = {"words":[{"idx":i,"t0":w.t0,"t1":w.t1,"audible_start":i+0.2,
                      "audible_end":i+0.8} for i,w in enumerate(words)], "boundaries":[]}
    params = ManualPlanParams()
    order = (1,2,3)
    args = dict(sentences=sentences, words=words, smap=smap,
                params=params, source_duration=duration)
    baseline = build_manual_plan(**args, play=order)
    if baseline.errors:
        raise HTTPException(503, "synthetic cut fixture unavailable")
    base = Reel(id="r01",start=baseline.start,end=baseline.end,score=80,hook="",
                title="fixture",description="fixture",planned=True,
                segments=[s for w in baseline.body for s in w.segments()],
                subtitles=baseline.subtitles, tail_last_word_end=baseline.last_audible_end,
                tail_next_word_start=baseline.next_onset)
    manifest = Manifest(source="SYNTHETIC_CUT.mp4",source_sha256="b"*64,
        duration_preset="shorts",run_key=_PROJECT,
        setup=SetupProfile(setup_id="cut-demo",crop=Crop(x=0,y=0,w=96,h=160),
                           frame=[96,160],scale=[96,160]),reels=[base])
    initial = manifest.model_dump_json().encode("utf-8")
    choices = {():initial}
    plans = [_projection(base.effective_segments(), (), order, initial)]
    for first in order:
        for last in range(first, len(order)+1):
            selected = tuple(range(first,last+1))
            if selected == order:
                continue
            try:
                proposal = sentence_edit.remove_sentences(base, play=order, selected=selected, **args)
            except sentence_edit.Unavailable:
                continue
            cut = proposal.plan
            reel = base.model_copy(update={"start":cut.start,"end":cut.end,
                "segments":[s for w in cut.body for s in w.segments()],
                "subtitles":cut.subtitles,"tail_last_word_end":cut.last_audible_end,
                "tail_next_word_start":cut.next_onset})
            reel.check_segments()
            raw = manifest.model_copy(update={"reels":[reel]}).model_dump_json().encode("utf-8")
            Manifest.model_validate_json(raw)
            choices[selected] = raw
            plans.append(_projection(reel.effective_segments(), selected, proposal.kept_sentences, raw))
    # Natural-order choices retain their exact historical Manifest bytes.
    # The finite demo adds only validated permutations of each kept body.
    for natural in list(plans):
        play = tuple(natural.order)
        raw = choices[tuple(natural.removed)]
        source = Manifest.model_validate_json(raw)
        for perm in permutations(play):
            if perm == play:
                continue
            try:
                reel = sentence_edit.reorder_sentences(source.reels[0], play=play, order=perm, **args)
            except sentence_edit.Unavailable:
                continue
            raw = source.model_copy(update={"reels": [reel]}).model_dump_json().encode("utf-8")
            Manifest.model_validate_json(raw)
            choices[_key(natural.removed, perm)] = raw
            plans.append(_projection(reel.effective_segments(), natural.removed, perm, raw))
    # Keep every original candidate byte-for-byte unchanged. Offer a bounded
    # list of one-edge trim variants on each existing cut/permutation.
    # Absolute integer milliseconds make keys deterministic and collision-free.
    for original in list(plans):
        source = Manifest.model_validate_json(choices[_key(original.removed, original.order)])
        base_reel = source.reels[0]
        for index, seg in enumerate(base_reel.effective_segments()):
            for edge in (1, 2):
                for delta in (50, 100, 150, 200):
                    ms = round((seg.start if edge == 1 else seg.end) * 1000) + (delta if edge == 1 else -delta)
                    start, end = (ms / 1000, seg.end) if edge == 1 else (seg.start, ms / 1000)
                    try:
                        reel = sentence_edit.trim_silence(
                            base_reel, play=tuple(original.order), segment_index=index,
                            start=start, end=end, **args)
                    except (sentence_edit.Unavailable, ValueError):
                        continue
                    trim = (index, edge, ms)
                    raw = source.model_copy(update={"reels": [reel]}).model_dump_json().encode("utf-8")
                    Manifest.model_validate_json(raw)
                    key = _key(original.removed, original.order, trim)
                    if key in choices:
                        raise ValueError("duplicate trim candidate")
                    choices[key] = raw
                    plans.append(_projection(reel.effective_segments(), original.removed,
                                             original.order, raw, trim))
    return duration, [CutSentence(number=i+1,text=w.word,start=i+0.2,end=i+0.8)
                      for i,w in enumerate(words)], plans, choices


def _initial(store, choices):
    raw = choices[()]
    return store.import_initial(_PROJECT,raw,expected_sha256=hashlib.sha256(raw).hexdigest())


def _view(store, fixture):
    duration,sentences,plans,choices = fixture
    with store.conn:
        store.conn.execute("BEGIN")
        head = store.current(_PROJECT)
        history = store.selection_history(_PROJECT)
        active = next((p for p in plans if p.plan_sha256==head.plan_sha256),None)
        if (active is None or head.plan_bytes != choices[_key(active.removed, active.order, active.trim)]
                or len(history)!=head.number or head.number>_MAX_REVISION
                or (history and (history[-1].selection_key!=_key(active.removed, active.order, active.trim)
                    or history[-1].candidate_plan_sha256!=head.plan_sha256))
                or (not history and _key(active.removed, active.order, active.trim))):
            raise revisions.Conflict("incompatible synthetic cut revision")
        return CutDemoView(enabled=True,source_duration=duration,sentences=sentences,
            plans=plans,revision=head.number,plan_sha256=head.plan_sha256,
            clip_uid=dict(head.clip_uids)["r01"],current_removed=active.removed,
            history=[CutSelectionEvent(revision=i,removed=list(op.removed),
                                       order=list(op.order) if op.order is not None else None,
                                       trim=list(op.trim) if op.trim is not None else None)
                     for i,op in reversed(list(enumerate(history,1)))])


def view(root: Path, enabled: bool) -> CutDemoView:
    if not enabled:
        return CutDemoView(enabled=False,source_duration=0,sentences=[],plans=[],
            revision=0,plan_sha256="",clip_uid="",current_removed=[],history=[])
    try:
        fixture = _fixture()
        path = _path(root)
        if path.exists():
            with closing(sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=5)) as conn:
                store = revisions.Store(conn,initialize=False)
                if store.has_project(_PROJECT):
                    return _view(store,fixture)
        with closing(sqlite3.connect(":memory:")) as conn:
            store = revisions.Store(conn)
            _initial(store,fixture[3])
            return _view(store,fixture)
    except (sqlite3.Error,OSError,ValueError,revisions.Conflict):
        raise HTTPException(503,"synthetic cut storage unavailable") from None


def command(root: Path, enabled: bool, body: CutCommand) -> CutDemoView:
    if not enabled:
        raise HTTPException(409,"synthetic editor disabled")
    try:
        op = revisions.FixtureSelection(action="select-fixture",project_id=_PROJECT,
              **{**body.model_dump(),"removed":tuple(body.removed),
                 "order":tuple(body.order) if body.order is not None else None,
                 "trim":tuple(body.trim) if body.trim is not None else None})
    except ValueError:
        raise HTTPException(422,"invalid synthetic cut selection") from None
    try:
        fixture = _fixture()
        choices = fixture[3]
        raw = choices.get(op.selection_key)
        if raw is None or hashlib.sha256(raw).hexdigest()!=op.candidate_plan_sha256:
            raise revisions.Conflict("fixture candidate unavailable")
        path = _path(root)
        with closing(sqlite3.connect(path,timeout=5)) as conn:
            store = revisions.Store(conn)
            _initial(store,choices)
            store.select_fixture(op,choices=choices,max_revision=_MAX_REVISION)
            return _view(store,fixture)
    except revisions.Conflict:
        raise HTTPException(409,"synthetic cut revision conflict") from None
    except ValueError:
        raise HTTPException(422,"invalid synthetic cut selection") from None
    except (sqlite3.Error,OSError):
        raise HTTPException(503,"synthetic cut storage unavailable") from None
