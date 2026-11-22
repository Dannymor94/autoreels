"""M56: montage lines proposed from the map (cloud/autocut.py, arl autocut)."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from autoreels.cloud import autocut as ac
from autoreels.cloud.autocut import AutoParams, Proposal, build_clip, eligible, leans_on, propose
from tests.test_m231_trace import U as _a2_U, _fx7l_units, _montage_project


def _m232_fx5():
    """Committed, entirely synthetic 25→23-second M232-A1 regression case."""
    data = json.loads((Path(__file__).parent / "fixtures/m23x/fx5_context_min.json").read_text(encoding="utf-8"))

    def sentences(refs):
        if refs == "1.1-2":
            return [tuple(row) for row in data["sentences"]]
        return [tuple(row) for row in data["sentences"] if row[0] == refs]

    return data["unit"], sentences, data["min_sec"]


def test_m232_a1_fx5_fail_before_25_to_23_and_guard_on():
    """The old helper publishes 23 seconds; A1 refuses the unsafe drop."""
    from dataclasses import replace
    from autoreels.cloud.autocut import context_start

    unit, sentences, minimum = _m232_fx5()
    p = AutoParams(clips=1, min_sec=minimum, target_sec=40, max_sec=80,
                   loop=False, prune=False, context_start=True)
    original, notes, why = context_start([unit], {1: unit}, p, sentences, seed_id=1)
    assert why is None and original and original[0]["refs"] == "1.2"
    assert original[0]["t1"] - original[0]["t0"] == 23
    assert any("убрана фраза" in n for n in notes)
    assert [(pr.pieces, pr.seconds) for pr in propose([unit], p, sentences)] == [("1.2", 23.0)]

    protected = replace(p, fix_context_min_sec=True)
    no_start = []
    assert propose([unit], protected, sentences, no_start=no_start) == []
    assert len(no_start) == 1 and "второй момент" in no_start[0][1]
    # The same shortening is still legal when 23 seconds meets the configured minimum.
    legal = replace(protected, min_sec=23)
    assert [(pr.pieces, pr.seconds) for pr in propose([unit], legal, sentences)] == [("1.2", 23.0)]


def test_m232_a1_final_duration_guard_rejects_short_context_return(monkeypatch):
    """The S5 post-check also rejects an unexpected short return, even on rank retry."""
    from autoreels.cloud import autocut as ac

    unit, sentences, minimum = _m232_fx5()
    attempts = []

    def fake_context(clip, by_id, p, lookup, *, judge=None, **kwargs):
        attempts.append(judge)
        if judge is not None:
            return None, [], "модель против"
        return [{**clip[0], "refs": "1.2", "t0": 2.0}], [], None

    monkeypatch.setattr(ac, "context_start", fake_context)
    no_start = []
    trace = []
    p = AutoParams(clips=1, min_sec=minimum, target_sec=40, max_sec=80, loop=False,
                   prune=False, context_start=True, fix_context_min_sec=True, start_judge="rank")
    assert ac.propose([unit], p, sentences, no_start=no_start,
                      judge=lambda *_: (False, "нет"), trace=trace) == []
    assert len(attempts) == 2 and attempts[0] is not None and attempts[1] is None
    assert no_start == [("1.1-2", "dur_below_min_sec")]
    assert [event["outcome"] for event in trace if event["event"] == "seed"] == ["start_fail"]


def test_m232_a1_blocked_drop_can_still_repair_with_previous_context():
    """A1 skips only the short drop; original backward-context repair remains available."""
    from dataclasses import replace

    unit, original_sentences, minimum = _m232_fx5()
    current = {**unit, "id": 2, "t0": 5.0, "t1": 30.0, "refs": "2.1-2"}
    prev = {**unit, "id": 1, "t0": 0.0, "t1": 5.0, "refs": "1.1",
            "role": "aside", "punch": 2, "summary": "Контекст перед тезисом"}

    def sentences(refs):
        if refs == "1.1":
            return [("1.1", 5.0, 5, True, "Есть важный урок для родителей.")]
        return [(ref.replace("1.", "2.", 1), sec, words, complete, text)
                for ref, sec, words, complete, text in original_sentences(refs.replace("2.", "1.", 1))]

    p = AutoParams(clips=1, min_sec=minimum, target_sec=40, max_sec=80, loop=False,
                   prune=False, context_start=True)
    assert [(pr.pieces, pr.seconds) for pr in propose([prev, current], p, sentences)] == [("2.2", 23.0)]
    rescued = propose([prev, current], replace(p, fix_context_min_sec=True), sentences)
    assert [(pr.pieces, pr.seconds) for pr in rescued] == [("1.1 2.1-2", 30.0)]
    assert any("контекст" in n and "#1" in n for n in rescued[0].notes)


def test_m232_a1_flag_defaults_off_and_is_exposed_in_config():
    from autoreels.core.config import AutocutConfig

    assert AutoParams().fix_context_min_sec is False
    assert AutocutConfig().fix_context_min_sec is False
    assert AutocutConfig.model_validate({"fix_context_min_sec": True}).fix_context_min_sec is True


def test_m232_a1_cli_wires_flag_with_no_provider(tmp_path, monkeypatch):
    from autoreels import __main__ as cli
    from autoreels.cloud import autocut as ac_mod
    from tests.test_m231_trace import _montage_project

    _montage_project(tmp_path)
    cfg = tmp_path / "config" / "r0.yaml"
    raw = cfg.read_text(encoding="utf-8")
    cfg.write_text(raw.replace("  context_start: ", "  fix_context_min_sec: true\n  context_start: "), encoding="utf-8")
    original_propose = ac_mod.propose
    observed = []

    def captured(units, params, *args, **kwargs):
        observed.append(params.fix_context_min_sec)
        return original_propose(units, params, *args, **kwargs)

    monkeypatch.setattr(ac_mod, "propose", captured)
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False, clips=2) == 0
    assert observed and all(observed)


def U(i, t0, dur, role, punch, refs, topic=1, standalone=True, refers=None, energy=50, summary="", similar=(),
      missing=False, filtered=""):
    return {"id": i, "t0": float(t0), "t1": float(t0 + dur), "role": role, "punch": punch, "refs": refs,
            "topic": topic, "standalone": standalone, "refers": refers, "voice": {"energy": energy},
            "summary": summary or f"мысль {i}", "similar": [list(x) for x in similar], "missing": missing,
            "filtered": filtered}


def _units():
    return [
        U(1, 0, 15, "aside", 1, "1.1-2"),
        U(2, 20, 15, "thesis", 4, "2.1-3", summary="маска защищает ребёнка"),
        U(3, 35, 20, "example", 3, "2.4-6", standalone=False, refers=2),
        U(4, 60, 12, "explanation", 2, "3.1-2"),
        U(5, 200, 15, "conclusion", 5, "9.1-2", standalone=False, refers=3, summary="маску можно снять"),
        U(6, 400, 10, "question", 4, "15.1", topic=2, summary="зачем нам маски"),
        U(7, 420, 25, "explanation", 3, "15.2-4", topic=2),
        U(8, 500, 20, "conclusion", 4, "17.1-3", topic=2),
        U(9, 600, 20, "thesis", 5, "x1.1-2", topic=1, filtered="tail"),
    ]


def test_eligibility_and_what_a_thought_leans_on():
    by = {u["id"]: u for u in _units()}
    p = AutoParams()
    assert not eligible(by[1], p) and not eligible(by[4], p) and not eligible(by[9], p)   # aside, weak, filtered
    assert eligible(by[9], AutoParams(use_filtered=True))
    assert leans_on(by[5], by) == [3, 2]                      # 5 → 3 → 2 (the «сноска» chain)
    assert leans_on(by[2], by) == []


def test_clip_takes_what_the_seed_leans_on_and_orders_by_source():
    units = _units()
    by = {u["id"]: u for u in units}
    clip = build_clip(by[5], units, by, AutoParams(target_sec=40))
    assert [u["id"] for u in clip] == [2, 3, 5]               # the payoff brings its chain, source order
    q = build_clip(by[8], units, by, AutoParams(target_sec=60))
    assert q[0]["id"] == 6 and q[-1]["id"] == 8                # the question opens, the payoff closes


def test_propose_lines_with_hook_title_and_caption():
    units = _units()

    def sentences(refs):
        # every sentence 3 s, 6 words, finished; 9.2 is 8 s (too long for a hook)
        out = []
        for piece in refs.split():
            b, _, r = piece.partition(".")
            a, _, z = r.partition("-")
            for k in range(int(a), int(z or a) + 1):
                out.append((f"{b}.{k}", 8.0 if f"{b}.{k}" == "9.2" else 3.0, 6, True))
        return out
    props = propose(units, AutoParams(clips=5, target_sec=40), sentences)
    assert len(props) == 2
    lines = {p.line(str(i)) for i, p in enumerate(props, 1)}
    a = next(p for p in props if 5 in p.units)
    assert a.pieces == "2.1-3 2.4-6 9.1-2" and a.hook == "9.1" and a.title == "маска защищает ребёнка"
    assert a.caption == "маску можно снять" and 40 <= a.score <= 95
    b = next(p for p in props if 6 in p.units)
    assert b.units[0] == 6 and b.hook in {"15.1", "17.1", "17.2", "17.3"}
    assert all(" | t: " in ln and ln.startswith("M") for ln in lines)
    assert all(9 not in p.units and 1 not in p.units for p in props)
    assert propose(units, AutoParams(min_sec=500)) == []


def test_cmd_autocut_writes_a_draft_that_applies(tmp_path, capsys):
    from autoreels import __main__ as cli
    from autoreels.cloud.edit import merge_group_sentences
    from autoreels.core.models import Manifest
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    cfg = tmp_path / "config" / "r0.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("  min_sec: 25 ", "  min_sec: 10 ").replace("  hook_llm: auto ", "  hook_llm: none ")
                   .replace("  short_variant: true ", "  short_variant: false "), encoding="utf-8")
    r0 = cli.load_r0_config(cfg)
    assert r0.autocut.min_sec == 10 and not r0.autocut.short_variant
    tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), tmp_path / "cache")
    _, kept, _ = cli._review_block_set(tx, r0, "lecture")

    def unit(i, blk, a, z, role, punch, **kw):
        s = merge_group_sentences([kept[blk - 1]], tx.words)
        return U(i, s[a - 1][0].t0, s[z - 1][-1].t1 - s[a - 1][0].t0, role, punch, f"{blk}.{a}-{z}", **kw)
    units = [unit(1, 2, 1, 3, "thesis", 4, summary="тезис про маски"), unit(2, 2, 4, 5, "example", 3),
             unit(3, 5, 1, 3, "conclusion", 5, summary="вывод про маски")]
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    (tmp_path / "transcripts" / "v.map.json").write_text(json.dumps(
        {"version": 1, "stem": "v", "source_sha256": "f" * 64, "units": units}), encoding="utf-8")
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache")) == 0
    out = capsys.readouterr().out
    draft = tmp_path / "reviews" / "v_auto_m56.txt"
    text = draft.read_text(encoding="utf-8")
    import re
    n = int(re.search(r"предложено сборок (\d+)", out).group(1))   # M120: 1 by montage, 2 by mixed (the defaults)
    assert "# fingerprint: " in text and "M1 " in text and "| t: тезис про маски" in text and n >= 1
    rc = cli._blocks_do_apply(str(draft), root=tmp_path, cache_dir=str(tmp_path / "cache"), labeler="auto")
    err = capsys.readouterr().err
    assert rc == 0, err[-1500:]
    man = Manifest.model_validate_json((tmp_path / "reviews" / "v.review.json").read_text())
    assert len(man.reels) == n and all(r.montage.startswith("M") for r in man.reels)
    assert "тезис про маски" in {r.title_overlay for r in man.reels}
    assert cli.cmd_autocut("nope", root=tmp_path) == 1


def test_cmd_autocut_replaces_a_proposal_that_fails_the_apply_checks(tmp_path, capsys):
    """M60: every proposal is run through --apply on its own; a failing one is commented with the reason
    and the next candidate takes its place."""
    from autoreels import __main__ as cli
    from autoreels.cloud.edit import merge_group_sentences
    from autoreels.core.models import Manifest
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    cfg = tmp_path / "config" / "r0.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("  min_sec: 25 ", "  min_sec: 10 ").replace("  hook_llm: auto ", "  hook_llm: none ")
                   .replace("  clips: 5\n", "  clips: 1\n").replace("  clips_every_min: ", "  clips_every_min: 0  # ")
                   .replace("  hookless_last: true ", "  hookless_last: false "),     # M60 alone (M107 puts «битая» last)
                   encoding="utf-8")
    r0 = cli.load_r0_config(cfg)
    tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), tmp_path / "cache")
    _, kept, _ = cli._review_block_set(tx, r0, "lecture")
    s2 = merge_group_sentences([kept[1]], tx.words)
    good = U(1, s2[0][0].t0, s2[4][-1].t1 - s2[0][0].t0, "thesis", 4, "2.1-5", summary="годная")
    bad = U(2, 3000.0, 40.0, "thesis", 5, "99.1-4", topic=2, summary="битая")     # no block 99
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    (tmp_path / "transcripts" / "v.map.json").write_text(json.dumps(
        {"version": 1, "stem": "v", "source_sha256": "f" * 64, "units": [good, bad]}), encoding="utf-8")
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache")) == 0
    out = capsys.readouterr().out
    text = (tmp_path / "reviews" / "v_auto_m56.txt").read_text(encoding="utf-8")
    assert "M1 " in text and "| t: годная" in text
    assert "#! M " in text and "99.1-4" in text and "not in the review numbering" in text
    assert "не прошли проверку: 1" in out
    assert not (tmp_path / "reviews" / "v.review.json").exists()          # checks ran in a scratch root


def test_no_two_proposals_share_their_payoff():
    """M61: IMG_6848 M1 and M4 both ended on the same «Эмпатия важнее алгоритма» thought."""
    units = [U(1, 0, 20, "thesis", 4, "1.1-3"), U(2, 25, 20, "example", 4, "1.4-6"),
             U(3, 300, 15, "conclusion", 5, "5.1-2"),
             U(4, 600, 20, "thesis", 5, "9.1-3"), U(5, 625, 20, "metaphor", 4, "9.4-6")]
    props = propose(units, AutoParams(clips=5, target_sec=40, overlap_max=0.9))
    lasts = [p.units[-1] for p in props]
    assert len(lasts) == len(set(lasts)) and len(props) >= 2


def test_cmd_autocut_falls_back_to_the_next_hook(tmp_path, capsys, monkeypatch):
    """M61: when the plan skips the hook (no sound of its own), the next candidate is tried."""
    from autoreels import __main__ as cli
    from autoreels.cloud.edit import merge_group_sentences
    from autoreels.core.models import Manifest
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    cfg = tmp_path / "config" / "r0.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("  min_sec: 25 ", "  min_sec: 10 ").replace("  hook_llm: auto ", "  hook_llm: none ")
                   .replace("  clips: 5\n", "  clips: 1\n").replace("  clips_every_min: ", "  clips_every_min: 0  # ").replace("  hook_min_words: 4 ", "  hook_min_words: 2 ")
                   .replace("  hook_teaser: true ", "  hook_teaser: false "),      # M61 alone (M83: any sentence)
                   encoding="utf-8")
    r0 = cli.load_r0_config(cfg)
    tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), tmp_path / "cache")
    _, kept, _ = cli._review_block_set(tx, r0, "lecture")
    s2 = merge_group_sentences([kept[1]], tx.words)
    unit = U(1, s2[0][0].t0, s2[4][-1].t1 - s2[0][0].t0, "conclusion", 5, "2.1-5", summary="вывод")
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    (tmp_path / "transcripts" / "v.map.json").write_text(json.dumps(
        {"version": 1, "stem": "v", "source_sha256": "f" * 64, "units": [unit]}), encoding="utf-8")
    seen = []

    def fake_check(head, line, root, cache_dir):
        seen.append(line)
        return (None, "    ! h:2.1 … — cold open skipped") if len(seen) == 1 else (None, "")
    monkeypatch.setattr(cli, "_autocut_check", fake_check)
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache")) == 0
    text = (tmp_path / "reviews" / "v_auto_m56.txt").read_text(encoding="utf-8")
    first = seen[0].split("h:")[1].split(" ")[0]
    second = seen[1].split("h:")[1].split(" ")[0] if "h:" in seen[1] else None
    assert len(seen) == 2 and second != first
    assert f"крючок h:{first} без своего звука" in text


# ── M65: hooks by interest, question → answer loop, shorter clips, speed by speech rate ─────────

def test_hook_score_prefers_questions_contrast_numbers_and_you():
    from autoreels.cloud.autocut import hook_score
    strong = hook_score("А вы знаете, почему 80% людей ошибаются?", 3.2)
    contrast = hook_score("Но на самом деле страх защищает нас.", 3.0)
    flat = hook_score("Мы говорили о разных вещах.", 3.0)
    leaning = hook_score("И это так.", 1.2)
    assert strong > contrast > flat > leaning
    assert hook_score("Мысль.", 3.0, {"punch": 5, "voice": {"energy": 100}}) > hook_score("Мысль.", 3.0)


def _rows(text_by_ref):
    def sentences(refs):
        out = []
        for piece in refs.split():
            b, _, r = piece.partition(".")
            a, _, z = r.partition("-")
            for k in range(int(a), int(z or a) + 1):
                ref = f"{b}.{k}"
                out.append((ref, 3.0, 6, True, text_by_ref.get(ref, "Обычная фраза про жизнь сегодня.")))
        return out
    return sentences


def test_loop_question_opens_and_the_hook_teases_the_answer():
    from autoreels.cloud.autocut import AutoParams, propose
    units = [U(1, 0, 15, "thesis", 4, "1.1-2", summary="маска защищает"),
             U(2, 20, 15, "example", 3, "1.3-4"),
             U(3, 40, 12, "conclusion", 5, "2.1-2", standalone=False, refers=2, summary="маску можно снять"),
             U(4, 900, 8, "question", 3, "30.1", summary="зачем нам маски")]          # far later, same topic
    sent = _rows({"2.1": "Но на самом деле маску можно снять!", "30.1": "Зачем нам вообще маски?"})
    (pr,) = propose(units, AutoParams(clips=1, target_sec=40, max_sec=80), sent)
    assert pr.units[0] == 4 and pr.units[-1] == 3
    assert any("вопрос-петля" in n for n in pr.notes)
    assert pr.hook == "2.1" and "30.1" not in pr.hooks          # the cold open teases the answer
    plain = propose(units, AutoParams(clips=1, target_sec=40, max_sec=80, loop=False), sent)[0]
    assert pr.score > plain.score


def test_prune_drops_the_weakest_middle_thought():
    from autoreels.cloud.autocut import AutoParams, _prune
    units = [U(1, 0, 15, "thesis", 4, "1.1-2"), U(2, 15, 20, "explanation", 3, "1.3-5", energy=10),
             U(3, 35, 20, "example", 4, "1.6-8", energy=90), U(4, 55, 12, "conclusion", 5, "2.1-2")]
    by = {u["id"]: u for u in units}
    clip, dropped = _prune(list(units), by, AutoParams(target_sec=45, prune_slack=2, min_sec=25))
    assert dropped == [2] and [u["id"] for u in clip] == [1, 3, 4]
    units[3] = U(4, 55, 12, "conclusion", 5, "2.1-2", standalone=False, refers=2)      # the payoff leans on #2
    by = {u["id"]: u for u in units}
    clip, dropped = _prune(list(units), by, AutoParams(target_sec=45, prune_slack=2, min_sec=25))
    assert dropped == [3] and [u["id"] for u in clip] == [1, 2, 4]


def test_speed_follows_the_speech_rate():
    from autoreels.cloud.autocut import AutoParams, _speed
    slow = [dict(U(1, 0, 20, "thesis", 4, "1.1"), voice={"energy": 50, "rate": 2.0})]
    mid = [dict(U(1, 0, 20, "thesis", 4, "1.1"), voice={"energy": 50, "rate": 2.5})]
    fast = [dict(U(1, 0, 20, "thesis", 4, "1.1"), voice={"energy": 50, "rate": 3.2})]
    p = AutoParams()
    assert (_speed(slow, p), _speed(mid, p), _speed(fast, p)) == (1.08, 1.05, None)
    from autoreels.cloud.autocut import Proposal
    assert Proposal(units=[1], pieces="1.1", hook=None, title="", caption="", score=80, seconds=20,
                    speed=1.08).line("1").startswith("M1 80@1.08 | 1.1")


def test_the_model_ranks_only_the_codes_candidates():
    from autoreels.cloud.autocut import Proposal, rank_hooks
    pr = Proposal(units=[1], pieces="1.1-3", hook="1.1", title="t", caption="", score=80, seconds=30,
                  hooks=["1.1", "1.2", "1.3"], hook_texts={"1.1": ("a", 1), "1.2": ("b", 1), "1.3": ("c", 1)})

    class P:
        def __init__(self, answers):
            self.answers = list(answers)
        def complete(self, msgs, temperature=0.0):
            return self.answers.pop(0)
    assert rank_hooks(pr, P(['{"best": 2, "why": "интрига"}']), log=lambda m: None)
    assert pr.hook == "1.2" and pr.hooks[0] == "1.2" and any("интрига" in n for n in pr.notes)
    pr2 = Proposal(units=[1], pieces="1.1-3", hook="1.1", title="t", caption="", score=80, seconds=30,
                   hooks=["1.1", "1.2"], hook_texts={})
    assert not rank_hooks(pr2, P(['{"best": 7}', 'нет']), log=lambda m: None)   # outside → retried → code's order
    assert pr2.hook == "1.1"


def test_accepted_clips_never_share_an_opener_a_title_or_a_thought():
    """M68: 11h42 — two of four reels opened on «Вы не сломаны, просто не изучали себя»; Pxl 112938952 —
    M3 and M5 both carried 33.7 34.1-3. A viewer scrolling one source must not see a reel twice."""
    from autoreels.cloud.autocut import Proposal, too_close
    mk = lambda units, opener, title: Proposal(units=units, pieces="", hook=None, title=title, caption="",
                                                score=70, seconds=40.0, opener=opener)
    a = mk([1, 2, 3], 1, "Вы не сломаны")
    assert too_close(mk([1, 7, 8], 1, "Другое"), [a]) == "то же начало, что у M1 (#1)"
    assert too_close(mk([9, 7, 8], 9, "Вы не сломаны"), [a]) == "тот же заголовок, что у M1"
    assert too_close(mk([9, 3, 8], 9, "Другое"), [a]) == "общие мысли с M1: #3"
    assert too_close(mk([9, 3, 8], 9, "Другое"), [a], max_shared=1) is None
    assert too_close(mk([9, 10, 8], 9, "Другое"), [a]) is None


def test_propose_records_the_opener_thought():
    from autoreels.cloud.autocut import AutoParams, propose
    out = propose(_units(), AutoParams(min_sec=20, target_sec=40, max_sec=90, loop=False))
    assert out and all(o.opener in o.units for o in out)



def _rows70(refs):
    out = []
    for piece in refs.split():
        b, _, r = piece.partition(".")
        a, _, z = r.partition("-")
        for k in range(int(a), int(z or a) + 1):
            out.append((f"{b}.{k}", 3.0, 6, True, f"Фраза {b}.{k} про маски и детей."))
    return out


def test_headline_is_used_only_when_it_stays_in_the_clip_words():
    """M70: the plate t: becomes a curiosity headline from the model — but never words the clip does not say."""
    from autoreels.cloud.autocut import Proposal, grounded_title, headline
    from tests.test_label import Scripted
    text = "Маска защищает ребёнка. Почему мы прячемся за маской, когда страшно? Маску можно снять."
    assert grounded_title("Почему мы прячемся за маской?", text) is None
    assert grounded_title("Как заработать миллион на крипте", text).startswith("слова не из ролика")
    assert grounded_title("3 причины прятаться", text) == "число 3, которого нет в ролике"
    assert grounded_title("Маска " * 12, text).startswith("длиннее") or grounded_title("Маска " * 12, text).startswith("слов")
    mk = lambda: Proposal(units=[1], pieces="2.1-3", hook=None, title="маска защищает ребёнка", caption="",
                          score=70, seconds=40)
    pr = mk()
    assert headline(pr, Scripted([{"titles": ["Почему мы прячемся за маской?"]}]), text, log=lambda m: None)
    assert pr.title == "Почему мы прячемся за маской?" and "заголовок-крючок" in pr.notes[-1]
    pr = mk()                                   # invented → the summary stays
    assert not headline(pr, Scripted([{"titles": ["Секрет богатства", "Тайна миллионеров"]}]), text,
                        log=lambda m: None)
    assert pr.title == "маска защищает ребёнка" and "отброшены" in pr.notes[-1]


def test_one_algorithm_picks_the_headline_rules_then_the_attention_score():
    """M71 (owner: «вкус — это вкус; нужен унифицированный алгоритм»): three proposals, hard rules drop the
    speaker-centric, the lecture plan and the off-topic ones, then the same attention score as the cold open
    picks; the current plate competes, so a weaker proposal never replaces it."""
    from autoreels.cloud.autocut import Proposal, headline, title_problem, title_score
    from tests.test_label import Scripted
    text = ("Мой лучший отдых — благодарность людей. Работа по душе не приводит к выгоранию. Почему так? "
            "Сначала понимание себя, потом инструменты. Вы выгораете, когда работаете не на себя.")
    core = "Работа по душе не приводит к выгоранию."
    assert title_problem("Мой лучший отдых — благодарность людей", text, core).startswith("про говорящего")
    assert title_problem("Сначала понимание себя, потом инструменты", text, core).startswith("план лекции")
    assert title_problem("Благодарность людей", text, core) == "не про начало и не про вывод ролика"
    assert title_problem("Почему работа по душе не выжигает?", text, core) is None
    assert title_score("Почему работа по душе не выжигает?") > title_score("Работа по душе не приводит к выгоранию.")
    assert title_score("Почему " + "очень " * 9 + "долго?") < title_score("Почему работа не выжигает?")   # > 40 chars
    pr = Proposal(units=[1], pieces="", hook=None, title="Работа по душе не приводит к выгоранию.", caption="",
                  score=70, seconds=40)
    ans = {"titles": ["Мой лучший отдых — благодарность людей", "Почему работа по душе не выжигает?",
                      "Работа по душе против выгорания"]}
    assert headline(pr, Scripted([ans]), text, core_text=core, log=lambda m: None)
    assert pr.title == "Почему работа по душе не выжигает?"
    assert "про говорящего" in pr.notes[-1]                                   # the dropped one is named
    weak = Proposal(units=[1], pieces="", hook=None, title="Почему вы выгораете на работе?", caption="",
                    score=70, seconds=40)
    assert not headline(weak, Scripted([{"titles": ["Работа по душе"]}]), text, core_text=core, log=lambda m: None)
    assert weak.title == "Почему вы выгораете на работе?" and "варианты слабее" in weak.notes[-1]


def test_seams_are_judged_and_a_jarring_clip_is_marked():
    """M70: pieces from far apart — the model says whether B follows A; every seam must get an answer."""
    from autoreels.cloud.autocut import Proposal, check_seams, seam_pairs
    from tests.test_label import Scripted
    by = {u["id"]: u for u in _units()}
    pr = Proposal(units=[6, 2, 3, 5], pieces="15.1 2.1-3 2.4-6 9.1-2", hook=None, title="t", caption="",
                  score=70, seconds=60)
    pairs = seam_pairs(pr, by, _rows70)
    assert [(a[:9], b[:9]) for a, b in pairs] == [("Фраза 15.", "Фраза 2.1"), ("Фраза 2.6", "Фраза 9.1")]   # 2→3 adjacent
    ans = {"seams": [{"n": 1, "ok": True, "why": ""}, {"n": 2, "ok": False, "why": "«это» без предмета"}]}
    assert check_seams(pr, pairs, Scripted([ans]), log=lambda m: None) == 1
    assert pr.bad_seams == 1 and "стык 2 рвётся" in pr.notes[-1] and "«это» без предмета" in pr.notes[-1]
    pr2 = Proposal(units=[6, 2], pieces="", hook=None, title="t", caption="", score=70, seconds=30)
    half = {"seams": [{"n": 1, "ok": True}, {"n": 2, "ok": True}]}
    assert check_seams(pr2, pairs, Scripted([{"seams": [{"n": 1, "ok": True}]}, {"seams": []}]),
                       log=lambda m: None) is None and pr2.bad_seams is None        # incomplete → not judged
    assert check_seams(pr2, pairs, Scripted([half]), log=lambda m: None) == 0


def test_short_variant_drops_the_weakest_middle_and_keeps_opener_and_payoff():
    from autoreels.cloud.autocut import AutoParams, Proposal, short_variant
    units = _units() + [U(10, 70, 14, "example", 3, "3.3-5"), U(11, 90, 14, "metaphor", 4, "4.1-3")]
    by = {u["id"]: u for u in units}
    pr = Proposal(units=[2, 3, 10, 11, 5], pieces="2.1-3 2.4-6 3.3-5 4.1-3 9.1-2", hook="2.2", title="t",
                  caption="d", score=80, seconds=78, opener=2)
    v = short_variant(pr, by, AutoParams(), _rows70, short_sec=50, short_min_sec=15, label=1)
    assert v is not None and v.units[0] == 2 and v.units[-1] == 5 and v.seconds <= 55
    assert v.variant_of == 1 and v.hook == "2.2" and "короткая версия M1" in v.notes[0]
    assert short_variant(pr, by, AutoParams(), _rows70, short_sec=5, short_min_sec=4, label=1) is None


def test_headline_score_prefers_the_specific_over_the_generic_and_varies_within_a_source():
    """M73 (M71 report): the score rewarded «?» and «вы» so much that generic questions won — «Вы понимаете,
    кто вы?» replaced «Эмпатия исцеляет лучше любого алгоритма», five of six IMG_6848 plates became «Вы…?», one
    said «тебя». Now: specific to the clip (shared content words with its opening/conclusion), generic and
    «ты» lose points, and a shape already used in the source costs a point."""
    from autoreels.cloud.autocut import title_form, title_score
    core = "Эмпатия важнее алгоритма для исцеления. Человеку нужна эмпатия."
    assert title_score("Эмпатия исцеляет лучше любого алгоритма", core) > title_score("Вы понимаете, кто вы?", core)
    core2 = "Какие жизненные ценности ты можешь назвать?"
    assert title_score("Какие жизненные ценности у вас?", core2) > title_score("Какие жизненные ценности у тебя?", core2)
    core3 = "Вся жизнь была компенсацией. Взросление — это осознание."
    q, st = "Вся ваша жизнь была компенсацией?", "Вся ваша жизнь была компенсацией"
    assert title_score(q, core3) > title_score(st, core3)                       # alone: the question
    assert title_score(st, core3, ["question", "question"]) > title_score(q, core3, ["question", "question"])
    assert title_form(q) == "question" and title_form(st) == "statement"


# ── M74: starts that give context ─────────────────────────────────────────────────────────────────

def _rows74(text_by_ref):
    def sentences(refs):
        out = []
        for piece in refs.split():
            b, _, r = piece.partition(".")
            a, _, z = r.partition("-")
            for k in range(int(a), int(z or a) + 1):
                ref = f"{b}.{k}"
                text = text_by_ref.get(ref, f"Обычная законченная фраза номер {k} про жизнь.")
                out.append((ref, 3.0, len(text.split()), True, text))
        return out
    return sentences


_P74 = AutoParams(clips=1, min_sec=20, target_sec=40, max_sec=80, loop=False, prune=False, context_start=True)


def test_back_reference_finds_what_leans_on_the_cut():
    """M74 (owner: «и второй момент, как я уже говорил, не делай другим то…» — мало контекста)."""
    from autoreels.cloud.autocut import back_reference
    assert back_reference("И второй момент, как я уже говорил, не делай другим то, чего не желаешь себе.")
    assert back_reference("Во-вторых, дети это видят.") == "«во вторых»"
    assert back_reference("Поэтому это важно.") == "«поэтому…»"
    assert back_reference("Это нормально?") == "«это…»"
    assert back_reference("Подожди, подожди, а что я сейчас чувствую?") is None
    assert back_reference("А что я сейчас чувствую?") is None             # a question may open with «А…»
    assert back_reference("Эмпатия лечит лучше любого алгоритма.") is None


def test_a_short_leaning_first_sentence_is_dropped():
    units = [U(1, 0, 30, "thesis", 5, "1.1-3"), U(2, 30, 10, "conclusion", 4, "1.4-5")]
    sent = _rows74({"1.1": "И второй момент.", "1.2": "Дети копируют родителей во всём."})
    (pr,) = propose(units, _P74, sent)
    assert pr.pieces == "1.2-3 1.4-5" and pr.unit_refs == {1: "1.2-3"}
    assert any("убрана фраза «И второй момент.»" in n for n in pr.notes)
    assert any(n.startswith("начало: «Дети копируют") for n in pr.notes)
    off = propose(units, AutoParams(clips=1, min_sec=20, target_sec=40, max_sec=80, loop=False, prune=False), sent)
    assert off[0].pieces == "1.1-3 1.4-5" and not any(n.startswith("начало") for n in off[0].notes)


def test_the_thought_right_before_is_added_as_context():
    units = [U(1, 0, 10, "aside", 2, "1.1-2"), U(2, 10, 25, "thesis", 5, "2.1-3"),
             U(3, 35, 10, "conclusion", 4, "2.4")]
    sent = _rows74({"2.1": "Как я уже говорил, не делай другим того, чего не желаешь себе.",
                    "1.1": "Есть два правила этики."})
    (pr,) = propose(units, _P74, sent)
    assert pr.units == [1, 2, 3] and pr.pieces.startswith("1.1-2 2.1-3")
    assert any("добавлена мысль #1" in n and "контекст" in n for n in pr.notes)


def test_a_clip_with_no_standing_start_is_not_proposed():
    units = [U(1, 0, 30, "thesis", 5, "1.1-3"), U(2, 30, 10, "conclusion", 4, "1.4")]
    sent = _rows74({"1.1": "Поэтому дети копируют нас во всём, что мы делаем."})
    no_start: list = []
    assert propose(units, _P74, sent, no_start=no_start) == []
    assert no_start and "ссылка назад «поэтому…»" in no_start[0][1]
    assert len(propose(units, AutoParams(clips=1, min_sec=20, target_sec=40, max_sec=80, loop=False,
                                         prune=False), sent)) == 1           # flag off = as before


def test_a_cold_open_that_points_back_loses_to_one_that_stands():
    units = [U(1, 0, 30, "thesis", 5, "1.1-3")]
    sent = _rows74({"1.1": "Мы боимся отказа с детства.", "1.2": "Почему мы боимся отказа, как я уже говорил?"})
    p = AutoParams(clips=1, min_sec=20, target_sec=40, max_sec=80, loop=False, prune=False)
    from dataclasses import replace
    assert propose(units, p, sent)[0].hook == "1.2"                          # a question wins …
    assert propose(units, replace(p, context_start=True), sent)[0].hook != "1.2"   # … unless it points back


def test_context_plate_names_the_subject_instead_of_a_second_hook():
    """M74: the hook pulls; the plate, shown when the body starts, says what the clip is about."""
    from autoreels.cloud.autocut import Proposal, headline, plate_score
    from tests.test_label import Scripted
    core = "Мы боимся отказа с детства. Отказ — это не приговор."
    assert plate_score("Почему мы боимся отказа", core) > plate_score("Вы готовы к этому?", core)
    assert plate_score("Отказ: откуда страх", core) > plate_score("Страх", core)
    text = core + " Почему так происходит? Вы готовы к этому?"
    pr = Proposal(units=[1], pieces="", hook=None, title="мысль 1", caption="", score=70, seconds=40)
    sc = Scripted([{"titles": ["Вы готовы к этому?", "Почему мы боимся отказа", "Отказ — не приговор"]}])
    assert headline(pr, sc, text, core_text=core, log=lambda m: None, mode="context")
    assert pr.title in {"Почему мы боимся отказа", "Отказ — не приговор"} and "плашка-контекст" in pr.notes[-1]
    assert "what the clip is about" in sc.calls[0][0]["content"]


# ── M75: a start is not a fragment; the model judges what rules cannot see; a pause after the hook ─────

_P75 = AutoParams(clips=1, min_sec=20, target_sec=40, max_sec=80, loop=False, prune=False, context_start=True,
                  context_min_words=4)


def test_stands_alone_rules_then_the_model():
    """M75 (M74 report): «Уйти.» and «Контролер, да, допустим.» passed as starts; «Хоть это, как говорят психологи…»
    too — the rules see the first word only."""
    from autoreels.cloud.autocut import stands_alone
    assert stands_alone("Уйти.", "", _P75) == "обрывок (1 сл.)"
    assert stands_alone("Контролер, да, допустим.", "", _P75) == "обрывок (3 сл.)"
    assert stands_alone("Как вы отдыхаете?", "", _P75) is None             # a short question is a fine start
    assert stands_alone("Уйти.", "", AutoParams(context_start=True)) is None    # min words off = M74
    no = lambda t, f, c="": (False, "«это» без предмета")
    yes = lambda t, f, c="": (True, "")
    silent = lambda t, f, c="": None
    hoth = "Хоть это, как говорят психологи, бывает полезно."
    assert stands_alone(hoth, "", _P75) is None
    assert stands_alone(hoth, "", _P75, no) == "не годится в начало (модель: «это» без предмета)"
    assert stands_alone(hoth, "", _P75, yes) is None and stands_alone(hoth, "", _P75, silent) is None
    assert stands_alone("Поэтому так.", "", _P75, yes).startswith("ссылка назад")     # rules first, no call needed


def test_a_question_is_not_cut_from_its_answer():
    """M75: Pxl M2 — «То есть, а из чего?» was dropped and left «Из чувства вины, из чувства стыда.» alone."""
    units = [U(1, 0, 10, "thesis", 2, "1.1-2"), U(2, 10, 30, "thesis", 5, "2.1-3"), U(3, 40, 10, "conclusion", 4, "2.4")]
    sent = _rows74({"2.1": "То есть, а из чего?", "2.2": "Из чувства вины, из чувства стыда.",
                    "1.1": "Манипуляция строится на наших чувствах."})
    (pr,) = propose(units, _P75, sent)
    assert pr.units[0] == 1 and pr.pieces.startswith("1.1-2 2.1-3")            # context added, question kept
    assert not any("убрана фраза" in n for n in pr.notes)


def test_a_fragment_is_not_context_and_the_model_can_veto_a_start():
    units = [U(1, 0, 3, "aside", 2, "1.1"), U(2, 3, 30, "thesis", 5, "2.1-3"), U(3, 33, 10, "conclusion", 4, "2.4")]
    sent = _rows74({"1.1": "Уйти.", "2.1": "Но вы выбираете в стрессовой ситуации привычное."})
    no_start: list = []
    assert propose(units, _P75, sent, no_start=no_start) == []                 # «Уйти.» is no context
    assert "ссылка назад «но…»" in no_start[0][1]
    units2 = [U(1, 0, 10, "thesis", 2, "1.1-2"), U(2, 10, 30, "thesis", 5, "2.1-3"), U(3, 40, 10, "conclusion", 4, "2.4")]
    sent2 = _rows74({"2.1": "Хоть это, как говорят психологи, бывает полезно.",
                     "1.1": "Обратная связь помогает взрослеть."})
    calls = []

    def judge(text, following, core=""):
        calls.append(text)
        return (not text.startswith("Хоть это"), "«это» без предмета")
    (pr,) = propose(units2, _P75, sent2, judge=judge)
    assert pr.units[0] == 1 and any("модель: «это» без предмета" in n for n in pr.notes)
    assert calls[0].startswith("Хоть это") and "Обратная связь помогает взрослеть." in calls


def test_make_judge_caches_retries_and_gives_none_without_an_answer():
    from autoreels.cloud.autocut import make_judge
    from tests.test_label import Scripted
    sc = Scripted([{"ok": False, "why": "обрывок"}])
    j = make_judge(sc, log=lambda m: None)
    assert j("Уйти.", "") == (False, "обрывок") and j("Уйти.", "") == (False, "обрывок") and len(sc.calls) == 1
    j2 = make_judge(Scripted(["мусор", {"ok": True}]), log=lambda m: None)
    assert j2("Фраза.", "") == (True, "")                                       # retried once
    j3 = make_judge(Scripted(["мусор", "снова мусор"]), log=lambda m: None)
    assert j3("Фраза.", "") is None


def test_cmd_autocut_takes_a_top_hook_with_a_pause_after_it(tmp_path, capsys, monkeypatch):
    """M75: 6 of 15 M74 clips had no silence after the hook — the next of the model's top hooks that has one."""
    from autoreels import __main__ as cli
    from autoreels.cloud.edit import merge_group_sentences
    from autoreels.core.models import Manifest
    from tests.test_montage import _source
    assert cli._hook_air_after("    hook air  +0.46s after the hook, +0.00s before the body") == 0.46
    assert cli._hook_air_after("no air") is None
    mpath = _source(tmp_path)
    cfg = tmp_path / "config" / "r0.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("  min_sec: 25 ", "  min_sec: 10 ").replace("  hook_llm: auto ", "  hook_llm: none ")
                   .replace("  clips: 5\n", "  clips: 1\n").replace("  clips_every_min: ", "  clips_every_min: 0  # ").replace("  hook_min_words: 4 ", "  hook_min_words: 2 ")
                   .replace("  short_variant: true ", "  short_variant: false ")
                   .replace("  hook_teaser: true ", "  hook_teaser: false "), encoding="utf-8")   # M75 alone
    r0 = cli.load_r0_config(cfg)
    assert r0.autocut.hook_pause_sec == 0.25 and not r0.autocut.hook_teaser and r0.autocut.hook_pause_top == 3
    tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), tmp_path / "cache")
    _, kept, _ = cli._review_block_set(tx, r0, "lecture")
    s2 = merge_group_sentences([kept[1]], tx.words)
    unit = U(1, s2[0][0].t0, s2[4][-1].t1 - s2[0][0].t0, "conclusion", 5, "2.1-5", summary="вывод")
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    (tmp_path / "transcripts" / "v.map.json").write_text(json.dumps(
        {"version": 1, "stem": "v", "source_sha256": "f" * 64, "units": [unit]}), encoding="utf-8")
    seen = []

    def fake_check(head, line, root, cache_dir):
        seen.append(line.split("h:")[1].split(" ")[0])
        air = "0.00" if len(seen) < 3 else "0.40"                  # the third hook tried has a pause
        return None, f"    hook air  +{air}s after the hook, +0.00s before the body"
    monkeypatch.setattr(cli, "_autocut_check", fake_check)
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache")) == 0
    text = (tmp_path / "reviews" / "v_auto_m56.txt").read_text(encoding="utf-8")
    assert len(seen) == 3 and len(set(seen)) == 3
    assert f"| h:{seen[2]} " in text and f"крючок h:{seen[2]} — после него пауза +0.40 с" in text
    seen.clear()
    monkeypatch.setattr(cli, "_autocut_check", lambda h, line, r, c: (seen.append(line.split("h:")[1].split(" ")[0]),
                                                                    (None, "hook air  +0.00s after the hook"))[1])
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache")) == 0
    text = (tmp_path / "reviews" / "v_auto_m56.txt").read_text(encoding="utf-8")
    assert f"| h:{seen[0]} " in text and "паузы после него нет" in text          # none has one → the first stays


