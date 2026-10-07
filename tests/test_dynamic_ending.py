"""Part 4: dynamic ending — no synthetic frozen tail, no fade to black, short end air,
40 ms audio declick only (last word stays fully audible)."""
from pathlib import Path

from autoreels.core.config import AudioProcessing, load_render_config
from autoreels.local.render import _audio_tail_fade_parts

_RENDER_YAML = Path(__file__).resolve().parents[1] / "config" / "render.yaml"


# ── config defaults ──────────────────────────────────────────────────────────────

def test_config_defaults_dynamic_ending_on():
    cfg = load_render_config(_RENDER_YAML, local_path="/nonexistent")
    ap = cfg.audio_processing
    assert ap.dynamic_ending is True
    assert ap.end_air_sec == 0.20
    assert ap.end_audio_fade_ms == 40
    assert ap.tail_video_fade is False          # no fade to black


# ── audio tail fade ───────────────────────────────────────────────────────────────

def _ap(**kw):
    base = dict(dynamic_ending=True, end_audio_fade_ms=40, tail_fade_sec=0.35)
    base.update(kw)
    return AudioProcessing(**base)


def test_dynamic_tail_fade_is_short_declick_at_end():
    parts = _audio_tail_fade_parts(_ap(), out_duration=10.0, word_end_out=9.8)
    assert len(parts) == 1
    # 40 ms fade at the very end; starts well after the last word (9.8) → word stays audible
    assert "afade=t=out:st=9.96:d=0.04" in parts[0]


def test_dynamic_tail_fade_independent_of_word_end():
    # declick length does not stretch to cover the air (unlike the legacy clean tail)
    parts = _audio_tail_fade_parts(_ap(), out_duration=10.0, word_end_out=8.0)
    assert "d=0.04" in parts[0] and "st=9.96" in parts[0]


def test_legacy_tail_fade_when_dynamic_off():
    parts = _audio_tail_fade_parts(_ap(dynamic_ending=False), out_duration=10.0, word_end_out=9.8)
    # legacy: fade length = max(tail_fade_sec, out-word_end) = max(0.35, 0.2) = 0.35
    assert "d=0.35" in parts[0]


def test_intruded_tail_unchanged_by_dynamic():
    # explicit tail_fade tuple (intruder) path is independent of dynamic_ending
    parts = _audio_tail_fade_parts(_ap(), out_duration=10.0, tail_fade=(8.5, 1.0))
    assert parts == ["afade=t=out:st=8.5:d=1"]   # _num strips the trailing zero
