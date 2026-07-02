"""too_long trim: обрезка длинных сегментов по паузе (cloud/trim.py).

Инвариант: LLM предлагает сегменты, код режет/бракует — не модель (CLAUDE.md инвариант 6).
Флаг too_long снимается после trim, остаётся при keep, сегмент удаляется при drop.
"""
from autoreels.cloud import trim as T
from autoreels.core.models import Reel, Word


def _reel(start: float, end: float, flags: list[str] | None = None) -> Reel:
    r = Reel(id="r01", start=start, end=end, score=80,
             hook="h", title="t", description="d")
    if flags:
        r.flags = list(flags)
    return r


def _words(*pairs: tuple[float, float]) -> list[Word]:
    """Слова по (t0, t1) парам."""
    return [Word(word=f"w{i}", t0=t0, t1=t1) for i, (t0, t1) in enumerate(pairs)]


MAX = 59  # shorts max_duration


# ----------------------------------------------------------------------- trim (обрезка)

def test_trim_cuts_long_reel_to_max():
    """87-сек рил при max=59 → end ≤ start+59."""
    r = _reel(100.0, 187.0, ["too_long"])
    words = _words((100.0, 101.0), (102.0, 103.0), (155.0, 156.0), (158.0, 159.0))
    T.trim_too_long([r], words, max_duration=MAX, pause_sec=0.35, policy="trim")
    assert r.end - r.start <= MAX, f"длина {r.end - r.start} > {MAX}"


def test_trim_cuts_at_pause_before_limit():
    """Обрезка идёт по ближайшей паузе ДО лимита, не посреди слова."""
    # Слова: пауза в 157.0-159.0 (2с), лимит = 100+59 = 159
    # Ожидаем конец у t1=157.0 (конец слова перед паузой)
    r = _reel(100.0, 190.0, ["too_long"])
    words = _words(
        (100.0, 101.0),   # w0
        (102.0, 103.0),   # w1
        (150.0, 157.0),   # w2 — конец в 157, потом пауза
        # пауза 2с
        (159.0, 160.0),   # w3 — за лимитом 159
        (161.0, 165.0),   # w4
    )
    T.trim_too_long([r], words, max_duration=MAX, pause_sec=0.35, policy="trim")
    # t1 слова w2 = 157.0, пауза до 159.0, лимит = 159.0
    # → обрезка должна быть у 157.0 (конец слова перед паузой)
    assert r.end == pytest.approx(157.0, abs=1.0), f"ожидали ~157, получили {r.end}"
    assert r.end <= 100.0 + MAX


def test_trim_removes_too_long_flag():
    """После trim флаг too_long снимается."""
    r = _reel(0.0, 90.0, ["too_long"])
    words = _words((0.0, 1.0), (50.0, 51.0), (57.0, 58.0))
    T.trim_too_long([r], words, max_duration=MAX, pause_sec=0.35, policy="trim")
    assert "too_long" not in r.flags


def test_trim_does_not_cut_within_word():
    """Обрезка не разрывает слово: end совпадает с t1 какого-то слова, не произвольной точкой."""
    r = _reel(100.0, 200.0, ["too_long"])
    # Слова каждые 5с, пауз нет (< pause_sec=0.35)
    words = [Word(word=f"w{i}", t0=100.0 + i * 5, t1=100.0 + i * 5 + 4.6) for i in range(25)]
    T.trim_too_long([r], words, max_duration=MAX, pause_sec=0.35, policy="trim")
    word_ends = {w.t1 for w in words}
    assert r.end in word_ends, f"end={r.end} не совпадает ни с одним t1 слова"


def test_trim_hard_cut_when_no_pause_before_limit():
    """Нет паузы до лимита → жёсткий рез по max_duration."""
    r = _reel(100.0, 200.0, ["too_long"])
    # Все слова до 159 идут без пауз; после 159 — пауза
    words = [Word(word="x", t0=100.0 + i * 1.5, t1=100.0 + i * 1.5 + 1.3) for i in range(80)]
    T.trim_too_long([r], words, max_duration=MAX, pause_sec=0.35, policy="trim")
    assert r.end <= 100.0 + MAX


def test_trim_preserves_start():
    """start всегда сохраняется — режется только хвост."""
    r = _reel(120.0, 200.0, ["too_long"])
    words = _words((120.0, 121.0), (170.0, 171.0), (178.0, 179.0))
    original_start = r.start
    T.trim_too_long([r], words, max_duration=MAX, pause_sec=0.35, policy="trim")
    assert r.start == original_start


def test_trim_skips_already_ok_reels():
    """Рилы без too_long флага не трогаются."""
    r = _reel(0.0, 45.0)    # 45с — в пределах пресета, нет флага
    original_end = r.end
    T.trim_too_long([r], _words((0.0, 1.0)), max_duration=MAX, pause_sec=0.35, policy="trim")
    assert r.end == original_end


# ----------------------------------------------------------------------- drop (отбраковка)

def test_drop_removes_too_long_reel():
    """policy='drop': рил с too_long флагом убирается из списка."""
    reels = [_reel(0.0, 90.0, ["too_long"]), _reel(200.0, 240.0)]
    T.trim_too_long(reels, [], max_duration=MAX, pause_sec=0.35, policy="drop")
    assert len(reels) == 1
    assert reels[0].start == 200.0


def test_drop_keeps_ok_reels_intact():
    """policy='drop': рилы без too_long остаются."""
    r = _reel(0.0, 45.0)
    reels = [r]
    T.trim_too_long(reels, [], max_duration=MAX, pause_sec=0.35, policy="drop")
    assert reels == [r]


# ----------------------------------------------------------------------- keep (текущее)

def test_keep_does_not_cut():
    """policy='keep': рил сохраняется как есть, end не меняется."""
    r = _reel(0.0, 90.0, ["too_long"])
    T.trim_too_long([r], _words((0.0, 1.0)), max_duration=MAX, pause_sec=0.35, policy="keep")
    assert r.end == 90.0


def test_keep_preserves_too_long_flag():
    """policy='keep': флаг too_long остаётся (текущее поведение)."""
    r = _reel(0.0, 90.0, ["too_long"])
    T.trim_too_long([r], [], max_duration=MAX, pause_sec=0.35, policy="keep")
    assert "too_long" in r.flags


# ----------------------------------------------------------------------- конфиг

import pytest

def test_r0_config_has_too_long_policy():
    """r0.yaml и R0Config содержат too_long_policy."""
    from pathlib import Path
    from autoreels.core.config import load_r0_config
    cfg = load_r0_config(Path(__file__).resolve().parents[1] / "config" / "r0.yaml")
    assert hasattr(cfg, "too_long_policy")
    assert cfg.too_long_policy in ("trim", "drop", "keep")