# ── M76: repair more starts before giving a clip up ───────────────────────────────────────────────

_P76 = AutoParams(clips=1, min_sec=20, target_sec=40, max_sec=80, loop=False, prune=False, context_start=True,
                  context_min_words=4, context_back=2, context_later=True, context_later_min_sec=8.0)


def test_two_thoughts_back_when_the_nearest_leans_too():
    """M76 (M75 report: 11h42 «Вот там прям в книжке…» had no start — the thought before it leaned back too)."""
    units = [U(1, 0, 6, "aside", 2, "1.1"), U(2, 6, 6, "aside", 2, "1.2"), U(3, 12, 30, "thesis", 5, "2.1-3"),
             U(4, 42, 10, "conclusion", 4, "2.4")]
    sent = _rows74({"2.1": "Вот там прям в книжке это описано подробно.", "1.2": "И мама так говорила всегда.",
                    "1.1": "Детские правила мы берём из семьи."})
    from dataclasses import replace
    assert propose(units, replace(_P76, context_back=1, context_later=False), sent) == []      # M75: no start
    (pr,) = propose(units, _P76, sent)
    assert pr.units[:2] == [1, 2] and any("добавлены мысли #1, #2" in n for n in pr.notes)


def test_a_later_sentence_of_the_first_thought_can_open_the_clip():
    units = [U(1, 0, 30, "thesis", 5, "1.1-5"), U(2, 30, 10, "conclusion", 4, "1.6")]
    sent = _rows74({"1.1": "Поэтому мама так говорила всегда и везде, где могла.",
                    "1.2": "И это тоже было про неё.",
                    "1.3": "Детские правила мы берём из семьи."})
    (pr,) = propose(units, _P76, sent)
    assert pr.pieces.startswith("1.3-5") and any("со фразы «Детские правила" in n and "убрано 2" in n for n in pr.notes)
    q = _rows74({"1.1": "Поэтому мама так говорила всегда и везде, где могла.",
                 "1.2": "А из чего это растёт?", "1.3": "Из страха остаться одной."})
    (pr2,) = propose(units, _P76, q)
    assert not pr2.pieces.startswith("1.3")                                     # an answer is not cut from its question



