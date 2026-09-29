"""Tests for M1.6 stage 4: LLM block scoring (score_blocks.py).

All mocked — no network, no LLM.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from autoreels.cloud.blocks import CandidateBlock, _Line, topk_filter
from autoreels.cloud.providers import ProviderError
from autoreels.cloud.score_blocks import (
    apply_llm_scores,
    build_score_messages,
    filter_no_terminal,
    parse_score_response,
    score_all_blocks,
    score_blocks_batch,
)

FIXTURE = Path(__file__).parent / "fixtures" / "score_blocks_response.json"
_SYSTEM = "Score blocks. Return {\"scores\":[{\"id\":\"...\",\"score\":N}]}"


def _block(bid: str, text: str = "Текст блока.") -> CandidateBlock:
    return CandidateBlock(
        id=bid,
        start=0.0,
        end=30.0,
        duration=30.0,
        text=text,
        boundary_reason="sentence",
    )


class _MockProvider:
    def __init__(self, responses):
        """responses: list of str (raw JSON) or Exception instances."""
        self._responses = list(responses)
        self.calls = 0

    def complete(self, messages, *, temperature=0.0):
        r = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        if isinstance(r, Exception):
            raise r
        return r


# ----------------------------------------------------------------- build_score_messages

def test_build_score_messages_structure():
    blocks = [_block("aaa"), _block("bbb"), _block("ccc")]
    fewshot = [{"input": "inp", "output": {"scores": [{"id": "x", "score": 80}]}}]
    msgs = build_score_messages(blocks, system_text=_SYSTEM, fewshot_examples=fewshot)
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user" and msgs[1]["content"] == "inp"
    assert msgs[2]["role"] == "assistant"
    assert msgs[-1]["role"] == "user"
    last = msgs[-1]["content"]
    assert "[aaa]" in last and "[bbb]" in last and "[ccc]" in last


def test_build_score_messages_no_fewshot():
    blocks = [_block("zzz")]
    msgs = build_score_messages(blocks, system_text=_SYSTEM, fewshot_examples=[])
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "[zzz]" in msgs[1]["content"]


# ----------------------------------------------------------------- parse_score_response

def test_parse_valid_response():
    raw = '{"scores":[{"id":"abc123","score":82}]}'
    result = parse_score_response(raw)
    assert result == [{"id": "abc123", "score": 82}]


def test_parse_empty_scores_list():
    result = parse_score_response('{"scores":[]}')
    assert result == []


def test_parse_null_response():
    with pytest.raises(ValueError):
        parse_score_response(None)


def test_parse_empty_string():
    with pytest.raises(ValueError):
        parse_score_response("")


def test_parse_invalid_json():
    with pytest.raises(ValueError):
        parse_score_response("not json")


def test_parse_missing_scores_key():
    with pytest.raises(ValueError):
        parse_score_response('{"result":[]}')


# ----------------------------------------------------------------- score_blocks_batch

def test_score_blocks_batch_applies_scores():
    blocks = [_block("id1"), _block("id2")]
    raw = '{"scores":[{"id":"id1","score":88},{"id":"id2","score":72}]}'
    provider = _MockProvider([raw])
    result = score_blocks_batch(blocks, provider=provider, system_text=_SYSTEM, fewshot_examples=[])
    assert result == {"id1": 88, "id2": 72}
    assert provider.calls == 1


# ----------------------------------------------------------------- score_blocks_batch retry

def test_score_blocks_batch_no_retry_when_complete():
    """No retry when all ids are present in the first response."""
    blocks = [_block("id1"), _block("id2")]
    raw = '{"scores":[{"id":"id1","score":88},{"id":"id2","score":72}]}'
    provider = _MockProvider([raw])
    result = score_blocks_batch(blocks, provider=provider, system_text=_SYSTEM, fewshot_examples=[])
    assert provider.calls == 1
    assert result == {"id1": 88, "id2": 72}


def test_score_blocks_batch_missing_id_retried():
    """If an id is missing from the first response, batch is retried once."""
    blocks = [_block("id1"), _block("id2"), _block("id3")]
    raw1 = '{"scores":[{"id":"id1","score":88},{"id":"id2","score":72}]}'
    raw2 = '{"scores":[{"id":"id1","score":88},{"id":"id2","score":72},{"id":"id3","score":55}]}'
    provider = _MockProvider([raw1, raw2])
    result = score_blocks_batch(blocks, provider=provider, system_text=_SYSTEM, fewshot_examples=[])
    assert provider.calls == 2
    assert result["id3"] == 55
    assert all(b.llm_score_reason is None for b in blocks)


def test_score_blocks_batch_still_missing_after_retry():
    """If id is still missing after retry, block gets llm_score_reason='missing'."""
    blocks = [_block("id1"), _block("id2"), _block("id3")]
    raw = '{"scores":[{"id":"id1","score":88},{"id":"id2","score":72}]}'
    provider = _MockProvider([raw, raw])
    result = score_blocks_batch(blocks, provider=provider, system_text=_SYSTEM, fewshot_examples=[])
    assert provider.calls == 2
    assert "id3" not in result
    id3 = next(b for b in blocks if b.id == "id3")
    assert id3.llm_score_reason == "missing"
    assert blocks[0].llm_score_reason is None
    assert blocks[1].llm_score_reason is None


def test_score_blocks_batch_provider_error_retried():
    """ProviderError on first call → retry → success; all blocks scored."""
    blocks = [_block("id1"), _block("id2")]
    raw = '{"scores":[{"id":"id1","score":80},{"id":"id2","score":70}]}'
    provider = _MockProvider([ProviderError("Service overloaded"), raw])
    result = score_blocks_batch(blocks, provider=provider, system_text=_SYSTEM, fewshot_examples=[])
    assert provider.calls == 2
    assert result == {"id1": 80, "id2": 70}


def test_score_blocks_batch_provider_error_both_fail():
    """ProviderError on both attempts → raises ValueError."""
    blocks = [_block("id1")]
    provider = _MockProvider([ProviderError("overloaded"), ProviderError("still overloaded")])
    with pytest.raises(ValueError, match="provider error"):
        score_blocks_batch(blocks, provider=provider, system_text=_SYSTEM, fewshot_examples=[])
    assert provider.calls == 2


# ----------------------------------------------------------------- apply_llm_scores

def test_apply_llm_scores_sets_field():
    b1 = _block("x1")
    b2 = _block("x2")
    count = apply_llm_scores([b1, b2], {"x1": 80, "x2": 65})
    assert count == 2
    assert b1.llm_score == 80.0
    assert b2.llm_score == 65.0


def test_apply_llm_scores_ignores_missing():
    b = _block("known")
    count = apply_llm_scores([b], {"unknown": 90, "known": 75})
    assert count == 1
    assert b.llm_score == 75.0


# ----------------------------------------------------------------- score_all_blocks

def test_score_all_blocks_batches_correctly():
    blocks = [_block(f"b{i:02d}") for i in range(10)]

    def make_response(batch):
        return json.dumps({"scores": [{"id": b.id, "score": 70 + i} for i, b in enumerate(batch)]})

    responses = [
        make_response(blocks[:8]),
        make_response(blocks[8:]),
    ]
    provider = _MockProvider(responses)
    result = score_all_blocks(
        blocks, provider=provider, system_text=_SYSTEM, fewshot_examples=[], batch_k=8
    )
    assert provider.calls == 2
    assert len(result) == 10
    # All blocks got llm_score set
    assert all(b.llm_score is not None for b in blocks)


# ----------------------------------------------------------------- filter_no_terminal

def test_filter_no_terminal_activates_when_dense():
    # 4 of 4 end with terminal punct → density=1.0 >= 0.75 → gate active
    blocks = [
        _block("t1", "Это завершённая мысль."),
        _block("t2", "Вопрос задан?"),
        _block("t3", "Восклицание!"),
        _block("t4", "Незавершённая мысль без знака"),  # no terminal
    ]
    kept, gated = filter_no_terminal(blocks, density_guard=0.75)
    assert len(kept) == 3
    assert len(gated) == 1
    assert gated[0].id == "t4"


def test_filter_no_terminal_inactive_when_sparse():
    # only 1 of 4 has terminal punct → density=0.25 < 0.75 → gate inactive
    blocks = [
        _block("s1", "Без знака раз"),
        _block("s2", "Без знака два"),
        _block("s3", "Без знака три"),
        _block("s4", "С точкой."),
    ]
    kept, gated = filter_no_terminal(blocks, density_guard=0.75)
    assert kept == blocks
    assert gated == []


def test_filter_no_terminal_empty():
    kept, gated = filter_no_terminal([])
    assert kept == [] and gated == []


# ----------------------------------------------------------------- real fixture

@pytest.mark.skipif(not FIXTURE.exists(), reason="real fixture not recorded yet — run eval_scores.py --record-fixture")
def test_fixture_response_parsing():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw = data["raw"]
    result = parse_score_response(raw)
    assert isinstance(result, list)
    assert len(result) > 0
    for entry in result:
        assert isinstance(entry.get("id"), str)
        assert isinstance(entry.get("score"), int)
        assert 0 <= entry["score"] <= 100


# ----------------------------------------------------------------- temperature forwarding

def test_score_blocks_batch_forwards_temperature():
    """temperature kwarg is forwarded to provider.complete()."""
    blocks = [_block("a1")]
    raw = '{"scores":[{"id":"a1","score":80}]}'
    calls: list[float] = []

    class _CapturingProvider:
        def complete(self, messages, *, temperature=0.0):
            calls.append(temperature)
            return raw

    score_blocks_batch(blocks, provider=_CapturingProvider(),
                       system_text=_SYSTEM, fewshot_examples=[], temperature=0.3)
    assert calls == [0.3]


def test_score_all_blocks_temperature_forwarded():
    """score_all_blocks passes temperature to every batch."""
    blocks = [_block("a1"), _block("a2")]
    raw = '{"scores":[{"id":"a1","score":70},{"id":"a2","score":80}]}'
    temps: list[float] = []

    class _CapturingProvider:
        def complete(self, messages, *, temperature=0.0):
            temps.append(temperature)
            return raw

    score_all_blocks(blocks, provider=_CapturingProvider(),
                     system_text=_SYSTEM, fewshot_examples=[], temperature=0.0)
    assert temps == [0.0]


# ----------------------------------------------------------------- score_passes averaging

def test_score_passes_2_averages_two_runs():
    """score_passes=2: two passes, result is mean. With 3 blocks < batch_k=8, rotation
    is a no-op (blocks[4:]+blocks[:4]==[a,b,c]), so mock returns responses in call order."""
    blocks = [_block("a"), _block("b"), _block("c")]
    # Pass 1: a=80, b=60, c=70
    # Pass 2 (rotated, no-op for 3 blocks): mock returns second response → a=100, b=80, c=90
    # Mean: a=90, b=70, c=80
    responses = [
        '{"scores":[{"id":"a","score":80},{"id":"b","score":60},{"id":"c","score":70}]}',
        '{"scores":[{"id":"c","score":90},{"id":"b","score":80},{"id":"a","score":100}]}',
    ]
    provider = _MockProvider(responses)
    result = score_all_blocks(blocks, provider=provider, system_text=_SYSTEM,
                              fewshot_examples=[], score_passes=2)
    assert provider.calls == 2
    assert result["a"] == 90   # round((80+100)/2)
    assert result["b"] == 70   # round((60+80)/2)
    assert result["c"] == 80   # round((70+90)/2)
    assert blocks[0].llm_score == 90.0
    assert blocks[1].llm_score == 70.0
    assert blocks[2].llm_score == 80.0


def test_score_passes_2_uses_other_pass_when_missing():
    """score_passes=2: block absent in pass 1 but scored in pass 2 → pass 2 score used."""
    blocks = [_block("a"), _block("b")]
    # Pass 1: only a scored (b missing)
    # Pass 2: both scored
    responses = [
        '{"scores":[{"id":"a","score":80}]}',
        '{"scores":[{"id":"a","score":90},{"id":"b","score":70}]}',
    ]
    provider = _MockProvider(responses)
    result = score_all_blocks(blocks, provider=provider, system_text=_SYSTEM,
                              fewshot_examples=[], score_passes=2)
    assert result["a"] == 85  # mean(80, 90)
    assert result["b"] == 70  # pass 2 only
    # b was missing in pass 1 → score_blocks_batch marks it "missing", but apply_llm_scores
    # clears reason once b gets a score from the merged result
    b_block = next(bl for bl in blocks if bl.id == "b")
    assert b_block.llm_score == 70.0
    assert b_block.llm_score_reason is None  # cleared by apply_llm_scores


def test_score_passes_1_single_run():
    """score_passes=1 (default): provider called once per batch, no averaging."""
    blocks = [_block("x1"), _block("x2")]
    raw = '{"scores":[{"id":"x1","score":75},{"id":"x2","score":65}]}'
    provider = _MockProvider([raw])
    score_all_blocks(blocks, provider=provider, system_text=_SYSTEM,
                     fewshot_examples=[], score_passes=1)
    assert provider.calls == 1
    assert blocks[0].llm_score == 75.0


# ----------------------------------------------------------------- heuristic does not prune before LLM

def test_heuristic_does_not_prune_before_llm():
    """Block with LOWEST heuristic score but HIGHEST llm_score must survive topk_filter.

    Verifies the pipeline order: gate → score_all_blocks (LLM) → topk_filter(by llm_score).
    The heuristic is never used to prune candidates before the LLM sees them.
    """
    import json as _json

    # 20 blocks; block "low_heur" has heuristic=0 but will get llm_score=100
    N = 20
    blocks = [_block(f"b{i:02d}") for i in range(N - 1)]
    low_heur = CandidateBlock(
        id="low_heur",
        start=float((N - 1) * 30),
        end=float(N * 30),
        duration=30.0,
        text="Этот блок имеет низкий эвристический балл.",
        boundary_reason="sentence",
    )
    blocks.append(low_heur)

    # Assign heuristic scores: all others get high scores, low_heur gets 0
    for b in blocks[:-1]:
        b.heuristic_score = 80.0
    low_heur.heuristic_score = 0.0

    # Mock LLM: gives low_heur score=100, everyone else score=10
    mock_response = _json.dumps({
        "scores": [{"id": "low_heur", "score": 100}]
        + [{"id": f"b{i:02d}", "score": 10} for i in range(N - 1)]
    })
    provider = _MockProvider([mock_response])

    score_all_blocks(blocks, provider=provider, system_text=_SYSTEM, fewshot_examples=[])

    # top_k=1: only the best block per window survives; window covers all blocks
    window = float(N * 30 + 1)
    kept, cut = topk_filter(blocks, chunk_window_sec=window, top_k=1)

    assert len(kept) == 1, f"expected 1 kept, got {len(kept)}"
    assert kept[0].id == "low_heur", (
        f"expected low_heur (llm=100) to win, got {kept[0].id} (llm={kept[0].llm_score})"
    )
