"""too_long trim: обрезка длинных сегментов от начала (cloud/trim.py).

Инвариант: LLM предлагает сегменты, код режет/бракует — не модель (CLAUDE.md инвариант 6).
Новое поведение (задача 2): excess срезается со СТАРТА, конец snap-позиции сохраняется.
Флаг too_long снимается после trim, остаётся при keep, сегмент удаляется при drop.
"""
import pytest
from autoreels.cloud import trim as T
from autoreels.core.models import Reel, Word


def _reel(start: float, end: float, flags: list[str] | None = None) -> Reel:
    r = Reel(id="r01", start=start, end=end, score=80,
             hook="h", title="t", description="d")
    if flags:
        r.flags = list(flags)
    return r


def _words(*pairs: tuple[float, float], word: str = "w") -> list[Word]:
    """Слова по (t0, t1) парам."""
    return [Word(word=f"{word}{i}", t0=t0, t1=t1) for i, (t0, t1) in enumerate(pairs)]


MAX = 90  # shorts max_duration


# ----------------------------------------------------------------------- trim от начала (основной путь)

def test_trim_trims_from_start_keeps_end():
    """Начало двигается вперёд, конец сохраняется — основной инвариант нового поведения."""
    r = _reel(100.0, 220.0, ["too_long"])  # 120с > 90
    words = _words((100.0, 101.0), (102.0, 103.0), (185.0, 186.0), (188.0, 189.0))
    original_end = r.end
    T.trim_too_long([r], words, max_duration=MAX, pause_sec=0.35, policy="trim")
    assert r.end == original_end, "end должен остаться нетронутым"
    assert r.end - r.start <= MAX, f"длина {r.end - r.start} > {MAX}"


def test_trim_start_moves_to_sentence_boundary():
    """start сдвигается к первому слову после sentence-terminal mark."""
    # Момент 100-220с (120с). Граница предложения на 133с (слово после ".")
    # Новый start = 133.0, clip = 220-133 = 87с ≤ 90
    r = _reel(100.0, 220.0, ["too_long"])
    words = [
        Word(word="начало.",   t0=100.0, t1=101.0),  # sentence end
        Word(word="следующее", t0=133.0, t1=134.0),  # ← новый start
        Word(word="финал.",    t0=200.0, t1=201.0),
    ]
    T.trim_too_long([r], words, max_duration=MAX, pause_sec=0.35, policy="trim")
    assert r.start == pytest.approx(133.0, abs=0.1)
    assert r.start_snap_reason == "sentence"


def test_trim_r11_regression_slightly_over_max():
    """Регресс r11: момент слегка за потолком теряет excess со START, не теряет 45с хвост.

    r11: start=1231.7, end=1292.7 (61.0с). Потолок 90с → нет обрезки (61 < 90).
    Симулируем аналог при потолке 59с: старый код резал до 16с; новый код должен дать ≥50с.
    """
    # 100-165с (65с > 59), потолок 59
    r = _reel(100.0, 165.0, ["too_long"])
    # Граница предложения на 107с → новый start=107, clip=165-107=58с ≤ 59
    words = [
        Word(word="первое.",   t0=100.0, t1=101.0),
        Word(word="второе",    t0=107.0, t1=108.0),
        Word(word="середина",  t0=130.0, t1=131.0),
        Word(word="конец.",    t0=163.0, t1=164.0),
    ]
    T.trim_too_long([r], words, max_duration=59.0, pause_sec=0.35, policy="trim")
    assert r.end == pytest.approx(165.0, abs=0.1), "end должен сохраниться"
    assert r.end - r.start >= 50.0, f"клип слишком короткий: {r.end - r.start}с"
    assert r.end - r.start <= 59.0


def test_trim_r03_regression_well_over_max():
    """Регресс r03: момент 76.4с триммируется от начала до границы предложения."""
    r = _reel(1120.7, 1197.1, ["too_long"])  # 76.4с > 59
    # Граница предложения на 1138с → clip = 1197.1-1138 = 59.1с ≈ ≤ 60 при pause-fallback
    words = [
        Word(word="старт.",    t0=1120.7, t1=1121.5),
        Word(word="новое",     t0=1138.0, t1=1139.0),
        Word(word="середина",  t0=1160.0, t1=1161.0),
        Word(word="финал.",    t0=1195.0, t1=1196.0),
    ]
    T.trim_too_long([r], words, max_duration=59.0, pause_sec=0.35, policy="trim")
    assert r.end == pytest.approx(1197.1, abs=0.1), "end не тронут"
    assert r.end - r.start <= 59.0


def test_trim_start_snap_reason_sentence_implies_after_terminal():
    """start_snap_reason == 'sentence' → выбранное слово следует за sentence-terminal mark."""
    r = _reel(0.0, 150.0, ["too_long"])
    words = [
        Word(word="начало.",   t0=0.0,  t1=1.0),
        Word(word="второе",    t0=62.0, t1=63.0),  # следует за "." → sentence boundary
        Word(word="финал.",    t0=140.0, t1=141.0),
    ]
    T.trim_too_long([r], words, max_duration=90.0, pause_sec=0.35, policy="trim")
    assert r.start_snap_reason == "sentence"
    # Убеждаемся, что слово ПЕРЕД новым start оканчивалось на .
    chosen_idx = next(i for i, w in enumerate(words) if abs(w.t0 - r.start) < 0.1)
    assert chosen_idx > 0
    assert words[chosen_idx - 1].word.endswith(".")