def test_plates_of_one_source_mix_shapes():
    """M77 (owner: «свобода — где-то текст, где-то вопрос»)."""
    from autoreels.cloud.autocut import plate_score
    core = "Мы боимся отказа с детства. Отказ — это не приговор."
    q, st = "Почему мы боимся отказа", "Отказ: откуда страх"
    q2 = "Почему мы боимся отказа?"
    assert plate_score(st, core, ["statement", "statement"]) < plate_score(st, core)
    assert plate_score(q2, core, ["statement", "statement"]) > plate_score(q2, core, ["question", "question"])



# ── M78: the model names the subject and says whether the start leads into the clip ───────────────

def test_judge_rejects_a_start_without_a_subject_or_off_the_clip_topic():
    """M78 (owner: IMG r03/r06 open on a phrase about the chair — «мало информативна»; M77 let «Конечно, перенос…»
    and «Допустим, папа приходил…» through): one answer, three checks — any «no» rejects."""
    from autoreels.cloud.autocut import make_judge
    from tests.test_label import Scripted
    sc = Scripted([{"subject": "кресло", "alone": True, "leads": False, "why": "про мебель"},
                   {"subject": "", "alone": True, "leads": True},
                   {"subject": "перенос", "alone": False, "leads": True, "why": "термин без пояснения"},
                   {"subject": "эмпатия в терапии", "alone": True, "leads": True}])
    j = make_judge(sc, log=lambda m: None)
    assert j("Садитесь в жёсткое кресло.", "", "эмпатия лечит") == (False, "про мебель")
    assert j("И вот так.", "", "эмпатия лечит")[0] is False
    assert j("Конечно, перенос — вещь неблагодарная.", "", "эмпатия лечит") == (False, "термин без пояснения")
    assert j("Эмпатия лечит лучше алгоритма.", "", "эмпатия лечит") == (True, "эмпатия в терапии")
    assert "The clip is about: эмпатия лечит" in sc.calls[0][1]["content"]


def test_the_clip_topic_reaches_the_judge_and_an_off_topic_start_goes():
    units = [U(1, 0, 10, "aside", 2, "1.1-2", summary="кресло в кабинете"),
             U(2, 10, 30, "thesis", 5, "2.1-3", summary="эмпатия лечит лучше алгоритма"),
             U(3, 40, 10, "conclusion", 4, "2.4", summary="человеку нужна эмпатия")]
    sent = _rows74({"1.1": "Я сажаю человека в жёсткое кресло специально.",
                    "2.1": "Эмпатия лечит лучше любого алгоритма."})
    seen = []

    def judge(text, following, core=""):
        seen.append(core)
        return (not text.startswith("Я сажаю"), "про мебель")
    from dataclasses import replace
    p = replace(_P75, min_sec=20)
    clip_with_chair = [units[0], units[1], units[2]]
    from autoreels.cloud.autocut import context_start
    by = {u["id"]: u for u in units}
    out, notes, why = context_start(clip_with_chair, by, p, sent, seed_id=2, judge=judge)
    assert why is None and out[0]["id"] == 2 and any("про мебель" in n for n in notes)
    assert "эмпатия лечит лучше алгоритма" in seen[0] and "человеку нужна эмпатия" in seen[0]


def test_titles_differing_only_by_yo_are_the_same_title():
    from autoreels.cloud.autocut import Proposal, too_close
    mk = lambda units, opener, title: Proposal(units=units, pieces="", hook=None, title=title, caption="",
                                                score=70, seconds=40.0, opener=opener)
    assert too_close(mk([5], 5, "Расположение и жесткий стул"), [mk([1], 1, "Расположение и жёсткий стул")]) \
        == "тот же заголовок, что у M1"


# ── M81: the cold open passes the same check as the start ─────────────────────────────────────────

def test_hooks_off_the_clip_topic_go_before_ranking_and_none_left_means_no_cold_open():
    """M81 (owner: IMG r03/r06 «начинаются с фразы про кресло — мало информативна»: the cold open is heard first)."""
    from autoreels.cloud.autocut import Proposal, judge_hooks
    mk = lambda: Proposal(units=[1], pieces="1.1-5", hook="1.1", title="t", caption="", score=80, seconds=40,
                          hooks=["1.1", "1.2", "1.3"],
                          hook_texts={"1.1": ("Я сажаю человека в жёсткое кресло.", 5), "1.2": ("Эмпатия лечит лучше алгоритма.", 4),
                                      "1.3": ("Это и есть ответ.", 3)})
    seen = []

    def judge(text, following, core=""):
        seen.append((text, core))
        if "кресло" in text:
            return (False, "про мебель")
        if text.startswith("Это"):
            return None                                   # no answer → kept
        return (True, "эмпатия")
    pr = mk()
    judge_hooks(pr, judge, "эмпатия лечит", log=lambda m: None)
    assert pr.hooks == ["1.2", "1.3"] and pr.hook == "1.2"
    assert any("про мебель" in n for n in pr.notes) and seen[0][1] == "эмпатия лечит"
    none = mk()
    judge_hooks(none, lambda t, f, c="": (False, "нет"), "x", log=lambda m: None)
    assert none.hooks == [] and none.hook is None and any("без крючка" in n for n in none.notes)
    assert none.line("1").startswith("M1 80 | 1.1-5 | t: t")          # no h: in the line → no cold open


def test_hook_judge_uses_its_own_prompt():
    from autoreels.cloud.autocut import HOOK_JUDGE_SYSTEM, make_judge
    from tests.test_label import Scripted
    sc = Scripted([{"subject": "кресло", "alone": True, "leads": False, "why": "про мебель"}])
    j = make_judge(sc, log=lambda m: None, system=HOOK_JUDGE_SYSTEM)
    assert j("Я сажаю человека в жёсткое кресло.", "", "эмпатия") == (False, "про мебель")
    assert "TEASER LINE" in sc.calls[0][0]["content"]


def test_teaser_cold_open_comes_from_the_second_half_and_is_replayed():
    """M83 (m80 hooks: every cold open was the clip's own first sentence — the body then went on from the
    second one, «В инстинкты.», «А второй момент…»): the cold open is a teaser from later, replayed (h:B.N!)."""
    from autoreels.cloud.autocut import AutoParams, propose
    units = [U(1, 0, 12, "thesis", 5, "1.1-2", summary="жизнь как компенсация"),
             U(2, 12, 12, "example", 4, "1.3-4", standalone=False, refers=1),
             U(3, 24, 12, "conclusion", 4, "2.1-2", standalone=False, refers=2, summary="маску можно снять")]
    sent = _rows({"1.1": "Вы знаете, почему вся ваша жизнь — компенсация?",
                  "2.1": "Но на самом деле маску можно снять!"})
    base = dict(clips=1, target_sec=36, max_sec=60, loop=False, prune=False)
    (old,) = propose(units, AutoParams(**base), sent)
    assert old.hook == "1.1" and "h:1.1 " in old.line("1") + " "      # off: the clip's own start, position rule
    (pr,) = propose(units, AutoParams(**base, hook_teaser=True), sent)
    assert pr.units == old.units
    assert "1.1" not in pr.hooks and "1.2" not in pr.hooks and "1.3" not in pr.hooks   # first half: no teaser
    assert pr.hook == "2.1" and "h:2.1! " in pr.line("1") + " "        # replayed in its place
    (none,) = propose(units, AutoParams(**base, hook_teaser=True, hook_teaser_pos=0.9), sent)
    assert none.hook is None and none.hooks == [] and "h:" not in none.line("1")
    assert any("сборка без крючка" in n for n in none.notes)


# ── M86: the cold open judged as a teaser, the judges' answers kept between runs, the owner's verdicts as examples ──
class _Answers:
    name = "scripted"

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def complete(self, messages, temperature=0.0):
        self.calls.append(messages)
        return self.answer


