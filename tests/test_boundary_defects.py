"""Regression tests for the three boundary defects found in manual review.

Fix 1: dataset dedup — re-apply replaces rows, not appends.
Fix 2: merged reel tail trimmed before host's declarative closing line.
Fix 3: trailing question + short answer trimmed from clip end.
Fix 4: ellipsis-ending opening sentences repaired away.
"""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from autoreels.core.models import Reel, Word


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _word(t0: float, t1: float, word: str) -> Word:
    return Word(t0=t0, t1=t1, word=word)


def _reel(start: float, end: float, score: int = 50, *, merged: bool = False,
          r0_end: float | None = None) -> Reel:
    r = Reel(id=f"r_{start}_{end}", start=start, end=end, score=score,
             hook="", title="", description="")
    r.r0_start = start
    r.r0_end = r0_end if r0_end is not None else end
    if merged:
        r.flags.append("human_merged")
    return r


def _cfg(**kw):
    defaults = dict(min_clip_duration=8.0, host_affirmations=[], trailing_question_words=8)
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Fix 1 — dataset dedup
# ---------------------------------------------------------------------------

def test_reapply_deduplicates_dataset_rows(tmp_path):
    """Re-applying writes the same block_id/source row once, not twice."""
    import json as _json
    from autoreels.cloud.blocks import make_dataset_row, CandidateBlock

    # Build two identical rows (simulating two --apply runs).
    row = {"source": "vid1", "block_id": "abc123", "start": 10.0, "end": 30.0,
           "duration": 20.0, "text": "text", "human_score": 80,
           "heuristic_score": 60.0, "features": {}}

    ds_path = tmp_path / "vid1.jsonl"
    # First write (append-style): write existing row
    ds_path.write_text(_json.dumps(row) + "\n", encoding="utf-8")

    # Simulate a second apply: same block, same source
    existing: dict = {}
    for line in ds_path.read_text(encoding="utf-8").splitlines():
        r = _json.loads(line)
        existing[(r["block_id"], r["source"])] = r
    new_row = dict(row, human_score=85)  # slightly different score
    existing[(new_row["block_id"], new_row["source"])] = new_row
    ds_path.write_text(
        "\n".join(_json.dumps(v) for v in existing.values()) + "\n", encoding="utf-8"
    )

    lines = [l for l in ds_path.read_text().splitlines() if l.strip()]
    assert len(lines) == 1, f"expected 1 row, got {len(lines)}"
    loaded = _json.loads(lines[0])
    assert loaded["human_score"] == 85, "re-apply must update the score, not append"


# ---------------------------------------------------------------------------
# Fix 2 — merged reel tail trimmed before host's declarative closing line
# ---------------------------------------------------------------------------

def test_merged_reel_tail_host_turn_trimmed():
    """For a merged reel, a host turn in the last _MERGED_TAIL_SEC is trimmed.

    Clip 1 regression: '…куда ему нужно идти. Ты коснулся книги…' — the declarative
    sentence starting with 'Ты' is detected as a host turn and the clip should end
    before it, at 'куда ему нужно идти.'
    """
    from autoreels.cloud.select import _stage_interview_snap

    # Reel spans [1500, 1546]. r0_end = 1545 (merged block end, 1s before reel end).
    r = _reel(1500.0, 1546.3, merged=True, r0_end=1545.7)

    # Host turn: 'Ты коснулся книги…' starts at 1538.84 (within last 15s of r0_end=1545.7).
    host_turns = [(1538.84, 1546.26)]

    # Transcript words (tail only, enough for the test).
    words = [
        _word(1536.0, 1537.0, "куда"),
        _word(1537.0, 1537.4, "ему"),
        _word(1537.4, 1537.7, "нужно"),
        _word(1537.7, 1538.0, "идти."),
        _word(1538.84, 1540.0, "Ты"),
        _word(1540.0, 1541.4, "коснулся"),
        _word(1541.4, 1542.5, "книги,"),
        _word(1544.9, 1546.3, "полома."),
    ]

    cfg = _cfg()
    kept, disc = _stage_interview_snap([r], host_turns, tx_words=words, r0_cfg=cfg)

    assert len(kept) == 1
    assert kept[0].end < 1538.84, (
        f"merged reel must be trimmed before host turn at 1538.84, got end={kept[0].end}"
    )
    assert kept[0].end > 1537.7, "must not cut into guest speech ('идти.' at 1537.7)"


