"""M138: the owner's taste (cloud/taste.py) — learned from his clips, it only orders autocut's proposals."""
from __future__ import annotations

import json

import pytest

from autoreels.cloud.autocut import AutoParams, propose
from autoreels.cloud.taste import clip_taste, features, fit, load, logit, owner_rows
from autoreels.core.config import AutocutConfig
from tests.test_autocut import _units


def _rows():
    # the owner starts on long thoughts and takes the strong ones (m137), on a toy set
    rows = []
    for i in range(40):
        u = {"id": i, "t0": float(i * 20), "t1": float(i * 20 + (25 if i % 4 == 0 else 8)), "punch": 5 if i % 2 else 2,
             "role": "thesis", "text": "Слово слово слово.", "voice": {"energy": 50, "level_db": -30, "rate": 2.0}}
        rows.append((features(u, 800.0), int(i % 2 == 1), int(i % 4 == 0)))
    return rows


def test_off_by_default():
    assert AutoParams().taste_weight == 0.0
    assert AutocutConfig().taste_weight == 0.0 and AutocutConfig().taste_model == "config/taste.json"


def test_fit_learns_the_direction_and_round_trips(tmp_path):
    m = fit(_rows(), provenance="toy")
    long_ = features({"t0": 0.0, "t1": 25.0, "punch": 2, "text": "А.", "voice": {}}, 800.0)
    short = features({"t0": 0.0, "t1": 8.0, "punch": 2, "text": "А.", "voice": {}}, 800.0)
    assert logit(m, long_, "start") > logit(m, short, "start")
    strong = features({"t0": 0.0, "t1": 8.0, "punch": 5, "text": "А.", "voice": {}}, 800.0)
    assert logit(m, strong, "taken") > logit(m, short, "taken")
    p = tmp_path / "taste.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    assert load(p)["heads"] == m["heads"] and load(p)["provenance"] == "toy"


def test_fit_refuses_a_head_without_both_labels():
    rows = [(r[0], 0, r[2]) for r in _rows()]
    with pytest.raises(ValueError):
        fit(rows)


def test_owner_rows_label_taken_and_start():
    units = [{"id": 1, "t0": 0.0, "t1": 10.0}, {"id": 2, "t0": 10.0, "t1": 20.0}, {"id": 3, "t0": 50.0, "t1": 60.0}]
    man = {"reels": [{"start": 9.5, "end": 21.0, "segments": [{"start": 9.5, "end": 21.0}]}]}
    rows = owner_rows(man, units)
    assert [(r[1], r[2]) for r in rows] == [(0, 0), (1, 1), (0, 0)]


def test_taste_only_orders_and_weight_zero_is_as_before():
    units = _units()
    base = propose(units, AutoParams(clips=5, target_sec=40))
    same = propose(units, AutoParams(clips=5, target_sec=40), taste=lambda clip: 100.0)     # weight 0: ignored
    assert [(p.units, p.score) for p in same] == [(p.units, p.score) for p in base]
    last = base[-1].units
    liked = propose(units, AutoParams(clips=5, target_sec=40, taste_weight=10.0),
                    taste=lambda clip: 1.0 if [u["id"] for u in clip] == last else -1.0)
    assert liked[0].units == last                                  # the clip the owner would like comes first
    assert sorted(p.units for p in liked) == sorted(p.units for p in base)   # the same clips, another order
    assert any("вкус владельца" in n for n in liked[0].notes)


def test_clip_taste_mixes_taken_and_start():
    m = fit(_rows())
    u_long = {"id": 1, "t0": 0.0, "t1": 25.0, "punch": 5, "text": "А.", "voice": {}}
    u_short = {"id": 2, "t0": 30.0, "t1": 38.0, "punch": 2, "text": "Б.", "voice": {}}
    assert clip_taste([u_long, u_short], m, 800.0) > clip_taste([u_short, u_long], m, 800.0)
    assert clip_taste([], m, 800.0) == 0.0


def test_m140_fill_pool_adds_only_new_thoughts_and_orders_by_score():
    from autoreels.cloud.autocut import Proposal, fill_pool
    mk = lambda units, score: Proposal(units=units, pieces="", hook=None, title="", caption="", score=score, seconds=30.0)
    pool = [mk([1, 2], 80), mk([5], 70)]
    extra = [mk([2, 3], 99), mk([7, 8], 75), mk([8, 9], 90)]
    out = fill_pool(pool, extra)
    assert [o.units for o in out] == [[1, 2], [7, 8], [5]]       # [2,3] shares 2; [8,9] shares 8 with the added one
    assert fill_pool(pool, []) == sorted(pool, key=lambda o: -o.score)
    assert AutocutConfig().fill_seed_punch == 0