def test_judge_answers_are_kept_between_runs_and_the_teaser_is_asked_as_a_teaser():
    from autoreels.cloud.autocut import HOOK_TEASER_SYSTEM, make_judge
    ok = '{"subject": "поздно", "alone": true, "leads": true, "why": ""}'
    store: dict = {}
    p1 = _Answers(ok)
    j1 = make_judge(p1, log=lambda m: None, system=HOOK_TEASER_SYSTEM, label="Teaser line", store=store)
    assert j1("И никогда, ребятки, не поздно.", "", "взросление") == (True, "поздно")
    assert p1.calls[0][-1]["content"] == "Teaser line: «И никогда, ребятки, не поздно.»\nThe clip is about: взросление"
    p2 = _Answers('{"subject": "", "alone": false, "leads": false, "why": "другое"}')
    j2 = make_judge(p2, log=lambda m: None, system=HOOK_TEASER_SYSTEM, label="Teaser line", store=store)
    assert j2("И никогда, ребятки, не поздно.", "", "взросление") == (True, "поздно") and not p2.calls   # next run
    j3 = make_judge(p2, log=lambda m: None, label="Teaser line", store=store)       # another prompt → asked again
    assert j3("И никогда, ребятки, не поздно.", "", "взросление")[0] is False and len(p2.calls) == 1
    p4 = _Answers("нет ответа")
    j4 = make_judge(p4, log=lambda m: None, store=store)
    assert j4("Фраза.", "Дальше.") is None and len(store) == 2                      # no answer is not kept
    p5 = _Answers(ok)
    make_judge(p5, log=lambda m: None)("Фраза.", "Дальше.", "тема")               # the start judge's request as before
    assert p5.calls[0][-1]["content"] == "First sentence: «Фраза.»\nFollowing sentence: «Дальше.»\nThe clip is about: тема"
    assert "open question" in HOOK_TEASER_SYSTEM and "not a pointer" in HOOK_TEASER_SYSTEM


def test_owner_verdicts_become_examples_for_the_judges():
    from autoreels.cloud.autocut import owner_examples, with_examples
    rows = [
        {"kind": "montage", "verdict": "drop", "reasons": ["крючок"],
         "draft_notes": ["начало: «Я стараюсь делать так практику.»", "крючок: «Есть какой-то жесткий стул, а есть мягкое кресло.»"]},
        {"kind": "montage", "verdict": "ok", "reasons": [],
         "draft_notes": ["начало: «Как вы отдыхаете?»", "крючок: «Чтобы выжить в семье, нам приходится надевать маски.»"]},
        {"kind": "montage", "verdict": "fix", "reasons": ["начало", "темп"], "draft_notes": ["начало: «А второй момент — это то.»"]},
        {"kind": "line", "verdict": "drop", "reasons": ["крючок"], "draft_notes": ["крючок: «не сборка»"]},
        {"kind": "montage", "verdict": "drop", "reasons": ["плашка"], "draft_notes": ["крючок: «плашка виновата»"]},
    ]
    assert owner_examples(rows, "hook", 6) == (["Есть какой-то жесткий стул, а есть мягкое кресло."],
                                               ["Чтобы выжить в семье, нам приходится надевать маски."])
    assert owner_examples(rows, "start", 6) == (["А второй момент — это то."], ["Как вы отдыхаете?"])
    assert owner_examples(rows, "hook", 0) == ([], [])
    s = with_examples("SYS", ["плохо"], ["хорошо"], "teaser line")
    assert s.startswith("SYS\n") and "Rejected as a teaser line: «плохо»" in s and "Kept as a teaser line: «хорошо»" in s
    assert with_examples("SYS", [], [], "x") == "SYS"


def test_cmd_autocut_judges_every_candidate_it_reaches_and_writes_the_hook_text(tmp_path, monkeypatch):
    """M86: before, only pool[:clips+2] got the hook judge, ranking and headline — a later candidate that took a
    rejected one's place went out with unjudged hooks. Now each candidate is polished when the selection reaches
    it; the draft names the chosen cold open («крючок: «…»») for the owner's verdicts."""
    from autoreels import __main__ as cli
    from autoreels.cloud import autocut as ac_mod
    from autoreels.cloud.edit import merge_group_sentences
    from autoreels.core.models import Manifest
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    cfg = tmp_path / "config" / "r0.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("  min_sec: 25 ", "  min_sec: 10 ")
                   .replace("  clips: 5\n", "  clips: 2\n").replace("  clips_every_min: ", "  clips_every_min: 0  # ").replace("  hook_min_words: 4 ", "  hook_min_words: 2 "),
                   encoding="utf-8")
    r0 = cli.load_r0_config(cfg)
    tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), tmp_path / "cache")
    _, kept, _ = cli._review_block_set(tx, r0, "lecture")
    units = []
    for b in range(6):
        ss = merge_group_sentences([kept[b]], tx.words)
        units.append(U(b + 1, ss[0][0].t0, ss[-1][-1].t1 - ss[0][0].t0, "conclusion", 5, f"{b + 1}.1-{len(ss)}",
                       topic=b + 1, summary=f"вывод {b + 1}"))
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    (tmp_path / "transcripts" / "v.map.json").write_text(json.dumps(
        {"version": 1, "stem": "v", "source_sha256": "f" * 64, "units": units}), encoding="utf-8")
    polished, checked = [], []
    monkeypatch.setattr(ac_mod, "rank_hooks", lambda pr, prov, **k: polished.append(pr.pieces) or False)
    monkeypatch.setattr(ac_mod, "headline", lambda *a, **k: None)
    monkeypatch.setattr(ac_mod, "check_seams", lambda *a, **k: None)

    def fake_check(head, line, root, cache_dir):
        checked.append(line)
        return ("plan: x", "") if len(checked) <= 4 else (None, "")              # the first four fail
    monkeypatch.setattr(cli, "_autocut_check", fake_check)
    prov = _Answers('{"subject": "вывод", "alone": true, "leads": true, "why": ""}')
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), llm="local", provider=prov) == 0
    assert len(polished) == 6 == len(set(polished))                              # was 4 (pool[:clips + 2])
    text = (tmp_path / "reviews" / "v_auto_m56.txt").read_text(encoding="utf-8")
    lines = text.splitlines()
    hooked = [i for i, ln in enumerate(lines) if ln.startswith("M") and " h:" in ln]
    assert len([ln for ln in lines if ln.startswith("M")]) == 2 and hooked
    for i in hooked:
        assert lines[i - 1].startswith("#   крючок: «") and lines[i - 1].endswith("»")
    assert (tmp_path / "cache" / "autocut_judge.json").is_file()                # the judges' answers are kept


# ── M88: key words of the subtitles; M91: the payoff in the close shot ─────────────────────────────
def test_key_words_are_grounded_one_per_sentence_and_capped():
    from autoreels.cloud.autocut import pick_keywords
    rows = [("2.1", "Маска защищает ребёнка от боли."), ("2.2", "Это так."), ("3.1", "Её можно снять по-своему!")]
    prov = _Answers('{"keys": [{"s": 1, "word": "Маска"}, {"s": 1, "word": "боли"}, {"s": 2, "word": "это"},'
                    ' {"s": 3, "word": "по-своему!"}, {"s": 9, "word": "снять"}, {"s": 3, "word": "вечность"}]}')
    assert pick_keywords(rows, prov, n=4, log=lambda m: None) == [("2.1", "маска"), ("3.1", "по-своему")]
    assert "at most 4 sentences" in prov.calls[0][0]["content"] and prov.calls[0][-1]["content"].startswith(
        "Sentences:\n1. Маска защищает")
    assert pick_keywords(rows, _Answers('{"keys": [{"s": 3, "word": "снять"}, {"s": 1, "word": "ребёнка"}]}'),
                         n=1, log=lambda m: None) == [("3.1", "снять")]         # the cap keeps the first named
    assert pick_keywords(rows, _Answers("нет"), n=2, log=lambda m: None) == []
    assert pick_keywords([], _Answers("{}"), n=2) == [] and pick_keywords(rows, _Answers("{}"), n=0) == []


def test_line_writes_close_last_and_key_words():
    from autoreels.cloud.autocut import AutoParams, propose
    units = [U(1, 0, 12, "thesis", 5, "1.1-2", summary="жизнь как компенсация"),
             U(2, 12, 12, "example", 4, "1.3-4", standalone=False, refers=1),
             U(3, 24, 12, "conclusion", 4, "2.1-2", standalone=False, refers=2, summary="маску можно снять")]
    sent = _rows({"2.1": "Но на самом деле маску можно снять!"})
    base = dict(clips=1, target_sec=36, max_sec=60, loop=False, prune=False)
    (old,) = propose(units, AutoParams(**base), sent)
    assert old.close == [] and " c:" not in old.line("1")
    (pr,) = propose(units, AutoParams(**base, close_last=True, close_last_sec=3.0), sent)
    assert pr.close == ["2.2"]                                   # 3 s is enough: one sentence
    (pr2,) = propose(units, AutoParams(**base, close_last=True, close_last_sec=5.0), sent)
    assert pr2.close == ["2.1", "2.2"]                           # at most two
    pr2.keys = [("2.1", "маску"), ("1.3", "жизнь")]
    line = pr2.line("1")
    assert "| c:2.1,2.2 |" in line and "| k:2.1=маску;1.3=жизнь |" in line
    from autoreels.cloud.montage import parse_montage
    entries, errors = parse_montage(line)                        # the review parser takes it as written
    assert not errors and entries[0].close == ((2, 1), (2, 2)) and entries[0].keys == (((2, 1), ("маску",)),
                                                                                      ((1, 3), ("жизнь",)))


def test_teaser_pointing_back_is_left_out_by_the_code():
    """M92 (m86: the model passed «Это и есть доверие к себе, понимание себя.», «Для меня это самый лучший отдых.»,
    «Но опять подростковая часть…», «Он как-то хочет скриншот наложить на реальность.»)."""
    from autoreels.cloud.autocut import AutoParams, propose, teaser_pointer
    for t in ("Это и есть доверие к себе, понимание себя.", "Для меня это самый лучший отдых.",
              "Но опять подростковая часть, он же про социальное.", "Он как-то хочет скриншот наложить на реальность.",
              "И второй момент — то, что я сказал."):
        assert teaser_pointer(t), t
    for t in ("Поздно — это когда уже завтра заказан священник.", "Маска — это и есть какая-то эго-конструкция.",
              "Когда есть благодарность, она тебе ложится на душу.", "А что я сейчас чувствую?",
              "Чтобы выжить в семье, в обществе, нам приходится надевать маски."):
        assert teaser_pointer(t) is None, t
    units = [U(1, 0, 12, "thesis", 5, "1.1-2", summary="доверие"),
             U(2, 12, 12, "example", 4, "1.3-4", standalone=False, refers=1),
             U(3, 24, 12, "conclusion", 4, "2.1-2", standalone=False, refers=2, summary="доверие к себе")]
    sent = _rows({"2.1": "Это и есть доверие к себе, понимание себя!", "2.2": "Поздно — это когда уже завтра заказан священник."})
    base = dict(clips=1, target_sec=36, max_sec=60, loop=False, prune=False, hook_teaser=True)
    (old,) = propose(units, AutoParams(**base), sent)
    assert "2.1" in old.hooks                                  # off: only the −3 of M74
    (pr,) = propose(units, AutoParams(**base, hook_no_pointer=True), sent)
    assert "2.1" not in pr.hooks and "2.2" in pr.hooks


def test_every_clip_gets_post_text_and_pronouns_are_no_key_words():
    """M93 (m88: Pxl 112938952 r02 — its payoff was its opening thought, so d: stayed empty, the render wrote no
    r02.txt and arl crosspost skipped it; «себя» marked as a key word in two clips)."""
    from autoreels.cloud.autocut import AutoParams, pick_keywords, propose
    units = [U(1, 0, 30, "conclusion", 5, "1.1-6", summary="взрослый точно чувствует себя")]
    (pr,) = propose(units, AutoParams(clips=1, min_sec=10, target_sec=30, max_sec=60, loop=False), _rows({}))
    assert pr.caption == "взрослый точно чувствует себя" and "| d: взрослый точно чувствует себя" in pr.line("1")
    rows = [("1.1", "Взрослый чувствует себя."), ("1.2", "Он про своё тело.")]
    assert pick_keywords(rows, _Answers('{"keys": [{"s": 1, "word": "себя"}, {"s": 2, "word": "своё"}]}'),
                         n=2, log=lambda m: None) == []


def test_m106_a_clip_without_a_teaser_says_why_and_what_a_third_would_give():
    """M106 (m105: 3 of 5 clips of PXL_20260729_copy without a cold open, «нет фразы для тизера» — the reason
    unseen): the note counts the sentences of the second half by the rule each fails, and how many candidates a
    teaser from a third of the clip on would have (a measure; nothing changes in the clip)."""
    from autoreels.cloud.autocut import AutoParams, propose, teaser_misses
    rows = {"1.1": (4.0, True, "Вы знаете, почему жизнь — компенсация?"), "1.2": (3.0, True, "Обычная фраза про жизнь."),
            "1.3": (3.0, True, "Это и есть доверие к себе."), "1.4": (3.0, True, "Маску можно снять, когда есть доверие!"),
            "2.1": (3.0, False, "Когда вы поймёте себя, то"), "2.2": (8.0, True, "Взрослый понимает, что маска нужна ребёнку.")}

    def sentences(refs):
        out = []
        for piece in refs.split():
            b, _, r = piece.partition(".")
            a, _, z = r.partition("-")
            for k in range(int(a), int(z or a) + 1):
                sec, complete, text = rows[f"{b}.{k}"]
                out.append((f"{b}.{k}", sec, len(text.split()), complete, text))
        return out
    units = [U(1, 0, 7, "thesis", 5, "1.1-2", summary="жизнь как компенсация"),
             U(2, 7, 6, "example", 4, "1.3-4", standalone=False, refers=1),
             U(3, 13, 11, "conclusion", 4, "2.1-2", standalone=False, refers=2, summary="маску можно снять")]
    p = AutoParams(clips=1, min_sec=10, target_sec=36, max_sec=60, loop=False, prune=False, hook_teaser=True,
                   hook_no_pointer=True)
    assert teaser_misses(units, sentences, p) == (2, {"незаконченная": 1, "длиннее 6 с": 1})
    (pr,) = propose(units, p, sentences)
    assert pr.hook is None
    assert ("крючок: во второй части клипа (с 50%) нет фразы для тизера — сборка без крючка (фраз там 2: "
            "незаконченная — 1, длиннее 6 с — 1; с 33% клипа нашлось бы 1)") in pr.notes


def test_m107_clips_without_a_cold_open_go_after_the_hooked_ones(tmp_path, monkeypatch, capsys):
    """M107 (m106: 6 of 15 clips had no cold open — one to four sentences in the second half, most pointing back):
    a candidate left without a hook after the judges is put aside; the hooked candidates are taken first, the
    hookless ones only when those run out. The ones not taken are listed (commented) in the draft. Off = as before."""
    from autoreels import __main__ as cli
    from autoreels.cloud import autocut as ac_mod
    from autoreels.cloud.edit import merge_group_sentences
    from autoreels.core.models import Manifest
    from tests.test_montage import _source

    def run(flag: str, n_hookless: int):
        root = tmp_path / f"{flag}{n_hookless}"
        root.mkdir()
        mpath = _source(root)
        cfg = root / "config" / "r0.yaml"
        cfg.write_text(cfg.read_text(encoding="utf-8").replace("  min_sec: 25 ", "  min_sec: 10 ")
                       .replace("  clips: 5\n", "  clips: 2\n").replace("  clips_every_min: ", "  clips_every_min: 0  # ").replace("  hook_min_words: 4 ", "  hook_min_words: 2 ")
                       .replace("  hookless_last: true ", f"  hookless_last: {flag} "), encoding="utf-8")
        r0 = cli.load_r0_config(cfg)
        tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), root / "cache")
        _, kept, _ = cli._review_block_set(tx, r0, "lecture")
        units = []
        for b in range(6):
            ss = merge_group_sentences([kept[b]], tx.words)
            units.append(U(b + 1, ss[0][0].t0, ss[-1][-1].t1 - ss[0][0].t0, "conclusion", 5, f"{b + 1}.1-{len(ss)}",
                           topic=b + 1, summary=f"вывод {b + 1}"))
        (root / "transcripts").mkdir(exist_ok=True)
        (root / "transcripts" / "v.map.json").write_text(json.dumps(
            {"version": 1, "stem": "v", "source_sha256": "f" * 64, "units": units}), encoding="utf-8")
        order = []

        def rank(pr, prov, **k):
            order.append(pr.pieces)
            if len(order) <= n_hookless:                     # the judges left the first candidates without a hook
                pr.hooks, pr.hook = [], None
            return False
        monkeypatch.setattr(ac_mod, "rank_hooks", rank)
        monkeypatch.setattr(ac_mod, "headline", lambda *a, **k: None)
        monkeypatch.setattr(ac_mod, "check_seams", lambda *a, **k: None)
        monkeypatch.setattr(cli, "_autocut_check", lambda head, line, r, c: (None, ""))
        prov = _Answers('{"subject": "вывод", "alone": true, "leads": true, "why": ""}')
        assert cli.cmd_autocut("v", root=root, cache_dir=str(root / "cache"), llm="local", provider=prov) == 0
        text = (root / "reviews" / "v_auto_m56.txt").read_text(encoding="utf-8")
        ms = [ln for ln in text.splitlines() if ln.startswith("M")]
        return order, ms, text, capsys.readouterr().out

    order, ms, text, out = run("false", 2)
    assert [m.split(" | ")[1] for m in ms] == order[:2] and all(" h:" not in m for m in ms)      # as before
    order, ms, text, out = run("true", 2)
    assert [m.split(" | ")[1] for m in ms] == order[2:4] and all(" h:" in m for m in ms)        # the hooked first
    left = text.split("# --- без холодного старта — не взяты")[1].splitlines()
    assert [any(ln.startswith("#! M") and f"| {o} |" in ln for ln in left) for o in order[:2]] == [True, True]
    assert "без крючка не взяты: 2" in out
    order, ms, text, out = run("true", 5)                                    # only one hooked: one hookless fills in
    assert len(ms) == 2 and " h:" in ms[0] and " h:" not in ms[1] and ms[1].split(" | ")[1] == order[0]
    assert "без крючка — взята, когда сборки с крючком кончились (M107)" in text


