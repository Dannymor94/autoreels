"""M233-G0: pure validation and blinded paired evaluation.

The caller MUST pin expected_experiment_hash in a trusted record outside this
module. This module does not authenticate or persist owner approvals.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import math
import re
from typing import Any, Mapping, Sequence

CRITERIA = ("hook", "start", "coherence", "fidelity", "ending", "audio", "visual", "subtitles")
REASONS = frozenset({"HOOK_WEAK", "START_DEPENDENT", "THOUGHT_INCOMPLETE", "FACT_MISMATCH",
                     "END_ABRUPT", "AUDIO_CUT", "VISUAL_CUT", "SUBTITLE_DRIFT", "DUPLICATE", "OTHER"})
VERDICTS = frozenset({"keep", "fix", "drop"})
_OPAQUE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z", re.ASCII)
_HASH = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
_PAIR_FIELDS = frozenset({"pair_id", "source_hash", "baseline_hash", "candidate_hash"})
_RATING_FIELDS = frozenset({"rating_id", "pair_id", "blind_variant", "reviewer_id", "rubric_version", "scores", "verdict", "reasons"})
_EXPERIMENT_FIELDS = frozenset({"schema_version", "experiment_id", "code_sha", "seed", "frozen", "media_go_ref", "snapshot_hash"})


class EvaluationError(ValueError):
    """Invalid experiment input; fail closed without exposing source data."""


def _mapping(value: Any, fields: frozenset[str] | None = None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(k) is not str for k in value):
        raise EvaluationError("expected string-key mapping")
    if fields is not None and set(value) != fields:
        raise EvaluationError("unexpected or missing fields")
    return value


def _canonical_json(value: Any) -> bytes:
    # A recursion stack permits shared aliases but rejects cycles.
    active: set[int] = set()

    def check(v: Any, depth: int = 0) -> None:
        if depth > 64:
            raise EvaluationError("configuration nesting exceeds limit")
        if isinstance(v, (Mapping, list, tuple)):
            ident = id(v)
            if ident in active:
                raise EvaluationError("cyclic configuration")
            active.add(ident)
            try:
                if isinstance(v, Mapping):
                    _mapping(v)
                    children = v.values()
                else:
                    children = v
                for child in children:
                    check(child, depth + 1)
            finally:
                active.remove(ident)
        elif v is None or type(v) in (str, int, bool):
            return
        elif type(v) is float:
            if not math.isfinite(v):
                raise EvaluationError("nonfinite number")
        else:
            raise EvaluationError("non-JSON configuration value")
    check(value)
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True,
                          allow_nan=False, separators=(",", ":")).encode("ascii")
    except (TypeError, ValueError, UnicodeError, OverflowError) as exc:
        raise EvaluationError("invalid canonical value") from exc


def canonical_hash(value: Mapping[str, Any]) -> str:
    """SHA256 of strict string-key JSON-compatible mapping."""
    _mapping(value)
    return sha256(_canonical_json(value)).hexdigest()


def _opaque(value: Any) -> bool:
    return type(value) is str and _OPAQUE.fullmatch(value) is not None


def _hash(value: Any) -> bool:
    return type(value) is str and _HASH.fullmatch(value) is not None


def _git_sha(value: Any) -> bool:
    return type(value) is str and _GIT_SHA.fullmatch(value) is not None


def blind_order(seed: str, pair_id: str) -> tuple[str, str]:
    if not _opaque(seed) or not _opaque(pair_id):
        raise EvaluationError("invalid seed or opaque pair id")
    digest = sha256(_canonical_json([seed, pair_id])).digest()
    return ("baseline", "candidate") if digest[0] & 1 == 0 else ("candidate", "baseline")


def validate_pair(pair: Mapping[str, Any]) -> None:
    row = _mapping(pair, _PAIR_FIELDS)
    if not _opaque(row["pair_id"]) or not all(_hash(row[k]) for k in ("source_hash", "baseline_hash", "candidate_hash")):
        raise EvaluationError("invalid pair provenance")
    if row["baseline_hash"] == row["candidate_hash"]:
        raise EvaluationError("duplicate variants")


def validate_rating(rating: Mapping[str, Any]) -> None:
    row = _mapping(rating, _RATING_FIELDS)
    if not all(_opaque(row[k]) for k in ("rating_id", "pair_id", "reviewer_id")):
        raise EvaluationError("invalid opaque rating id")
    if type(row["rubric_version"]) is not int or row["rubric_version"] != 1:
        raise EvaluationError("unknown rubric")
    if type(row["blind_variant"]) is not str or row["blind_variant"] not in ("A", "B"):
        raise EvaluationError("invalid blind variant")
    if type(row["verdict"]) is not str or row["verdict"] not in VERDICTS:
        raise EvaluationError("invalid verdict")
    scores = _mapping(row["scores"], frozenset(CRITERIA))
    if any(not (type(v) is int and 1 <= v <= 5 or v == "not_rateable") for v in scores.values()):
        raise EvaluationError("invalid score")
    reasons = row["reasons"]
    if type(reasons) is not list or any(type(r) is not str or r not in REASONS for r in reasons) or len(reasons) != len(set(reasons)):
        raise EvaluationError("invalid reasons")


def snapshot_hash(pairs: Sequence[Mapping[str, Any]], ratings: Sequence[Mapping[str, Any]]) -> str:
    """Canonical full snapshot digest insensitive to record ordering."""
    if not isinstance(pairs, (list, tuple)) or not isinstance(ratings, (list, tuple)):
        raise EvaluationError("expected sequences")
    seen_pairs, seen_ratings, seen_arms = set(), set(), set()
    for p in pairs:
        validate_pair(p)
        if p["pair_id"] in seen_pairs:
            raise EvaluationError("duplicate pair")
        seen_pairs.add(p["pair_id"])
    for r in ratings:
        validate_rating(r)
        key = (r["pair_id"], r["blind_variant"])
        if r["rating_id"] in seen_ratings or key in seen_arms or r["pair_id"] not in seen_pairs:
            raise EvaluationError("duplicate rating or unknown pair")
        seen_ratings.add(r["rating_id"])
        seen_arms.add(key)
    return canonical_hash({
        "pairs": sorted(pairs, key=lambda p: p["pair_id"]),
        "ratings": sorted(ratings, key=lambda r: (r["pair_id"], r["blind_variant"])),
    })


def reviewer_projection(pair: Mapping[str, Any]) -> dict[str, Any]:
    """Safe first-pass public labels only; no source or arm identity."""
    validate_pair(pair)
    return {"pair_id": pair["pair_id"], "variants": ("A", "B")}


def paired_summary(pairs: Sequence[Mapping[str, Any]], ratings: Sequence[Mapping[str, Any]],
                   *, experiment: Mapping[str, Any], expected_experiment_hash: str) -> dict[str, Any]:
    """Compare frozen ratings bound to an externally pinned experiment digest.

    Recomputing expected_experiment_hash from attacker-controlled experiment
    data is NOT authorization; callers must supply a trusted stored digest.
    """
    exp = _mapping(experiment, _EXPERIMENT_FIELDS)
    if not _hash(expected_experiment_hash) or canonical_hash(exp) != expected_experiment_hash:
        raise EvaluationError("experiment digest mismatch")
    if type(exp["schema_version"]) is not int or exp["schema_version"] != 1:
        raise EvaluationError("unknown experiment schema")
    if not _opaque(exp["experiment_id"]) or not _git_sha(exp["code_sha"]):
        raise EvaluationError("invalid experiment identity")
    if exp["frozen"] is not True or not _opaque(exp["media_go_ref"]) or not _opaque(exp["seed"]):
        raise EvaluationError("experiment is not frozen and approved")
    if not _hash(exp["snapshot_hash"]) or exp["snapshot_hash"] != snapshot_hash(pairs, ratings):
        raise EvaluationError("rating snapshot mismatch")
    by_pair = {(r["pair_id"], r["blind_variant"]): r for r in ratings}
    counts = Counter()
    for pair in sorted(pairs, key=lambda row: row["pair_id"]):
        pid = pair["pair_id"]
        a, b = by_pair.get((pid, "A")), by_pair.get((pid, "B"))
        if a is None or b is None:
            counts["missing_pairs"] += 1
            continue
        first, _ = blind_order(exp["seed"], pid)
        base, cand = (a, b) if first == "baseline" else (b, a)
        bk, ck = base["verdict"] == "keep", cand["verdict"] == "keep"
        counts["rateable_pairs"] += 1
        counts["baseline_keep"] += int(bk)
        counts["candidate_keep"] += int(ck)
        counts["candidate_wins" if ck and not bk else "baseline_wins" if bk and not ck else "ties"] += 1
    n = counts["rateable_pairs"]
    return {k: counts[k] for k in ("rateable_pairs", "missing_pairs", "baseline_keep", "candidate_keep",
                                    "candidate_wins", "baseline_wins", "ties")} | {
        "keep_rate_delta": (counts["candidate_keep"] - counts["baseline_keep"]) / n if n else None,
        "total_pairs": len(pairs),
    }
