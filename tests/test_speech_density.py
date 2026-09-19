"""Fix 1 (video review): speech density on the FINISHED clip.

A clip assembled across a long pause passes the block-level density check yet plays with dead
air. `_stage_speech_density` recomputes density on the final boundaries and either splits the
clip at a single long gap (keeping the longer half) or drops it as low_speech_density.
"""
from pathlib import Path

from autoreels import __main__ as cli
from autoreels.core.config import load_r0_config
from autoreels.core.models import Reel, Transcript, Word

REPO_ROOT = Path(__file__).resolve().parent.parent


def _r0():
    # Real config: final_speech_density_min=0.80, split_gap=3s, min_clip_duration=8, max=90 (shorts).
    return load_r0_config(REPO_ROOT / "config" / "r0.yaml")


def _reel(rid, start, end):
    return Reel(id=rid, start=start, end=end, score=80, hook="h", title="t", description="d")


def _dense_words(t0, t1):
    """One 1-second speech word per second in [t0, t1) — solid speech, no internal gaps."""
    return [Word(word=f"w{int(t)}", t0=float(t), t1=float(t) + 1.0) for t in range(int(t0), int(t1))]


def test_low_density_single_gap_is_split_longer_half_kept():
    """(1) 72% density with one 14s gap → split at the gap, longer (left) half kept."""
    words = _dense_words(0, 20) + _dense_words(34, 50)   # speech [0,20]+[34,50]; gap 20→34 = 14s
    tx = Transcript(language="ru", words=words)
    reel = _reel("r08", 0.0, 50.0)                        # 50s clip, 36s speech → 72%

    kept, disc = cli._stage_speech_density([reel], tx, r0_cfg=_r0())

    assert disc == []
    assert kept == [reel]
    assert reel.start == 0.0 and reel.end == 20.0          # longer (20s) half kept, gap dropped


def test_low_density_no_large_gap_is_dropped_with_reason():
    """(2) below the floor but no single large gap → dropped, low_speech_density in the sidecar."""
    # 25 words of 1s speech each with a 1s micro-gap between → ~50% density, every gap < 3s.
    words = [Word(word=f"w{i}", t0=float(i * 2), t1=float(i * 2) + 1.0) for i in range(25)]
    tx = Transcript(language="ru", words=words)
    reel = _reel("r_lowdens", 0.0, 50.0)

    kept, disc = cli._stage_speech_density([reel], tx, r0_cfg=_r0())

    assert kept == []
    assert len(disc) == 1
    assert disc[0]["id"] == "r_lowdens"
    assert disc[0]["reason"].startswith("low_speech_density")


def test_high_density_clip_untouched():
    """(3) 95% density → kept unchanged, boundaries not moved."""
    words = _dense_words(0, 38)                            # 38s speech in a 40s clip → 95%
    tx = Transcript(language="ru", words=words)
    reel = _reel("r_good", 0.0, 40.0)

    kept, disc = cli._stage_speech_density([reel], tx, r0_cfg=_r0())

    assert disc == []
    assert kept == [reel]
    assert reel.start == 0.0 and reel.end == 40.0          # untouched
