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


# ====================================================== TEST 2: overlap zone consistency (e2e)

def test_overlap_zone_consistency(tmp_path, monkeypatch):
    """СКВОЗНОЙ тест: VAD-срез на 598с (target=600) → слова получают offset=598, НЕ 600.

    Сценарий: аудио 1200с, target-граница 600с, тишина на [597.5, 598.5] → реальный срез 598с.
    Чанк 0 возвращает слово «тест» у самого конца (relative t0=598.5).
    Чанк 1 возвращает слово «тест» у самого начала (relative t0=0.5).
    Обе копии слова получают одинаковое абсолютное время 598+0.5=598.5 → это overlap-зона,
    и дедуп склейки схлопывает её в ОДНО слово (merge_transcripts убирает дубль по таймкодам).

    Это одновременно проверяет offset: только при верном offset=598 копии совпадают по времени
    (598.5) и дедупятся → 1 слово. При ошибочном offset=600 копия чанка 1 встала бы на 600.5,
    не попала бы в overlap-зону и осталась бы вторым словом → len==2 (тест ПАДАЕТ).
    """
    from autoreels.core.config import AudioExtract

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"\x00" * 100)

    # Мок: длительность аудио = 1200с (2 чанка, target-граница = 600с)
    monkeypatch.setattr(CT, "_probe_duration", lambda path, ffmpeg: 1200.0)

    # Мок: VAD находит тишину [597.5, 598.5] → find_split_point → 598.0 (НЕ 600!)
    monkeypatch.setattr(CT, "detect_silences", lambda *a, **k: [(597.5, 598.5)])

    # Мок: split_audio_chunk создаёт файлы с разным содержимым (разный sha → разный кэш)
    def _fake_split(src, start, end, out, audio_cfg, *, ffmpeg="ffmpeg"):
        out.write_bytes(bytes([int(start) % 256, 0, 0]) * 10)
    monkeypatch.setattr(CT, "split_audio_chunk", _fake_split)

    # Бэкенд: чанк 0 → слово у конца чанка (relative 598.5); чанк 1 → слово у начала (relative 0.5)
    call_idx = [0]
    class _BoundaryBackend:
        def transcribe(self, path, *, language=None):
            i = call_idx[0]; call_idx[0] += 1
            if i == 0:
                return Transcript(language="ru", words=[_w("тест", 598.5, 599.0)])
            return Transcript(language="ru", words=[_w("тест", 0.5, 1.0)])

    audio_cfg = AudioExtract(sample_rate=16000, channels=1, codec="libmp3lame",
                             format="mp3", bitrate="64k")
    cfg = _make_chunking_cfg(whisper_chunk_duration_sec=600, whisper_threshold_minutes=15,
                             silence_window_sec=30)

    transcript, _ = CT.transcribe_chunked(
        audio, cfg, audio_cfg, tmp_path, _BoundaryBackend()
    )

    # Overlap-зона (обе копии «тест» на абс. 598.5) схлопнута дедупом склейки → 1 слово.
    # len==1 доказывает и дедуп, и верный offset=598 (при offset=600 копия встала бы на
    # 600.5, не совпала бы с 598.5 → не дедупнулась → len==2).
    assert len(transcript.words) == 1, (
        f"ожидалось 1 слово после дедупа overlap, получено {len(transcript.words)} — "
        f"либо offset != 598 (копии разъехались), либо дедуп не сработал"
    )
    assert transcript.words[0].t0 == pytest.approx(598.5)


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


def test_merge_dedups_overlap_zone():
    """Соседние чанки перекрываются: хвост chunk0 и начало chunk1 — одни и те же слова
    с совпадающими АБСОЛЮТНЫМИ таймкодами (offset выравнивает их). В склейке overlap-зона
    остаётся ОДИН раз (дедуп по word-таймкодам), а не дублируется в тексте.
    """
    # chunk0: обычное слово + хвостовая фраза «страх порождает страх» в абс. [10.0, 12.0]
    chunk0 = _tr(("мысль", 8.0, 8.5),
                 ("страх", 10.0, 10.5), ("порождает", 10.6, 11.2), ("страх", 11.3, 12.0))
    # chunk1: та же фраза в overlap-зоне (relative 0.0–2.0), затем новое слово.
    # offset=10.0 → абс. времена overlap-слов совпадают с хвостом chunk0.
    chunk1 = _tr(("страх", 0.0, 0.5), ("порождает", 0.6, 1.2), ("страх", 1.3, 2.0),
                 ("дальше", 2.5, 3.0))

    result = CT.merge_transcripts([chunk0, chunk1], [0.0, 10.0])
    text = " ".join(w.word for w in result.words)

    assert text == "мысль страх порождает страх дальше"
    assert text.count("порождает") == 1          # overlap-фраза не задвоилась
    assert result.words[-1].t0 == pytest.approx(12.5)  # «дальше» = 10.0 + 2.5


def test_merge_keeps_intrachunk_jitter():
    """Пословный джиттер Whisper ВНУТРИ чанка (t0 слова < t1 предыдущего) — НЕ дедуп.

    Дедуп режет только стык чанков; внутри чанка все слова сохраняются, даже если их
    таймкоды слегка налезают друг на друга (нормально для Whisper на русской речи).
    Иначе глобальный frontier выкидывал бы легитимные слова и рвал текст.
    """
    # «свою» стартует (59.72) РАНЬШЕ, чем кончилось «через» (t1=60.20) — джиттер, не overlap
    chunk0 = _tr(("через", 59.80, 60.20), ("свою", 59.72, 60.40), ("призму", 60.40, 60.90))
    result = CT.merge_transcripts([chunk0], [0.0])

    assert [w.word for w in result.words] == ["через", "свою", "призму"]  # ничего не выкинуто


