"""M205: two reels are too close by the sentences heard in both (close_by: sound), not by the map's thoughts; the set
with the largest total score and no two too close is taken first (select: global). m200: «Алгоритм или эмпатия» was
refused as sharing map thought #52 with M3 while no sentence was heard in both."""
from __future__ import annotations

import json
import re

from autoreels.cloud.autocut import Proposal, select_global, sound_close


def _pr(pieces: str, title: str = "") -> Proposal:
    return Proposal(score=90, pieces=pieces, units=[1], hook=None, title=title, caption="", seconds=0.0)


SECS = {"a": {"1.1": 3.0, "1.2": 4.0}, "b": {"1.2": 4.0, "1.3": 6.0}, "c": {"2.1": 5.0}, "d": {"1.1": 2.0, "3.1": 9.0},
        "e": {"4.1": 2.0, "1.2": 4.0, "4.2": 30.0}}


def _secs(pr):
    return SECS[pr.pieces]


def test_sound_close_shared_sentences_first_sentence_and_title():
    a, b, c, d = _pr("a"), _pr("b"), _pr("c", "Тема"), _pr("d")
    assert sound_close(c, [a], _secs) is None                                   # nothing heard in both
    assert sound_close(b, [a], _secs).startswith("общие фразы с M1: 1.2")       # 1.2 is played in both
    assert sound_close(d, [a], _secs) == "то же начало, что у M1 (фраза 1.1)"
    assert sound_close(_pr("b", "Тема"), [c], _secs) == "тот же заголовок, что у M1"


def test_sound_close_share_threshold_is_of_the_shorter_reel():
    a, e = _pr("a"), _pr("e")
    assert sound_close(e, [a], _secs, max_share=0.0) is not None                # 4 s of a's 7 s heard in both
    assert sound_close(e, [a], _secs, max_share=0.5) is not None                # 57 % > 50 %
    assert sound_close(e, [a], _secs, max_share=0.6) is None


def test_select_global_takes_the_best_set_not_the_first():
    clash = {(0, 1), (0, 2)}
    conflict = lambda i, j: (i, j) in clash or (j, i) in clash                 # noqa: E731
    assert select_global([10, 7, 6, 3], conflict, 3) == [1, 2, 3]               # greedy: 0, 3 (13) — global: 16
    assert select_global([10, 7, 6, 3], conflict, 2) == [0, 3]                  # 13 = 13: the heaviest found first
    assert select_global([10, 7, 6, 3], conflict, 1) == [0]
    assert select_global([], conflict, 3) == [] and select_global([5], conflict, 0) == []
    assert select_global([10, 7, 6, 3], conflict, 3, exact_max=2) == [0, 3]     # above exact_max: greedy by weight


def _project(tmp_path, close_by: str, select: str):
    """The fake source of test_scenario (8 sentences 2.1-8), a map of two thoughts (2.1-4, 2.5-8) and a scenarist
    writing R1 = 2.4-5 (both thoughts), R2 = 2.1-3, R3 = 2.6-8 in that order."""
    from tests.test_m202_replay_accounting import _scenario_project
    cli, _Fake, first, second = _scenario_project(tmp_path)
    assert (first, second) == ("2.1-4", "2.5-8")
    mp = tmp_path / "transcripts" / "v.map.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    u = m["units"][0]
    m["units"] = [dict(u, id=1, refs="2.1-4", summary="первая"), dict(u, id=2, refs="2.5-8", summary="вторая")]
    mp.write_text(json.dumps(m), encoding="utf-8")
    cfg = tmp_path / "config" / "r0.yaml"
    text = cfg.read_text(encoding="utf-8")
    for key, val in (("close_by", close_by), ("select", select)):
        assert len(re.findall(rf"(?m)^  {key}: \w+", text)) == 1
        text = re.sub(rf"(?m)^  {key}: \w+", f"  {key}: {val}", text)
    cfg.write_text(text, encoding="utf-8")

    class Fake:
        model_id = "fake:scenarist"

        def complete(self, messages, temperature=0.0):
            return ("M | 2.4-5 | t: Обе мысли | why: a\nM | 2.1-3 | t: Первая мысль | why: b\n"
                    "M | 2.6-8 | t: Вторая мысль | why: c")
    return cli, Fake


def _run(tmp_path, capsys, close_by, select):
    cli, Fake = _project(tmp_path, close_by, select)
    out = tmp_path / "reviews" / f"v_{close_by}_{select}.txt"
    rc = cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False, scenario=True,
                         scenario_provider=Fake(), out=str(out))
    con = capsys.readouterr().out
    body = [ln.split(" | ")[1] for ln in out.read_text(encoding="utf-8").splitlines() if re.match(r"^M\d* \d", ln)]
    return rc, body, con


def test_units_greedy_is_as_before(tmp_path, capsys):
    rc, body, con = _run(tmp_path, capsys, "units", "greedy")
    assert rc == 0 and body == ["2.4-5"]                       # R1 blocks both: they share its thoughts
    assert "отбор: глобальный" not in con and "общие мысли с M1" in con


def test_units_global_takes_the_two_that_do_not_clash(tmp_path, capsys):
    rc, body, con = _run(tmp_path, capsys, "units", "global")
    assert rc == 0 and sorted(body) == ["2.1-3", "2.6-8"]
    assert "отбор: глобальный — 2 без пересечений" in con and "по порядку было бы 1" in con


def test_sound_keeps_reels_that_share_a_thought_but_no_sentence(tmp_path, capsys):
    rc, body, con = _run(tmp_path, capsys, "sound", "greedy")
    assert rc == 0 and sorted(body) == ["2.1-3", "2.4-5", "2.6-8"]  # the «Алгоритм» case: same thought, other sentences
    assert "≈" not in con and "учёт кандидатов" not in con


def test_defaults_are_the_behaviour_before_m205():
    from autoreels import __main__ as cli
    from autoreels.core.config import AutocutConfig
    for ac in (AutocutConfig(), cli.load_r0_config("config/r0.yaml").autocut):
        assert ac.close_by == "units" and ac.select == "greedy" and ac.close_share_max == 0.0