def test_m112_a_clip_without_a_cold_open_gets_a_curiosity_plate(tmp_path, monkeypatch):
    """M112: a clip with no cold open opens on its plate t:, so there the plate is the M71/M73 curiosity headline
    (mode «hook»); a clip with a cold open keeps the plate that names the subject (plate: context). When the checks
    drop the cold open after the plate was written, the plate is written again. plate_hookless "" = as before."""
    from autoreels import __main__ as cli
    from autoreels.cloud import autocut as ac_mod
    from autoreels.cloud.edit import merge_group_sentences
    from autoreels.core.models import Manifest
    from tests.test_montage import _source

    def run(flag: str, n_hookless: int, skip_hook: bool = False):
        root = tmp_path / f"{flag or 'off'}{n_hookless}{skip_hook}"
        root.mkdir()
        mpath = _source(root)
        cfg = root / "config" / "r0.yaml"
        cfg.write_text(cfg.read_text(encoding="utf-8").replace("  min_sec: 25 ", "  min_sec: 10 ")
                       .replace("  clips: 5\n", "  clips: 2\n").replace("  clips_every_min: ", "  clips_every_min: 0  # ").replace("  hook_min_words: 4 ", "  hook_min_words: 2 ")
                       .replace("  plate_hookless: hook ", f"  plate_hookless: \"{flag}\" "), encoding="utf-8")
        r0 = cli.load_r0_config(cfg)
        assert r0.autocut.plate_hookless == flag and r0.autocut.plate == "context"
        tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), root / "cache")
        _, kept, _ = cli._review_block_set(tx, r0, "lecture")
        units = []
        for b in range(6):
            ss = merge_group_sentences([kept[b]], tx.words)
            units.append(U(b + 1, ss[0][0].t0, ss[-1][-1].t1 - ss[0][0].t0, "conclusion", 5, f"{b + 1}.1-{len(ss)}",
                           topic=b + 1, summary=f"вывод {b + 1}"))
        (root / "transcripts").mkdir(exist_ok=True)
        (root / "transcripts" / "v.map.json").write_text(json.dumps(
            {"version": 1, "stem": "v", "source_sha256": "f" * 64, "units": units}), encoding="utf-8")
        order, plates = [], []

        def rank(pr, prov, **k):
            order.append(pr.pieces)
            if len(order) <= n_hookless:
                pr.hooks, pr.hook = [], None
            else:
                pr.hooks = pr.hooks[:1]
            return False

        def headline(pr, prov, text, *, mode, **k):
            plates.append((pr.pieces, mode))
            pr.title = f"плашка {mode} {pr.pieces.split('.')[0]}"      # distinct titles (M78: same title = too close)
            return True
        checks = []

        def check(head, line, r, c):
            checks.append(line)
            return (None, "    ! h:x — cold open skipped") if skip_hook and len(checks) == 1 and " h:" in line else (None, "")
        monkeypatch.setattr(ac_mod, "rank_hooks", rank)
        monkeypatch.setattr(ac_mod, "headline", headline)
        monkeypatch.setattr(ac_mod, "check_seams", lambda *a, **k: None)
        monkeypatch.setattr(cli, "_autocut_check", check)
        prov = _Answers('{"subject": "вывод", "alone": true, "leads": true, "why": ""}')
        assert cli.cmd_autocut("v", root=root, cache_dir=str(root / "cache"), llm="local", provider=prov) == 0
        text = (root / "reviews" / "v_auto_m56.txt").read_text(encoding="utf-8")
        return order, plates, [ln for ln in text.splitlines() if ln.startswith("M")], text

    order, plates, ms, _ = run("", 5)                           # off: every plate as plate: context
    assert {m for _, m in plates} == {"context"} and len(ms) == 2
    order, plates, ms, _ = run("hook", 5)                       # one hooked clip, one hookless fills in
    modes = dict(plates)
    assert modes[order[5]] == "context" and modes[order[0]] == "hook"
    assert " h:" in ms[0] and "t: плашка context" in ms[0]
    assert " h:" not in ms[1] and "t: плашка hook" in ms[1]
    order, plates, ms, text = run("hook", 0, skip_hook=True)    # the check dropped the only cold open
    first = order[0]
    assert [m for p, m in plates if p == first] == ["context", "hook"]
    assert " h:" not in ms[0] and "t: плашка hook" in ms[0]
    assert "крючок снят проверкой — плашка заново (hook)" in text


def test_keep_refs_until():
    from autoreels.cloud.autocut import keep_refs_until
    assert keep_refs_until("13.2-5 14.1-3", "14.2") == "13.2-5 14.1-2"
    assert keep_refs_until("13.2-5 14.1-3", "13.4") == "13.2-4"
    assert keep_refs_until("13.2-5", "13.2") == "13.2"
    assert keep_refs_until("13.2-5", "12.1") is None and keep_refs_until("13.2-5", "13.7") is None


def test_m115_a_clip_does_not_end_with_the_voice_up():
    """M115 (M1.9 C): the last sentence spoken «→» (voice up — the speaker goes on) is not an ending: the last thought
    loses trailing sentences back to one that is not «→» while the clip stays ≥ min_sec; else the clip goes and is
    listed. «unsure» stays. Off (end_tone false) = as before, whatever the intonation says."""
    from autoreels.cloud.autocut import AutoParams, propose
    units = [U(1, 0, 12, "thesis", 5, "1.1-4", summary="жизнь как компенсация"),
             U(2, 12, 15, "conclusion", 4, "2.1-5", standalone=False, refers=1, summary="маску можно снять")]
    sent = _rows({})                                             # every sentence 3 s, finished
    base = dict(clips=1, min_sec=20, target_sec=36, max_sec=60, loop=False, prune=False)
    tones = {"2.5": "open", "2.4": "open", "2.3": "final"}
    tone = lambda ref: tones.get(ref)                           # noqa: E731
    (old,) = propose(units, AutoParams(**base), sent, end_tone=tone)
    assert old.pieces == "1.1-4 2.1-5"                           # flag off: as before
    gone: list = []
    (pr,) = propose(units, AutoParams(**base, end_tone=True), sent, end_tone=tone, open_end=gone)
    assert pr.pieces == "1.1-4 2.1-3" and pr.unit_refs == {2: "2.1-3"} and not gone
    assert pr.seconds == 21.0                                    # 27 s − two sentences of 3 s
    assert any(n.startswith("конец: «") and "клип кончается на 2.3" in n and "убрано фраз: 2" in n for n in pr.notes)
    tones["2.5"] = "unsure"
    (pr2,) = propose(units, AutoParams(**base, end_tone=True), sent, end_tone=tone)
    assert pr2.pieces == "1.1-4 2.1-5"                           # unsure is not «→»
    tones.update({"2.5": "open", "2.3": "open"})                 # the nearest non-«→» end would leave < 20 s
    assert propose(units, AutoParams(**base, end_tone=True), sent, end_tone=tone, open_end=gone) == []
    assert len(gone) == 1 and gone[0][0] == "1.1-4 2.1-5" and "укоротить нельзя" in gone[0][1]
    assert propose(units, AutoParams(**base, end_tone=True), sent, end_tone=None)[0].pieces == "1.1-4 2.1-5"


def test_m115_cmd_autocut_reads_the_voice_from_the_intonation_map(tmp_path, monkeypatch):
    """M115: arl autocut takes the end tone of each sentence from the intonation map (prosody by Whisper t0); a clip
    whose ending stays «→» and cannot be shortened is listed in the draft; no map — a warning, clips as before."""
    from autoreels import __main__ as cli
    from autoreels.cloud import plan as plan_mod
    from autoreels.cloud.edit import merge_group_sentences
    from autoreels.core.models import Manifest
    from autoreels.local import prosody as pros
    from tests.test_montage import _source

    def run(with_map: bool):
        root = tmp_path / f"m{with_map}"
        root.mkdir()
        mpath = _source(root)
        cfg = root / "config" / "r0.yaml"
        cfg.write_text(cfg.read_text(encoding="utf-8").replace("  min_sec: 25 ", "  min_sec: 10 ")
                       .replace("  hook_llm: auto ", "  hook_llm: none ").replace("  clips: 5\n", "  clips: 1\n").replace("  clips_every_min: ", "  clips_every_min: 0  # "),
                       encoding="utf-8")
        r0 = cli.load_r0_config(cfg)
        assert r0.autocut.end_tone is True
        tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), root / "cache")
        _, kept, _ = cli._review_block_set(tx, r0, "lecture")
        ss = merge_group_sentences([kept[1]], tx.words)
        unit = U(1, ss[0][0].t0, ss[-1][-1].t1 - ss[0][0].t0, "conclusion", 5, f"2.1-{len(ss)}", summary="вывод")
        (root / "transcripts").mkdir(exist_ok=True)
        (root / "transcripts" / "v.map.json").write_text(json.dumps(
            {"version": 1, "stem": "v", "source_sha256": "f" * 64, "units": [unit]}), encoding="utf-8")
        if with_map:                                             # every sentence of block 2 ends with the voice up
            ends = {round(s[-1].t0 * 1000) for s in ss}
            monkeypatch.setattr(plan_mod, "load_alignment", lambda *a, **k: {"words": []})
            monkeypatch.setattr(pros, "load_prosody", lambda *a, **k: {"words": []})
            monkeypatch.setattr(pros, "tone_lookup", lambda p, *a: (lambda w: ("open", "x")
                                                                    if round(w.t0 * 1000) in ends else ("final", "x")))
        monkeypatch.setattr(cli, "_autocut_check", lambda head, line, r, c: (None, ""))
        assert cli.cmd_autocut("v", root=root, cache_dir=str(root / "cache")) == 0
        return (root / "reviews" / "v_auto_m56.txt").read_text(encoding="utf-8"), len(ss)

    text, n = run(False)
    assert f"| 2.1-{n} |" in text and "M115" not in text
    text, n = run(True)
    assert "# --- конец звучит с продолжением" in text and f"укоротить нельзя: 2.1-{n}" in text
    assert not any(ln.startswith("M1 ") for ln in text.splitlines())


def test_m116_autocut_shows_the_words_the_voice_draws_out_to_the_keyword_model(tmp_path, monkeypatch):
    """M116 (M1.9 D): with keywords_voice the words the voice draws out (intonation map: duration per letter) go to the
    k: request as a hint and into the draft note; --no-voice-keys (voice_keys=False) = the M88 request."""
    from autoreels import __main__ as cli
    from autoreels.cloud import autocut as ac_mod
    from autoreels.cloud import plan as plan_mod
    from autoreels.cloud.edit import merge_group_sentences
    from autoreels.core.models import Manifest
    from autoreels.local import prosody as pros
    from tests.test_montage import _source

    def run(voice: bool):
        root = tmp_path / f"v{voice}"
        root.mkdir()
        mpath = _source(root)
        cfg = root / "config" / "r0.yaml"
        cfg.write_text(cfg.read_text(encoding="utf-8").replace("  min_sec: 25 ", "  min_sec: 10 ")
                       .replace("  clips: 5\n", "  clips: 1\n").replace("  clips_every_min: ", "  clips_every_min: 0  # ")
                       .replace("  keywords_voice: false ", "  keywords_voice: true ")   # M118: off by default
                       .replace("  keywords_source: rule ", "  keywords_source: model "), encoding="utf-8")  # M204: k: by the model here
        r0 = cli.load_r0_config(cfg)
        assert r0.autocut.keywords and r0.autocut.keywords_voice and r0.autocut.keywords_source == "model"
        tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), root / "cache")
        _, kept, _ = cli._review_block_set(tx, r0, "lecture")
        ss = merge_group_sentences([kept[1]], tx.words)
        unit = U(1, ss[0][0].t0, ss[-1][-1].t1 - ss[0][0].t0, "conclusion", 5, f"2.1-{len(ss)}", summary="вывод")
        (root / "transcripts").mkdir(exist_ok=True)
        (root / "transcripts" / "v.map.json").write_text(json.dumps(
            {"version": 1, "stem": "v", "source_sha256": "f" * 64, "units": [unit]}), encoding="utf-8")
        long = {s[1].t0 for s in ss if len(s) > 2}                   # the second word of each sentence drawn out
        monkeypatch.setattr(plan_mod, "load_alignment", lambda *a, **k: {"words": []})
        monkeypatch.setattr(pros, "load_prosody", lambda *a, **k: {"words": [
            {"t0": w.t0, "v": 20, "end_pct": 10.0,                   # speech at 0.06 s a letter, the drawn-out 0.2
             "dur": (0.2 if w.t0 in long else 0.06) * sum(c.isalpha() for c in w.word)} for w in tx.words]})
        seen = []
        monkeypatch.setattr(ac_mod, "pick_keywords", lambda rows, prov, **k: seen.append(k.get("voiced")) or [])
        monkeypatch.setattr(ac_mod, "rank_hooks", lambda *a, **k: False)
        monkeypatch.setattr(ac_mod, "headline", lambda *a, **k: False)
        monkeypatch.setattr(ac_mod, "check_seams", lambda *a, **k: None)
        monkeypatch.setattr(cli, "_autocut_check", lambda head, line, r, c: (None, ""))
        prov = _Answers('{"subject": "вывод", "alone": true, "leads": true, "why": ""}')
        assert cli.cmd_autocut("v", root=root, cache_dir=str(root / "cache"), llm="local", provider=prov,
                               voice_keys=voice) == 0
        return seen, (root / "reviews" / "v_auto_m56.txt").read_text(encoding="utf-8"), ss

    seen, text, ss = run(True)
    assert seen and seen[0] is not None and any(seen[0])
    from autoreels.cloud.autocut import _kw_norm
    hinted = {w for v in seen[0] for w in v}
    assert hinted <= {_kw_norm(s[1].word) for s in ss}
    assert "голос выделяет: 2." in text
    seen, text, _ = run(False)
    assert seen == [None] and "голос выделяет" not in text


def test_m118_hedges_and_fillers_are_never_key_words():
    """M118 (m116: k: «потом»; the voice hints «допустим», «какой-то»): the code drops them whatever the model says."""
    from autoreels.cloud.autocut import pick_keywords
    rows = [("1.1", "Потом допустим какой-то человек приходит к психологу."), ("1.2", "Вообще это значит доверие.")]
    ans = _Answers('{"keys": [{"s": 1, "word": "потом"}, {"s": 1, "word": "какой-то"}, {"s": 2, "word": "вообще"},'
                   ' {"s": 2, "word": "доверие"}]}')
    assert pick_keywords(rows, ans, n=2, log=lambda m: None) == [("1.2", "доверие")]


def _units119():
    return [
        U(1, 0, 10, "explanation", 3, "1.1"),
        U(2, 10, 12, "example", 2, "1.2", standalone=False, refers=1),          # weak: inside a run, never at an end
        U(3, 22, 14, "thesis", 4, "1.3", standalone=False, refers=2),           # the seed leans back
        U(4, 36, 10, "conclusion", 3, "1.4"),
        U(5, 46, 8, "question", 3, "1.5"),
        U(6, 54, 20, "explanation", 4, "2.1", topic=2),                          # another topic
        U(7, 74, 15, "thesis", 4, "2.2", topic=2),
        U(8, 200, 15, "example", 3, "3.1", topic=2),                             # 111 s after #7
    ]


def test_m119_passage_is_a_run_of_adjacent_thoughts_of_one_topic():
    """M119 (m118: 60 of the owner's 66 clips are one stretch of the talk inside one topic; build_clip failed on half
    the seeds — a thought that leans back brings its whole chain, here through the weak #2)."""
    from autoreels.cloud.autocut import build_passage
    units = _units119()
    by = {u["id"]: u for u in units}
    p = AutoParams(min_sec=20, target_sec=40, max_sec=65, generator="passage")
    assert build_clip(by[3], units, by, p) is None                    # the montage builder gives up on this seed
    run = build_passage(by[3], by, p)
    assert [u["id"] for u in run] == [1, 2, 3, 4]                      # back while it leans, then the neighbour
    run = build_passage(by[3], by, AutoParams(min_sec=20, target_sec=70, max_sec=80))
    assert [u["id"] for u in run] == [1, 2, 3, 4]                      # #5 (a question) does not end it, #6 is topic 2
    assert [u["id"] for u in build_passage(by[3], by, p, taken={1})] == [3, 4]   # the weak #2 is not left at the start
    assert build_passage(by[3], by, AutoParams(min_sec=50, target_sec=60, max_sec=80)) is None
    assert [u["id"] for u in build_passage(by[7], by, AutoParams(min_sec=20, target_sec=60, max_sec=80))] == [6, 7]
    assert [u["id"] for u in build_passage(by[7], by, AutoParams(min_sec=20, target_sec=60, max_sec=80,
                                                                 passage_gap_sec=200))] == [6, 7, 8]


def test_m119_propose_passages_share_no_thought_and_take_no_question_from_elsewhere():
    units = _units119() + [U(9, 300, 8, "question", 4, "4.1", summary="зачем?")]
    p = AutoParams(clips=5, min_sec=20, target_sec=40, max_sec=65, generator="passage")
    props = propose(units, p)
    assert props and all(pr.units == list(range(pr.units[0], pr.units[-1] + 1)) for pr in props)
    flat = [i for pr in props for i in pr.units]
    assert len(flat) == len(set(flat)) and 9 not in flat
    assert all(pr.start_doubt is None for pr in props)
    montage = propose(units, AutoParams(clips=5, min_sec=20, target_sec=40, max_sec=65))
    assert [pr.units for pr in montage] != [pr.units for pr in props]          # the flag off = the montage builder


