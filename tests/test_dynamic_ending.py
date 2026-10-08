"""Part 3: dynamic ending — fast fade to black, 0.30s air, 0.25s video+audio fade, last frame black."""
from pathlib import Path

from autoreels.core.config import AudioProcessing, load_render_config
from autoreels.local.render import _audio_tail_fade_parts, _tail_video_fade_filter

_RENDER_YAML = Path(__file__).resolve().parents[1] / "config" / "render.yaml"


# ── config defaults ──────────────────────────────────────────────────────────────

def test_config_defaults_dynamic_ending_on():
    cfg = load_render_config(_RENDER_YAML, local_path="/nonexistent")
    ap = cfg.audio_processing
    assert ap.dynamic_ending is True
    assert ap.end_air_sec == 0.30
    assert ap.end_audio_fade_sec == 0.25
    assert ap.end_video_fade_sec == 0.25
    assert ap.tail_video_fade is False       # legacy flag stays off


# ── audio tail fade ───────────────────────────────────────────────────────────────

def _ap(**kw):
    base = dict(dynamic_ending=True, end_audio_fade_sec=0.25, tail_fade_sec=0.35)
    base.update(kw)
    return AudioProcessing(**base)


def test_dynamic_audio_fade_is_025s_at_end():
    parts = _audio_tail_fade_parts(_ap(), out_duration=10.0, word_end_out=9.7)
    assert len(parts) == 1
    # 0.25s audio fade at the very end; starts well after the last word (9.7) → word audible
    assert "afade=t=out:st=9.75:d=0.25" in parts[0]


def test_dynamic_audio_fade_independent_of_word_end():
    # fade length does not stretch to cover the air (unlike the legacy clean tail)
    parts = _audio_tail_fade_parts(_ap(), out_duration=10.0, word_end_out=8.0)
    assert "d=0.25" in parts[0] and "st=9.75" in parts[0]


def test_legacy_tail_fade_when_dynamic_off():
    parts = _audio_tail_fade_parts(_ap(dynamic_ending=False), out_duration=10.0, word_end_out=9.8)
    # legacy: fade length = max(tail_fade_sec, out-word_end) = max(0.35, 0.2) = 0.35
    assert "d=0.35" in parts[0]


def test_intruded_tail_unchanged_by_dynamic():
    # explicit tail_fade tuple (intruder) path is independent of dynamic_ending
    parts = _audio_tail_fade_parts(_ap(), out_duration=10.0, tail_fade=(8.5, 1.0))
    assert parts == ["afade=t=out:st=8.5:d=1"]   # _num strips the trailing zero


# ── video tail fade ───────────────────────────────────────────────────────────────

def test_dynamic_video_fade_fires_with_evf():
    """dynamic_ending + end_video_fade_sec > 0: video fade filter is non-empty."""
    ap = _ap(end_video_fade_sec=0.25)
    result = _tail_video_fade_filter(ap, out_duration=10.0, word_end_out=9.7,
                                     fps_out=30.0, force=True, min_sec_floor=0.25)
    assert result.startswith("fade=t=out"), f"expected fade filter, got: {result!r}"
    assert "color=black" in result or "d=" in result


def test_dynamic_video_fade_duration_at_least_end_video_fade_sec():
    """Fade duration is at least end_video_fade_sec (the minimum floor)."""
    import re
    ap = _ap(end_video_fade_sec=0.25)
    result = _tail_video_fade_filter(ap, out_duration=10.0, word_end_out=9.7,
                                     fps_out=30.0, force=True, min_sec_floor=0.25)
    m = re.search(r":d=([0-9.]+)", result)
    assert m is not None, f"no duration in: {result!r}"
    assert float(m.group(1)) >= 0.25 - 0.001, f"fade shorter than min: {m.group(1)}"
