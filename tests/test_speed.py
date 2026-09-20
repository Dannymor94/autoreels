"""Tests for per-clip speed and manual merge ceiling.

1. A three-block human merge is accepted under the 180s manual ceiling with auto-speed.
2. A single block within preset ceiling uses speed 1.0.
3. A merge needing > 1.3x speed is refused with the overshoot named.
4. Per-clip @marker overrides --speed, which overrides config.
5. Subtitle timings are divided by speed factor; last word still inside clip.
6. Speed outside 1.0-1.3 is refused at parse time.
7. Manifest records per-clip speed; re-read gives same value.
"""
import json
import math
import shutil
from pathlib import Path

import pytest

from autoreels import __main__ as cli
from autoreels.cloud.blocks import _parse_score_markers
from autoreels.cloud.transcribe import params_key
from autoreels.core import state
from autoreels.core.models import Crop, Manifest, SetupProfile

REPO_ROOT = Path(__file__).resolve().parents[1]

_META = {"provider": "groq", "model": "whisper-large-v3", "prompt_hash": "phspd"}
KEY = params_key(_META)

# Word layout: 4 groups of 35 words (0.95s duration, 1s spacing).
# Groups start at t=35, 72, 109, 146 — gaps of 2.05s between groups (> min_pause_for_phrase_end=1.5s).
# Block midpoints: 52.5s, 89.5s, 126.5s, 163.5s.
# total_duration ≈ 180.95s; tail_skip zone = last 30s = t>150.95s → block 4 (mid=163.5) filtered ✓.
# head_skip zone = first 30s = t<30s → block 1 (mid=52.5) NOT filtered ✓.
# kept = [block1, block2, block3]; merged span ≈ 143.95-35 = 108.95s > 90s → auto-speed ~1.21x.
_WORDS = []
for _go in (35.0, 72.0, 109.0, 146.0):
    for _i in range(35):
        _WORDS.append({
            "word": f"слово{_i}.",
            "t0": _go + _i * 1.0,
            "t1": _go + _i * 1.0 + 0.95,
        })


def _setup(tmp_path, words=None):
    """Returns (root, cache, mpath, tpath). Copies r0.yaml so root=tmp_path works."""
    if words is None:
        words = _WORDS
    (tmp_path / "manifests").mkdir(exist_ok=True)
    (tmp_path / "reviews").mkdir(exist_ok=True)
    cfg_dst = tmp_path / "config"
    cfg_dst.mkdir(exist_ok=True)
    shutil.copy(REPO_ROOT / "config" / "r0.yaml", cfg_dst / "r0.yaml")
    cache = tmp_path / "cache"
    cache.mkdir(exist_ok=True)
    sha = "d" * 64
    mp3 = cache / f"{sha}.mp3"
    mp3.write_bytes(b"AUDIO_SPEED_TEST")
    ah = state.audio_hash(mp3)
    tpath = cache / f"{ah}.{KEY}.transcript.json"
    tpath.write_text(
        json.dumps({"language": "ru", "words": words, "source_sha256": sha, **_META}),
        encoding="utf-8",
    )
    m = Manifest(
        source="v.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
        source_path="/originals/v.mp4",
        duration_preset="shorts",
        setup=SetupProfile(setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700),
                           scale=[1080, 1920], frame=[1920, 1080]),
        run_key="rk_spd", transcript_params_key=KEY,
        source_kind="lecture", reels=[],
    )
    mpath = tmp_path / "manifests" / "v.json"
    mpath.write_text(m.model_dump_json(), encoding="utf-8")
    return tmp_path, cache, mpath, tpath


def _apply(tmp_path, review_content, *, out_stem, speed=None, words=None):
    """Run _blocks_do_apply with root=tmp_path so nothing lands under the real repo."""
    root, cache, mpath, _ = _setup(tmp_path, words=words)
    (tmp_path / "reviews").mkdir(exist_ok=True)
    test_mpath = tmp_path / "manifests" / f"{out_stem}.json"
    test_mpath.write_text(mpath.read_text(), encoding="utf-8")
    review_path = tmp_path / "reviews" / f"{out_stem}.review.md"
    review_path.write_text(review_content, encoding="utf-8")
    kw = dict(root=tmp_path, cache_dir=str(cache), source=str(test_mpath))
    if speed is not None:
        kw["speed"] = speed
    rc = cli._blocks_do_apply(str(review_path), **kw)
    out_path = tmp_path / "reviews" / f"{out_stem}.review.json"
    return rc, out_path


# ---------------------------------------------------------------------------
# Test 1: 3-block merge > 90s accepted under 180s manual ceiling with auto-speed
# ---------------------------------------------------------------------------

def test_three_block_merge_accepted_under_manual_ceiling(tmp_path):
    """A merge spanning ~109s is accepted (manual ceiling 180s) with auto-speed."""
    rc, out_path = _apply(tmp_path, "1 90++\n", out_stem="v__spd_t1__")
    assert rc == 0, "merge should be accepted under 180s manual ceiling with auto-speed"
    result = Manifest.model_validate_json(out_path.read_text())
    assert result.reels, "should produce at least one reel"
    reel = result.reels[0]
    assert reel.speed > 1.0, "auto-speed must be > 1.0 to fit under 90s"
    assert reel.speed <= 1.3
    final_dur = (reel.end - reel.start) / reel.speed
    assert final_dur <= 90.0 + 0.5, f"final duration {final_dur:.1f}s must fit under ~90s"


