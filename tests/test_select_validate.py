"""R0 — детерминированный слой выбора (cloud/select.py).

ВНИМАНИЕ: зелёная сюита здесь = «код вокруг LLM корректен», НЕ «выборка хорошая».
Качество рубрики проверяется на реальном транскрипте в 5b (глазами), не pytest.
Всё на мокнутых ответах Qwen.
"""
import json
from pathlib import Path

import pytest

from autoreels.core.config import load_r0_config
from autoreels.core.models import Reel
from autoreels.cloud import select as S

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_MD = ROOT / "prompts" / "r0_system.md"
FEWSHOT = ROOT / "prompts" / "r0_fewshot.json"
QWEN_FIXTURE = ROOT / "tests" / "fixtures" / "qwen_r0_response.json"


@pytest.fixture
def r0_cfg():
    return load_r0_config(ROOT / "config" / "r0.yaml")


@pytest.fixture
def fewshot():
    return json.loads(FEWSHOT.read_text(encoding="utf-8"))


class _MockLLM:
    """Мок-провайдер: отдаёт заранее заданные ответы по очереди, считает вызовы."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def complete(self, messages, *, temperature=0.0):
        r = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return r


def _reel(score, start, end, rid="rXX"):
    return Reel(id=rid, start=start, end=end, score=score,
                hook="h", title="t", description="d")


# ----------------------------------------------------------------- промпт

def test_build_prompt_substitutes_config_variables(fewshot, r0_cfg):
    system_text = SYSTEM_MD.read_text(encoding="utf-8")
    msgs = S.build_prompt(
        system_text, fewshot, "[0000.0-0005.0] привет",
        min_score=r0_cfg.min_score, min_duration=r0_cfg.min_duration,
        max_duration=r0_cfg.max_duration,
    )
    assert msgs[0]["role"] == "system"
    assert "{{" not in msgs[0]["content"]                  # все плейсхолдеры подставлены
    assert "65" in msgs[0]["content"]                      # min_score
    # few-shot развёрнут в user/assistant пары, реальный транскрипт — последним user.
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"] == "[0000.0-0005.0] привет"
    assert sum(1 for m in msgs if m["role"] == "assistant") == len(fewshot["examples"])


# ----------------------------------------------------------------- парсинг

def test_parse_valid_contract_to_reels():
    # Против РЕАЛЬНОГО multi-segment ответа Qwen (снимок 5b). Проверяем ПАРСИНГ формы;
    # len меняется только если сломан парсер (фикстура статична), не «5 как качество».
    content = QWEN_FIXTURE.read_text(encoding="utf-8")
    segments = S.parse_segments(content)
    reels = S.segments_to_reels(segments)
    assert len(reels) == 5
    assert [r.id for r in reels] == ["r01", "r02", "r03", "r04", "r05"]  # порядок фикстуры
    assert isinstance(reels[0], Reel)
    assert reels[0].start == 284.5 and reels[0].end == 341.5 and reels[0].score == 78
    assert reels[1].start == 432.1 and reels[1].score == 85
    assert reels[4].start == 590.0 and reels[4].score == 80
    assert reels[0].title.startswith("ПОЧЕМУ ДЫШ")


def test_invalid_json_retries_then_errors(fewshot, r0_cfg):
    provider = _MockLLM(["не json", "опять не json"])
    with pytest.raises(S.SelectError):
        S.select("[0000.0-0005.0] x", system_text="sys", fewshot=fewshot,
                 provider=provider, r0_cfg=r0_cfg)
    assert provider.calls == 2                              # один ретрай и стоп


def test_invalid_then_valid_recovers(fewshot, r0_cfg):
    good = QWEN_FIXTURE.read_text(encoding="utf-8")
    provider = _MockLLM(["мусор", good])
    reels = S.select("[0000.0-0005.0] x", system_text="sys", fewshot=fewshot,
                     provider=provider, r0_cfg=r0_cfg)
    assert provider.calls == 2
    assert len(reels) == 5


def test_real_fixture_flags_too_long(fewshot, r0_cfg):
    # Инвариант 6 на РЕАЛЬНЫХ данных: 590.0–651.8 (61.8с > 59 shorts) код метит too_long;
    # сегмент в пределах пресета — без флага. Ставит код, не модель.
    content = QWEN_FIXTURE.read_text(encoding="utf-8")
    reels = S.select("[0000.0-0005.0] x", system_text="sys", fewshot=fewshot,
                     provider=_MockLLM([content]), r0_cfg=r0_cfg)
    by_start = {r.start: r for r in reels}
    assert "too_long" in by_start[590.0].flags     # 61.8с — за пресетом
    assert by_start[432.1].flags == []             # 52.5с — в пределах


# ----------------------------------------------------------- валидаторы (код, не модель)

def test_flags_too_long_and_too_short(r0_cfg):
    # Пресет shorts: 15..59с. Код ставит флаги на граничных длинах.
    short = _reel(80, 0.0, 10.0)     # 10с < 15 → too_short
    ok = _reel(80, 0.0, 30.0)        # 30с в пределах → без флага
    long = _reel(80, 0.0, 70.0)      # 70с > 59 → too_long
    S.flag_durations([short, ok, long],
                     min_duration=r0_cfg.min_duration, max_duration=r0_cfg.max_duration)
    assert short.flags == ["too_short"]
    assert ok.flags == []
    assert long.flags == ["too_long"]


def test_reject_below_min_score(r0_cfg):
    keep = _reel(65, 0.0, 30.0)       # == min_score → остаётся
    drop = _reel(64, 0.0, 30.0)       # < min_score → отбраковка
    out = S.filter_by_score([keep, drop], min_score=r0_cfg.min_score)
    assert out == [keep]


def test_dedup_keeps_higher_score(r0_cfg):
    a = _reel(80, 100.0, 130.0)       # overlap с b > 50%
    b = _reel(60, 110.0, 140.0)
    far = _reel(70, 300.0, 330.0)     # не пересекается
    out = S.dedup([a, b, far], overlap_threshold=r0_cfg.dedup_overlap_threshold)
    assert a in out and far in out and b not in out


# ----------------------------------------------------------- инвариант 3: пустой результат

def test_empty_segments_is_valid_result(fewshot, r0_cfg):
    provider = _MockLLM(['{"segments": []}'])
    reels = S.select("[0400.0-0410.0] давайте сделаем перерыв",
                     system_text="sys", fewshot=fewshot, provider=provider, r0_cfg=r0_cfg)
    assert reels == []                 # «хороших моментов нет» — НЕ ошибка


# ----------------------------------------------------------- R0 chunking

def _make_compressed(n_lines: int, line_chars: int = 60) -> str:
    """Синтетический сжатый транскрипт: n строк по line_chars символов."""
    lines = []
    for i in range(n_lines):
        t0 = i * 5.0
        t1 = t0 + 4.0
        text = ("слово " * 8).strip()[:line_chars - 20]
        lines.append(f"[{t0:06.1f}-{t1:06.1f}] {text}")
    return "\n".join(lines)


def test_split_compressed_single_chunk_when_short():
    """Короткий текст помещается в один чанк — дополнительного чанкинга нет."""
    compressed = _make_compressed(5)    # 5 строк, ~300 символов ≈ 75 токенов
    chunks = S.split_compressed(compressed, chunk_tokens=500, overlap_tokens=50)
    assert len(chunks) == 1
    assert chunks[0] == compressed


def test_split_compressed_produces_multiple_chunks():
    """Длинный текст → несколько чанков; каждый не превышает лимит по токенам."""
    compressed = _make_compressed(100)   # 100 строк
    # chunk_tokens=120 → примерно каждые 8 строк
    chunks = S.split_compressed(compressed, chunk_tokens=120, overlap_tokens=30)
    assert len(chunks) >= 3
    for c in chunks:
        # каждый чанк в пределах chunk + 1 строка (последняя строка может слегка превысить)
        assert S._count_tokens(c) <= 150   # с небольшим запасом


def test_split_compressed_overlap_lines_repeated():
    """Последние строки чанка i входят в начало чанка i+1 (overlap)."""
    compressed = _make_compressed(40, line_chars=40)
    chunks = S.split_compressed(compressed, chunk_tokens=100, overlap_tokens=40)
    assert len(chunks) >= 2
    # Последняя строка чанка 0 должна быть где-то в начале чанка 1
    last_line_of_chunk0 = chunks[0].splitlines()[-1]
    assert last_line_of_chunk0 in chunks[1], "overlap не работает: последняя строка чанка 0 не в чанке 1"


def test_split_compressed_empty():
    """Пустой текст → пустой список, без ошибки."""
    assert S.split_compressed("", chunk_tokens=500, overlap_tokens=50) == []


def test_split_compressed_no_infinite_loop():
    """Гарантия выхода: алгоритм не зависает даже на одной строке с overlap > chunk."""
    line = "[0000.0-0005.0] " + "слово " * 20
    compressed = "\n".join([line] * 5)
    chunks = S.split_compressed(compressed, chunk_tokens=10, overlap_tokens=10)
    assert len(chunks) >= 1   # завершился (не завис)


def test_select_single_llm_call_when_short(fewshot, r0_cfg):
    """Короткий транскрипт (< chunk_tokens) → ровно 1 вызов LLM."""
    provider = _MockLLM(['{"segments": []}'])
    S.select("[0000.0-0005.0] короткий текст",
             system_text="sys", fewshot=fewshot, provider=provider, r0_cfg=r0_cfg)
    assert provider.calls == 1


def test_select_chunked_multiple_llm_calls_when_long(fewshot, r0_cfg):
    """Длинный транскрипт (> chunk_tokens) → несколько вызовов LLM."""
    # Создаём транскрипт, который точно превышает r0_cfg.chunking.r0_chunk_tokens
    compressed = _make_compressed(300, line_chars=60)   # ~300 строк * 60 символов ≈ 4500 токенов
    provider = _MockLLM(['{"segments": []}'])
    S.select(compressed, system_text="sys", fewshot=fewshot, provider=provider, r0_cfg=r0_cfg)
    assert provider.calls >= 2


def test_select_chunked_dedup_overlap_reels(fewshot, r0_cfg):
    """Один и тот же момент найден в 2 чанках → после дедупа остаётся 1 рил."""
    reel_json = json.dumps({"segments": [
        {"start": 100.0, "end": 130.0, "score": 85, "hook": "h", "title": "t", "description": "d"},
    ]})
    # Оба чанка возвращают одинаковый рил (overlap zone)
    provider = _MockLLM([reel_json, reel_json])
    compressed = _make_compressed(300, line_chars=60)
    reels = S.select(compressed, system_text="sys", fewshot=fewshot,
                     provider=provider, r0_cfg=r0_cfg)
    # Дедуп должен оставить ровно 1 рил, не 2
    matching = [r for r in reels if abs(r.start - 100.0) < 1.0]
    assert len(matching) == 1


def test_select_chunked_delays_between_chunks(fewshot, r0_cfg, monkeypatch):
    """select_chunked делает паузу r0_chunk_delay_sec между R0-чанками."""
    import autoreels.cloud.select as sel_mod
    sleeps = []
    monkeypatch.setattr(sel_mod.time, "sleep", lambda s: sleeps.append(s))

    provider = _MockLLM(['{"segments": []}'])
    compressed = _make_compressed(300, line_chars=60)  # гарантированно > chunk_tokens → ≥2 чанка
    S.select(compressed, system_text="sys", fewshot=fewshot, provider=provider, r0_cfg=r0_cfg)

    # Между N чанками должно быть N-1 пауз
    assert len(sleeps) >= 1, "нет пауз между R0-чанками"
    expected_delay = r0_cfg.chunking.r0_chunk_delay_sec
    assert all(s == expected_delay for s in sleeps), f"неверная пауза: {sleeps}"


def test_select_chunked_no_delay_after_last_chunk(fewshot, r0_cfg, monkeypatch):
    """После последнего чанка паузы не должно быть (только между чанками)."""
    import autoreels.cloud.select as sel_mod
    sleeps = []
    monkeypatch.setattr(sel_mod.time, "sleep", lambda s: sleeps.append(s))

    provider = _MockLLM(['{"segments": []}'])
    compressed = _make_compressed(300, line_chars=60)
    S.select(compressed, system_text="sys", fewshot=fewshot, provider=provider, r0_cfg=r0_cfg)

    # N чанков → N-1 пауз (не N)
    chunks = S.split_compressed(
        compressed, r0_cfg.chunking.r0_chunk_tokens, r0_cfg.chunking.r0_overlap_tokens
    )
    assert len(sleeps) == len(chunks) - 1


def test_split_compressed_uses_prompt_aware_budget(fewshot, r0_cfg):
    """Бюджет чанка уменьшается на размер промпта (system + few-shot)."""
    system_text = "x" * 400   # ~100 токенов
    fewshot_small = {"examples": []}

    compressed = _make_compressed(100, line_chars=60)
    budget_full = r0_cfg.chunking.r0_chunk_tokens

    # При маленьком промпте (0 токенов) → много строк на чанк
    chunks_no_overhead = S.split_compressed(compressed, budget_full, r0_cfg.chunking.r0_overlap_tokens)
    # При большом промпте (~100 токенов) → меньше строк на чанк → больше чанков
    # Симулируем: вызов select_chunked передаёт эффективный бюджет = chunk_tokens - prompt_tokens
    effective = S._effective_chunk_tokens(system_text, fewshot_small, budget_full)
    chunks_with_overhead = S.split_compressed(compressed, effective, r0_cfg.chunking.r0_overlap_tokens)

    # prompt_tokens > 0 → effective < full → больше чанков (или равно, но не меньше)
    assert effective < budget_full
    assert len(chunks_with_overhead) >= len(chunks_no_overhead)


def test_select_chunked_renumbers_sequentially(fewshot, r0_cfg):
    """После смержа чанков id рилов сквозные: r01, r02, …"""
    def _seg(start, end, score):
        return {"start": start, "end": end, "score": score,
                "hook": "h", "title": "t", "description": "d"}
    r1 = json.dumps({"segments": [_seg(0, 40, 85), _seg(50, 90, 75)]})
    r2 = json.dumps({"segments": [_seg(600, 640, 80)]})
    provider = _MockLLM([r1, r2])
    compressed = _make_compressed(300, line_chars=60)
    reels = S.select(compressed, system_text="sys", fewshot=fewshot,
                     provider=provider, r0_cfg=r0_cfg)
    assert [r.id for r in reels] == [f"r{i:02d}" for i in range(1, len(reels) + 1)]


def test_select_ranks_by_score_and_assigns_ids(fewshot, r0_cfg):
    # Ранжирование/нумерация — логика кода, не форма Groq (её проверяет тест парсинга
    # на реальной фикстуре). Здесь синтетический многосегментный ответ.
    raw = json.dumps({"segments": [
        {"start": 100.0, "end": 130.0, "score": 72, "hook": "h", "title": "t1", "description": "d"},
        {"start": 200.0, "end": 230.0, "score": 90, "hook": "h", "title": "t2", "description": "d"},
    ]})
    provider = _MockLLM([raw])
    reels = S.select("[0000.0-0005.0] x", system_text="sys", fewshot=fewshot,
                     provider=provider, r0_cfg=r0_cfg)
    assert [r.score for r in reels] == [90, 72]   # ранжировано по score (убыв.)
    assert [r.id for r in reels] == ["r01", "r02"]
