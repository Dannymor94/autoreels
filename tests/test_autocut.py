"""M56: montage lines proposed from the map (cloud/autocut.py, arl autocut)."""
from __future__ import annotations

import json

from autoreels.cloud.autocut import AutoParams, build_clip, eligible, leans_on, propose


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
                   .replace("  clips: 5\n", "  clips: 1\n")
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
                   .replace("  clips: 5\n", "  clips: 1\n").replace("  hook_min_words: 4 ", "  hook_min_words: 2 ")
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
                   .replace("  clips: 5\n", "  clips: 1\n").replace("  hook_min_words: 4 ", "  hook_min_words: 2 ")
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
                   .replace("  clips: 5\n", "  clips: 2\n").replace("  hook_min_words: 4 ", "  hook_min_words: 2 "),
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
                       .replace("  clips: 5\n", "  clips: 2\n").replace("  hook_min_words: 4 ", "  hook_min_words: 2 ")
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
                       .replace("  clips: 5\n", "  clips: 2\n").replace("  hook_min_words: 4 ", "  hook_min_words: 2 ")
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
                       .replace("  hook_llm: auto ", "  hook_llm: none ").replace("  clips: 5\n", "  clips: 1\n"),
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
                       .replace("  clips: 5\n", "  clips: 1\n")
                       .replace("  keywords_voice: false ", "  keywords_voice: true "), encoding="utf-8")   # M118: off by default
        r0 = cli.load_r0_config(cfg)
        assert r0.autocut.keywords and r0.autocut.keywords_voice
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