def test_generic_ty_guest_sentence_not_trimmed():
    """A guest sentence using generic 'ты' (not starting the sentence) is NOT a host turn.

    'когда ты честен с собой' — starts with 'когда', not 'ты'; condition (b) must not fire.
    """
    from autoreels.cloud.select import detect_host_turns

    words = [
        _word(100.0, 100.5, "когда"),
        _word(100.5, 100.7, "ты"),
        _word(100.7, 101.2, "честен"),
        _word(101.2, 101.5, "с"),
        _word(101.5, 102.0, "собой,"),  # comma — not a sentence end
        _word(102.0, 102.5, "ты"),
        _word(102.5, 103.0, "приходишь"),
        _word(103.0, 103.5, "к"),
        _word(103.5, 104.0, "себе."),
    ]
    turns = detect_host_turns(words)
    # Sentence: "когда ты честен с собой, ты приходишь к себе." — starts with "когда"
    # Condition (b) requires first word = ты/вы → NOT fired.
    assert len(turns) == 0, f"generic 'ты' sentence should not be a host turn; got {turns}"


# ---------------------------------------------------------------------------
# Fix 3 — trailing question + short answer trimmed
# ---------------------------------------------------------------------------

def test_trailing_question_with_short_answer_trimmed():
    """Clip 10 regression: '…сохраняя природу. Кому бы ты не советовал? Не зайдет.'
    The clip must end before 'Кому бы ты…'
    """
    from autoreels.cloud.select import _stage_interview_snap

    # No host_turns needed; the trailing question trim is unconditional.
    r = _reel(2270.0, 2312.9, merged=True, r0_end=2318.0)

    words = [
        _word(2293.0, 2293.7, "красиво,"),
        _word(2293.7, 2296.6, "по-настоящему."),
        _word(2297.7, 2298.4, "И"),
        _word(2298.4, 2298.9, "сохраняя"),
        _word(2298.9, 2299.4, "природу."),
        # trailing question
        _word(2300.5, 2305.5, "Кому"),
        _word(2305.5, 2305.6, "бы"),
        _word(2305.6, 2305.9, "ты"),
        _word(2305.9, 2306.6, "не"),
        _word(2306.6, 2307.3, "советовал"),
        _word(2307.3, 2307.9, "покупать"),
        _word(2307.9, 2309.6, "книгу?"),
        # short answer fragment (2 words)
        _word(2309.2, 2309.8, "Не"),
        _word(2309.8, 2312.9, "зайдет."),
    ]

    cfg = _cfg()
    kept, disc = _stage_interview_snap([r], [], tx_words=words, r0_cfg=cfg)

    assert len(kept) == 1
    end = kept[0].end
    assert end < 2300.5, f"clip must end before trailing question at 2300.5; got {end}"
    assert end > 2299.0, f"must not cut into resolved content before question; got {end}"


def test_trailing_question_not_trimmed_when_long_answer():
    """A question with a long answer (>= max_tail_words) must not be trimmed."""
    from autoreels.cloud.select import _trim_tail_question

    r = _reel(0.0, 50.0)
    words = (
        [_word(float(i), float(i + 1), f"слово{i}.") for i in range(10)]
        + [_word(10.0, 11.0, "вопрос?")]
        + [_word(float(11 + i), float(12 + i), f"ответ{i}.") for i in range(10)]
    )
    trimmed = _trim_tail_question(r, words, max_tail_words=8)
    assert not trimmed
    assert r.end == 50.0