def test_m119_seed_roles_choose_what_a_clip_grows_around():
    units = [U(1, 0, 25, "explanation", 4, "1.1-2"), U(2, 25, 10, "explanation", 3, "1.3")]
    p = AutoParams(clips=5, min_sec=20, target_sec=40, max_sec=65, generator="passage")
    assert propose(units, p) == []                                              # explanation is not in STORY
    (pr,) = propose(units, AutoParams(**{**p.__dict__, "seed_roles": ("explanation",)}))
    assert pr.units == [1, 2]


def test_m119_rank_keeps_a_start_only_the_model_rejects_and_marks_it():
    """M119 (m118: the judges accepted 22–46% of the owner's own starts): with start_judge rank the model's «no» on a
    start the rules accept only marks the clip (start_doubt); veto — the M75 behaviour — drops it."""
    units = [U(1, 0, 30, "thesis", 5, "1.1-3"), U(2, 30, 10, "conclusion", 4, "1.4")]
    sent = _rows74({"1.1": "Хоть это бывает полезно, как говорят психологи."})

    def judge(text, following, core=""):
        return (not text.startswith("Хоть это"), "«это» без предмета")
    base = dict(clips=1, min_sec=20, target_sec=40, max_sec=80, loop=False, prune=False, context_start=True)
    no_start: list = []
    assert propose(units, AutoParams(**base), sent, judge=judge, no_start=no_start) == []
    assert "«это» без предмета" in no_start[0][1]
    (pr,) = propose(units, AutoParams(**base, start_judge="rank"), sent, judge=judge)
    assert pr.start_doubt and "«это» без предмета" in pr.start_doubt
    assert any("модель против" in n and "правила принимают" in n for n in pr.notes)
    rules_no = _rows74({"1.1": "Поэтому это бывает полезно, как говорят психологи."})
    no_start = []
    assert propose(units, AutoParams(**base, start_judge="rank"), rules_no, judge=judge, no_start=no_start) == []
    assert "ссылка назад «поэтому…»" in no_start[0][1]                        # the rules still decide


def test_m119_ac_overrides_check_names_and_types():
    from autoreels.__main__ import _autocut_overrides
    from autoreels.core.config import AutocutConfig
    base = AutocutConfig()
    assert (base.generator, base.seed_roles, base.start_judge, base.clips_every_min) == ("montage", [], "veto", 0.0)
    c = _autocut_overrides(base, ["generator=passage", "seed_roles=thesis, explanation", "target_sec=35",
                                  "start_judge=rank", "clips_every_min=3.5"])
    assert (c.generator, c.seed_roles, c.target_sec, c.start_judge, c.clips_every_min) == \
        ("passage", ["thesis", "explanation"], 35.0, "rank", 3.5)
    assert _autocut_overrides(base, ["seed_roles="]).seed_roles == []
    for bad in (["generator=collage"], ["nope=1"], ["target_sec"], ["seed_roles=aside"]):
        try:
            _autocut_overrides(base, bad)
        except ValueError as exc:
            assert str(exc).startswith("--ac")
        else:
            raise AssertionError(bad)


def test_m119_cmd_autocut_takes_overrides_counts_clips_by_length_and_puts_doubts_last(tmp_path, monkeypatch, capsys):
    from autoreels import __main__ as cli
    from autoreels.cloud import autocut as ac_mod
    from autoreels.cloud.autocut import Proposal
    from tests.test_montage import _source
    _source(tmp_path)
    cfg = tmp_path / "config" / "r0.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("  hook_llm: auto ", "  hook_llm: none "), encoding="utf-8")
    cfg_text = cfg.read_text(encoding="utf-8")
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    (tmp_path / "transcripts" / "v.map.json").write_text(json.dumps(
        {"version": 1, "stem": "v", "source_sha256": "f" * 64, "units": [U(1, 0, 30, "thesis", 5, "2.1")]}),
        encoding="utf-8")
    seen = {}

    def fake_propose(units, p, sentences=None, **kw):
        seen["p"] = p
        return [Proposal(units=[1], pieces="2.1", hook=None, title="сомнение", caption="", score=90, seconds=30,
                         opener=1, start_doubt="модель: нет"),
                Proposal(units=[2], pieces="2.2", hook=None, title="чистое", caption="", score=80, seconds=30,
                         opener=2)]
    monkeypatch.setattr(ac_mod, "propose", fake_propose)
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False,
                           ac_over=["generator=passage", "clips_every_min=0.001", "start_judge=rank"]) == 0
    out = capsys.readouterr().out
    assert seen["p"].generator == "passage" and seen["p"].start_judge == "rank" and seen["p"].clips > 5
    assert "autocut для этого запуска: generator=passage" in out and "сборок: до " in out
    assert "у 1 кандидатов модель против начала" in out
    lines = [ln for ln in (tmp_path / "reviews" / "v_auto_m56.txt").read_text(encoding="utf-8").splitlines()
             if ln.startswith("M")]
    assert "t: чистое" in lines[0] and "t: сомнение" in lines[1]
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), ac_over=["generator=x"]) == 1
    assert "--ac" in capsys.readouterr().err
    assert cfg.read_text(encoding="utf-8") == cfg_text                            # the config file is not touched


def test_m119_lean_depth_limits_the_chain_a_thought_brings():
    """M119 (IMG_6848: 10 of 20 seeds built nothing — the map marks 71% of thoughts as leaning back, chains ran over
    16 thoughts or through a weak one): lean_depth 1 — a thought brings only the one it leans on; 0 — as before."""
    by = {u["id"]: u for u in _units()}
    assert leans_on(by[5], by) == [3, 2] and leans_on(by[5], by, 1) == [3] and leans_on(by[5], by, 2) == [3, 2]
    units = [U(1, 0, 10, "explanation", 2, "1.1"), U(2, 10, 15, "example", 3, "1.2", standalone=False, refers=1),
             U(3, 25, 15, "conclusion", 5, "1.3", standalone=False, refers=2)]
    by = {u["id"]: u for u in units}
    assert build_clip(by[3], units, by, AutoParams(min_sec=20, target_sec=40)) is None      # through the weak #1
    clip = build_clip(by[3], units, by, AutoParams(min_sec=20, target_sec=40, lean_depth=1))
    assert [u["id"] for u in clip] == [2, 3]


def test_m120_the_jump_rule_is_flexible_by_distance_and_place():
    """M120 (owner: «перестановки можно, но без частых быстрых скачков; гибкий алгоритм кусков»; his 66 clips: 48 one
    stretch, 12 one jump, 6 two, none three): the piece after a jump needs more time the farther the jump, the last one
    (the payoff) half of it; no more than max_jumps."""
    from autoreels.cloud.autocut import rhythm_pieces, rhythm_why, settle_need
    p = AutoParams(rhythm=True)
    assert rhythm_pieces([(0, 10), (12, 20), (40, 50), (5, 8)], 10.0) == [[0, 1], [2], [3]]   # 20 s gap; back
    assert settle_need(10, p) == 6.0 and settle_need(120, p) == 12.0 and settle_need(500, p) == 12.0
    assert settle_need(-1, p) == 12.0 and 6.0 < settle_need(65, p) < 12.0
    assert rhythm_why([(0, 40)], p) == (None, None)
    why, k = rhythm_why([(0, 20), (300, 308), (500, 530)], p)                  # 8 s between two far jumps
    assert why and "8.0 с" in why and k == 1
    assert rhythm_why([(0, 20), (300, 313), (500, 520)], p)[0] is None         # 13 s after a far jump
    assert rhythm_why([(0, 20), (300, 306.5)], p)[0] is None                   # a punchline: 6.5 ≥ 12 × 0.5
    assert "5.0 с" in rhythm_why([(0, 20), (300, 305)], p)[0]
    assert rhythm_why([(0, 20), (35, 41.5), (42, 60)], p)[0] is None           # a 15 s skip needs ~6 s
    assert "скачков 3" in rhythm_why([(0, 15), (100, 115), (200, 215), (300, 315)], p)[0]
    assert "до первого скачка" in rhythm_why([(0, 4), (100, 130)], p)[0]
    assert rhythm_why([(0, 4), (100, 130)], p, first_is_question=True)[0] is None   # the loop question opens


def test_m120_fit_rhythm_grows_the_piece_at_fault_or_drops_it():
    from autoreels.cloud.autocut import fit_rhythm
    units = [U(1, 0, 20, "thesis", 4, "1.1"), U(2, 300, 5, "example", 3, "5.1"), U(3, 305, 9, "example", 3, "5.2"),
             U(4, 600, 20, "conclusion", 4, "9.1"), U(5, 900, 5, "example", 3, "12.1", topic=2)]
    by = {u["id"]: u for u in units}
    p = AutoParams(rhythm=True, min_sec=20, max_sec=80)
    clip, notes = fit_rhythm([by[1], by[2], by[4]], by, p, {1, 4})
    assert [u["id"] for u in clip] == [1, 2, 3, 4] and "дополнен мыслью #3" in notes[0]
    clip, notes = fit_rhythm([by[1], by[5], by[4]], by, p, {1, 4})                 # #5 cannot grow: it goes
    assert [u["id"] for u in clip] == [1, 4] and "убран кусок #5" in notes[0]
    assert fit_rhythm([by[1], by[5], by[4]], by, p, {1, 5, 4})[0] is None          # … unless it is the seed
    assert fit_rhythm([by[1], by[2], by[4]], by, p, {1, 4}, taken={3})[1][0].endswith("убран кусок #2")


def test_m120_builders_keep_the_jump_cap_and_mixed_ends_on_a_later_conclusion():
    from autoreels.cloud.autocut import add_payoff, build_passage
    units = [U(i, 30 * (i - 1) + (25 * (i - 1) if i > 1 else 0), 15, "example", 3, f"{i}.1") for i in range(1, 6)]
    by = {u["id"]: u for u in units}                                                # 40 s gaps between thoughts
    on = AutoParams(min_sec=20, target_sec=70, max_sec=80, passage_gap_sec=60, rhythm=True, max_jumps=2)
    assert len(build_passage(by[3], by, on)) == 3                                   # two skips, no third
    assert len(build_passage(by[3], by, AutoParams(min_sec=20, target_sec=70, max_sec=80, passage_gap_sec=60))) == 5
    run = [U(1, 0, 20, "thesis", 4, "1.1"), U(2, 20, 15, "example", 3, "1.2")]
    later = [U(3, 60, 10, "conclusion", 4, "3.1"), U(4, 400, 10, "conclusion", 5, "9.1"),
             U(5, 30, 10, "conclusion", 5, "0.9", topic=2), U(6, 500, 10, "conclusion", 4, "10.1", standalone=False,
                                                              refers=99)]
    p = AutoParams(max_sec=60)
    clip, note = add_payoff(run, run[0], run + later, p)
    assert [u["id"] for u in clip] == [1, 2, 3] and "вывод из другого места: #3" in note   # the nearest later one
    assert add_payoff(run, run[0], run + later, p, taken={3})[0][-1]["id"] == 4
    assert add_payoff(run + [later[0]], run[0], run + later, p)[1] is None          # it has its payoff
    props = propose(run + later, AutoParams(clips=5, min_sec=20, target_sec=35, max_sec=60, generator="mixed",
                                            rhythm=True))
    assert any(pr.units[-1] in (3, 4) for pr in props)


def test_m120_a_rank_doubt_is_the_models_word_on_the_start_actually_used():
    """m119: «И работай дальше.» — ссылка назад «и…» was noted as the model's verdict: the judge's run failed on another
    sentence (a repair path), the rules' run kept the first one. The doubt is the judge's word on the start used."""
    units = [U(1, 0, 20, "thesis", 4, "1.1-2"), U(2, 20, 20, "conclusion", 5, "2.1-2")]
    sent = _rows74({"1.1": "Хоть это бывает полезно, как говорят психологи.",
                    "2.1": "И работай дальше, всё получится обязательно у вас."})

    def judge(text, following, core=""):
        return (not text.startswith("Хоть это"), "«это» без предмета")
    p = AutoParams(clips=1, min_sec=15, target_sec=40, max_sec=80, loop=False, prune=False, context_start=True,
                   start_judge="rank")
    (pr,) = propose(units, p, sent, judge=judge)
    assert pr.units == [1, 2] and "«это» без предмета" in pr.start_doubt and "ссылка назад" not in pr.start_doubt
    (pr,) = propose(units, p, sent, judge=lambda t, f, c="": (True, ""))
    assert pr.start_doubt is None


def test_m120_cmd_autocut_lists_clips_that_could_not_keep_the_rhythm(tmp_path, monkeypatch, capsys):
    from autoreels import __main__ as cli
    from autoreels.cloud import autocut as ac_mod
    from tests.test_montage import _source
    _source(tmp_path)
    cfg = tmp_path / "config" / "r0.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("  hook_llm: auto ", "  hook_llm: none "), encoding="utf-8")
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    (tmp_path / "transcripts" / "v.map.json").write_text(json.dumps(
        {"version": 1, "stem": "v", "source_sha256": "f" * 64, "units": [U(1, 0, 30, "thesis", 5, "2.1")]}),
        encoding="utf-8")
    seen = {}

    def fake_propose(units, p, sentences=None, rhythm_out=None, **kw):
        seen["p"] = p
        rhythm_out.append(("2.1 7.1", "скачков 3 (можно 2)"))
        rhythm_out.append(("2.1 7.1", "скачков 3 (можно 2)"))                    # the same clip from another seed
        return []
    monkeypatch.setattr(ac_mod, "propose", fake_propose)
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False,
                           ac_over=["rhythm=true", "generator=mixed", "context_judge=false"]) == 0
    p = seen["p"]
    assert p.rhythm and p.generator == "mixed" and p.max_jumps == 2 and p.settle_far_sec == 12.0
    assert "(скачки, не поправить: 1)" in capsys.readouterr().out
    text = (tmp_path / "reviews" / "v_auto_m56.txt").read_text(encoding="utf-8")
    assert text.count("скачков 3 (можно 2): 2.1 7.1") == 1 and "# --- скачки:" in text


# M232-A2: fully synthetic final-integrity and reversible-CLI-shortening tests.
# Kept in test_autocut.py so the existing offline smoke workflow always runs them.


def _params(**kw):
    return replace(AutoParams(clips=1, min_sec=1, max_sec=90, target_sec=30,
                              generator="montage", loop=False, prune=False,
                              context_start=False, rhythm=False), **kw)


def test_a2_s4_removed_established_target_rejected_and_attributed(monkeypatch):
    one = _a2_U(1, 0, 15, "thesis", 5, "1.1")
    target = _a2_U(2, 16, 15, "example", 3, "2.1")
    dependent = _a2_U(3, 32, 15, "conclusion", 3, "3.1", standalone=False, refers=2)
    monkeypatch.setattr(ac, "build_clip", lambda *a, **kw: [one, target, dependent])
    monkeypatch.setattr(ac, "fit_rhythm", lambda *a, **kw: ([one, dependent], []))
    monkeypatch.setattr(ac, "rhythm_why", lambda *a, **kw: (None, None))
    units = [one, target, dependent]
    assert [p.units for p in propose(units, _params(rhythm=True))] == [[1, 3]]  # FAIL BEFORE
    rejected = []
    assert propose(units, _params(rhythm=True, fix_final_integrity=True), rhythm_out=rejected) == []
    assert len(rejected) == 1 and "#2" in rejected[0][1] and "#3" in rejected[0][1]
    assert "ритм" in rejected[0][1]


def test_a2_s5_fx7l_loop_support_removed_rejected_to_no_start(monkeypatch):
    units = _fx7l_units()
    def drop_support(clip, *a, **kw):
        kept = [u for u in clip if u["id"] != 10]
        return (kept or clip), [], ""
    monkeypatch.setattr(ac, "context_start", drop_support)
    lookup = lambda refs: [("1.1", 5.0, 3, True)]
    p = _params(context_start=True)
    assert any(11 in o.units and 10 not in o.units for o in propose(units, p, lookup))  # FAIL BEFORE
    no_start = []
    assert propose(units, replace(p, fix_final_integrity=True), lookup, no_start=no_start) == []
    assert any("#10" in why and "#11" in why for _, why in no_start)


def test_a2_aq7_loop_target_introduced_at_s1_then_removed_at_s5(monkeypatch):
    """AQ7: target absent at S0 but established at S1 is still protected."""
    question = _a2_U(10, 0, 5, "question", 3, "1.1")
    dependent = _a2_U(11, 10, 30, "thesis", 5, "1.2", standalone=False, refers=10)
    monkeypatch.setattr(ac, "build_clip", lambda *a, **kw: [dependent])
    monkeypatch.setattr(ac, "_loop_question", lambda *a, **kw: question)

    def drop_loop(clip, *a, **kw):
        return [u for u in clip if u["id"] != 10], [], ""

    monkeypatch.setattr(ac, "context_start", drop_loop)
    p = _params(loop=True, context_start=True)
    lookup = lambda refs: [("1.2", 15.0, 5, True)]
    old_trace = []
    assert [o.units for o in propose([question, dependent], p, lookup, trace=old_trace)] == [[11]]
    seed = next(ev for ev in old_trace if ev["event"] == "seed")
    assert seed["snap"]["S0"] == [11] and seed["snap"]["S1"] == [10, 11]
    assert seed["snap"]["S5"] == [11] and seed["dep_broken"] == [[11, 10, "S5"]]

    refused = []
    assert propose([question, dependent], replace(p, fix_final_integrity=True),
                   lookup, no_start=refused) == []
    assert len(refused) == 1 and "#10" in refused[0][1] and "#11" in refused[0][1]