def test_merge_no_overlap_gap_keeps_first_word():
    """Неперекрывающиеся чанки (силенс-срез с зазором): первое слово след. чанка сохраняется.

    prev_t1 < t0 первого слова следующего чанка → дедуп ничего не режет (k=0).
    """
    chunk0 = _tr(("один", 0.0, 0.5), ("два", 1.0, 1.5))
    chunk1 = _tr(("три", 0.0, 0.5))          # offset 600 → абс. 600.0, зазор ~598.5с
    result = CT.merge_transcripts([chunk0, chunk1], [0.0, 600.0])

    assert [w.word for w in result.words] == ["один", "два", "три"]
    assert result.words[-1].t0 == pytest.approx(600.0)


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
    """2 рила с 80% пересечением → остаётся ранний по t0, независимо от порядка во входном списке."""
    # r1: [0, 60], r2: [5, 65] → intersection=55, min_dur=60 → ratio=55/60≈0.92 > 0.5
    r1 = _reel("r01", 0.0,  60.0)
    r2 = _reel("r02", 5.0,  65.0)
    # Подаём в обратном порядке: r2 первый. После сортировки по t0 → r1 первый → r1 остаётся
    result = CT.dedup_reels([r2, r1], threshold=0.5)
    assert len(result) == 1
    assert result[0].id == "r01"   # ранний по t0, НЕ первый в списке входа


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


def test_dedup_sorted_by_t0_not_score():
    """dedup_reels сортирует по t0 перед дедупом: ранний рил остаётся, даже если score ниже."""
    # r1 у конца (start=100), r2 в начале (start=0) с высоким score
    # После сортировки по t0: r2 идёт первым → при дедупе r2 остаётся, не r1
    r1 = _reel("r01", 100.0, 160.0, score=70)
    r2 = _reel("r02", 0.0,   60.0,  score=90)
    result = CT.dedup_reels([r1, r2], threshold=0.5)
    # Нет пересечения → оба остаются, в порядке t0 (r2 раньше)
    assert [r.id for r in result] == ["r02", "r01"]


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


# ====================================================== TEST 11: _derive_ffprobe

def test_derive_ffprobe_from_path(monkeypatch, tmp_path):
    """Если ffprobe НЕТ в PATH, но лежит рядом с ffmpeg — берётся сосед."""
    fake_ffmpeg = tmp_path / "ffmpeg"
    fake_ffprobe = tmp_path / "ffprobe"
    fake_ffprobe.touch()

    monkeypatch.setattr(CT.shutil, "which", lambda name: None)  # не в PATH

    result = CT._derive_ffprobe(str(fake_ffmpeg))
    assert result == str(fake_ffprobe)


def test_derive_ffprobe_prefers_path(monkeypatch, tmp_path):
    """Если ffprobe есть в PATH — берётся из PATH, а не из каталога ffmpeg."""
    fake_ffprobe_path = str(tmp_path / "system_ffprobe")
    monkeypatch.setattr(CT.shutil, "which", lambda name: fake_ffprobe_path if name == "ffprobe" else None)

    result = CT._derive_ffprobe("/some/other/dir/ffmpeg")
    assert result == fake_ffprobe_path


def test_derive_ffprobe_fallback_bare(monkeypatch):
    """Ни PATH, ни соседний файл — возвращает голое 'ffprobe' (последний шанс)."""
    monkeypatch.setattr(CT.shutil, "which", lambda name: None)

    result = CT._derive_ffprobe("ffmpeg")  # нет пути → нет соседа
    assert result == "ffprobe"


def test_detect_silences_file_not_found_gives_clear_error(monkeypatch, tmp_path):
    """FileNotFoundError при запуске ffmpeg → ChunkTranscribeError с именем утилиты и шагом."""
    import subprocess
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"\x00")

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(CT.subprocess, "run", fake_run)

    with pytest.raises(CT.ChunkTranscribeError) as exc:
        CT.detect_silences(audio, threshold_db=-40, ffmpeg="/nonexistent/ffmpeg")
    msg = str(exc.value)
    assert "ffmpeg" in msg
    assert "VAD" in msg or "тишин" in msg


def test_probe_duration_file_not_found_gives_clear_error(monkeypatch, tmp_path):
    """FileNotFoundError от ffprobe → ChunkTranscribeError с именем утилиты и шагом."""
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"\x00")

    monkeypatch.setattr(CT.shutil, "which", lambda name: None)

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(CT.subprocess, "run", fake_run)

    with pytest.raises(CT.ChunkTranscribeError) as exc:
        CT._probe_duration(audio, ffmpeg="ffmpeg")
    msg = str(exc.value)
    assert "ffprobe" in msg
    assert "длительност" in msg


# ====================================================== GUARD: нет голых 'ffmpeg'/'ffprobe' в subprocess

def test_no_bare_ffmpeg_in_subprocess_calls():
    """Guard: ни один .py-файл кроме __main__.py не содержит литерального ['ffmpeg' или ['ffprobe'
    как первый аргумент подпроцесса. Все вызовы внешних бинарей должны идти через параметр."""
    import re
    from pathlib import Path

    src = Path(__file__).parent.parent / "src" / "autoreels"
    pattern = re.compile(r"\[\s*[\"']ff(?:mpeg|probe)[\"']")

    violations = []
    for f in sorted(src.rglob("*.py")):
        if f.name == "__main__.py":
            continue  # резолверы определяют bare-имена здесь, это допустимо
        text = f.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            lineno = text[: m.start()].count("\n") + 1
            violations.append(f"{f.relative_to(src.parent.parent)}:{lineno}")

    assert not violations, (
        "Голые 'ffmpeg'/'ffprobe' в начале subprocess-списка — "
        "использовать параметр ffmpeg=... везде:\n" + "\n".join(violations)
    )
