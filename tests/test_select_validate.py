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