def test_a2_question_tail_rejected_but_question_first_passes(monkeypatch):
    one = _a2_U(1, 0, 30, "thesis", 5, "1.1")
    question = _a2_U(2, 31, 10, "question", 3, "2.1")
    monkeypatch.setattr(ac, "build_clip", lambda *a, **kw: [one])
    monkeypatch.setattr(ac, "fit_rhythm", lambda *a, **kw: ([one, question], []))
    monkeypatch.setattr(ac, "rhythm_why", lambda *a, **kw: (None, None))
    assert [p.units for p in propose([one, question], _params(rhythm=True))] == [[1, 2]]
    blocked = []
    assert propose([one, question], _params(rhythm=True, fix_final_integrity=True), rhythm_out=blocked) == []
    assert blocked and "вопрос" in blocked[0][1]

    monkeypatch.setattr(ac, "fit_rhythm", lambda clip, *a, **kw: (clip, []))
    monkeypatch.setattr(ac, "_loop_question", lambda *a, **kw: question)
    one["standalone"], one["refers"] = False, 2  # established support intact in a question-first loop
    assert [o.units for o in propose([one, question], _params(rhythm=True, loop=True,
                                  fix_final_integrity=True))] == [[2, 1]]


def test_a2_never_established_edge_not_rejected_and_bool_refers_not_int(monkeypatch):
    one = _a2_U(1, 0, 15, "thesis", 5, "1.1")
    absent = _a2_U(2, 16, 15, "example", 3, "2.1")
    dep = _a2_U(3, 32, 15, "conclusion", 3, "3.1", standalone=False, refers=2)
    monkeypatch.setattr(ac, "build_clip", lambda *a, **kw: [one, dep])
    assert [o.units for o in propose([one, absent, dep], _params(fix_final_integrity=True))] == [[1, 3]]
    dep["refers"] = True  # bool == 1 in Python; a bool is not an exact integer id
    monkeypatch.setattr(ac, "fit_rhythm", lambda *a, **kw: ([dep], []))
    monkeypatch.setattr(ac, "rhythm_why", lambda *a, **kw: (None, None))
    assert [o.units for o in propose([one, dep], _params(rhythm=True,
                                   fix_final_integrity=True))] == [[3]]


def test_a2_flag_defaults_off_and_validates_as_typed_config():
    from autoreels.core.config import AutocutConfig
    assert AutoParams().fix_final_integrity is False
    assert AutocutConfig().fix_final_integrity is False
    assert AutocutConfig.model_validate({"fix_final_integrity": True}).fix_final_integrity is True
    with pytest.raises(Exception):
        AutocutConfig.model_validate({"fix_final_integrity": "invalid"})


@pytest.mark.parametrize("shortening", ["m167", "m173"])
@pytest.mark.parametrize("origin", ["main", "weak"])
def test_a2_cli_reversible_integrity_for_both_shortenings_and_origins(
        tmp_path, monkeypatch, shortening, origin):
    """Main and fill-pool candidates both get pre-adoption checks; OFF keeps legacy bytes."""
    from autoreels import __main__ as cli
    proj = _montage_project(tmp_path)
    r1, r2 = proj["refs"][:2]
    t0 = float(proj["sbr"][r1][0].t0)
    units = [_a2_U(1, 40, 15, "thesis", 5, r1, standalone=shortening != "m167",
               refers=2 if shortening == "m167" else None),
             _a2_U(2, 56, 15, "conclusion", 4, r2, standalone=shortening == "m167",
               refers=1 if shortening == "m173" else None)]
    import json
    path = tmp_path / "transcripts" / "v.map.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["units"] = units
    path.write_text(json.dumps(data), encoding="utf-8")

    created = []
    def fake_propose(units_arg, p, *a, **kw):
        if (origin == "weak") != (p.seed_punch < 4):
            return []
        new = Proposal([1, 2], f"{r1} {r2}", None, "", "", 80, 30)
        created.append(new)
        return [new]
    monkeypatch.setattr(ac, "propose", fake_propose)
    errors = []
    def fake_check(_head, line, *_a):
        errors.append(line)
        if shortening == "m167":
            return ("no room after last word", "") if r2 in line else (None, "")
        return (f"short shot whole sentences s1@{t0:.3f}", "") if r1 in line else (None, "")
    monkeypatch.setattr(cli, "_autocut_check", fake_check)
    common = dict(root=tmp_path, cache_dir=str(tmp_path / "cache"),
                  check=True, clips=1, llm="none", voice_keys=False)
    if origin == "weak":
        common["ac_over"] = ["fill_seed_punch=3", "seed_punch=4"]
    assert cli.cmd_autocut("v", **common) == 0
    off = (tmp_path / "reviews/v_auto_m56.txt").read_bytes()
    assert b"M1" in off and len(errors) == 2
    errors.clear()
    on_args = {**common, "ac_over": [*(common.get("ac_over") or []), "fix_final_integrity=true"]}
    assert cli.cmd_autocut("v", **on_args) == 0
    on = (tmp_path / "reviews/v_auto_m56.txt").read_text(encoding="utf-8")
    assert len(errors) == 1  # refused shortening BEFORE re-check
    assert len(created) == 2
    assert any("укорочение не взято" in note and "#1" in note and "#2" in note
               for note in created[-1].notes)
    assert ("#   причина: no room after last word" if shortening == "m167"
            else "#   причина: short shot whole sentences") in on  # original check error kept
    assert "# --- не прошли проверку" in on and "#! M 80" in on


@pytest.mark.parametrize("shortening", ["m167", "m173"])
def test_a2_cli_legal_shortening_kept(tmp_path, monkeypatch, shortening):
    """A2 is a guard, not a global veto of CLI repairs."""
    from autoreels import __main__ as cli
    from autoreels.cloud import autocut
    import json

    proj = _montage_project(tmp_path)
    r1, r2 = proj["refs"][:2]
    t0 = float(proj["sbr"][r1][0].t0)
    mpath = tmp_path / "transcripts/v.map.json"
    data = json.loads(mpath.read_text(encoding="utf-8"))
    data["units"] = [_a2_U(1, 40, 15, "thesis", 5, r1), _a2_U(2, 56, 15, "conclusion", 4, r2)]
    mpath.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(autocut, "propose", lambda *a, **kw: [
        Proposal([1, 2], f"{r1} {r2}", None, "", "", 80, 30)])
    calls = []

    def fake_check(_h, line, *_a):
        calls.append(line)
        if shortening == "m167":
            return ("no room after last word", "") if r2 in line else (None, "")
        return (f"short shot whole sentences s1@{t0:.3f}", "") if r1 in line else (None, "")

    monkeypatch.setattr(cli, "_autocut_check", fake_check)
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"),
                           check=True, clips=1, llm="none", voice_keys=False,
                           ac_over=["fix_final_integrity=true"]) == 0
    body = (tmp_path / "reviews/v_auto_m56.txt").read_text(encoding="utf-8")
    assert len(calls) == 2 and "# --- M1" in body and "укорочение не взято" not in body
    assert (f"M1 80 | {r1}" if shortening == "m167" else f"M1 80 | {r2}") in body


def test_a2_cli_m167_question_tail_rejected(tmp_path, monkeypatch):
    from autoreels import __main__ as cli
    import json

    proj = _montage_project(tmp_path)
    r1, r2 = proj["refs"][:2]
    path = tmp_path / "transcripts/v.map.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["units"] = [_a2_U(1, 40, 15, "question", 5, r1),
                     _a2_U(2, 56, 15, "conclusion", 4, r2)]
    path.write_text(json.dumps(data), encoding="utf-8")
    created = []
    def fake_propose(*a, **kw):
        p = Proposal([1, 2], f"{r1} {r2}", None, "", "", 80, 30)
        created.append(p)
        return [p]
    monkeypatch.setattr(ac, "propose", fake_propose)
    calls = []
    def fake_check(_head, line, *_a):
        calls.append(line)
        return "no room after last word", ""
    monkeypatch.setattr(cli, "_autocut_check", fake_check)
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"),
                           check=True, clips=1, llm="none", voice_keys=False,
                           ac_over=["fix_final_integrity=true"]) == 0
    assert len(calls) == 1 and any("последняя звучащая мысль — вопрос" in n for n in created[0].notes)


def test_a2_scenario_pool_is_not_rechecked_by_montage_guard(tmp_path, monkeypatch):
    """The feature applies only to montage-origin pools; scenario bytes stay unchanged."""
    from autoreels import __main__ as cli
    import json

    proj = _montage_project(tmp_path)
    r1, r2 = proj["refs"][:2]
    path = tmp_path / "transcripts/v.map.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["units"] = [_a2_U(1, 40, 15, "thesis", 5, r1),
                     _a2_U(2, 56, 15, "conclusion", 4, r2, standalone=False, refers=1)]
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(cli, "_scenario_pool", lambda *a, **kw: [
        Proposal([1, 2], f"{r1} {r2}", None, "", "", 80, 30)])
    t0 = float(proj["sbr"][r1][0].t0)
    checks = []
    def fake_check(_head, line, *_a):
        checks.append(line)
        return ((f"short shot whole sentences s1@{t0:.3f}", "") if r1 in line else (None, ""))
    monkeypatch.setattr(cli, "_autocut_check", fake_check)
    args = dict(root=tmp_path, cache_dir=str(tmp_path / "cache"),
                check=True, clips=1, llm="none", voice_keys=False, scenario=True)
    assert cli.cmd_autocut("v", **args) == 0
    before = (tmp_path / "reviews/v_auto_m56.txt").read_bytes()
    assert len(checks) == 2 and f"M1 80 | {r2}".encode() in before
    checks.clear()
    assert cli.cmd_autocut("v", **args, ac_over=["fix_final_integrity=true"]) == 0
    after = (tmp_path / "reviews/v_auto_m56.txt").read_bytes()
    assert after == before and len(checks) == 2


def test_a2_tc8b_pin_rhythm_rejects_after_open_end_trimming(monkeypatch):
    one = _a2_U(1, 0, 30, "thesis", 5, "1.1")
    monkeypatch.setattr(ac, "fix_open_end", lambda clip, *a, **kw: (
        [{**clip[0], "t1": 2.5}], "убран открытый хвост", None))
    def invalid_after_trim(spans, *a, **kw):
        return ("после конца короче", 0) if spans[-1][1] == 2.5 else (None, None)
    monkeypatch.setattr(ac, "rhythm_why", invalid_after_trim)
    for flag in (False, True):
        rhythm, open_ends = [], []
        result = propose([one], _params(end_tone=True, rhythm=True, fix_final_integrity=flag),
                         sentences=lambda refs: [("1.1", 30., 12, True)],
                         end_tone=lambda r: "open", rhythm_out=rhythm, open_end=open_ends)
        assert result == [] and len(rhythm) == 1 and not open_ends


# M232-A3: synthetic fail-before oracles; no owner media, network, or render.
def test_a3_fx2g_strict_semantic_start_cannot_use_timing_soft_fallback():
    from autoreels.cloud.autocut import context_start

    unit = U(1, 0, 25, "thesis", 5, "1.1", summary="Смысл разговора")
    sentence = lambda _: [("1.1", 25.0, 2, True, "Да, конечно.")]
    base = AutoParams(context_start=True, min_sec=1, start_strict=True,
                      answer_start=True, start_pause_min=0.2, loop=False, prune=False)
    # Fail-before: the old M145 timing-only soft path accepts this answer.
    old, old_notes, old_why = context_start([unit], {1: unit}, base, sentence,
                                            seed_id=1, start_pause=lambda _: 0.0)
    assert old and old_why is None and any("оставлено" in n for n in old_notes)
    fixed, _notes, why = context_start([unit], {1: unit}, replace(base, fix_body_start=True), sentence,
                                       seed_id=1, start_pause=lambda _: 0.0)
    assert fixed is None and why


def test_a3_valid_timing_soft_and_question_first_survive():
    from autoreels.cloud.autocut import context_start

    unit = U(1, 0, 25, "thesis", 5, "1.1", summary="Смысл разговора")
    base = AutoParams(context_start=True, min_sec=1, start_strict=True, answer_start=True,
                      fix_body_start=True, start_pause_min=0.2, loop=False, prune=False)
    for content in ("Человек самостоятельно выбирает своё направление.", "А что помогает человеку выбрать путь?"):
        result, notes, why = context_start([unit], {1: unit}, base,
                                           lambda _: [("1.1", 25.0, 6, True, content)],
                                           seed_id=1, start_pause=lambda _: 0.0)
        assert result and why is None and any("оставлено" in n for n in notes)


def test_a3_strict_morph_is_required_even_on_empty_sentence_lookup(monkeypatch):
    from autoreels.cloud import clipcheck
    from autoreels.cloud.autocut import context_start

    unit = U(1, 0, 25, "thesis", 5, "1.1")
    monkeypatch.setattr(clipcheck, "require_morph", lambda: (_ for _ in ()).throw(RuntimeError("MORPH_MISSING")))
    p = AutoParams(fix_body_start=True, start_strict=True, start_morph=True)
    with pytest.raises(RuntimeError, match="MORPH_MISSING"):
        context_start([unit], {1: unit}, p, lambda _: [], seed_id=1)


def _a3_cli_seed(tmp_path, number=3):
    """Use only committed synthetic transcript words and map in a scratch project."""
    project = _montage_project(tmp_path)
    refs = project["refs"][:number]
    units = [U(i, 40 + i * 15, 14, "thesis" if i == 1 else "conclusion", 5,
               ref, summary={1: "Исходная тема", 2: "Промежуточный вывод",
                             3: "Итоговая тема"}.get(i, f"Мысль {i}"))
             for i, ref in enumerate(refs, 1)]
    path = tmp_path / "transcripts" / "v.map.json"
    map_json = json.loads(path.read_text(encoding="utf-8"))
    map_json["units"] = units
    path.write_text(json.dumps(map_json), encoding="utf-8")
    return project, refs


@pytest.mark.parametrize("origin", ["main", "weak"])
def test_a3_following_rechecked_if_first_ref_unchanged(tmp_path, monkeypatch, origin):
    """A3-FOLLOW: M173 deletes the *second* sentence; old first ref stays put."""
    from autoreels import __main__ as cli

    project, (r1, r2, r3) = _a3_cli_seed(tmp_path)
    created, calls, semantic = [], [], []
    t0 = project["sbr"][r2][0].t0
    next_text = " ".join(w.word for w in project["sbr"][r3])

    def make_proposal(_units, params, *args, **kwargs):
        if (origin == "weak") != (params.seed_punch < 4):
            return []
        pr = Proposal([1, 2, 3], f"{r1} {r2} {r3}", None, "", "", 80, 30)
        pr.seed_id = 1
        created.append(pr)
        return [pr]

    def fake_check(*args):
        calls.append(args[1])
        return (f"short shot whole sentences s1@{t0:.3f}", "") if len(calls) == 1 else (None, "")

    def fake_semantic(first, following, params, judge, core):
        semantic.append((first, following, core))
        return "fake judge: following changed" if following == next_text else None

    monkeypatch.setattr(ac, "propose", make_proposal)
    monkeypatch.setattr(ac, "stands_alone", fake_semantic)
    monkeypatch.setattr(cli, "_autocut_check", fake_check)
    args = dict(root=tmp_path, cache_dir=str(tmp_path / "cache"), llm="none", clips=1,
                check=True, voice_keys=False)
    extra = ["fill_seed_punch=3", "seed_punch=4"] if origin == "weak" else []
    assert cli.cmd_autocut("v", **args, ac_over=extra) == 0
    assert len(calls) == 2  # fail-before: old shortening accepted
    calls.clear()
    assert cli.cmd_autocut("v", **args, ac_over=extra + ["fix_body_start=true", "start_morph=false"]) == 0
    assert len(calls) == 1  # never apply or re-check rejected candidate
    assert len(semantic) == 1 and semantic[0][1] == next_text
    assert semantic[0][2] == "Исходная тема Итоговая тема"
    assert sum("укорочение не взято" in n for n in created[-1].notes) == 1
    review = (tmp_path / "reviews/v_auto_m56.txt").read_text(encoding="utf-8")
    assert "# --- не прошли проверку" in review
    assert "short shot whole sentences" in review  # preserved original error


def test_a3_one_sentence_following_is_empty_and_core_uses_new_last_unit(tmp_path, monkeypatch):
    """A3-ONE/CORE: M167 removes the last unit; next text is empty for one sentence."""
    from autoreels import __main__ as cli

    _project, (r1, r2) = _a3_cli_seed(tmp_path, number=2)
    pr = Proposal([1, 2], f"{r1} {r2}", None, "", "", 80, 30)
    pr.seed_id = 1
    monkeypatch.setattr(ac, "propose", lambda *args, **kwargs: [pr])
    calls, semantic = [], []

    def fake_check(*args):
        calls.append(args[1])
        return ("no room after last word", "") if len(calls) == 1 else (None, "")

    def fake_semantic(first, following, params, judge, core):
        semantic.append((first, following, core))
        return None

    monkeypatch.setattr(cli, "_autocut_check", fake_check)
    monkeypatch.setattr(ac, "stands_alone", fake_semantic)
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"),
                           llm="none", check=True, clips=1, voice_keys=False,
                           ac_over=["fix_body_start=true", "start_morph=false"]) == 0
    assert len(calls) == 2 and len(semantic) == 1
    assert semantic[0][1] == "" and semantic[0][2] == "Исходная тема"
    assert "# --- M1" in (tmp_path / "reviews/v_auto_m56.txt").read_text(encoding="utf-8")


def test_a3_scenario_bytes_unchanged_with_flag_on(tmp_path, monkeypatch):
    """A3-ORIGIN: scenario shortening is byte-for-byte outside A3."""
    from autoreels import __main__ as cli

    project, (r1, r2) = _a3_cli_seed(tmp_path, number=2)
    monkeypatch.setattr(cli, "_scenario_pool", lambda *args, **kwargs: [
        Proposal([1, 2], f"{r1} {r2}", None, "", "", 80, 30)])
    t0 = project["sbr"][r1][0].t0
    calls = []

    def fake_check(*args):
        calls.append(args[1])
        return (f"short shot whole sentences s1@{t0:.3f}", "") if len(calls) % 2 else (None, "")

    monkeypatch.setattr(cli, "_autocut_check", fake_check)
    args = dict(root=tmp_path, cache_dir=str(tmp_path / "cache"), check=True,
                scenario=True, llm="none", clips=1, voice_keys=False)
    assert cli.cmd_autocut("v", **args) == 0
    off = (tmp_path / "reviews/v_auto_m56.txt").read_bytes()
    calls.clear()
    assert cli.cmd_autocut("v", **args, ac_over=["fix_body_start=true"]) == 0
    assert (tmp_path / "reviews/v_auto_m56.txt").read_bytes() == off
    assert len(calls) == 2