def test_trim_end_trim_when_final_sentence_exceeds_max():
    """Конец двигается назад ТОЛЬКО когда финальное предложение само > max_duration.

    Условие: нет sentence-terminal mark до порога (end - max_duration).
    Все слова непрерывные (пауза < pause_sec=0.35), одно длинное предложение.
    """
    r = _reel(0.0, 150.0, ["too_long"])
    # Слова с зазором 0.1с (< pause_sec=0.35) — нет пауз, нет sentence-terminal до floor=60с
    words = [
        Word(word=f"w{i}", t0=i * 1.0, t1=i * 1.0 + 0.9)
        for i in range(145)                   # 0-145с без punctuation, пауза 0.1 < 0.35
    ] + [Word(word="конец.", t0=145.0, t1=146.0)]  # единственный terminal на 145с
    # floor = 150-90 = 60. Нет sentence-terminal до 60с → end-trim
    T.trim_too_long([r], words, max_duration=90.0, pause_sec=0.35, policy="trim")
    assert r.end - r.start <= 90.0
    assert r.end_snap_reason == "max_duration_end_trim"


def test_trim_removes_too_long_flag():
    """После trim флаг too_long снимается."""
    r = _reel(0.0, 120.0, ["too_long"])
    words = _words((0.0, 1.0), (31.0, 32.0), (100.0, 101.0))
    T.trim_too_long([r], words, max_duration=MAX, pause_sec=0.35, policy="trim")
    assert "too_long" not in r.flags


def test_trim_skips_already_ok_reels():
    """Рилы без too_long флага не трогаются."""
    r = _reel(0.0, 45.0)
    original_start, original_end = r.start, r.end
    T.trim_too_long([r], _words((0.0, 1.0)), max_duration=MAX, pause_sec=0.35, policy="trim")
    assert r.start == original_start
    assert r.end == original_end


def test_trim_76s_not_too_long_under_new_ceiling():
    """76с момент НЕ попадает в trim-путь при потолке 90с (регресс r03 ceiling task)."""
    r = _reel(0.0, 76.0)    # нет флага too_long
    original_start, original_end = r.start, r.end
    T.trim_too_long([r], _words((0.0, 1.0)), max_duration=MAX, pause_sec=0.35, policy="trim")
    assert r.start == original_start
    assert r.end == original_end


def test_trim_95s_still_triggers_ceiling():
    """95с момент с флагом too_long обрезается до ≤90с."""
    r = _reel(0.0, 95.0, ["too_long"])
    words = [Word(word=f"w{i}", t0=i * 2.0, t1=i * 2.0 + 1.8) for i in range(50)]
    T.trim_too_long([r], words, max_duration=MAX, pause_sec=0.35, policy="trim")
    assert r.end - r.start <= MAX


def test_trim_clip_below_min_rejected_not_padded():
    """Клип, не достигающий min_duration после trim, удаляется, не дополняется."""
    # Момент 0-50с, max=10 → start придётся сдвинуть до 40с, clip=10с. min=15 → отбраковка.
    r = _reel(0.0, 50.0, ["too_long"])
    words = [Word(word=f"w{i}", t0=i * 2.0, t1=i * 2.0 + 1.8) for i in range(26)]
    reels = [r]
    T.trim_too_long(reels, words, max_duration=10.0, pause_sec=0.35, policy="trim", min_duration=15.0)
    assert r not in reels, "клип ниже min_duration должен быть удалён"


# ----------------------------------------------------------------------- drop (отбраковка)

def test_drop_removes_too_long_reel():
    """policy='drop': рил с too_long флагом убирается из списка."""
    reels = [_reel(0.0, 120.0, ["too_long"]), _reel(200.0, 240.0)]
    T.trim_too_long(reels, [], max_duration=MAX, pause_sec=0.35, policy="drop")
    assert len(reels) == 1
    assert reels[0].start == 200.0


def test_drop_keeps_ok_reels_intact():
    """policy='drop': рилы без too_long остаются."""
    r = _reel(0.0, 45.0)
    reels = [r]
    T.trim_too_long(reels, [], max_duration=MAX, pause_sec=0.35, policy="drop")
    assert reels == [r]


# ----------------------------------------------------------------------- keep

def test_keep_does_not_cut():
    """policy='keep': рил сохраняется как есть, ни start ни end не меняется."""
    r = _reel(0.0, 120.0, ["too_long"])
    T.trim_too_long([r], _words((0.0, 1.0)), max_duration=MAX, pause_sec=0.35, policy="keep")
    assert r.start == 0.0
    assert r.end == 120.0


def test_keep_preserves_too_long_flag():
    """policy='keep': флаг too_long остаётся."""
    r = _reel(0.0, 120.0, ["too_long"])
    T.trim_too_long([r], [], max_duration=MAX, pause_sec=0.35, policy="keep")
    assert "too_long" in r.flags


# ----------------------------------------------------------------------- конфиг

def test_r0_config_has_too_long_policy():
    """r0.yaml и R0Config содержат too_long_policy."""
    from pathlib import Path
    from autoreels.core.config import load_r0_config
    cfg = load_r0_config(Path(__file__).resolve().parents[1] / "config" / "r0.yaml")
    assert hasattr(cfg, "too_long_policy")
    assert cfg.too_long_policy in ("trim", "drop", "keep")
