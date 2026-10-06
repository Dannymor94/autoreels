"""Tests for scripts/make_covers.py — pure logic, no ffmpeg, no real clip."""

import sys
from pathlib import Path

import pytest

# Allow importing the script directly (it lives outside the package)
_SCRIPTS = Path(__file__).parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import make_covers


# ── filter_candidate_times ─────────────────────────────────────────────────────


def test_filter_skips_before_start():
    times = [0.0, 0.2, 0.5, 1.0, 5.0]
    result = make_covers.filter_candidate_times(times, clip_duration=10.0)
    assert 0.0 not in result
    assert 0.2 not in result
    assert 0.5 in result  # SKIP_START_SEC == 0.5 → inclusive


def test_filter_skips_fade_zone():
    # clip=10s, fade_guard=1.5 → guard_end = 8.5
    times = [8.0, 8.5, 9.0, 9.9]
    result = make_covers.filter_candidate_times(times, clip_duration=10.0)
    assert 8.0 in result
    assert 8.5 in result
    assert 9.0 not in result
    assert 9.9 not in result


def test_filter_skips_synthetic_tail():
    # clip=12s, fade_guard=1.5, tail=2.0 → guard_end = 8.5 (inclusive boundary)
    times = [5.0, 8.0, 8.5, 9.0]
    result = make_covers.filter_candidate_times(
        times, clip_duration=12.0, synthetic_tail=2.0
    )
    assert 5.0 in result
    assert 8.0 in result
    assert 8.5 in result  # boundary inclusive — last frame before fade
    assert 9.0 not in result  # inside synthetic tail → excluded


def test_filter_empty_input():
    assert make_covers.filter_candidate_times([], clip_duration=10.0) == []


# ── pick_top_frames ────────────────────────────────────────────────────────────


def test_pick_top_respects_min_gap():
    scored = [(0.0, 10.0), (1.0, 9.0), (2.5, 8.0), (5.0, 7.0)]
    top = make_covers.pick_top_frames(scored, n=3, min_gap=2.0)
    times = [t for t, _ in top]
    assert len(top) == 3
    for i in range(len(times)):
        for j in range(i + 1, len(times)):
            assert abs(times[i] - times[j]) >= 2.0


def test_pick_top_chronological_order():
    scored = [(0.0, 5.0), (10.0, 9.0), (5.0, 7.0)]
    top = make_covers.pick_top_frames(scored, n=3, min_gap=0.0)
    times = [t for t, _ in top]
    assert times == sorted(times)


def test_pick_top_fewer_than_n():
    scored = [(0.0, 5.0)]
    top = make_covers.pick_top_frames(scored, n=3, min_gap=2.0)
    assert len(top) == 1


# ── wrap_title ─────────────────────────────────────────────────────────────────


class _FixedWidthFont:
    """Mock font: each character is 14px wide."""

    def getbbox(self, text):
        return (0, 0, len(text) * 14, 20)


def test_wrap_title_single_short_line():
    font = _FixedWidthFont()
    lines = make_covers.wrap_title("Короткий заголовок", font, max_width_px=1000)
    assert len(lines) == 1
    assert lines[0] == "Короткий заголовок"


def test_wrap_title_at_most_3_lines():
    font = _FixedWidthFont()
    # Very long title that would need 5+ lines at 200px width
    long = " ".join([f"слово{i}" for i in range(20)])
    lines = make_covers.wrap_title(long, font, max_lines=3, max_width_px=200)
    assert len(lines) <= 3


def test_wrap_title_respects_max_width():
    font = _FixedWidthFont()
    # Each word is "абвгд" = 5 chars * 14px = 70px; max_width=200px → ~2-3 words/line
    text = " ".join(["абвгд"] * 8)
    lines = make_covers.wrap_title(text, font, max_lines=3, max_width_px=200)
    for line in lines[:-1]:  # last line may overflow if forced
        assert font.getbbox(line)[2] <= 200 + 70  # one word tolerance on last


