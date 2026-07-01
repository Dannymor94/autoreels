"""Chunking транскрипции (M1.2): Whisper-чанкинг + склейка таймкодов + дедуп рилов.

Все тесты на детерминированные функции — ffmpeg/Groq мокированы фикстурами/monkeypatch.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from autoreels.core.models import Reel, Transcript, Word
from autoreels.cloud import chunk_transcribe as CT


# ------------------------------------------------------------------- helpers

def _w(word: str, t0: float, t1: float) -> Word:
    return Word(word=word, t0=t0, t1=t1)


def _tr(*word_tuples: tuple) -> Transcript:
    return Transcript(language="ru", words=[_w(*t) for t in word_tuples])


def _reel(rid: str, start: float, end: float, score: int = 80) -> Reel:
    return Reel(
        id=rid, start=start, end=end, score=score,
        hook="hook", title="title", description="desc",
    )


def _make_chunking_cfg(**overrides):
    """Минимальный ChunkingConfig для тестов. Перебить поля через overrides."""
    from autoreels.core.config import ChunkingConfig
    defaults = dict(
        enabled=True,
        whisper_chunk_duration_sec=600,
        whisper_threshold_minutes=15,
        whisper_threshold_bytes=20 * 1024 * 1024,
        silence_window_sec=30,
        silence_threshold_db=-40,
        r0_chunk_tokens=3000,
        r0_overlap_tokens=300,
        dedup_overlap_ratio=0.5,
        fail_fast=False,
    )
    defaults.update(overrides)
    return ChunkingConfig(**defaults)


class _SuccessBackend:
    """Мок бэкенда транскрипции — всегда возвращает один слово."""
    def __init__(self, word="слово", call_log=None):
        self._word = word
        self._log = call_log if call_log is not None else []

    def transcribe(self, path, *, language=None):
        self._log.append(path)
        return Transcript(language="ru", words=[_w(self._word, 0.0, 0.5)])


class _FailingBackend:
    """Мок бэкенда, падающий на заданных индексах (0-based)."""
    def __init__(self, fail_on: set[int]):
        self._fail_on = fail_on
        self._call_idx = 0

    def transcribe(self, path, *, language=None):
        idx = self._call_idx
        self._call_idx += 1
        if idx in self._fail_on:
            raise CT.ChunkTranscribeError(f"mock fail on chunk {idx}")
        return Transcript(language="ru", words=[_w(f"word{idx}", 0.0, 0.5)])


# ====================================================== TEST 1: timestamp offset

def test_timestamp_offset():
    """chunk_start=600 → все слова сдвинуты на 600."""
    tr = _tr(("привет", 0.0, 0.5), ("мир", 1.0, 1.5))
    result = CT.apply_offset(tr, 600.0)
    assert result.words[0].t0 == pytest.approx(600.0)
    assert result.words[0].t1 == pytest.approx(600.5)
    assert result.words[1].t0 == pytest.approx(601.0)
    assert result.words[1].t1 == pytest.approx(601.5)
    assert result.language == "ru"


def test_timestamp_offset_zero():
    """offset=0 → transcript неизменён."""
    tr = _tr(("тест", 5.0, 5.5))
    result = CT.apply_offset(tr, 0.0)
    assert result.words[0].t0 == pytest.approx(5.0)


# ====================================================== TEST 2: overlap zone consistency

def test_overlap_zone_consistency():
    """Слово у границы чанка → одинаковое абсолютное время из чанка i и i+1.

    Главный баг чанкинга: offset_{i+1} берётся по TARGET (600), а не по реальному
    VAD-срезу (598) → слова смещаются на 2с. Тест ловит это.

    chunk_i:   offset=0,   word «тест» в relative [598.5, 599.5] → absolute [598.5, 599.5]
    chunk_i+1: offset=598, word «тест» в relative [0.5,   1.5]   → absolute [598.5, 599.5]
    """
    from_i    = CT.apply_offset(_tr(("тест", 598.5, 599.5)), 0.0)
    from_next = CT.apply_offset(_tr(("тест", 0.5,   1.5)),   598.0)

    assert from_i.words[0].t0 == pytest.approx(from_next.words[0].t0)
    assert from_i.words[0].t1 == pytest.approx(from_next.words[0].t1)


def test_overlap_zone_wrong_offset_differs():
    """Если offset_i+1 = 600 (target) вместо 598 (VAD) → времена расходятся на 2с."""
    from_i          = CT.apply_offset(_tr(("тест", 598.5, 599.5)), 0.0)
    from_next_wrong = CT.apply_offset(_tr(("тест", 0.5,   1.5)),   600.0)   # ← неправильный offset

    # Должны ОТЛИЧАТЬСЯ — это именно тот баг, который тест 2 должен ловить
    assert abs(from_i.words[0].t0 - from_next_wrong.words[0].t0) == pytest.approx(2.0)


# ====================================================== TEST 3: merge continuity

def test_merge_continuity():
    """3 чанка → нет дублей слов, правильные абсолютные времена, слова идут по возрастанию."""
    chunks = [
        _tr(("один",   0.0, 0.8), ("два",    1.0, 1.5)),
        _tr(("три",    0.0, 0.4), ("четыре", 0.6, 1.0)),
        _tr(("пять",   0.0, 0.4)),
    ]
    start_secs = [0.0, 600.0, 1200.0]
    result = CT.merge_transcripts(chunks, start_secs)

    assert len(result.words) == 5
    words = result.words

    # Правильные абсолютные времена
    assert words[0].t0 == pytest.approx(0.0)
    assert words[2].t0 == pytest.approx(600.0)   # первое слово чанка 2
    assert words[4].t0 == pytest.approx(1200.0)  # первое слово чанка 3

    # Слова идут строго по возрастанию t0 (чанки неперекрывающиеся)
    for i in range(len(words) - 1):
        assert words[i].t0 < words[i + 1].t0


def test_merge_none_chunk_skipped():
    """None-чанк (провал транскрипции) пропускается, остальные сшиваются корректно."""
    warns: list[str] = []
    chunks = [
        _tr(("a", 0.0, 0.5)),
        None,
        _tr(("c", 0.0, 0.5)),
    ]
    result = CT.merge_transcripts(chunks, [0.0, 600.0, 1200.0], warns=warns)
    assert len(result.words) == 2
    assert result.words[0].word == "a"
    assert result.words[1].word == "c"
    assert result.words[1].t0 == pytest.approx(1200.0)


# ====================================================== TEST 4: chunking threshold

def test_chunking_threshold_long_audio():
    """>15 мин → chunk mode."""
    cfg = _make_chunking_cfg(whisper_threshold_minutes=15)
    assert CT.should_chunk(0, 16 * 60, cfg) is True


def test_chunking_threshold_short_audio():
    """<=15 мин, маленький файл → single request."""
    cfg = _make_chunking_cfg(whisper_threshold_minutes=15)
    assert CT.should_chunk(0, 14 * 60, cfg) is False


def test_chunking_threshold_large_bytes():
    """Большой файл даже при короткой длительности → chunk mode."""
    cfg = _make_chunking_cfg(whisper_threshold_bytes=20 * 1024 * 1024)
    assert CT.should_chunk(21 * 1024 * 1024, 5 * 60, cfg) is True


def test_chunking_threshold_exactly_on_limit():
    """Ровно на пороге → НЕ чанкить (строго больше)."""
    cfg = _make_chunking_cfg(whisper_threshold_minutes=15)
    assert CT.should_chunk(0, 15 * 60, cfg) is False


# ====================================================== TEST 5: dedup heavy overlap

def test_dedup_heavy_overlap():
    """2 рила с 80% пересечением → остаётся первый по t0."""
    # r1: [0, 60], r2: [5, 65] → intersection=55, min_dur=60 → ratio=55/60≈0.92 > 0.5
    r1 = _reel("r01", 0.0,  60.0)
    r2 = _reel("r02", 5.0,  65.0)
    result = CT.dedup_reels([r1, r2], threshold=0.5)
    assert len(result) == 1
    assert result[0].id == "r01"


def test_dedup_exact_threshold_kept():
    """Пересечение ровно на пороге → оба остаются (граница включительно НЕ удаляет)."""
    # r1: [0,100], r2: [50,150] → intersection=50, min_dur=100 → ratio=0.5 (== threshold)
    r1 = _reel("r01", 0.0, 100.0)
    r2 = _reel("r02", 50.0, 150.0)
    result = CT.dedup_reels([r1, r2], threshold=0.5)
    assert len(result) == 2


# ====================================================== TEST 6: dedup no overlap

def test_dedup_no_overlap():
    """2 рила без пересечения → оба остаются."""
    r1 = _reel("r01", 0.0,  60.0)
    r2 = _reel("r02", 70.0, 130.0)
    result = CT.dedup_reels([r1, r2], threshold=0.5)
    assert len(result) == 2


def test_dedup_order_preserved():
    """dedup_reels сохраняет порядок по t0 (не сортирует по score)."""
    r1 = _reel("r01", 100.0, 160.0, score=70)
    r2 = _reel("r02", 0.0,   60.0,  score=90)
    result = CT.dedup_reels([r1, r2], threshold=0.5)
    assert [r.id for r in result] == ["r01", "r02"]   # порядок входного списка


# ====================================================== TEST 7: partial failure, continue

def test_partial_failure_continue(tmp_path):
    """Чанк 2 из 6 падает, fail_fast=False → 5 ок, 1 warning с временным интервалом."""
    chunk_files = []
    for i in range(6):
        p = tmp_path / f"chunk_{i:02d}.mp3"
        p.write_bytes(bytes([i, i, i]) * 10)   # разное содержимое → разные sha
        chunk_files.append(p)

    start_secs = [i * 600.0 for i in range(6)]
    end_secs   = [(i + 1) * 600.0 for i in range(6)]
    chunks_info = list(zip(chunk_files, start_secs, end_secs))

    backend = _FailingBackend(fail_on={2})
    results, warns = CT.transcribe_chunks(chunks_info, backend, tmp_path, fail_fast=False)

    assert len(results) == 6
    assert results[2] is None
    ok = [r for r in results if r is not None]
    assert len(ok) == 5
    assert len(warns) == 1
    # warning должен содержать временной интервал провального чанка
    assert "1200" in warns[0] or "20:00" in warns[0] or "20м" in warns[0].lower()


# ====================================================== TEST 8: partial failure, abort

def test_partial_failure_abort(tmp_path):
    """Чанк 2 из 6 падает, fail_fast=True → исключение, дальнейшие чанки не вызываются."""
    chunk_files = []
    for i in range(6):
        p = tmp_path / f"chunk_{i:02d}.mp3"
        p.write_bytes(bytes([i, i, i]) * 10)
        chunk_files.append(p)

    start_secs = [i * 600.0 for i in range(6)]
    end_secs   = [(i + 1) * 600.0 for i in range(6)]
    chunks_info = list(zip(chunk_files, start_secs, end_secs))

    backend = _FailingBackend(fail_on={2})
    with pytest.raises(CT.ChunkTranscribeError):
        CT.transcribe_chunks(chunks_info, backend, tmp_path, fail_fast=True)

    # После падения на чанке 2 бэкенд вызывался ровно 3 раза (0,1,2)
    assert backend._call_idx == 3


# ====================================================== TEST 9: VAD split

def test_vad_split_prefers_silence():
    """Тишина на 598с (target=600, window=30) → split в 598с (середина интервала тишины)."""
    silences = [(597.5, 598.5)]
    result = CT.find_split_point(silences, target_sec=600.0, window_sec=30.0)
    assert result == pytest.approx(598.0)   # midpoint of silence interval


def test_vad_split_chooses_closest_silence():
    """Несколько тишин в окне → выбирается ближайшая к target."""
    silences = [(570.0, 571.0), (598.0, 599.0), (625.0, 626.0)]
    result = CT.find_split_point(silences, target_sec=600.0, window_sec=30.0)
    assert result == pytest.approx(598.5)   # midpoint [598, 599] — ближайший к 600


def test_vad_no_silence_fallback():
    """Нет тишины в окне → fallback на target_sec."""
    silences = [(200.0, 201.0)]   # за пределами окна [570, 630]
    result = CT.find_split_point(silences, target_sec=600.0, window_sec=30.0)
    assert result == pytest.approx(600.0)


def test_vad_empty_silences_fallback():
    """Пустой список тишин → fallback на target_sec."""
    result = CT.find_split_point([], target_sec=600.0, window_sec=30.0)
    assert result == pytest.approx(600.0)


# ====================================================== TEST 10: R0 renumbering

def test_r0_numbering():
    """Рилы из 3 чанков после дедупа → сквозная нумерация r01, r02, r03."""
    reels = [
        _reel("r01", 10.0,  70.0),    # из чанка 0
        _reel("r03", 610.0, 670.0),   # из чанка 1 (не r02!)
        _reel("r07", 1210.0, 1270.0), # из чанка 2 (не r03!)
    ]
    result = CT.renumber_reels(reels)
    assert [r.id for r in result] == ["r01", "r02", "r03"]


def test_r0_numbering_empty():
    """Пустой список → пустой результат, без ошибки."""
    assert CT.renumber_reels([]) == []


def test_r0_numbering_does_not_mutate_original():
    """renumber_reels не мутирует входной список (возвращает новые объекты)."""
    reels = [_reel("r05", 0.0, 60.0)]
    result = CT.renumber_reels(reels)
    assert reels[0].id == "r05"   # оригинал не тронут
    assert result[0].id == "r01"
