"""M152 (owner on IMG_6848 m126: r01 «спутанный сценарий» — opened on «То есть…», small cuts in the middle; r09 ended
on the interviewer's reaction): the scenarist is told so, and a reel opening on a back reference is sorted last."""
from __future__ import annotations

from autoreels.cloud.autocut import AutoParams
from autoreels.cloud.scenario import SCENARIO_SYSTEM, _start_doubt, scenario_proposals


def test_the_prompt_names_the_rules():
    assert "Второй момент" in SCENARIO_SYSTEM and "«То есть»" in SCENARIO_SYSTEM and "interviewer's reaction" in SCENARIO_SYSTEM


def test_a_reel_opening_on_a_back_reference_is_doubted():
    assert _start_doubt("То есть ребенок, если у человека, он может быть.") is not None
    assert _start_doubt("Взрослый понимает, что врёт себе.") is None
    sent = {"1.1": (0, 15, "То есть ребёнок говорит правду в лоб.", True, 6),
            "1.2": (15, 30, "И кому-то это заходит, а кого-то обижает.", True, 7),
            "2.1": (100, 115, "Взрослый понимает, что врёт себе.", True, 5),
            "2.2": (115, 130, "Он выбирает, когда сказать правду.", True, 5)}
    units = [{"id": 1, "refs": "1.1-2", "summary": "а"}, {"id": 2, "refs": "2.1-2", "summary": "б"}]
    scens = [{"refs": ["1.1", "1.2"], "hook": None, "title": "", "why": ""},
             {"refs": ["2.1", "2.2"], "hook": None, "title": "", "why": ""}]
    props, _ = scenario_proposals(scens, sent, units, AutoParams(min_sec=20, target_sec=55, max_sec=90))
    assert props[0].start_doubt and "«то…»" in props[0].start_doubt and props[1].start_doubt is None
