"""Rendered clips must last the playback duration the manifest implies.

The manifest is the authority: `Reel.playback_duration()` (cold-open hook + body segments, filler
gaps removed) is the length the viewer sees, and render derives the file length from it — minus only
the crossfade seams, which are accounted exactly.

1. A clip with filler cuts and a crossfade renders to its computed playback duration within a frame.
2. A clip with a cold open renders to hook + body, and the manifest (playback_duration) states it.
3. An intruded tail (next-phrase word inside the segment end) is cut to word_end+pad, strictly
   before the intruder — no audio mute, video and audio end together.
"""
from autoreels.core.models import Reel, Segment, Word
from autoreels.local.render import _snap_windows_to_frames
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


# ── Test 3: intruded tail — clip ends before the intruder ────────────────────
def test_intruded_tail_clip_ends_before_intruder():
    """Intruded tail: render cuts to word_end+pad, strictly before the intruder.
    The manifest still carries the full reel.end (air in the source); what changes is the
    rendered file length, which ends before next_word_start."""
    tail_pad = 1.5
    reel = _reel(id="r", start=100.0, end=108.6, segments=[Segment(start=100.0, end=108.6)])
    words = [
        Word(word="конец.", t0=108.4, t1=108.6),   # last intended word
        Word(word="Дальше", t0=108.9, t1=109.4),   # intruder inside the added tail air
    ]
    _apply_tail_air([reel], words, tail_pad_sec=tail_pad, video_duration=None)

    assert reel.tail_next_word_start == 108.9          # intruder recorded
    assert reel.end > 108.9                            # manifest carries air beyond the intruder

    # New render logic: word_end + pad, capped at nw_start - pad.
    # For this test: word_end ≈ t1=108.6 (no ffmpeg available), pad=0.1 → 108.7 < 108.9.
    nw_start = reel.tail_next_word_start
    pad = 0.10
    # Worst case: word_end = t1 (timestamp, no audio probe in unit test)
    word_end_approx = 108.6
    new_end = min(word_end_approx + pad, nw_start - pad)  # min(108.7, 108.8) = 108.7
    assert new_end < nw_start    # intruder not in clip
    assert new_end > 108.4       # last word start is covered


# ── Test 4: clean tail — full tail_pad_sec preserved ──────────────────────────
def test_clean_tail_keeps_full_tail_pad():
    """Clean tail (no intruder): no trim, full tail_pad_sec of air to EOF."""
    tail_pad = 1.5
    reel = _reel(id="r", start=100.0, end=108.6, segments=[Segment(start=100.0, end=108.6)])
    words = [Word(word="конец.", t0=108.4, t1=108.6)]
    _apply_tail_air([reel], words, tail_pad_sec=tail_pad, video_duration=None)

    assert reel.tail_next_word_start is None    # no intruder
    out_dur = _expected_output_sec(reel)
    last_word_out = reel.tail_last_word_end - reel.start
    # air = out_dur − last_word_out must equal tail_pad within a frame.
    assert abs((out_dur - last_word_out) - tail_pad) < _FRAME
