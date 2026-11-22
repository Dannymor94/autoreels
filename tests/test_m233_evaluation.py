"""Synthetic-only M233-G0 evaluation contract tests."""

import pytest

from autoreels.evaluation import (
    CRITERIA, EvaluationError, blind_order, canonical_hash, paired_summary,
    validate_pair, validate_rating,
)


def pair(pid):
    return dict(pair_id=pid, source_hash="source-" + pid,
                baseline_hash="baseline-" + pid, candidate_hash="candidate-" + pid)


def rating(pid, arm, verdict, i):
    return dict(rating_id=str(i), pair_id=pid, blind_variant=arm, verdict=verdict,
                rubric_version=1, scores={key: 3 for key in CRITERIA}, reasons=[])


def test_hash_and_blinding_deterministic():
    assert canonical_hash({"a": 1, "b": [2, 3]}) == canonical_hash({"b": [2, 3], "a": 1})
    assert blind_order("seed", "one") == blind_order("seed", "one")
    with pytest.raises(EvaluationError):
        canonical_hash({"bad": float("nan")})


def test_bad_pair_rejected():
    with pytest.raises(EvaluationError):
        validate_pair({**pair("x"), "candidate_hash": "baseline-x"})
    with pytest.raises(EvaluationError):
        validate_pair({"pair_id": "x"})


@pytest.mark.parametrize("change", [
    {"rubric_version": 2}, {"verdict": "maybe"}, {"blind_variant": "baseline"},
    {"reasons": ["unlisted"]}, {"scores": {}},
])
def test_invalid_rating_rejected(change):
    with pytest.raises(EvaluationError):
        validate_rating({**rating("x", "A", "keep", 1), **change})


def test_no_unapproved_or_unfrozen_analysis():
    with pytest.raises(EvaluationError):
        paired_summary([], [], seed="seed", frozen=False, media_go_ref="GO")
    with pytest.raises(EvaluationError):
        paired_summary([], [], seed="seed", frozen=True, media_go_ref=None)


def test_known_pair_counts_and_missing_denominator():
    entries = [pair("1"), pair("2"), pair("3"), pair("4")]
    values = []
    for i, (pid, base, cand) in enumerate((("1", "fix", "keep"), ("2", "keep", "drop"),
                                            ("3", "keep", "keep"))):
        first, _ = blind_order("seed", pid)
        values.extend((rating(pid, "A", base if first == "baseline" else cand, i * 2),
                       rating(pid, "B", cand if first == "baseline" else base, i * 2 + 1)))
    out = paired_summary(entries, values, seed="seed", frozen=True, media_go_ref="synthetic-GO")
    assert out == dict(total_pairs=4, rateable_pairs=3, missing_pairs=1, baseline_keep=2,
                       candidate_keep=2, candidate_wins=1, baseline_wins=1, ties=1,
                       keep_rate_delta=0.0)


def test_duplicate_rating_and_pair_fail_closed():
    x = rating("1", "A", "keep", 1)
    for pairs, ratings in (([pair("1"), pair("1")], []), ([pair("1")], [x, x]),
                           ([pair("1")], [rating("missing", "A", "keep", 3)])):
        with pytest.raises(EvaluationError):
            paired_summary(pairs, ratings, seed="s", frozen=True, media_go_ref="GO")