def test_a3_cli_requires_morph_before_montage_even_with_empty_pool(tmp_path, monkeypatch):
    """A3-MORPH: no silent downgrade if required morphology is unavailable."""
    from autoreels import __main__ as cli
    from autoreels.cloud import clipcheck

    _a3_cli_seed(tmp_path, number=1)
    generated, checked = [], []
    monkeypatch.setattr(ac, "propose", lambda *args, **kwargs: generated.append(True) or [])
    monkeypatch.setattr(cli, "_autocut_check", lambda *args: checked.append(True) or (None, ""))
    monkeypatch.setattr(clipcheck, "require_morph", lambda: (_ for _ in ()).throw(RuntimeError("MORPH_MISSING")))
    with pytest.raises(RuntimeError, match="MORPH_MISSING"):
        cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"),
                        llm="none", check=True, clips=1, voice_keys=False,
                        ac_over=["fix_body_start=true", "start_strict=true", "start_morph=true"])
    assert not generated and not checked


@pytest.mark.parametrize("configured", [False, True])
def test_a3_four_shortening_semantic_probes_and_fake_budget(tmp_path, monkeypatch, configured):
    """A3-RATE: 2×M167 + 2×M173, ≤4 probes, ≤8 fake cold judge attempts."""
    from autoreels import __main__ as cli

    project, refs = _a3_cli_seed(tmp_path, number=5)
    pr = Proposal([1, 2, 3, 4, 5], " ".join(refs), None, "", "", 80, 40)
    pr.seed_id = 1
    monkeypatch.setattr(ac, "propose", lambda *args, **kwargs: [pr])
    checks, probes, requests = [], [], []

    def fake_check(*args):
        checks.append(args[1])
        stage = len(checks)
        if stage <= 2:
            return "no room after last word", ""
        if stage in (3, 4):
            t0 = float(project["sbr"][refs[stage - 2]][0].t0)
            return f"short shot whole sentences s1@{t0:.3f}", ""
        return None, ""

    def semantic(first, following, params, judge, core):
        probes.append((first, following, core))
        return judge(first, following, core) if judge is not None else None

    monkeypatch.setattr(cli, "_autocut_check", fake_check)
    monkeypatch.setattr(ac, "stands_alone", semantic)
    opts = ["fix_body_start=true", "start_morph=false"]
    provider = None
    if configured:
        class FakeProvider:
            model_id = "A3_SYNTHETIC"

        provider = FakeProvider()

        def fake_make_judge(*args, **kwargs):
            def cold(first, following, core):
                requests.extend([(first, following, core), (first, following, core)])
                return None  # two failed fake attempts, rules keep the candidate
            return cold

        monkeypatch.setattr(ac, "make_judge", fake_make_judge)
        monkeypatch.setattr(ac, "rank_hooks", lambda *args, **kwargs: None)
        opts += ["context_start=true", "context_judge=true", "hook_judge=false",
                 "hook_title=false", "seam_check=false", "keywords=0"]
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"),
                           llm="auto" if configured else "none", provider=provider,
                           check=True, clips=1, voice_keys=False, ac_over=opts) == 0
    assert len(checks) == 5 and len(probes) == 4
    assert len(requests) == (8 if configured else 0)
    assert all(x == probes[i] for i in range(4) for x in requests[i*2:i*2+2]) if configured else not requests


def test_a3_fx2s_m173_new_first_sentence_strict_invalid_refused(tmp_path, monkeypatch):
    """FX-2S: when M173 removes the first sentence, do not publish a strict-invalid successor."""
    from autoreels import __main__ as cli

    project, (r1, r2, r3) = _a3_cli_seed(tmp_path)
    created, calls = [], []
    t0 = project["sbr"][r1][0].t0
    banned = " ".join(w.word for w in project["sbr"][r2])

    def proposed(*args, **kwargs):
        pr = Proposal([1, 2, 3], f"{r1} {r2} {r3}", None, "", "", 80, 30)
        pr.seed_id = 1
        created.append(pr)
        return [pr]

    def fake_check(*args):
        calls.append(args[1])
        return (f"short shot whole sentences s1@{t0:.3f}", "") if len(calls) == 1 else (None, "")

    monkeypatch.setattr(ac, "propose", proposed)
    monkeypatch.setattr(cli, "_autocut_check", fake_check)
    monkeypatch.setattr(ac, "strict_start_reason", lambda text: "strict-invalid" if text == banned else None)
    args = dict(root=tmp_path, cache_dir=str(tmp_path / "cache"), llm="none", clips=1,
                check=True, voice_keys=False)
    assert cli.cmd_autocut("v", **args) == 0
    assert len(calls) == 2  # legacy accepts shortened first r2
    calls.clear()
    assert cli.cmd_autocut("v", **args, ac_over=["fix_body_start=true", "start_morph=false"]) == 0
    assert len(calls) == 1 and len(created) >= 2
    assert any("укорочение не взято" in n and "strict-invalid" in n for pr in created for n in pr.notes)
    review = (tmp_path / "reviews/v_auto_m56.txt").read_text(encoding="utf-8")
    assert "short shot whole sentences" in review and "#! M 80" in review


def test_a3_core_change_with_following_unchanged(tmp_path, monkeypatch):
    """A3-CORE: only last unit changes; seed is not Proposal.opener."""
    from autoreels import __main__ as cli

    project, (r1, r2, r3) = _a3_cli_seed(tmp_path)
    pr = Proposal([1, 2, 3], f"{r1} {r2} {r3}", None, "", "", 80, 30, opener=3)
    pr.seed_id = 1
    monkeypatch.setattr(ac, "propose", lambda *args, **kwargs: [pr])
    calls, probe = [], []

    def fake_check(*args):
        calls.append(args[1])
        return ("no room after last word", "") if len(calls) == 1 else (None, "")

    def fake_semantic(first, following, params, judge, core):
        probe.append((following, core))
        return None

    monkeypatch.setattr(cli, "_autocut_check", fake_check)
    monkeypatch.setattr(ac, "stands_alone", fake_semantic)
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"),
                           llm="none", check=True, clips=1, voice_keys=False,
                           ac_over=["fix_body_start=true", "start_morph=false"]) == 0
    next_text = " ".join(w.word for w in project["sbr"][r2])
    assert len(calls) == 2 and probe == [(next_text, "Исходная тема Промежуточный вывод")]


def test_a3_unresolved_seed_rejects_reversible_shortening(tmp_path, monkeypatch):
    """Missing original seed is never guessed from opener or first unit."""
    from autoreels import __main__ as cli

    _project, (r1, r2) = _a3_cli_seed(tmp_path, number=2)
    created, calls = [], []

    def proposed(*args, **kwargs):
        pr = Proposal([1, 2], f"{r1} {r2}", None, "", "", 80, 30, opener=1)
        created.append(pr)  # intentionally no seed_id
        return [pr]

    monkeypatch.setattr(ac, "propose", proposed)

    def fake_check(*args):
        calls.append(args[1])
        return "no room after last word", ""

    monkeypatch.setattr(cli, "_autocut_check", fake_check)
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"),
                           llm="none", check=True, clips=1, voice_keys=False,
                           ac_over=["fix_body_start=true", "start_morph=false"]) == 0
    assert len(calls) == 1 and sum("укорочение не взято" in n for n in created[0].notes) == 1
    assert "неизвестная исходная мысль" in created[0].notes[-1]


def test_a3_real_propose_populates_unserialized_original_seed():
    """Flag OFF keeps dataclasses.asdict golden unchanged; ON keeps seed for CLI."""
    from dataclasses import asdict

    one = U(1, 0, 30, "thesis", 5, "1.1", summary="Независимая мысль")
    p = AutoParams(clips=1, min_sec=1, max_sec=80, loop=False, prune=False,
                   context_start=True, fix_body_start=True, start_strict=True, start_morph=False)
    sentences = lambda _: [("1.1", 30.0, 4, True, "Человек выбирает собственный путь.")]
    result = propose([one], p, sentences)
    assert len(result) == 1 and result[0].seed_id == 1
    assert "seed_id" not in asdict(result[0])
    baseline = propose([one], replace(p, fix_body_start=False), sentences)
    assert asdict(result[0]) == asdict(baseline[0])


def test_a3_flag_is_typed_and_defaults_off():
    from autoreels.core.config import AutocutConfig

    assert AutoParams().fix_body_start is False
    assert AutocutConfig().fix_body_start is False
    assert AutocutConfig.model_validate({"fix_body_start": True}).fix_body_start is True
    with pytest.raises(Exception):
        AutocutConfig.model_validate({"fix_body_start": "not a boolean"})


def test_a3_m197_long_answer_can_drop_only_to_a_valid_remaining_start():
    """R3 §2.3: M197 removes a long first answer independent of context_drop_words."""
    from autoreels.cloud.autocut import context_start, _strict_body_why

    unit = U(1, 0, 30, "thesis", 5, "1.1-2")
    rows = [("1.1", 15.0, 12, True, "Да, конечно, если рассматривать этот путь, многое можно изменить."),
            ("1.2", 15.0, 6, True, "Человек постепенно учится понимать собственные потребности.")]
    def sentences(refs):
        return rows if refs == "1.1-2" else [row for row in rows if row[0] == refs]

    base = AutoParams(context_start=True, min_sec=12, context_drop_words=2,
                      start_strict=True, answer_start=True)
    old, _, why = context_start([unit], {1: unit}, base, sentences, seed_id=1)
    assert why is None and old and old[0]["refs"] == "1.1-2"
    assert _strict_body_why(rows[0][4], base) is None  # OFF means strict helper is inert

    on = replace(base, fix_body_start=True)
    fixed, notes, why = context_start([unit], {1: unit}, on, sentences, seed_id=1)
    assert why is None and fixed and fixed[0]["refs"] == "1.2"
    assert sum("убрана фраза" in note for note in notes) == 1

    too_short, _, why = context_start([unit], {1: unit}, replace(on, min_sec=20),
                                       sentences, seed_id=1)
    assert too_short is None and why and "ответ" in why

    bad_rows = [rows[0], ("1.2", 15.0, 2, True, "Да, конечно.")]
    no_repair, _, why = context_start([unit], {1: unit}, on,
                                       lambda refs: bad_rows if refs == "1.1-2" else [r for r in bad_rows if r[0] == refs],
                                       seed_id=1)
    assert no_repair is None and why and "ответ" in why


@pytest.mark.parametrize("repair", ["short_drop", "back_context", "later_sentence"])
def test_a3_each_context_repair_checks_strict_semantics(repair):
    """The old M74/M76 repair points may not substitute a strict-invalid opener."""
    from autoreels.cloud.autocut import context_start

    first = ("2.1", 10.0, 3, True, "И второй момент.")
    invalid = ("2.2", 15.0, 2, True, "Да, конечно.")
    prev = ("1.1", 10.0, 2, True, "Да, конечно.")
    unit = U(2, 11, 25, "thesis", 5, "2.1-2", summary="Тема начала")
    predecessor = U(1, 0, 10, "aside", 2, "1.1")
    lookup = {2: unit, 1: predecessor} if repair == "back_context" else {2: unit}

    def sentences(refs):
        if refs == "2.1-2":
            return [first, invalid]
        return [x for x in (first, invalid, prev) if x[0] == refs]

    base = AutoParams(context_start=True, min_sec=1, start_strict=True, answer_start=True,
                      context_drop_words=4 if repair == "short_drop" else 0,
                      context_later=repair == "later_sentence", context_later_min_sec=1,
                      context_back=1, context_max_sec=15)
    old, _, old_reason = context_start([unit], lookup, base, sentences, seed_id=2)
    assert old and old_reason is None
    if repair == "back_context":
        assert old[0]["id"] == 1
    else:
        assert old[0]["refs"] == "2.2"

    guarded, _, why = context_start([unit], lookup, replace(base, fix_body_start=True),
                                     sentences, seed_id=2)
    assert guarded is None and why


def _a4_fx9a_units():
    """Synthetic TC9a: the preferred next unit overflows; the previous one fits."""
    units = [U(4, 0, 25, "thesis", 3, "4.1"),
             U(5, 25, 20, "explanation", 4, "5.1"),
             U(6, 45, 35, "conclusion", 5, "6.1")]
    return {u["id"]: u for u in units}


def test_a4_fx9a_retries_other_side_after_preferred_overflow():
    """The frozen helper loses FX-9a; A4 can publish the 45-second [4,5] passage."""
    from autoreels.cloud.autocut import build_passage

    by = _a4_fx9a_units()
    base = AutoParams(min_sec=25, target_sec=48, max_sec=50, passage_gap_sec=30)
    assert build_passage(by[5], by, base) is None
    repaired = build_passage(by[5], by, replace(base, fix_passage_side=True))
    assert repaired is not None and [u["id"] for u in repaired] == [4, 5]
    assert sum(ac._dur(u) for u in repaired) == 45


def test_a4_both_overlong_sides_fail_closed():
    from autoreels.cloud.autocut import build_passage

    by = _a4_fx9a_units()
    by[4] = {**by[4], "t0": -10.0}  # previous 35s > the remaining 30s
    p = AutoParams(min_sec=25, target_sec=48, max_sec=50, fix_passage_side=True)
    assert build_passage(by[5], by, p) is None


def test_a4_overlong_previous_side_can_retry_next():
    from autoreels.cloud.autocut import build_passage

    by = _a4_fx9a_units()
    by[4] = {**by[4], "t0": -10.0}  # previous duration is 35s
    by[5] = {**by[5], "standalone": False, "refers": 4}  # first choose previous
    by[6] = {**by[6], "t1": 70.0}  # next duration is 25s and fits
    p = AutoParams(min_sec=25, target_sec=48, max_sec=50)
    assert build_passage(by[5], by, p) is None
    repaired = build_passage(by[5], by, replace(p, fix_passage_side=True))
    assert repaired is not None and [u["id"] for u in repaired] == [5, 6]
    assert sum(ac._dur(u) for u in repaired) == 45


def test_a4_closed_side_never_bypasses_existing_eligibility_rules():
    from autoreels.cloud.autocut import build_passage

    by = _a4_fx9a_units()
    p = AutoParams(min_sec=25, target_sec=48, max_sec=50, fix_passage_side=True)
    assert build_passage(by[5], by, p, taken={4}) is None
    by[4] = {**by[4], "topic": 99}
    assert build_passage(by[5], by, p) is None


@pytest.mark.parametrize("seed_role,stands,expected", [
    ("question", True, [5, 6]),
    ("explanation", False, [4, 5]),
])
def test_a4_no_overflow_preserves_original_preference(seed_role, stands, expected):
    from autoreels.cloud.autocut import build_passage

    units = [U(4, 0, 15, "thesis", 3, "4.1"),
             U(5, 15, 20, seed_role, 4, "5.1", standalone=stands, refers=4),
             U(6, 35, 20, "conclusion", 5, "6.1")]
    by = {u["id"]: u for u in units}
    p = AutoParams(min_sec=10, target_sec=32, max_sec=65)
    legacy = build_passage(by[5], by, p)
    guarded = build_passage(by[5], by, replace(p, fix_passage_side=True))
    assert [u["id"] for u in legacy] == expected
    assert [u["id"] for u in guarded] == expected


def test_a4_iteration_bound_even_if_both_sides_overflow():
    """Count actual loop-body entries, not a proxy such as duration calls."""
    import inspect
    import sys
    from autoreels.cloud.autocut import build_passage

    by = _a4_fx9a_units()
    by[4] = {**by[4], "t0": -10.0}
    source, first_line = inspect.getsourcelines(build_passage)
    body_line = first_line + next(i for i, row in enumerate(source) if "prv, nxt =" in row)
    entries = []

    def count_body(frame, event, arg):
        if frame.f_code is build_passage.__code__ and event == "line" and frame.f_lineno == body_line:
            entries.append(1)
        return count_body

    previous_trace = sys.gettrace()
    try:
        sys.settrace(count_body)
        result = build_passage(by[5], by, AutoParams(min_sec=25, target_sec=48, max_sec=50,
                                                    fix_passage_side=True))
    finally:
        sys.settrace(previous_trace)
    assert result is None
    assert len(entries) == 3  # close next, close previous, discover both closed
    assert len(entries) <= len(by) + 2


def test_a4_flag_default_off_and_typed_config():
    from autoreels.core.config import AutocutConfig

    assert AutoParams().fix_passage_side is False
    assert AutocutConfig().fix_passage_side is False
    assert AutocutConfig.model_validate({"fix_passage_side": True}).fix_passage_side is True
    with pytest.raises(Exception):
        AutocutConfig.model_validate({"fix_passage_side": "nonboolean"})


def test_a4_cli_maps_flag_without_provider(tmp_path, monkeypatch):
    from autoreels import __main__ as cli

    _montage_project(tmp_path)
    cfg = tmp_path / "config" / "r0.yaml"
    content = cfg.read_text(encoding="utf-8")
    assert "  context_start: " in content
    cfg.write_text(content.replace("  context_start: ", "  fix_passage_side: true\n  context_start: "),
                   encoding="utf-8")
    seen = []
    original = ac.propose

    def capture(units, params, *args, **kwargs):
        seen.append(params.fix_passage_side)
        return original(units, params, *args, **kwargs)

    monkeypatch.setattr(ac, "propose", capture)
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False, clips=2) == 0
    assert seen and all(seen)
