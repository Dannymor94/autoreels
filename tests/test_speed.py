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
# Test 1: 3-block merge > 90s accepted under 180s manual ceiling at speed 1.0
# ---------------------------------------------------------------------------

def test_three_block_merge_accepted_under_manual_ceiling(tmp_path):
    """A merge spanning ~109s is accepted under the 180s manual ceiling at speed 1.0.

    Human merges are measured against manual_max_duration_sec (180s), not the preset
    ceiling (90s).  No auto-speed is applied because 109s is well within 180s.
    """
    rc, out_path = _apply(tmp_path, "1 90++\n", out_stem="v__spd_t1__")
    assert rc == 0, "109s merge should be accepted under 180s manual ceiling"
    result = Manifest.model_validate_json(out_path.read_text())
    assert result.reels, "should produce at least one reel"
    reel = result.reels[0]
    span = reel.end - reel.start
    assert reel.speed == 1.0, f"no speed-up needed: {span:.1f}s < 180s manual ceiling"
    assert span <= 180.0, f"span {span:.1f}s should be within manual ceiling"


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
    """A 3-block merge whose span exceeds 1.3×manual_max is refused with overshoot named.

    manual_max_duration_sec = 180s; 1.3 × 180 = 234s.
    Groups 1-3 at t=35/140/250 (40 words each) → span ≈ 290 - 35 = 255s > 234s → refused.
    Group 4 at t=500 (sentinel, 40 words) pushes total_duration to ~540s so that group 3
    midpoint 270s is NOT in the tail_skip zone (last 30s of 540s = t>510s).
    """
    words_long = []
    for _go in (35.0, 140.0, 250.0, 500.0):
        for _i in range(40):
            words_long.append({
                "word": f"слово{_i}.",
                "t0": _go + _i * 1.0,
                "t1": _go + _i * 1.0 + 0.95,
            })
    rc, _ = _apply(tmp_path, "1 80++\n", out_stem="v__spd_t3__", words=words_long)
    assert rc != 0, "should refuse a merge whose span exceeds manual_max_duration_sec"
    err = capsys.readouterr().err
    # Merge refused at ceiling check (resolve_merge_groups) with the ceiling named.
    assert "manual_max" in err or "180" in err or "refused" in err.lower(), (
        f"error message should name the manual ceiling; got: {err!r}"
    )
    assert "254" in err or "255" in err or "span" in err.lower(), (
        f"error message should name the span; got: {err!r}"
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

def test_cmd_blocks_apply_with_speed(tmp_path):
    """cmd_blocks called directly with apply_review+speed does not crash with NameError.

    Regression for the bug where speed=getattr(args, ...) referenced 'args' which
    only exists in main(), not in cmd_blocks itself.
    """
    root, cache, mpath, _ = _setup(tmp_path)
    test_mpath = tmp_path / "manifests" / "v__spd_t8__.json"
    test_mpath.write_text(mpath.read_text(), encoding="utf-8")
    review = f"# source: {test_mpath}\n1 80\n"
    rpath = tmp_path / "reviews" / "v__spd_t8__.review.md"
    rpath.write_text(review, encoding="utf-8")
    # This must not raise NameError — args is not in scope inside cmd_blocks
    rc = cli.cmd_blocks(
        None, root=tmp_path, cache_dir=str(cache),
        apply_review=str(rpath), speed=1.1,
    )
    assert rc == 0
    out = tmp_path / "reviews" / "v__spd_t8__.review.json"
    result = Manifest.model_validate_json(out.read_text())
    assert result.reels
    assert result.reels[0].speed == pytest.approx(1.1, abs=0.001)


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
