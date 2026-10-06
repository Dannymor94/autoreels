"""Tests for _refine_seams — internal seam speech-map refinement."""
from autoreels.core.models import Segment
from autoreels.cloud.edit import _refine_seams


def _word(text: str, t0: float, t1: float):
    class W:
        pass
    w = W()
    w.word = text
    w.t0 = t0
    w.t1 = t1
    return w


def _smap_entry(t0: float, t1: float, as_: float, ae: float) -> dict:
    return {"t0": t0, "t1": t1, "audible_start": as_, "audible_end": ae}


def test_seam_whisper_early_uses_audible_end():
    """Whisper t1 is 0.3s early vs map → A-side end moves to audible_end + pad."""
    words = [_word("а", 0.0, 1.0), _word("б", 2.0, 3.0)]
    smap = [_smap_entry(0.0, 1.0, 0.1, 1.3), _smap_entry(2.0, 3.0, 2.1, 2.9)]
    segs = [Segment(start=0.0, end=1.5), Segment(start=2.0, end=3.0)]
    result = _refine_seams(segs, words, smap, seam_pad=0.04)
    assert len(result) == 2
    # A-side: audible_end(word_a)=1.3 + 0.04=1.34, capped at audible_start(word_b)=2.1
    assert abs(result[0].end - 1.34) < 1e-6
    # B-side: audible_start(word_b)=2.1 - 0.04=2.06, floored at audible_end(word_a)=1.3
    assert abs(result[1].start - 2.06) < 1e-6


def test_seam_overlapping_duplicates_removed():
    """Overlapping duplicate words are deduplicated before seam lookup."""
    # first "я" is over-extended artifact (t0=0.0, t1=2.5); second is precise (t0=1.0, t1=2.0)
    words = [_word("я", 0.0, 2.5), _word("я", 1.0, 2.0)]
    smap = [_smap_entry(0.0, 2.5, 0.1, 2.3), _smap_entry(1.0, 2.0, 1.05, 1.95)]
    segs = [Segment(start=0.0, end=1.5), Segment(start=2.5, end=4.0)]
    result = _refine_seams(segs, words, smap, seam_pad=0.04)
    # After dedup: artifact dropped, precise "я" at t0=1.0 kept as last_a
    # A-side end = audible_end(t0=1.0)=1.95 + 0.04 = 1.99
    assert abs(result[0].end - 1.99) < 1e-6


def test_seam_never_inside_word():
    """After refinement, seam times must not fall inside any word's audible span."""
    words = [_word("раз", 0.0, 1.0), _word("два", 1.5, 2.5)]
    smap = [_smap_entry(0.0, 1.0, 0.1, 0.95), _smap_entry(1.5, 2.5, 1.55, 2.45)]
    segs = [Segment(start=0.0, end=1.2), Segment(start=1.5, end=2.5)]
    result = _refine_seams(segs, words, smap, seam_pad=0.04)
    for i in range(len(result) - 1):
        for t in (result[i].end, result[i + 1].start):
            for w in smap:
                assert not (w["audible_start"] < t < w["audible_end"]), (
                    f"Seam at {t:.3f} inside [{w['audible_start']:.3f}, {w['audible_end']:.3f}]"
                )


def test_seam_no_smap_unchanged():
    """Without smap, segments are returned unchanged."""
    words = [_word("а", 0.0, 1.0), _word("б", 2.0, 3.0)]
    segs = [Segment(start=0.0, end=1.5), Segment(start=2.0, end=3.0)]
    result = _refine_seams(segs, words, None, seam_pad=0.04)
    assert result[0].end == 1.5
    assert result[1].start == 2.0


def test_seam_gap_under_two_frames_cut_in_middle():
    """Gap < 2 frames → cut in the middle."""
    # Gap = new_b - new_a would be very small; force it by tight audible bounds
    words = [_word("раз", 0.0, 1.0), _word("два", 1.05, 2.0)]
    # audible_end(раз)=1.02, audible_start(два)=1.04 → new_a=1.02+0.04=1.06, new_b=1.04-0.04=1.00
    # new_a > new_b → midpoint = (1.06+1.00)/2 = 1.03
    smap = [_smap_entry(0.0, 1.0, 0.05, 1.02), _smap_entry(1.05, 2.0, 1.04, 1.95)]
    segs = [Segment(start=0.0, end=1.0), Segment(start=1.05, end=2.0)]
    result = _refine_seams(segs, words, smap, seam_pad=0.04)
    assert result[0].end == result[1].start  # both at midpoint
