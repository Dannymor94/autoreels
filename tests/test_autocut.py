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
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("  min_sec: 25 ", "  min_sec: 10 ").replace("  hook_llm: auto ", "  hook_llm: none "), encoding="utf-8")
    r0 = cli.load_r0_config(cfg)
    assert r0.autocut.min_sec == 10
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
    assert "# fingerprint: " in text and "M1 " in text and "| t: тезис про маски" in text and "предложено сборок 1" in out
    rc = cli._blocks_do_apply(str(draft), root=tmp_path, cache_dir=str(tmp_path / "cache"), labeler="auto")
    err = capsys.readouterr().err
    assert rc == 0, err[-1500:]
    man = Manifest.model_validate_json((tmp_path / "reviews" / "v.review.json").read_text())
    (mont,) = man.reels
    assert mont.montage.startswith("M1 ") and mont.title_overlay == "тезис про маски"
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
                   .replace("  clips: 5\n", "  clips: 1\n"), encoding="utf-8")
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
                   .replace("  clips: 5\n", "  clips: 1\n").replace("  hook_min_words: 4 ", "  hook_min_words: 2 "),
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