def test_wrap_title_empty():
    font = _FixedWidthFont()
    assert make_covers.wrap_title("", font) == []


# ── score_frame — face detection injectable ────────────────────────────────────


try:
    import numpy as np
    import cv2 as _cv2
    _NUMPY_OK = True
except ImportError:
    _NUMPY_OK = False


class _FaceCascade:
    """Always detects one large face."""

    def detectMultiScale(self, gray, *a, **kw):
        h, w = gray.shape
        return [(0, 0, w // 2, h // 2)]


class _NoFaceCascade:
    """Never detects a face."""

    def detectMultiScale(self, gray, *a, **kw):
        return []


@pytest.mark.skipif(not _NUMPY_OK, reason="numpy/cv2 required")
def test_face_score_higher_with_face_cascade():
    h, w = 200, 200
    blank = np.zeros((h, w, 3), dtype=np.uint8)
    score_face = make_covers.score_frame(blank, cascade=_FaceCascade())
    score_none = make_covers.score_frame(blank, cascade=_NoFaceCascade())
    assert score_face > score_none


@pytest.mark.skipif(not _NUMPY_OK, reason="numpy/cv2 required")
def test_drawn_face_sharper_than_blank():
    """A frame with drawn edges scores higher via sharpness than a solid blank."""
    h, w = 200, 200
    blank = np.zeros((h, w, 3), dtype=np.uint8)
    face_frame = blank.copy()
    # Draw a head (circle outline) and eyes
    _cv2.circle(face_frame, (w // 2, h // 3), 50, (200, 180, 160), 2)
    _cv2.circle(face_frame, (w // 2 - 15, h // 3 - 10), 8, (50, 50, 50), -1)
    _cv2.circle(face_frame, (w // 2 + 15, h // 3 - 10), 8, (50, 50, 50), -1)

    sharp_blank = make_covers.sharpness(blank)
    sharp_face = make_covers.sharpness(face_frame)
    assert sharp_face > sharp_blank, "drawn edges make frame sharper than solid blank"

    # With a mock cascade, the drawn-face frame also gets the face bonus
    score_face = make_covers.score_frame(face_frame, cascade=_FaceCascade())
    score_blank = make_covers.score_frame(blank, cascade=_FaceCascade())
    assert score_face > score_blank


# ── subtitle_sentence_starts ───────────────────────────────────────────────────


def _words(*pairs):
    return [{"word": f"w{i}", "t0": t0, "t1": t0 + 0.3} for i, (t0, _) in enumerate(pairs)]


def test_subtitle_sentence_starts_single_segment():
    reel = {
        "start": 10.0,
        "end": 30.0,
        "segments": [],
        "speed": 1.0,
        "subtitles": _words((10.0, 10.3), (10.5, 10.8), (13.0, 13.3), (13.5, 13.8)),
    }
    render_json = {"source_start": 10.0}
    times = make_covers.subtitle_sentence_starts(reel, render_json)
    # gap between 10.8 and 13.0 > 0.5 → two sentence starts at ~0.0 and ~3.0
    assert len(times) == 2
    assert abs(times[0] - 0.0) < 0.01
    assert abs(times[1] - 3.0) < 0.01


def test_subtitle_sentence_starts_empty():
    reel = {"start": 0.0, "end": 10.0, "segments": [], "speed": 1.0, "subtitles": []}
    assert make_covers.subtitle_sentence_starts(reel, {}) == []


# ── resolve_clip_context ───────────────────────────────────────────────────────


def test_resolve_gate_context():
    clip = Path("/data/reels-out/VID_01/_gate/g1/r01.mp4")
    reel_id, video_stem, gate_label = make_covers.resolve_clip_context(clip)
    assert reel_id == "r01"
    assert video_stem == "VID_01"
    assert gate_label == "g1"


def test_resolve_final_context():
    clip = Path("/data/reels-out/VID_01/r01.mp4")
    reel_id, video_stem, gate_label = make_covers.resolve_clip_context(clip)
    assert reel_id == "r01"
    assert video_stem == "VID_01"
    assert gate_label == "final"
