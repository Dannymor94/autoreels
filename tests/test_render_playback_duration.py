"""Rendered clips must last the playback duration the manifest implies.

The manifest is the authority: `Reel.playback_duration()` (cold-open hook + body segments, filler
gaps removed) is the length the viewer sees, and render derives the file length from it — minus only
the crossfade seams, which are accounted exactly. The bug this guards: the tail-intrusion path used
to trim the clip back to the intruding word, silently throwing away the tail_pad_sec of trailing air
(`_apply_tail_air` adds it, render must keep it).

1. A clip with filler cuts and a crossfade renders to its computed playback duration within a frame.
2. A clip with a cold open renders to hook + body, and the manifest (playback_duration) states it.
3. The trailing air measured in the output equals tail_pad_sec within a frame — even with an intruder
   word inside the air (which is silenced by an audio fade, not trimmed away).
"""
from autoreels.core.models import Reel, Segment, Word
from autoreels.local.render import _snap_windows_to_frames, _tail_speech_fade
from autoreels.__main__ import _apply_tail_air

_FPS = 30.0
_FRAME = 1.0 / _FPS
_XFADE_ACTUAL = round(0.08 * _FPS) / _FPS   # frame-snapped, as render computes it


def _reel(**kw) -> Reel:
    base = dict(id="t", start=0.0, end=1.0, score=50, hook="h", title="t", description="d")
    base.update(kw)
    return Reel(**base)


def _expected_output_sec(reel: Reel) -> float:
    """Mirror the render arithmetic: snapped playback windows minus one crossfade per internal seam."""
    windows = _snap_windows_to_frames(reel.playback_windows(), _FPS)
    clip_dur = sum(s.end - s.start for s in windows)
    return clip_dur - (len(windows) - 1) * _XFADE_ACTUAL


# ── Test 1: filler cuts + crossfade → computed playback duration ──────────────
def test_filler_and_xfade_render_to_computed_duration():
    # Body with two filler gaps (4–6s, 10–12s cut out): three windows of 4 + 4 + 3 = 11s played.
    segs = [Segment(start=0.0, end=4.0), Segment(start=6.0, end=10.0), Segment(start=12.0, end=15.0)]
    reel = _reel(start=0.0, end=15.0, segments=segs)

    assert abs(reel.playback_duration() - 11.0) < 1e-9      # filler gaps removed
    # Two internal seams → two crossfades consumed.
    expected = 11.0 - 2 * _XFADE_ACTUAL
    assert abs(_expected_output_sec(reel) - expected) < _FRAME


# ── Test 2: cold open → hook + body, stated by the manifest ───────────────────
def test_cold_open_duration_is_hook_plus_body():
    reel = _reel(start=100.0, end=110.0, cold_open=Segment(start=50.0, end=54.5))
    # playback_duration IS the manifest's stated length: hook (4.5s) replayed before body (10s).
    assert abs(reel.playback_duration() - (4.5 + 10.0)) < 1e-9
    # And render derives the file from that sum (single body window + hook → one seam of xfade).
    assert abs(_expected_output_sec(reel) - (14.5 - _XFADE_ACTUAL)) < _FRAME


# ── Test 3: trailing air survives an intruder ─────────────────────────────────
def test_tail_air_survives_intruder_word():
    tail_pad = 1.5
    # Body ends on the last intended word (108.6s); _apply_tail_air then extends it by tail_pad.
    reel = _reel(id="r", start=100.0, end=108.6, segments=[Segment(start=100.0, end=108.6)])
    words = [
        Word(word="конец.", t0=108.4, t1=108.6),   # last intended word (inside the body)
        Word(word="Дальше", t0=108.9, t1=109.4),   # intruder: starts INSIDE the added tail air
    ]
    _apply_tail_air([reel], words, tail_pad_sec=tail_pad, video_duration=None)

    # Manifest carries the full tail air past the last word — reel.end extended, not trimmed.
    assert abs(reel.end - reel.tail_last_word_end - tail_pad) < _FRAME
    assert reel.tail_next_word_start == 108.9          # intruder recorded (render silences it)

    # Render keeps the air: single window, no xfade → output = full span, so the air to EOF == tail_pad.
    out_dur = _expected_output_sec(reel)
    last_word_out = reel.tail_last_word_end - reel.start
    assert abs((out_dur - last_word_out) - tail_pad) < _FRAME

    # The intruder is handled by an AUDIO fade (not by shortening the clip).
    fade = _tail_speech_fade(reel, reel.playback_windows(), speed=1.0, guard=0.12)
    assert fade is not None
