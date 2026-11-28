"""Fixed synthetic cut preview using the existing audio-aware planner.

No owner project files or media reads. Only the isolated demo revision
store may be written. The map is generated evidence, not transcription.
"""
import hashlib
import re
from itertools import permutations, product
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from autoreels.cloud.plan import ManualPlanParams, build_manual_plan
from autoreels.core.models import Crop, Manifest, Reel, SetupProfile, Word
from autoreels.core.playback_timing import build_window_timing

from . import sentence_edit, editor_revisions as revisions
from .synthetic_editor import _path, _MAX_REVISION
from .synthetic_soundtrack import TRACKS, soundtrack
from .longform_review import LongformReview, synthetic_review

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
    rates: list[int] | None = None
    crop: list[int] | None = None
    music: list[int] | None = None
    dip_ms: int | None = None
    graphic: list[int] | None = None


class CutSelectionEvent(BaseModel):
    revision: int
    removed: list[int]
    order: list[int] | None = None
    trim: list[int] | None = None
    rates: list[int] | None = None
    crop: list[int] | None = None
    music: list[int] | None = None
    dip_ms: int | None = None
    graphic: list[int] | None = None
    candidate_plan_sha256: str
    navigation: Literal["undo", "redo"] | None = None


class CutSoundtrackAsset(BaseModel):
    number: int
    label: str
    sha256: str
    format: str
    rights: str
    rights_note: str


def _soundtrack_catalog() -> list[CutSoundtrackAsset]:
    return [CutSoundtrackAsset(number=i, **asset.model_dump())
            for i, asset in enumerate(TRACKS, 1)]


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
    soundtracks: list[CutSoundtrackAsset]
    longform_review: LongformReview | None


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
    rates: list[int] | None = None
    crop: list[int] | None = None
    music: list[int] | None = None
    dip_ms: int | None = None
    graphic: list[int] | None = None
    navigation: Literal["undo", "redo"] | None = None


def _key(removed, order, trim=None, rates=None, crop=None, music=None, dip_ms=None, graphic=None):
    removed, order = tuple(removed), tuple(order)
    key = removed if order == tuple(sorted(order)) else (*removed, 0, *order)
    if trim is not None:
        key = (*key, -1, *trim)
    if rates is not None:
        key = (*key, -2, *rates)
    if crop is not None:
        key = (*key, -3, *crop)
    if music is not None:
        key = (*key, -4, *music)
    if dip_ms is not None:
        key = (*key, -5, dip_ms)
    return key if graphic is None else (*key, -6, *graphic)


def _projection(segments, removed, order, raw, trim=None, rates=None):
    windows = []
    offset = 0.0
    if rates is None:
        # Keep the existing projection unchanged for historical choices.
        for seg in segments:
            end = offset + seg.end - seg.start
            windows.append(CutWindow(source_start=seg.start, source_end=seg.end,
                                     output_start=offset, output_end=end))
            offset = end
    else:
        for w in build_window_timing(segments, [n / 100 for n in rates]):
            windows.append(CutWindow(source_start=w.source_start, source_end=w.source_end,
                                     output_start=w.output_start, output_end=w.output_end))
            offset = w.output_end
    return CutPreview(removed=list(removed), order=list(order), duration=offset,
                      windows=windows, plan_sha256=hashlib.sha256(raw).hexdigest(),
                      trim=list(trim) if trim is not None else None,
                      rates=list(rates) if rates is not None else None)


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
    # Finite three-sentence fixture only; no exponential catalog for real projects.
    # Every vector is indexed by the current playback windows and bound to its
    # exact cut/trim candidate. Unchanged vectors keep their historical bytes.
    for original in list(plans):
        source = Manifest.model_validate_json(choices[_key(original.removed, original.order, original.trim)])
        base_reel = source.reels[0]
        segments = base_reel.effective_segments()
        if len(segments) > 3:
            raise ValueError("synthetic rate fixture exceeds window bound")
        for rates in product((50, 100, 200), repeat=len(segments)):
            if all(n == 100 for n in rates):
                continue
            reel = base_reel.model_copy(update={"window_rates": [n / 100 for n in rates]})
            try:
                reel.check_segments()
            except ValueError:
                continue
            raw = source.model_copy(update={"reels": [reel]}).model_dump_json().encode("utf-8")
            Manifest.model_validate_json(raw)
            key = _key(original.removed, original.order, original.trim, rates)
            if key in choices:
                raise ValueError("duplicate rate candidate")
            choices[key] = raw
            plans.append(_projection(segments, original.removed, original.order,
                                     raw, original.trim, rates))
    return duration, [CutSentence(number=i+1,text=w.word,start=i+0.2,end=i+0.8)
                      for i,w in enumerate(words)], plans, choices