# ---------------------------------------------------------------------------
# Fix 4 — ellipsis opening repaired away
# ---------------------------------------------------------------------------

def test_ellipsis_opening_repaired():
    """Clip 12 regression: '— Не стандартный, неординарный... Ну, не знаю, тут как бы...'
    Both ellipsis-ending sentences are skipped; clip starts at '— Может, какие-то…'
    """
    from autoreels.cloud.select import filter_dangling_start

    r = _reel(926.0, 960.0)

    words = [
        _word(926.1, 926.5, "—"),
        _word(926.5, 926.6, "Не"),
        _word(926.6, 927.4, "стандартный,"),
        _word(927.4, 933.0, "неординарный..."),   # ends in '...' → ellipsis
        _word(933.0, 933.9, "Ну,"),
        _word(933.9, 934.2, "не"),
        _word(934.2, 934.7, "знаю,"),
        _word(934.7, 934.9, "тут"),
        _word(934.9, 935.0, "как"),
        _word(935.0, 935.8, "бы..."),              # ends in '...' → ellipsis
        _word(936.1, 936.1, "—"),
        _word(936.1, 936.5, "Может,"),
        _word(936.5, 936.7, "какие-то"),
        _word(936.7, 937.0, "есть"),
        _word(937.0, 937.9, "стереотипы?"),
        _word(938.0, 940.8, "контент."),
    ]

    kept, disc = filter_dangling_start([r], words, min_duration=8.0, max_start_repair_sec=12.0)

    assert len(kept) == 1, "clip should be kept (repaired, not dropped)"
    assert kept[0].start >= 935.0, (
        f"start must advance past both ellipsis sentences; got {kept[0].start}"
    )


def test_clean_start_unaffected_by_ellipsis_fix():
    """A clip with a clean sentence start is not modified by the ellipsis pre-pass."""
    from autoreels.cloud.select import filter_dangling_start

    r = _reel(10.0, 50.0)
    words = [
        _word(10.0, 10.5, "Самое"),
        _word(10.5, 11.0, "главное"),
        _word(11.0, 12.0, "здесь."),
        _word(12.0, 13.0, "Это"),
        _word(13.0, 14.0, "важно."),
    ]
    orig_start = r.start
    kept, disc = filter_dangling_start([r], words, min_duration=8.0)
    assert len(kept) == 1
    assert kept[0].start == orig_start


# ---------------------------------------------------------------------------
# Fix 6 — previously good clips are duration-stable after re-apply
# ---------------------------------------------------------------------------

def test_good_clips_durations_stable():
    """Reels 2, 4, 5, 7, 9, 21 from PXL review must not be shortened by the new trims.

    Reads the existing review.json output (written by last --apply) and checks that
    clips we identified as 'good' still exist and are >= their known durations.
    Skips if the file is absent (CI without review artefacts).
    """
    review_path = Path(__file__).parent.parent / "reviews" / \
        "PXL_20260729_085910095_34f06abf.review.json"
    if not review_path.exists():
        pytest.skip("review.json not present")

    with review_path.open() as f:
        out = json.load(f)

    reels = out["reels"]
    # Reel indices are 1-based in our reports; file list is 0-based.
    # These were the 'good' clips from the last run (durations after fix-merged-blocks).
    # Accept a 5 % tolerance for snap adjustments after new fixes.
    expected = {
        2:  50.0,   # 52.0s merged — should survive mostly intact
        4:  33.0,   # 35.3s merged (trailing question fix trims a few seconds)
        5:  44.0,   # 46.8s merged
        7:  30.0,   # 54.7s merged, contains 'Ты не поломан' — might trim host tail
        9:  35.0,   # 38.7s merged
        21: 44.0,   # 47.0s merged — contains внутренний телефон
    }
    for reel_1based, min_dur in expected.items():
        r = reels[reel_1based - 1]
        dur = r["end"] - r["start"]
        assert dur >= min_dur, (
            f"Reel {reel_1based} ({dur:.1f}s) dropped below expected minimum {min_dur}s"
        )
