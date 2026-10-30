"""M144 (m143: 11 of 12 IMG_6848 m126 clips started glued to the speech before them — the owner: «не слышно первой
буквы»): a clip's first sound needs start_pause_min of silence heard before it; a glued start is repaired."""
from __future__ import annotations

from autoreels.cloud.autocut import AutoParams, _hook_cands, context_start, glued_start
from autoreels.cloud.scenario import scenario_proposals
from autoreels.core.config import AutocutConfig
from tests.test_autocut import U
from tests.test_scenario import _sent

PAUSE = {"1.1": 0.8, "2.1": 0.02, "2.2": 0.5, "3.1": 0.01, "3.2": 0.01}


def sp(ref):
    return PAUSE.get(ref)


def _sentences(refs):
    out = []
    for piece in refs.split():
        b, _, r = piece.partition(".")
        a, _, z = r.partition("-")
        for k in range(int(a), int(z or a) + 1):
            out.append((f"{b}.{k}", 4.0, 6, True, f"Мама мыла раму сегодня утром {b}{k}."))
    return out


def test_off_by_default_and_the_reason():
    assert AutocutConfig().start_pause_min == 0.0 and AutoParams().start_pause_min == 0.0
    assert glued_start("2.1", AutoParams(), sp) is None                       # off
    assert glued_start("2.1", AutoParams(start_pause_min=0.15), None) is None  # no map
    assert "склеено" in glued_start("2.1", AutoParams(start_pause_min=0.15), sp)
    assert glued_start("1.1", AutoParams(start_pause_min=0.15), sp) is None


def test_a_glued_start_takes_the_thought_before_as_context():
    u1, u2 = U(1, 0, 8, "thesis", 4, "1.1-2"), U(2, 8.5, 8, "example", 4, "2.1-2")
    by = {1: u1, 2: u2}
    p = AutoParams(context_start=True, min_sec=6, max_sec=60, context_max_sec=20, start_pause_min=0.15)
    clip, notes, why = context_start([u2], by, p, _sentences, start_pause=sp)
    assert why is None and [u["id"] for u in clip] == [1, 2] and any("склеено" in n for n in notes)
    off, _, _ = context_start([u2], by, AutoParams(context_start=True, min_sec=6, max_sec=60, context_max_sec=20),
                              _sentences, start_pause=sp)
    assert [u["id"] for u in off] == [2]                                      # off: as before


def test_a_glued_cold_open_is_not_taken():
    clip = [U(1, 0, 8, "thesis", 4, "1.1"), U(2, 9, 30, "conclusion", 5, "2.1-2")]
    p = AutoParams(hook_min_words=3, hook_min_sec=1.0, hook_max_sec=6.0, start_pause_min=0.15)
    refs = [c[0] for c in _hook_cands(clip, _sentences, p, sp)]
    assert "2.1" not in refs and "2.2" in refs
    assert "2.1" in [c[0] for c in _hook_cands(clip, _sentences, p)]          # no map: as before


def test_scenarist_reel_starts_earlier_or_goes():
    sent = _sent({"1.1": (0, 12, True), "2.1": (12, 12, True), "2.2": (24, 12, True),
                  "3.1": (300, 12, True), "3.2": (312, 12, True)})
    units = [{"id": 1, "refs": "1.1", "summary": "а"}, {"id": 2, "refs": "2.1-2", "summary": "б"},
             {"id": 3, "refs": "3.1-2", "summary": "в"}]
    p = AutoParams(min_sec=20, target_sec=55, max_sec=90, start_pause_min=0.15)
    scens = [{"refs": ["2.1", "2.2"], "hook": None, "title": "", "why": ""},
             {"refs": ["3.1", "3.2"], "hook": None, "title": "", "why": ""}]
    props, gone = scenario_proposals(scens, sent, units, p, None, sp)
    assert [pr.pieces for pr in props] == ["1.1 2.1-2", "3.1-2"]              # 1.1 put before the glued 2.1
    assert not gone and any("оставлено" in n for n in props[1].notes)         # M145: 3.1 cannot be fixed — kept, noted
    props0, gone0 = scenario_proposals(scens, sent, units, AutoParams(min_sec=20, target_sec=55, max_sec=90), None, sp)
    assert len(props0) == 2 and not gone0                                      # off: as before


def test_m145_a_glued_start_with_no_repair_is_kept_not_dropped():
    u3 = U(3, 300, 30, "thesis", 4, "3.1-2")                                 # nothing before it to borrow
    p = AutoParams(context_start=True, min_sec=6, max_sec=60, context_max_sec=20, start_pause_min=0.15,
                   context_later=True, context_later_min_sec=5)
    clip, notes, why = context_start([u3], {3: u3}, p, _sentences, start_pause=sp)
    assert why is None and [u["id"] for u in clip] == [3] and clip[0]["refs"] == "3.1-2"
    assert any("оставлено" in n for n in notes)
