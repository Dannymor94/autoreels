"""M233-G0: pure, synthetic-safe contract for blinded paired reel evaluation.

No media access, I/O, random module, providers, or pipeline integration.
"""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence


CRITERIA = ("hook", "start", "coherence", "fidelity", "ending", "audio", "visual", "subtitles")
REASONS = frozenset({
    "HOOK_WEAK", "START_DEPENDENT", "THOUGHT_INCOMPLETE", "FACT_MISMATCH",
    "END_ABRUPT", "AUDIO_CUT", "VISUAL_CUT", "SUBTITLE_DRIFT", "DUPLICATE", "OTHER",
})
VERDICTS = frozenset({"keep", "fix", "drop"})


class EvaluationError(ValueError):
    """Invalid experiment input; fail closed rather than silently excluding data."""


def canonical_hash(value: Mapping[str, Any]) -> str:
    """Hash a JSON-compatible effective configuration, independent of dict order."""
    try:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                             allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvaluationError("invalid canonical configuration") from exc
    return sha256(encoded).hexdigest()


def blind_order(seed: str, pair_id: str) -> tuple[str, str]:
    if not seed or not pair_id:
        raise EvaluationError("seed and pair_id required")
    digest = sha256(json.dumps([seed, pair_id], ensure_ascii=False).encode()).digest()
    return ("baseline", "candidate") if digest[0] & 1 == 0 else ("candidate", "baseline")


def validate_pair(pair: Mapping[str, Any]) -> None:
    required = {"pair_id", "source_hash", "baseline_hash", "candidate_hash"}
    if not required.issubset(pair):
        raise EvaluationError("missing pair provenance")
    if any(not isinstance(pair[k], str) or not pair[k] for k in required):
        raise EvaluationError("empty pair provenance")
    if pair["baseline_hash"] == pair["candidate_hash"]:
        raise EvaluationError("duplicate variant artifact")


def validate_rating(rating: Mapping[str, Any]) -> None:
    if rating.get("rubric_version") != 1:
        raise EvaluationError("unknown rubric")
    if rating.get("blind_variant") not in ("A", "B") or rating.get("verdict") not in VERDICTS:
        raise EvaluationError("invalid variant or verdict")
    if not isinstance(rating.get("rating_id"), str) or not rating["rating_id"]:
        raise EvaluationError("missing rating id")
    if not isinstance(rating.get("pair_id"), str) or not rating["pair_id"]:
        raise EvaluationError("missing pair id")
    scores = rating.get("scores")
    if not isinstance(scores, dict) or set(scores) != set(CRITERIA):
        raise EvaluationError("invalid score dimensions")
    if any(not (type(v) is int and 1 <= v <= 5 or v == "not_rateable") for v in scores.values()):
        raise EvaluationError("scores must be 1..5 or not_rateable")
    reasons = rating.get("reasons")
    if not isinstance(reasons, list) or any(r not in REASONS for r in reasons):
        raise EvaluationError("invalid reason code")


def paired_summary(pairs: Sequence[Mapping[str, Any]], ratings: Sequence[Mapping[str, Any]],
                   *, seed: str, frozen: bool, media_go_ref: str | None) -> dict[str, Any]:
    """Analyze only frozen, approved ratings; no source paths or unblinding export."""
    if not frozen or not media_go_ref:
        raise EvaluationError("frozen ratings and explicit media approval required")
    indexed = {}
    for pair in pairs:
        validate_pair(pair)
        pid = pair["pair_id"]
        if pid in indexed:
            raise EvaluationError("duplicate pair id")
        indexed[pid] = pair
    seen_ids, by_pair = set(), {}
    for rating in ratings:
        validate_rating(rating)
        rid, pid, arm = rating["rating_id"], rating["pair_id"], rating["blind_variant"]
        if rid in seen_ids or pid not in indexed or (pid, arm) in by_pair:
            raise EvaluationError("duplicate rating or unknown pair")
        seen_ids.add(rid)
        by_pair[pid, arm] = rating
    counts = Counter()
    for pid in sorted(indexed):
        a, b = by_pair.get((pid, "A")), by_pair.get((pid, "B"))
        if a is None or b is None:
            counts["missing_pairs"] += 1
            continue
        first, _ = blind_order(seed, pid)
        base = a if first == "baseline" else b
        cand = b if first == "baseline" else a
        bk, ck = base["verdict"] == "keep", cand["verdict"] == "keep"
        counts["rateable_pairs"] += 1
        counts["baseline_keep"] += bk
        counts["candidate_keep"] += ck
        counts["candidate_wins" if ck and not bk else "baseline_wins" if bk and not ck else "ties"] += 1
    n = counts["rateable_pairs"]
    return {k: counts[k] for k in ("rateable_pairs", "missing_pairs", "baseline_keep",
                                    "candidate_keep", "candidate_wins", "baseline_wins", "ties")} | {
        "keep_rate_delta": (counts["candidate_keep"] - counts["baseline_keep"]) / n if n else None,
        "total_pairs": len(indexed),
    }
