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
    # Против РЕАЛЬНОГО ответа Qwen (захвачен в 5b): 1 сегмент.
    content = QWEN_FIXTURE.read_text(encoding="utf-8")
    segments = S.parse_segments(content)
    reels = S.segments_to_reels(segments)
    assert [r.id for r in reels] == ["r01"]
    assert isinstance(reels[0], Reel)
    assert reels[0].start == 237.0 and reels[0].score == 82
    assert reels[0].title.startswith("ПОЧЕМУ НЕЛЬЗЯ")


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
    assert len(reels) == 1


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