def _framed(fixture, base, crop):
    """Materialize only the requested crop, using the existing Manifest setup."""
    if crop is None:
        return base
    crop = tuple(crop)
    if crop not in revisions.FIXTURE_CROPS or base.crop is not None:
        raise revisions.Conflict("invalid fixture crop")
    _, _, plans, choices = fixture
    key = _key(base.removed, base.order, base.trim, base.rates, crop)
    if key in choices:
        digest = hashlib.sha256(choices[key]).hexdigest()
        return next(p for p in plans if p.plan_sha256 == digest)
    source = Manifest.model_validate_json(
        choices[_key(base.removed, base.order, base.trim, base.rates)])
    setup = source.setup.model_copy(update={"crop": Crop(**dict(zip(("x", "y", "w", "h"), crop)))})
    raw = source.model_copy(update={"setup":setup}).model_dump_json().encode("utf-8")
    Manifest.model_validate_json(raw)
    choices[key] = raw
    p = base.model_copy(update={"crop":list(crop),"plan_sha256":hashlib.sha256(raw).hexdigest()})
    plans.append(p)
    return p


def _scored(fixture, base, music):
    if music is None:
        return base
    music = tuple(music)
    track = soundtrack(music)
    if base.music is not None:
        raise revisions.Conflict("duplicate soundtrack layer")
    _, _, plans, choices = fixture
    parent = _key(base.removed, base.order, base.trim, base.rates, base.crop)
    key = (*parent, -4, *music)
    if key in choices:
        digest = hashlib.sha256(choices[key]).hexdigest()
        return next(p for p in plans if p.plan_sha256 == digest)
    source = Manifest.model_validate_json(choices[parent])
    reel = source.reels[0].model_copy(update={"background_track":track})
    raw = source.model_copy(update={"reels":[reel]}).model_dump_json().encode("utf-8")
    Manifest.model_validate_json(raw)
    choices[key] = raw
    p = base.model_copy(update={"music":list(music),"plan_sha256":hashlib.sha256(raw).hexdigest()})
    plans.append(p)
    return p


def _dipped(fixture, base, dip_ms):
    if dip_ms is None:
        return base
    if base.dip_ms is not None or dip_ms not in (100, 200, 300):
        raise revisions.Conflict("invalid fixture transition")
    _, _, plans, choices = fixture
    parent = _key(base.removed, base.order, base.trim, base.rates, base.crop, base.music)
    key = (*parent, -5, dip_ms)
    if key in choices:
        digest = hashlib.sha256(choices[key]).hexdigest()
        return next(p for p in plans if p.plan_sha256 == digest)
    source = Manifest.model_validate_json(choices[parent])
    reel = source.reels[0].model_copy(update={"seam_dip_ms":dip_ms})
    try:
        reel.check_segments()
    except ValueError as exc:
        raise revisions.Conflict("transition incompatible with windows") from exc
    raw = source.model_copy(update={"reels":[reel]}).model_dump_json().encode("utf-8")
    Manifest.model_validate_json(raw)
    choices[key] = raw
    p = base.model_copy(update={"dip_ms":dip_ms,"plan_sha256":hashlib.sha256(raw).hexdigest()})
    plans.append(p)
    return p


def _graphic(fixture, base, code):
    if code is None:
        return base
    if base.graphic is not None:
        raise revisions.Conflict("duplicate graphic layer")
    fields = revisions.graphic_fields(code)
    _, _, plans, choices = fixture
    parent = _key(base.removed, base.order, base.trim, base.rates,
                  base.crop, base.music, base.dip_ms)
    key = (*parent, -6, *code)
    if key in choices:
        digest = hashlib.sha256(choices[key]).hexdigest()
        return next(p for p in plans if p.plan_sha256 == digest)
    source = Manifest.model_validate_json(choices[parent])
    reel = source.reels[0].model_copy(update=fields)
    try:
        reel.check_segments()
    except ValueError as exc:
        raise revisions.Conflict("graphic incompatible with montage duration") from exc
    raw = source.model_copy(update={"reels":[reel]}).model_dump_json().encode("utf-8")
    Manifest.model_validate_json(raw)
    choices[key] = raw
    p = base.model_copy(update={"graphic":list(code),"plan_sha256":hashlib.sha256(raw).hexdigest()})
    plans.append(p)
    return p


