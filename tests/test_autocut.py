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
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("  min_sec: 30 ", "  min_sec: 10 "), encoding="utf-8")
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
