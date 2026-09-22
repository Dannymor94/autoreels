"""Part D: a reel-definition fingerprint next to each clip drives re-render, so a re-applied review
with new bounds cannot leave a stale clip in reels-out/."""
from types import SimpleNamespace

import pytest

from autoreels.core.models import Crop, Reel, Segment, SetupProfile, Word
from autoreels.__main__ import (
    _missing_reels,
    _read_render_fingerprint,
    _reel_render_fingerprint,
    _write_render_fingerprint,
)

_SETUP = SetupProfile(setup_id="s", crop=Crop(x=0, y=0, w=100, h=200),
                      scale=[1080, 1920], frame=[1920, 1080])


def _reel(**kw):
    base = dict(id="r01", start=10.0, end=20.0, score=80, hook="h", title="t", description="d")
    base.update(kw)
    return Reel(**base)


def _fp(reel, **over):
    args = dict(setup=_SETUP, palette="neutral", profile="hevc", zoom_on=False, music_path=None)
    args.update(over)
    return _reel_render_fingerprint(reel, **args)


def test_fingerprint_stable_for_same_definition():
    assert _fp(_reel()) == _fp(_reel())


@pytest.mark.parametrize("mutate", [
    lambda r: r.model_copy(update={"end": 21.0}),                      # windows (bounds)
    lambda r: r.model_copy(update={"speed": 1.5}),                     # speed
    lambda r: r.model_copy(update={"title_overlay": "NEW"}),          # title plate
    lambda r: r.model_copy(update={"cold_open": Segment(start=5.0, end=7.0)}),  # cold open
    lambda r: r.model_copy(update={"segments": [Segment(start=10.0, end=15.0),
                                                Segment(start=17.0, end=20.0)]}),  # windows (filler cut)
    lambda r: r.model_copy(update={"subtitles": [Word(word="x", t0=10.0, t1=10.5)]}),  # burned subs
    lambda r: r.model_copy(update={"tail_next_word_start": 19.9}),     # tail fade
])
def test_fingerprint_changes_when_definition_changes(mutate):
    assert _fp(mutate(_reel())) != _fp(_reel())


@pytest.mark.parametrize("over", [
    dict(palette="warm"), dict(profile="h264"),
    dict(zoom_on=True), dict(music_path="/x/track.mp3"),
    dict(setup=SetupProfile(setup_id="s", crop=Crop(x=5, y=0, w=100, h=200),
                            scale=[1080, 1920], frame=[1920, 1080])),   # crop moved
])
def test_fingerprint_changes_with_render_inputs(over):
    assert _fp(_reel(), **over) != _fp(_reel())


def _fake_manifest(reels):
    return SimpleNamespace(reels=reels)


def test_missing_reels_reports_no_clip(tmp_path):
    m = _fake_manifest([_reel()])
    assert _missing_reels(m, tmp_path, _fp) == m.reels        # no mp4 → needs render


def test_missing_reels_skips_fresh_clip(tmp_path):
    r = _reel()
    (tmp_path / "r01.mp4").write_bytes(b"x")
    _write_render_fingerprint(tmp_path, "r01", _fp(r))
    assert _missing_reels(_fake_manifest([r]), tmp_path, _fp) == []   # file + matching fp → skip


def test_missing_reels_re_renders_stale_clip(tmp_path):
    old = _reel()
    (tmp_path / "r01.mp4").write_bytes(b"x")
    _write_render_fingerprint(tmp_path, "r01", _fp(old))
    new = old.model_copy(update={"end": 25.0})                 # review moved the bound
    stale = _missing_reels(_fake_manifest([new]), tmp_path, _fp)
    assert [r.id for r in stale] == ["r01"]                    # fp mismatch → re-render


def test_missing_reels_re_renders_clip_without_fingerprint(tmp_path):
    # Legacy clip rendered before this feature has no sidecar → treated as stale (safe).
    r = _reel()
    (tmp_path / "r01.mp4").write_bytes(b"x")
    assert _missing_reels(_fake_manifest([r]), tmp_path, _fp) == [r]


def test_fingerprint_roundtrip(tmp_path):
    _write_render_fingerprint(tmp_path, "r01", "abc123")
    assert _read_render_fingerprint(tmp_path, "r01") == "abc123"
    assert _read_render_fingerprint(tmp_path, "missing") is None
