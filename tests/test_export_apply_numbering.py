"""Tests for merge_group_sentences — sentence numbering consistency across export and apply.

The reviewer sees sentence numbers from the export (which shows per-block sentences with
junction merging).  The apply path must use the same numbering so s:/e:/x: resolve correctly.
"""
from autoreels.core.models import Word
from autoreels.cloud.edit import merge_group_sentences, split_sentences


def _w(text: str, t0: float, t1: float) -> Word:
    return Word(word=text, t0=t0, t1=t1)


class _Block:
    def __init__(self, start: float, end: float):
        self.start = start
        self.end = end


# ---------------------------------------------------------------------------
# Test 1: single block — same as split_sentences
# ---------------------------------------------------------------------------

def test_single_block_matches_split_sentences():
    """Single-block group: merge_group_sentences == split_sentences for the block's span."""
    words = [_w("Привет,", 0.0, 0.5), _w("как", 0.5, 0.8), _w("дела?", 0.8, 1.2),
             _w("Хорошо.", 1.5, 1.9)]
    b = _Block(0.0, 2.0)
    result = merge_group_sentences([b], words)
    expected = split_sentences(words)
    assert result == expected


# ---------------------------------------------------------------------------
# Test 2: splice — terminal last sentence → no junction
# ---------------------------------------------------------------------------

def test_splice_terminal_last_no_junction():
    """When block[i]'s last sentence ends terminally, blocks are concatenated without junction."""
    w_b1 = [_w("Раз,", 0.0, 0.4), _w("два,", 0.4, 0.8), _w("три.", 0.8, 1.2)]
    w_b2 = [_w("четыре,", 10.0, 10.4), _w("пять.", 10.4, 10.8)]
    words = w_b1 + w_b2
    b1 = _Block(0.0, 2.0)
    b2 = _Block(10.0, 11.0)
    result = merge_group_sentences([b1, b2], words)
    # b1 ends terminally ("три.") → no junction; result = b1_sents + b2_sents
    assert len(result) == 2
    assert result[0][-1].word == "три."
    assert result[1][-1].word == "пять."


# ---------------------------------------------------------------------------
# Test 3: splice with lowercase-start continuation — junction formed
# ---------------------------------------------------------------------------

def test_splice_lowercase_start_junction_numbering():
    """Block[i]'s last sentence is incomplete → junction with block[i+1]'s first sentence.

    The junction must count as ONE sentence number so that export and apply agree:
    - Export shows block[i] ending "...→" and block[i+1] starting with the continuation.
    - Apply must resolve the same merged sentence at the junction.

    This is the regression that was fixed: previously split_sentences(merged_span) produced
    a different sentence count than the per-block approach when Whisper overlap placed the
    junction words out of t0 order.
    """
    # Block 1 ends with an incomplete sentence ("сказал," — comma, no terminal punct)
    w_b1 = [_w("Он", 0.0, 0.3), _w("сказал,", 0.3, 0.7)]
    # Block 2 starts with a lowercase word (continuation of block 1's sentence)
    w_b2 = [_w("что", 5.0, 5.3), _w("всё", 5.3, 5.6), _w("хорошо.", 5.6, 6.0),
            _w("Правда?", 6.5, 7.0)]
    words = w_b1 + w_b2
    b1 = _Block(0.0, 1.0)
    b2 = _Block(5.0, 7.5)
    result = merge_group_sentences([b1, b2], words)
    # Junction: "Он сказал," + "что всё хорошо." → one sentence
    # Then "Правда?" → second sentence
    assert len(result) == 2, f"Expected 2 sentences, got {len(result)}: {[[w.word for w in s] for s in result]}"
    junction = result[0]
    assert junction[0].word == "Он"
    assert junction[-1].word == "хорошо."
    assert result[1][0].word == "Правда?"


# ---------------------------------------------------------------------------
# Test 4: Whisper overlap — junction uses per-block sentences, not merged-span split
# ---------------------------------------------------------------------------

def test_whisper_overlap_junction_sentence_count():
    """Whisper chunk overlap at a block boundary: per-block split gives the correct count.

    In the actual corpus: block30 ends with "ну уже все." (terminal) followed by
    "Мне врач сказал," (incomplete, from the overlapping Whisper chunk).  block31 starts
    at 1487.6 — "Мне"(t0=1487.556) is just before the start so it lands only in block30;
    "уже"(t0=1487.676) and "все."(t0=1487.836) land in both block30 and block31.

    In tx_words list order (Whisper chunk order), block30 words come first:
        ну, уже, все., Мне, врач, сказал,
    then block31 words (overlap zone starts earlier in time but later in the list):
        уже, все., врач, сказал, что, …

    The junction = block30[-1] (incomplete "Мне врач сказал,") + block31[0] ("уже все.").
    Total = [block30 complete sentences] + 1 junction + [block31 remaining].
    """
    # tx_words in Whisper list order (block30 chunk first, then block31 chunk).
    # block31.start=1.05: "ну"(t0=1.0) and "врач,"(t0=0.95) stay in b30 only;
    # "уже"(t0=1.1) and "все."(t0=1.2) land in both spans (Whisper overlap zone).
    words = [
        _w("Слушай.", 0.0, 0.5),   # block30 S1 terminal
        _w("ну", 1.0, 1.3),         # block30 S2 start — NOT in b31 (t0=1.0 < 1.05)
        _w("уже", 1.1, 1.4),        # block30 S2 overlap word — also in b31 (t0=1.1 >= 1.05)
        _w("все.", 1.2, 1.5),       # block30 S2 terminal — also in b31
        _w("Мне", 0.8, 1.0),         # block30 S3 start — NOT in b31 (t0=0.8 < 1.05)
        _w("врач,", 0.95, 1.1),      # block30 S3 incomplete — NOT in b31 (t0=0.95 < 1.05)
        _w("что", 2.0, 2.3),         # block31 continuation sentence
        _w("понял.", 2.3, 2.7),       # block31 terminal
    ]
    b30 = _Block(0.0, 1.8)   # covers all 6 block30 words
    b31 = _Block(1.05, 3.0)  # Мне(0.8), врач,(0.95), ну(1.0) excluded; уже(1.1), все.(1.2), что, понял. included

    result = merge_group_sentences([b30, b31], words)
    # b30 sents: [Слушай.], [ну уже все.] (terminal), [Мне врач,] (incomplete)
    # b31 sents: [уже все.] (terminal), [что понял.]
    # junction = [Мне, врач,] + [уже, все.] → no duplication of words within junction
    # Result: [Слушай.], [ну уже все.], [junction Мне врач, уже все.], [что понял.] = 4 sentences
    assert len(result) == 4, (
        f"Expected 4 sentences, got {len(result)}: {[[w.word for w in s] for s in result]}"
    )
    assert result[0][-1].word == "Слушай."
    assert result[1][-1].word == "все."          # b30 S2: "ну уже все."
    assert result[2][0].word == "Мне"            # junction starts with Мне (only in b30)
    assert result[2][-1].word == "все."           # junction ends with b31[0]'s "все."
    assert result[3][0].word == "что"
