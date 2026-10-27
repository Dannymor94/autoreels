"""M166: the render checks the first word against the plan's span; an automatic clip with no room after its last
word is refused (it needs another end), the owner's own keeps the warning."""
from __future__ import annotations

from types import SimpleNamespace


def test_m166_first_word_reference_planned_uses_the_plan():
    from autoreels.local.render import _first_word_reference
    planned = SimpleNamespace(planned=True, head_first_word_start=125.381)
    assert _first_word_reference(planned, 125.180) == 125.381
    assert _first_word_reference(SimpleNamespace(planned=True, head_first_word_start=None), 125.18) == 125.18
    assert _first_word_reference(SimpleNamespace(planned=False, head_first_word_start=125.381), 125.18) == 125.18


def test_m166_no_room_errors_only_planned_with_the_warning():
    from autoreels.__main__ import _no_room_errors
    w = "no room after last word «опытом.» (next speech at 341.050) — clip ends at its audible end"
    reels = [SimpleNamespace(id="r15", planned=True, warnings=[w]),
             SimpleNamespace(id="r16", planned=True, warnings=["other"]),
             SimpleNamespace(id="r17", planned=False, warnings=[w])]
    assert _no_room_errors(reels) == [("r15", w)]


def test_m166_reel_model_has_head_first_word_start():
    from autoreels.core.models import Reel
    assert "head_first_word_start" in Reel.model_fields