def _selection(fixture, op):
    _, _, plans, choices = fixture
    # Match the temporal selection without inventing a crop/plan combination.
    order = op.order or tuple(n for n in (1, 2, 3) if n not in op.removed)
    base_key = _key(op.removed, order, op.trim, op.rates)
    raw = choices.get(base_key)
    if raw is None:
        raise revisions.Conflict("fixture temporal selection unavailable")
    digest = hashlib.sha256(raw).hexdigest()
    base = next(p for p in plans if p.plan_sha256 == digest and p.crop is None)
    parent = _dipped(fixture, _scored(fixture, _framed(fixture, base, op.crop), op.music), op.dip_ms)
    return _graphic(fixture, parent, op.graphic)


def _initial(store, choices):
    raw = choices[()]
    return store.import_initial(_PROJECT,raw,expected_sha256=hashlib.sha256(raw).hexdigest())


def _view(store, fixture):
    duration,sentences,plans,choices = fixture
    # Normalize transient command candidates so GET and PUT project the same catalog.
    plans[:] = [p for p in plans if p.crop is None and p.music is None and p.dip_ms is None and p.graphic is None]
    for key in list(choices):
        if -3 in key or -4 in key or -5 in key or -6 in key:
            del choices[key]
    with store.conn:
        store.conn.execute("BEGIN")
        head = store.current(_PROJECT)
        history = store.selection_history(_PROJECT)
        # Keep base catalog and current framing choices only; avoid a Cartesian
        # product of all historical crop presets and temporal selections.
        if history:
            _selection(fixture, history[-1])
        active = next((p for p in plans if p.plan_sha256==head.plan_sha256),None)
        if (active is None or head.plan_bytes != choices[_key(active.removed, active.order, active.trim, active.rates, active.crop, active.music, active.dip_ms, active.graphic)]
                or len(history)!=head.number or head.number>_MAX_REVISION
                or (history and (history[-1].selection_key!=_key(active.removed, active.order, active.trim, active.rates, active.crop, active.music, active.dip_ms, active.graphic)
                    or history[-1].candidate_plan_sha256!=head.plan_sha256))
                or (not history and _key(active.removed, active.order, active.trim, active.rates, active.crop, active.music, active.dip_ms, active.graphic))):
            raise revisions.Conflict("incompatible synthetic cut revision")
        undo, _ = store.fixture_stacks(history, hashlib.sha256(choices[()]).hexdigest())
        if undo[-1][1] != head.plan_sha256:
            raise revisions.Conflict("incompatible fixture navigation")
        base = next(p for p in plans if p.crop is None and p.music is None and p.dip_ms is None and p.graphic is None and
                    _key(p.removed,p.order,p.trim,p.rates) == _key(active.removed,active.order,active.trim,active.rates))
        if active.crop is not None:
            for p in [p for p in plans if p.crop is None and p.music is None and p.dip_ms is None and p.graphic is None]:
                _framed(fixture,p,active.crop)
        for crop in revisions.FIXTURE_CROPS:
            _framed(fixture,base,crop)
        # Preserve current soundtrack across currently exposed temporal/crop edits.
        # Enumerate settings only on the active temporal/crop plan, not a full product.
        if active.music is not None:
            for p in [p for p in plans if p.music is None and p.dip_ms is None and p.graphic is None]:
                _scored(fixture,p,active.music)
        parent = _framed(fixture,base,active.crop)
        for music in product(range(1, len(TRACKS)+1),(10,20,30),(0,1),(0,1)):
            _scored(fixture,parent,music)
        if active.dip_ms is not None:
            for p in [p for p in plans if p.dip_ms is None and p.graphic is None]:
                try:
                    _dipped(fixture,p,active.dip_ms)
                except revisions.Conflict:
                    # Do not silently drop a transition if a temporal edit makes
                    # it invalid; the editor exposes only compatible choices.
                    continue
        parent = _scored(fixture,parent,active.music)
        for dip_ms in (100,200,300):
            try:
                _dipped(fixture,parent,dip_ms)
            except revisions.Conflict:
                continue
        # Materialize graphic choices only for the active underlying montage.
        # Other edits require explicitly removing the graphic first.
        parent = _dipped(fixture,parent,active.dip_ms)
        for code in revisions.FIXTURE_GRAPHICS:
            try:
                _graphic(fixture,parent,code)
            except revisions.Conflict:
                continue
        return CutDemoView(enabled=True,source_duration=duration,sentences=sentences,
            plans=plans,revision=head.number,plan_sha256=head.plan_sha256,
            clip_uid=dict(head.clip_uids)["r01"],current_removed=active.removed,
            soundtracks=_soundtrack_catalog(),longform_review=synthetic_review(),
            history=[CutSelectionEvent(revision=i,removed=list(op.removed),
                                       order=list(op.order) if op.order is not None else None,
                                       trim=list(op.trim) if op.trim is not None else None,
                                       rates=list(op.rates) if op.rates is not None else None,
                                       crop=list(op.crop) if op.crop is not None else None,
                                       music=list(op.music) if op.music is not None else None,
                                       dip_ms=op.dip_ms,
                                       graphic=list(op.graphic) if op.graphic is not None else None,
                                       candidate_plan_sha256=op.candidate_plan_sha256,
                                       navigation=op.navigation)
                     for i,op in reversed(list(enumerate(history,1)))])


