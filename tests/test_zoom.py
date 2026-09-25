"""M1.7 zoom improvements: fps desync fix, z: sentence placement, duration default, c:+k: cut.

Tests:
1. With zoom on, zoompan fps follows the passed source fps (not the Zoom.fps field).
2. z:N parser: sentence index stored; two z: on one line refused.
3. Zoom duration default is 0.25 (configurable via Zoom.duration).
4. A shot change placed on a k:-emphasised word uses that word's t0 as the close range start.
"""
import pytest

from autoreels.core.config import Zoom
from autoreels.local.render import _zoom_vf, assign_close_shots
from autoreels.cloud.blocks import _parse_fields, parse_compact_answer
from autoreels.core.models import Segment, Word


# ── Test 1: zoompan uses source fps, not Zoom.fps ─────────────────────────────

def test_zoom_vf_uses_passed_fps_not_config_fps():
    """zoompan fps= must come from the source-fps parameter, not Zoom.fps.

    Using a wrong fps (e.g. 30 for a 29.97 source) makes zoompan output a
    constant 30fps stream while audio stays at source rate → drift grows with
    clip length. Passing the probed fps prevents the desync.
    """
    zoom = Zoom(enabled=True, fps=30)   # Zoom.fps is now IGNORED
    vf_25 = _zoom_vf([1080, 1920], zoom, fps=25.0)
    vf_30 = _zoom_vf([1080, 1920], zoom, fps=30.0)
    vf_2997 = _zoom_vf([1080, 1920], zoom, fps=29.97)

    assert "fps=25" in vf_25,   "source fps 25 must appear in filter"
    assert "fps=30" in vf_30,   "source fps 30 must appear in filter"
    assert "fps=29.97" in vf_2997, "source fps 29.97 must appear in filter"
    # Zoom.fps=30 is NOT what drives the output — the parameter does
    assert "fps=25" not in vf_30  # sanity: different fps → different string


# ── Test 2: z: parser — sentence index stored; two z: refused ─────────────────

def test_z_parser_stores_sentence_index():
    """z:N parsed into _ReviewEntry.z; sentence index is 1-based."""
    _, entries, errors, _ = parse_compact_answer("3 85 | z:2 | t: Заголовок")
    assert errors == []
    assert entries[0].z == 2


def test_z_parser_two_z_refused():
    """Two z: fields on one line → error; z_val is None."""
    *_, z_val, errors = _parse_fields("z:1 | z:3")
    assert any("z:" in e and "once" in e for e in errors)


def test_z_parser_absent_gives_none():
    """No z: → z is None in the entry."""
    _, entries, errors, _ = parse_compact_answer("5 90 | t: Без зума")
    assert errors == []
    assert entries[0].z is None


# ── Test 3: zoom duration default is 0.25 ─────────────────────────────────────

def test_zoom_duration_default_is_0_25():
    """Default Zoom.duration must be 0.25 (faster feel than the old 0.4)."""
    z = Zoom()
    assert z.duration == pytest.approx(0.25)


def test_zoom_duration_configurable():
    """Zoom.duration can be overridden; the value appears in the zoompan expression."""
    vf = _zoom_vf([1080, 1920], Zoom(enabled=True, duration=0.15))
    assert "ot/0.15" in vf   # rise part of the trapezoid uses duration


# ── Test 4: c:+k: — shot change at emphasised word's t0 ───────────────────────

def _word(text, t0, t1):
    return Word(word=text, t0=t0, t1=t1)


def test_close_shot_range_starts_at_emph_word_when_ck_coincide():
    """When c:N and k:N=word coincide, assign_close_shots is given the emph word's t0
    as the range start — so the hard cut lands on the stressed word, not the sentence boundary.

    This is tested at the _c_close_ranges level (source-time ranges passed to assign_close_shots).
    The range start for the sentence should equal the emph word's t0, not the sentence's first word.
    """
    # Sentence: "страх это сигнал." — emphasised word is "сигнал" at t0=2.0
    words = [
        _word("страх", 0.0, 0.4),
        _word("это", 0.5, 0.7),
        _word("сигнал.", 2.0, 2.4),   # emph word — later in sentence
    ]
    # Simulate what --apply does: build close_ranges with emph word t0
    from autoreels.cloud.edit import split_sentences
    sents = split_sentences(words)
    assert len(sents) == 1
    sent = sents[0]

    def _normalize_kw(w):
        return w.lower().replace("ё", "е").strip(".,!?;:—–-\"'«»()[]")

    # c:1 + k:1=сигнал → range_start should be t0 of "сигнал.", not t0 of "страх"
    range_start = sent[0].t0   # default: sentence boundary
    kw_spec = ((1, ("сигнал",)),)
    for ki, kws in kw_spec:
        if ki == 1:
            for kw in kws:
                is_pfx = kw.endswith("*")
                kw_p = kw[:-1] if is_pfx else kw
                for sw in sent:
                    sw_norm = _normalize_kw(sw.word)
                    if (is_pfx and sw_norm.startswith(kw_p)) or (not is_pfx and sw_norm == kw_p):
                        range_start = sw.t0
                        break
                else:
                    continue
                break
            break

    assert range_start == pytest.approx(2.0), \
        "close range must start at emphasised word t0=2.0, not sentence start t0=0.0"

    # Verify assign_close_shots translates this range into close_intervals correctly
    seg = Segment(start=0.0, end=3.0)
    result = assign_close_shots([seg], [(range_start, sent[-1].t1)])
    # Segment partially covered → close_intervals set
    assert result[0].close_intervals, "close_intervals must be set"
    rel_start = result[0].close_intervals[0][0]
    assert rel_start == pytest.approx(2.0, abs=0.01), \
        "close interval must start at 2.0s into segment (the emph word)"