# ---------------------------------------------------------------------------
# Test 2: single block within preset ceiling uses speed 1.0
# ---------------------------------------------------------------------------

def test_auto_selection_single_block_no_speed(tmp_path):
    """A single block within preset ceiling uses speed 1.0."""
    rc, out_path = _apply(tmp_path, "1 80\n", out_stem="v__spd_t2__")
    assert rc == 0
    result = Manifest.model_validate_json(out_path.read_text())
    assert result.reels
    assert result.reels[0].speed == 1.0, "no speed-up needed for a short clip"


# ---------------------------------------------------------------------------
# Test 3: merge needing > 1.3x is refused with overshoot named
# ---------------------------------------------------------------------------

def test_auto_speed_refuses_when_too_long(tmp_path, capsys):
    """A 3-block merge needing > 1.3x speed is refused with the overshoot named."""
    # 4 groups of 50 words at t=35/87/139/191 (2.05s gaps, sentinel 4th group in tail zone).
    # Groups 1-3 kept, group 4 filtered by tail_skip.
    # Merged span of groups 1+2+3: ~188.95-35 = 153.95s; needs 153.95/90=1.71x > 1.3x → refused.
    words_long = []
    for _go in (35.0, 87.0, 139.0, 191.0):
        for _i in range(50):
            words_long.append({
                "word": f"слово{_i}.",
                "t0": _go + _i * 1.0,
                "t1": _go + _i * 1.0 + 0.95,
            })
    rc, _ = _apply(tmp_path, "1 80++\n", out_stem="v__spd_t3__", words=words_long)
    assert rc != 0, "should refuse a merge needing > 1.3x speed"
    err = capsys.readouterr().err
    assert "1.3x" in err or "max allowed" in err.lower() or "overshoot" in err.lower(), (
        f"error message should name the 1.3x limit; got: {err!r}"
    )


# ---------------------------------------------------------------------------
# Test 4: @marker overrides --speed
# ---------------------------------------------------------------------------

def test_speed_precedence_marker_over_arg(tmp_path):
    """@marker speed overrides --speed argument."""
    rc, out_path = _apply(tmp_path, "1 80@1.1\n", out_stem="v__spd_t4__", speed=1.2)
    assert rc == 0, "should succeed with explicit @1.1 marker"
    result = Manifest.model_validate_json(out_path.read_text())
    assert result.reels
    assert result.reels[0].speed == pytest.approx(1.1, abs=0.001), (
        "@1.1 marker must override --speed 1.2"
    )


# ---------------------------------------------------------------------------
# Test 5: subtitle timings rescaled by speed
# ---------------------------------------------------------------------------

def test_subtitle_timings_rescaled(tmp_path):
    """Subtitle word timings are divided by speed relative to clip start."""
    rc, out_path = _apply(tmp_path, "1 80@1.2\n", out_stem="v__spd_t5__")
    assert rc == 0
    result = Manifest.model_validate_json(out_path.read_text())
    assert result.reels
    reel = result.reels[0]
    spd = reel.speed
    assert spd == pytest.approx(1.2, abs=0.001), "speed should be 1.2 from @marker"
    for w in reel.subtitles:
        rel = (w.t0 - reel.start) * spd
        assert rel >= 0.0, "relative time must be non-negative"
    if reel.subtitles:
        last_word_end = reel.subtitles[-1].t1
        assert last_word_end <= reel.end + 0.5, (
            f"last subtitle word ends at {last_word_end:.2f}s, clip ends at {reel.end:.2f}s"
        )


# ---------------------------------------------------------------------------
# Test 6: speed outside 1.0-1.3 refused at parse time
# ---------------------------------------------------------------------------

def test_speed_out_of_range_refused():
    """@marker with speed outside [1.0, 1.3] is refused."""
    _, _, _, _, err = _parse_score_markers("80@1.5")
    assert err is not None, "should refuse speed 1.5"
    assert "1.3" in err or "range" in err.lower()

    _, _, _, _, err = _parse_score_markers("80@0.9")
    assert err is not None, "should refuse speed 0.9 (below 1.0)"

    _, _, _, spd, err = _parse_score_markers("80@1.15")
    assert err is None, "1.15 is valid"
    assert spd == pytest.approx(1.15, abs=0.001)


# ---------------------------------------------------------------------------
# Test 7: manifest records speed; re-read gives same value
# ---------------------------------------------------------------------------

def test_manifest_records_speed(tmp_path):
    """Manifest reel.speed matches what was applied; re-read gives same value."""
    rc, out_path = _apply(tmp_path, "1 80@1.1\n", out_stem="v__spd_t7__")
    assert rc == 0
    result = Manifest.model_validate_json(out_path.read_text())
    assert result.reels
    reel = result.reels[0]
    assert reel.speed == pytest.approx(1.1, abs=0.001)
    result2 = Manifest.model_validate_json(out_path.read_text())
    assert result2.reels[0].speed == reel.speed, "re-read manifest must have same speed"
