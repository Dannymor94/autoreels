"""M1.6 stage 4: short LLM scoring call.

Blocks from stages 1-3 go in; scores come out.
K=8 blocks per call ≈ 120 output tokens (vs 900 for full R0 call).
"""
from __future__ import annotations

import json

from autoreels.cloud.blocks import CandidateBlock

SCORE_BATCH_K = 8
SCORE_MAX_OUTPUT_TOKENS = 200

_TRAILING = "»\"')]"


def filter_no_terminal(
    blocks: list[CandidateBlock],
    *,
    density_guard: float = 0.75,
) -> tuple[list[CandidateBlock], list[CandidateBlock]]:
    """Pre-LLM gate: drop blocks that don't end with terminal punctuation (.?!…).

    Only activates when the source's terminal-punct density >= density_guard.
    Low density means the transcription model didn't add punctuation reliably,
    so the absence of a period is not a meaningful signal.

    Returns (kept, gated_out). When inactive, returns (blocks, []).
    """
    if not blocks:
        return list(blocks), []
    n_term = sum(1 for b in blocks if b.text.rstrip(_TRAILING)[-1:] in ".?!…")
    if n_term / len(blocks) < density_guard:
        return list(blocks), []
    kept      = [b for b in blocks if     b.text.rstrip(_TRAILING)[-1:] in ".?!…"]
    gated_out = [b for b in blocks if not b.text.rstrip(_TRAILING)[-1:] in ".?!…"]
    return kept, gated_out


def build_score_messages(
    blocks: list[CandidateBlock],
    *,
    system_text: str,
    fewshot_examples: list[dict],
) -> list[dict]:
    """Build chat messages for scoring a batch of blocks."""
    messages: list[dict] = [{"role": "system", "content": system_text}]
    for ex in fewshot_examples:
        messages.append({"role": "user", "content": ex["input"]})
        messages.append({"role": "assistant", "content": json.dumps(ex["output"], ensure_ascii=False)})
    user_content = "\n".join(f"[{b.id}] {b.text}" for b in blocks)
    messages.append({"role": "user", "content": user_content})
    return messages


def parse_score_response(raw: str | None) -> list[dict]:
    """Parse {"scores":[{"id":..., "score":N},...]} from LLM response.

    Raises ValueError on empty, invalid JSON, or missing 'scores' key.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise ValueError("empty response")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from e
    if not isinstance(obj, dict) or not isinstance(obj.get("scores"), list):
        raise ValueError("response missing 'scores' array")
    return obj["scores"]


def apply_llm_scores(blocks: list[CandidateBlock], id_to_score: dict[str, int]) -> int:
    """Set block.llm_score for each matched block. Returns count of matched blocks.

    Also clears llm_score_reason on any block that receives a score (rescues blocks
    that were marked 'missing' in pass 1 but scored in pass 2).
    """
    id_map = {b.id: b for b in blocks}
    count = 0
    for bid, score in id_to_score.items():
        if bid in id_map:
            id_map[bid].llm_score = float(score)
            id_map[bid].llm_score_reason = None
            count += 1
    return count


def score_blocks_batch(
    blocks: list[CandidateBlock],
    *,
    provider,
    system_text: str,
    fewshot_examples: list[dict],
    max_output_tokens: int = SCORE_MAX_OUTPUT_TOKENS,
    temperature: float = 0.0,
) -> dict[str, int]:
    """One LLM call for one batch. Returns {block_id: score}.

    If any batch ids are missing from the response, retries once with the same messages.
    Still-missing blocks get llm_score_reason='missing' set on the block object and are
    excluded from the returned dict (never treated as a low score).
    """
    from autoreels.cloud.providers import ProviderEmptyResponse, ProviderError, ProviderTimeout

    messages = build_score_messages(blocks, system_text=system_text, fewshot_examples=fewshot_examples)
    try:
        raw = provider.complete(messages, temperature=temperature)
    except (ProviderError, ProviderEmptyResponse, ProviderTimeout) as e:
        raise ValueError(f"provider error: {e}") from e
    entries = parse_score_response(raw)
    scores = {e["id"]: e["score"] for e in entries if "id" in e and "score" in e}

    missing = {b.id for b in blocks} - scores.keys()
    if missing:
        print(f"  ⚠ {len(missing)} id(s) missing from response, retrying batch", flush=True)
        try:
            raw2 = provider.complete(messages, temperature=temperature)
            for e in parse_score_response(raw2):
                if "id" in e and "score" in e and e["id"] not in scores:
                    scores[e["id"]] = e["score"]
        except (ProviderError, ProviderEmptyResponse, ProviderTimeout, ValueError) as e2:
            print(f"  ⚠ retry failed: {e2}", flush=True)
        still_missing = {b.id for b in blocks} - scores.keys()
        if still_missing:
            id_map = {b.id: b for b in blocks}
            for bid in still_missing:
                if bid in id_map:
                    id_map[bid].llm_score_reason = "missing"
            print(f"  ⚠ still missing after retry, reason='missing': {[bid[:8] for bid in still_missing]}", flush=True)

    return scores


def score_all_blocks(
    blocks: list[CandidateBlock],
    *,
    provider,
    system_text: str,
    fewshot_examples: list[dict],
    batch_k: int = SCORE_BATCH_K,
    max_output_tokens: int = SCORE_MAX_OUTPUT_TOKENS,
    temperature: float = 0.0,
    score_passes: int = 1,
) -> dict[str, int]:
    """Score all blocks in batches. Sets block.llm_score; returns merged {id: score}.

    score_passes=2: scores each block twice (second pass rotated by batch_k//2 so neighbours
    differ) and sets llm_score to mean(pass1, pass2). If a block is present in only one
    pass, that score is used. Uses 2× the token budget.
    """
    def _one_pass(ordered_blocks: list[CandidateBlock]) -> dict[str, int]:
        pass_scores: dict[str, int] = {}
        for i in range(0, len(ordered_blocks), batch_k):
            batch = ordered_blocks[i : i + batch_k]
            try:
                scores = score_blocks_batch(
                    batch,
                    provider=provider,
                    system_text=system_text,
                    fewshot_examples=fewshot_examples,
                    max_output_tokens=max_output_tokens,
                    temperature=temperature,
                )
            except ValueError as e:
                print(f"  ⚠ score_all_blocks batch {i // batch_k + 1} failed: {e}", flush=True)
                continue
            pass_scores.update(scores)
        return pass_scores

    all_scores = _one_pass(blocks)

    if score_passes >= 2:
        # Second pass rotated by half a batch so every block sees different neighbours.
        # Merge: mean when both passes score a block; if one pass is missing, use the other.
        rotated = blocks[batch_k // 2 :] + blocks[: batch_k // 2]
        scores2 = _one_pass(rotated)
        merged: dict[str, int] = {}
        for bid in set(all_scores) | set(scores2):
            s1, s2 = all_scores.get(bid), scores2.get(bid)
            if s1 is not None and s2 is not None:
                merged[bid] = round((s1 + s2) / 2)
            else:
                if s1 is None:
                    print(f"  ℹ {bid[:8]} missing in pass 1, using pass 2 score", flush=True)
                else:
                    print(f"  ℹ {bid[:8]} missing in pass 2, using pass 1 score", flush=True)
                merged[bid] = s1 if s1 is not None else s2  # type: ignore[assignment]
        all_scores = merged

    apply_llm_scores(blocks, all_scores)
    return all_scores
