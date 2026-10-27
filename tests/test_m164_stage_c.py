"""M164 (M1.8 stage C): the tail is placed by the speech map only — no point audio probe left in the render."""
from __future__ import annotations

import inspect


def test_m164_no_point_tail_probe_in_render():
    from autoreels.local import render as R
    assert not hasattr(R, "_tail_find_word_end")
    assert "silencedetect=" not in inspect.getsource(R)
