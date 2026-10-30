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


def test_m167_drop_last_sentence_keeps_min_sec_and_hook_rules():
    from autoreels.__main__ import _drop_last_sentence
    from autoreels.cloud.autocut import Proposal

    def st(a, b):
        return [SimpleNamespace(t0=a, t1=a + 0.5), SimpleNamespace(t0=b - 0.5, t1=b)]
    sent = {"5.1": st(0, 10), "5.2": st(10, 20), "5.3": st(20, 30)}
    pr = Proposal(units=[1], pieces="5.1-3", hook="5.3", title="t", caption="c", score=1, seconds=30.0,
                  hooks=["5.3", "5.2"], keys=[("5.3", "слово"), ("5.1", "x")], close=["5.3"])
    s = _drop_last_sentence(pr, sent, 15.0)
    assert s.pieces == "5.1-2" and s.seconds == 20.0 and s.hook is None and s.hooks == ["5.2"]
    assert s.keys == [("5.1", "x")] and s.close == []
    assert _drop_last_sentence(pr, sent, 25.0) is None
    assert _drop_last_sentence(Proposal(units=[1], pieces="5.1", hook=None, title="", caption="", score=1,
                                        seconds=10.0), sent, 1.0) is None