def view(root: Path, enabled: bool) -> CutDemoView:
    if not enabled:
        return CutDemoView(enabled=False,source_duration=0,sentences=[],plans=[],
            revision=0,plan_sha256="",clip_uid="",current_removed=[],history=[],soundtracks=[],longform_review=None)
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


def preview_graphic(root: Path, enabled: bool, base_revision: int,
                    base_plan_sha256: str, clip_uid: str, graphic: str) -> CutPreview:
    """Read-only, exact current-montage candidate; no persisted draft or asset input."""
    if not enabled:
        raise HTTPException(409,"synthetic editor disabled")
    if not re.fullmatch(r"[0-9]{1,5}(?:,[0-9]{1,5}){6}(?:(?:,[0-9]{1,5}){7}){0,3}",graphic):
        raise HTTPException(422,"invalid graphic parameters")
    state = view(root,enabled)
    if (state.revision != base_revision or state.plan_sha256 != base_plan_sha256
            or state.clip_uid != clip_uid):
        raise HTTPException(409,"synthetic cut revision conflict")
    active = next(p for p in state.plans if p.plan_sha256==state.plan_sha256)
    order = tuple(active.order)
    try:
        op = revisions.FixtureSelection(action="select-fixture",op_id="preview",
             project_id=_PROJECT,clip_uid=clip_uid,base_revision=base_revision,
             base_plan_sha256=base_plan_sha256,candidate_plan_sha256=base_plan_sha256,
             removed=tuple(active.removed),order=order if order!=tuple(sorted(order)) else None,
             trim=tuple(active.trim) if active.trim is not None else None,
             rates=tuple(active.rates) if active.rates is not None else None,
             crop=tuple(active.crop) if active.crop is not None else None,
             music=tuple(active.music) if active.music is not None else None,
             dip_ms=active.dip_ms,graphic=tuple(map(int,graphic.split(","))))
        op.selection_key
        return _selection(_fixture(),op)
    except (ValueError,revisions.Conflict):
        raise HTTPException(409,"graphic incompatible with montage") from None


def command(root: Path, enabled: bool, body: CutCommand) -> CutDemoView:
    if not enabled:
        raise HTTPException(409,"synthetic editor disabled")
    try:
        op = revisions.FixtureSelection(action="select-fixture",project_id=_PROJECT,
              **{**body.model_dump(),"removed":tuple(body.removed),
                 "order":tuple(body.order) if body.order is not None else None,
                 "trim":tuple(body.trim) if body.trim is not None else None,
                 "rates":tuple(body.rates) if body.rates is not None else None,
                 "crop":tuple(body.crop) if body.crop is not None else None,
                 "music":tuple(body.music) if body.music is not None else None,
                 "graphic":tuple(body.graphic) if body.graphic is not None else None})
    except ValueError:
        raise HTTPException(422,"invalid synthetic cut selection") from None
    try:
        fixture = _fixture()
        choices = fixture[3]
        key = op.selection_key
        _selection(fixture,op)
        raw = choices.get(key)
        if raw is None or hashlib.sha256(raw).hexdigest()!=op.candidate_plan_sha256:
            raise revisions.Conflict("fixture candidate unavailable")
        path = _path(root)
        with closing(sqlite3.connect(path,timeout=5)) as conn:
            store = revisions.Store(conn)
            _initial(store,choices)
            history = store.selection_history(_PROJECT)
            if history:
                _selection(fixture,history[-1])
            store.select_fixture(op,choices=choices,max_revision=_MAX_REVISION)
            return _view(store,fixture)
    except revisions.Conflict:
        raise HTTPException(409,"synthetic cut revision conflict") from None
    except ValueError:
        raise HTTPException(422,"invalid synthetic cut selection") from None
    except (sqlite3.Error,OSError):
        raise HTTPException(503,"synthetic cut storage unavailable") from None
