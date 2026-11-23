"""M233-G0: synthetic regression, immutable snapshot and negative input tests."""
import pytest

from autoreels.evaluation import (
    CRITERIA, EvaluationError, blind_order, canonical_hash, paired_summary,
    reviewer_projection, snapshot_hash, validate_pair, validate_rating,
)


def pair(pid):
    return dict(pair_id=pid, source_hash="a" * 64, baseline_hash="b" * 64,
                candidate_hash="c" * 64)


def rating(pid, arm, verdict, i):
    return dict(rating_id=f"r{i}", reviewer_id="owner", pair_id=pid,
                blind_variant=arm, verdict=verdict, rubric_version=1,
                scores={key: 3 for key in CRITERIA}, reasons=[])


def experiment(pairs, ratings, **overrides):
    record = dict(schema_version=1, experiment_id="pilot1", code_sha="a" * 40,
                  seed="seed", frozen=True, media_go_ref="G0_SYNTHETIC",
                  snapshot_hash=snapshot_hash(pairs, ratings))
    record.update(overrides)
    return record


def summary(pairs, ratings, exp=None, expected=None):
    exp = experiment(pairs, ratings) if exp is None else exp
    return paired_summary(pairs, ratings, experiment=exp,
                          expected_experiment_hash=canonical_hash(exp) if expected is None else expected)


def test_pair_counts_missing_denominator_and_order():
    pairs = [pair(pid) for pid in ("p1", "p2", "p3", "p4")]
    ratings = []
    for i, (pid, base, cand) in enumerate((("p1", "fix", "keep"),
                                           ("p2", "keep", "drop"),
                                           ("p3", "keep", "keep"))):
        first, _ = blind_order("seed", pid)
        ratings += [rating(pid, "A", base if first == "baseline" else cand, i * 2),
                    rating(pid, "B", cand if first == "baseline" else base, i * 2 + 1)]
    expected = dict(total_pairs=4, rateable_pairs=3, missing_pairs=1,
                    baseline_keep=2, candidate_keep=2, candidate_wins=1,
                    baseline_wins=1, ties=1, keep_rate_delta=0.0)
    assert summary(pairs, ratings) == expected
    assert summary(list(reversed(pairs)), list(reversed(ratings))) == expected
    assert summary([], [])["keep_rate_delta"] is None


def test_snapshot_seed_and_verdict_changes_rejected_with_pinned_hash():
    pairs = [pair("p1")]
    ratings = [rating("p1", "A", "keep", 1), rating("p1", "B", "drop", 2)]
    exp = experiment(pairs, ratings)
    pinned = canonical_hash(exp)
    assert summary(pairs, ratings, exp, pinned)["rateable_pairs"] == 1
    with pytest.raises(EvaluationError):
        summary(pairs, [dict(ratings[0], verdict="drop"), ratings[1]], exp, pinned)
    with pytest.raises(EvaluationError):
        summary(pairs, ratings, dict(exp, seed="other"), pinned)
    with pytest.raises(EvaluationError):
        summary(pairs, ratings, dict(exp, snapshot_hash="d"*64), pinned)


@pytest.mark.parametrize("change", [
    {"frozen": "false"}, {"frozen": 1}, {"frozen": False},
    {"media_go_ref": " "}, {"media_go_ref": 123}, {"seed": ""},
    {"seed": 1}, {"schema_version": True}, {"schema_version": 1.0},
    {"experiment_id": "/private/thing"},
])
def test_experiment_fail_closed(change):
    exp = experiment([], [], **change)
    with pytest.raises(EvaluationError):
        summary([], [], exp)


@pytest.mark.parametrize("bad", [
    {1: "x"}, {"nested": {1: 2}}, [1, 2],
    {"f": float("nan")}, {"x": object()}, {"x": float("inf")},
])
def test_invalid_canonical_config(bad):
    with pytest.raises(EvaluationError):
        canonical_hash(bad)


def test_config_canonical_order_and_seed_stability():
    assert canonical_hash({"x": {"b": 2, "a": [1]}}) == canonical_hash({"x": {"a": [1], "b": 2}})
    assert blind_order("seed", "p1") == blind_order("seed", "p1")
    with pytest.raises(EvaluationError):
        blind_order("\ud800", "p1")


@pytest.mark.parametrize("bad", [
    None, [], {}, {"pair_id": "/private/owner.mp4"},
    dict(pair("p1"), source_path="/private/owner.mp4"),
])
def test_invalid_pair(bad):
    with pytest.raises(EvaluationError):
        validate_pair(bad)


@pytest.mark.parametrize("bad", [
    None, [], dict(rating("p1", "A", "keep", 1), rubric_version=True),
    dict(rating("p1", "A", "keep", 1), rubric_version=1.0),
    dict(rating("p1", "A", "keep", 1), baseline_or_candidate="baseline"),
    dict(rating("p1", "A", "keep", 1), verdict=[]),
    dict(rating("p1", "A", "keep", 1), reasons={}),
    dict(rating("p1", "A", "keep", 1), scores={"hook": True}),
])
def test_invalid_rating(bad):
    with pytest.raises(EvaluationError):
        validate_rating(bad)


def test_blind_projection_is_anonymous():
    assert reviewer_projection(pair("p1")) == {"pair_id": "p1", "variants": ("A", "B")}


def test_duplicate_pair_arm_rating_and_unknown_pair_rejected():
    p = [pair("p1")]
    r = rating("p1", "A", "keep", 1)
    for pairs, ratings in (([p[0], p[0]], []),
                           (p, [r, r]),
                           (p, [r, dict(r, rating_id="r2")]),
                           (p, [rating("missing", "A", "keep", 3)])):
        with pytest.raises(EvaluationError):
            snapshot_hash(pairs, ratings)


def test_score_boundaries_and_all_verdicts_reasons():
    r = rating("p1", "A", "keep", 1)
    for verdict in ("keep", "fix", "drop"):
        validate_rating(dict(r, verdict=verdict,
                             reasons=sorted(["HOOK_WEAK", "START_DEPENDENT", "OTHER"]),
                             scores={k: "not_rateable" if i % 2 else 5 for i, k in enumerate(CRITERIA)}))
    for invalid in (True, 1.0, 0, 6, float("nan")):
        with pytest.raises(EvaluationError):
            validate_rating(dict(r, scores={**r["scores"], "hook": invalid}))


def test_real_git_sha40_accepted_and_wrong_width_rejected():
    pairs, ratings = [], []
    exp = experiment(pairs, ratings, code_sha="ab7ba2238e1127c39ec8da79c74a958edf348515")
    assert summary(pairs, ratings, exp)["total_pairs"] == 0
    for bad in ("a" * 64, "a" * 39, "g" * 40, 123, True):
        with pytest.raises(EvaluationError):
            summary(pairs, ratings, experiment(pairs, ratings, code_sha=bad))


def test_cycle_and_excessive_nesting_are_controlled_failures():
    for cyclic in ({}, []):
        if isinstance(cyclic, dict):
            cyclic["nested"] = cyclic
        else:
            cyclic.append(cyclic)
        with pytest.raises(EvaluationError):
            canonical_hash({"nested": cyclic})
    nested = None
    for _ in range(80):
        nested = {"next": nested}
    with pytest.raises(EvaluationError):
        canonical_hash(nested)


def test_shared_acyclic_alias_is_permitted():
    shared = {"text": [1, 2]}
    assert canonical_hash({"a": shared, "b": shared}) == canonical_hash({"a": {"text": [1, 2]}, "b": {"text": [1, 2]}})
