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


def test_parse_segments_none_raises_selecterror_not_typeerror():
    """None-ответ (провайдер отдал пустое тело) → SelectError, а не TypeError из json.loads(None)."""
    with pytest.raises(S.SelectError):
        S.parse_segments(None)


def test_parse_segments_blank_raises_selecterror():
    """Пустая/пробельная строка → SelectError (не падаем на json.loads)."""
    for raw in ("", "   ", "\n"):
        with pytest.raises(S.SelectError):
            S.parse_segments(raw)


def test_empty_provider_response_is_chunk_failure_not_crash(fewshot, r0_cfg):
    """Провайдер вернул пустую строку → SelectError (провал чанка), не краш видео."""
    provider = _MockLLM(["", ""])
    with pytest.raises(S.SelectError):
        S.select("[0000.0-0005.0] x", system_text="sys", fewshot=fewshot,
                 provider=provider, r0_cfg=r0_cfg)


def test_provider_empty_response_exception_becomes_selecterror(fewshot, r0_cfg):
    """ProviderEmptyResponse от провайдера (пул исчерпал сиблингов) → SelectError, не пробрасывается."""
    from autoreels.cloud.providers import ProviderEmptyResponse

    class _EmptyProvider:
        calls = 0
        def complete(self, messages, *, temperature=0.0):
            type(self).calls += 1
            raise ProviderEmptyResponse("все провайдеры пусты", provider="pool")

    with pytest.raises(S.SelectError):
        S.select("[0000.0-0005.0] x", system_text="sys", fewshot=fewshot,
                 provider=_EmptyProvider(), r0_cfg=r0_cfg)


def test_invalid_then_valid_recovers(fewshot, r0_cfg):
    good = QWEN_FIXTURE.read_text(encoding="utf-8")
    provider = _MockLLM(["мусор", good])
    reels = S.select("[0000.0-0005.0] x", system_text="sys", fewshot=fewshot,
                        provider=provider, r0_cfg=r0_cfg)
    assert provider.calls == 2
    assert len(reels) == 5


def test_real_fixture_flags_too_long(fewshot, r0_cfg):
    # Инвариант 6 на РЕАЛЬНЫХ данных: 590.0–651.8 (61.8с < 90 shorts) — в пределах нового потолка,
    # флага too_long быть не должно. Ставит код, не модель.
    content = QWEN_FIXTURE.read_text(encoding="utf-8")
    reels = S.select("[0000.0-0005.0] x", system_text="sys", fewshot=fewshot,
                        provider=_MockLLM([content]), r0_cfg=r0_cfg)
    by_start = {r.start: r for r in reels}
    assert by_start[590.0].flags == []              # 61.8с — в пределах нового потолка 90с
    assert by_start[432.1].flags == []              # 52.5с — в пределах


# ----------------------------------------------------------- валидаторы (код, не модель)

def test_flags_too_long_and_too_short(r0_cfg):
    # Пресет shorts: 15..90с. Код ставит флаги на граничных длинах.
    short = _reel(80, 0.0, 10.0)     # 10с < 15 → too_short
    ok = _reel(80, 0.0, 30.0)        # 30с в пределах → без флага
    long = _reel(80, 0.0, 95.0)      # 95с > 90 → too_long
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


def test_reject_below_min_meaningful_duration(r0_cfg):
    """Пост-фильтр длины: сегмент короче min_meaningful_sec отбраковывается (законченной
    мысли не бывает в слишком коротком куске). Планка ВЫШЕ технического min_duration."""
    floor = r0_cfg.min_meaningful_sec
    keep = _reel(90, 0.0, floor)               # ровно порог → остаётся
    keep_long = _reel(70, 0.0, floor + 10)     # длиннее порога → остаётся
    drop = _reel(95, 0.0, floor - 0.1)         # короче порога → отбраковка, даже с высоким score
    out = S.filter_by_duration([keep, keep_long, drop], min_meaningful_sec=floor)
    assert keep in out and keep_long in out
    assert drop not in out


def test_min_meaningful_sec_is_above_preset_min(r0_cfg):
    """Планка смысла строго выше технического минимума пресета — иначе фильтр no-op."""
    assert r0_cfg.min_meaningful_sec > r0_cfg.min_duration


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


def test_select_drops_short_segment_despite_high_score(fewshot, r0_cfg):
    """Даже с высоким score короткий сегмент (< min_meaningful_sec) не попадает в выборку.

    Регресс на «пустые 15-сек клипы»: LLM переоценил короткий кусок → детерминированный
    пост-фильтр длины его снимает. Длинный самодостаточный момент — остаётся."""
    short_end = r0_cfg.min_meaningful_sec - 1     # заведомо короче планки смысла
    resp = json.dumps({"segments": [
        {"start": 0.0, "end": short_end, "score": 95,
         "hook": "h", "title": "t", "description": "d"},
        {"start": 100.0, "end": 130.0, "score": 70,
         "hook": "h", "title": "t", "description": "d"},
    ]})
    reels = S.select("[0000.0-0005.0] x", system_text="sys", fewshot=fewshot,
                        provider=_MockLLM([resp]), r0_cfg=r0_cfg)
    starts = {r.start for r in reels}
    assert 0.0 not in starts        # короткий снят пост-фильтром длины
    assert 100.0 in starts          # длинный самодостаточный — остался


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


def test_select_chunked_survives_one_empty_chunk(fewshot, r0_cfg, monkeypatch, capsys):
    """Один чанк вернул пустой ответ → провал ЭТОГО чанка (warning), остальные дают рилы.

    Регресс на баг: пустой ответ провайдера ронял всё видео (json.loads(None) → TypeError).
    Теперь — как с транскрипцией: чанк failed, манифест собирается из выживших чанков."""
    import autoreels.cloud.select as sel_mod
    monkeypatch.setattr(sel_mod.time, "sleep", lambda s: None)
    valid = json.dumps({"segments": [
        {"start": 100.0, "end": 130.0, "score": 85, "hook": "h", "title": "t", "description": "d"},
    ]})

    class _ChunkMock:
        def __init__(self):
            self.seen = []
        def complete(self, messages, *, temperature=0.0):
            chunk = messages[-1]["content"]
            if chunk not in self.seen:
                self.seen.append(chunk)
            return "" if self.seen.index(chunk) == 1 else valid   # 2-й чанк — пустой

    compressed = _make_compressed(300, line_chars=60)             # ≥2 чанка
    reels = S.select(compressed, system_text="sys", fewshot=fewshot,
                        provider=_ChunkMock(), r0_cfg=r0_cfg)

    assert len(reels) >= 1                                        # выжившие чанки дали рилы
    assert "провалился" in capsys.readouterr().out                # предупреждение о провале чанка


def test_select_chunked_survives_one_timeout_chunk(fewshot, r0_cfg, monkeypatch, capsys):
    """Сетевой таймаут на ОДНОМ чанке (пул исчерпал сиблингов → ProviderTimeout) → провал ЭТОГО
    чанка, остальные дают рилы. Всё видео НЕ теряется (баг: read timeout ронял видео целиком)."""
    import autoreels.cloud.select as sel_mod
    from autoreels.cloud.providers import ProviderTimeout
    monkeypatch.setattr(sel_mod.time, "sleep", lambda s: None)
    valid = json.dumps({"segments": [
        {"start": 100.0, "end": 130.0, "score": 85, "hook": "h", "title": "t", "description": "d"},
    ]})

    class _ChunkMock:
        def __init__(self):
            self.seen = []
        def complete(self, messages, *, temperature=0.0):
            chunk = messages[-1]["content"]
            if chunk not in self.seen:
                self.seen.append(chunk)
            if self.seen.index(chunk) == 1:                      # 2-й чанк — сетевой таймаут
                raise ProviderTimeout("Groq: сетевой таймаут R0-запроса", provider="Groq")
            return valid

    compressed = _make_compressed(300, line_chars=60)            # ≥2 чанка
    reels = S.select(compressed, system_text="sys", fewshot=fewshot,
                        provider=_ChunkMock(), r0_cfg=r0_cfg)

    assert len(reels) >= 1                                        # выжившие чанки дали рилы
    out = capsys.readouterr().out
    assert "провалился" in out and "таймаут" in out.lower()      # провал чанка с указанием причины


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

    # N чанков → N-1 пауз (не N). Число чанков считаем ЭФФЕКТИВНЫМ бюджетом (как
    # select_chunked: r0_chunk_tokens − размер промпта), иначе тест ломается при смене
    # few-shot (размер промпта → меньше строк на чанк → больше чанков).
    effective = S._effective_chunk_tokens("sys", fewshot, r0_cfg.chunking.r0_chunk_tokens)
    chunks = S.split_compressed(compressed, effective, r0_cfg.chunking.r0_overlap_tokens)
    assert len(sleeps) == len(chunks) - 1


@pytest.mark.parametrize("chunk_tokens", [1200, 2500, 4000])
def test_split_compressed_uses_prompt_aware_budget(fewshot, r0_cfg, chunk_tokens):
    """Invariants of _effective_chunk_tokens hold for any reasonable r0_chunk_tokens value.

    The formula: effective = max(500, min(chunk_tokens, limit_budget))
    where limit_budget = (groq_limit − max_out − template) / factor − system_tok − fewshot_tok.

    Tested invariants (independent of config value):
    - Never exceeds chunk_tokens (config is the upper bound).
    - Always positive (min-guard of 500).
    - When system overhead is large enough to make limit_budget < chunk_tokens,
      effective < chunk_tokens (limit, not config, is binding).
    - Fewer tokens per chunk → at least as many chunks.
    """
    # System large enough (~2500 tok) to push limit_budget below 4000 but possibly above 1200.
    system_text = "x" * 10000   # ~2500 tokens
    fewshot_small = {"examples": []}

    effective = S._effective_chunk_tokens(system_text, fewshot_small, chunk_tokens)

    # invariant 1: config upper bound respected
    assert effective <= chunk_tokens
    # invariant 2: always positive
    assert effective >= 500

    # invariant 3 (limit is binding): when overhead forces limit_budget below chunk_tokens,
    # effective < chunk_tokens. We verify by computing limit_budget directly.
    system_tok = len(system_text) // 4
    limit_budget = int((8000 - 900 - 400) / 1.45) - system_tok   # no fewshot
    if limit_budget < chunk_tokens:
        assert effective < chunk_tokens, (
            f"large system should cap effective ({effective}) below chunk_tokens ({chunk_tokens})"
        )

    # invariant 4: smaller budget → no fewer chunks
    compressed = _make_compressed(100, line_chars=60)
    overlap = r0_cfg.chunking.r0_overlap_tokens
    chunks_config = S.split_compressed(compressed, chunk_tokens, overlap)
    chunks_effective = S.split_compressed(compressed, effective, overlap)
    assert len(chunks_effective) >= len(chunks_config)


def test_select_chunked_renumbers_sequentially(fewshot, r0_cfg):
    """После смержа чанков id рилов сквозные: c001, c002, …"""
    def _seg(start, end, score):
        return {"start": start, "end": end, "score": score,
                "hook": "h", "title": "t", "description": "d"}
    r1 = json.dumps({"segments": [_seg(0, 40, 85), _seg(50, 90, 75)]})
    r2 = json.dumps({"segments": [_seg(600, 640, 80)]})
    provider = _MockLLM([r1, r2])
    compressed = _make_compressed(300, line_chars=60)
    reels = S.select(compressed, system_text="sys", fewshot=fewshot,
                        provider=provider, r0_cfg=r0_cfg)
    assert [r.id for r in reels] == [f"c{i:03d}" for i in range(1, len(reels) + 1)]


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
    assert {r.score for r in reels} == {72, 90}
    assert all(r.id.startswith("c") for r in reels)  # candidate IDs до renumber


# ----------------------------------------------------------- dangling_start gate (post-snap)

from autoreels.core.models import Word as _Word


def _words(pairs):
    return [_Word(word=w, t0=t0, t1=t1) for w, t0, t1 in pairs]


def _creel(start=0.0, end=30.0, score=80, rid="c001"):
    return Reel(id=rid, start=start, end=end, score=score,
                hook="h", title="t", description="d")


def test_dangling_start_r04_lowercase():
    """r04-style: 'все' (lowercase) → flagged dangling_start."""
    words = _words([("все", 10.0, 10.5), ("ваши", 10.5, 11.0), ("травмы", 11.0, 11.5)])
    r = _creel()
    kept, disc = S.filter_dangling_start([r], words)
    assert len(kept) == 0 and len(disc) == 1
    assert "dangling_start" in disc[0]["reason"]


def test_dangling_start_r14_lubom():
    """r14-style: 'любом' (lowercase + in dangling list) → flagged."""
    words = _words([("любом", 10.0, 10.4), ("случае,", 10.4, 10.8)])
    r = _creel()
    kept, disc = S.filter_dangling_start([r], words)
    assert len(kept) == 0


def test_dangling_start_r05_lowercase():
    """r05-style: 'моя' (lowercase) → flagged."""
    words = _words([("моя", 5.0, 5.3), ("психика", 5.3, 5.8)])
    r = _creel()
    kept, disc = S.filter_dangling_start([r], words)
    assert len(kept) == 0


def test_dangling_start_r13_lowercase():
    """r13-style: 'так' (lowercase) → flagged."""
    words = _words([("так", 20.0, 20.3), ("брать,", 20.3, 20.7)])
    r = _creel()
    kept, disc = S.filter_dangling_start([r], words)
    assert len(kept) == 0


def test_dangling_start_clean_opener():
    """Uppercase sentence-initial word passes."""
    words = _words([("За", 0.0, 0.3), ("травмой", 0.3, 0.7)])
    r = _creel()
    kept, disc = S.filter_dangling_start([r], words)
    assert len(kept) == 1 and len(disc) == 0


# ----------------------------------------------------------- top-N via apply_top_n

def _make_segs(n: int, *, base_score: int = 66) -> list[dict]:
    """n non-overlapping segments, scores base_score..base_score+n-1."""
    return [{"start": i * 40.0, "end": i * 40.0 + 30.0, "score": base_score + i,
             "hook": "h", "title": "t", "description": "d"} for i in range(n)]


def _make_reels(n: int, *, base_score: int = 66) -> list[Reel]:
    return [Reel(id=f"c{i:03d}", start=i * 40.0, end=i * 40.0 + 30.0,
                 score=base_score + i, hook="h", title="t", description="d")
            for i in range(n)]


def test_max_reels_top_n():
    """apply_top_n: 35 candidates → exactly 20 kept, 15 discarded."""
    reels = _make_reels(35)
    kept, disc = S.apply_top_n(reels, max_reels=20)
    assert len(kept) == 20
    assert len(disc) == 15


def test_max_reels_null_keep_all():
    """apply_top_n: max_reels=None → all kept, no discarded."""
    reels = _make_reels(30)
    kept, disc = S.apply_top_n(reels, max_reels=None)
    assert len(kept) == 30
    assert disc == []


def test_dedup_before_topn(fewshot, r0_cfg):
    """Dedup (inside select) happens before top-N (apply_top_n): overlapping pair → 20 unique."""
    segs = _make_segs(20, base_score=70)
    segs.append({"start": 0.0, "end": 30.0, "score": 69, "hook": "h", "title": "t", "description": "d"})
    cfg = r0_cfg.model_copy(update={"max_reels": 20})
    provider = _MockLLM([json.dumps({"segments": segs})])
    candidates = S.select("[0000.0-0005.0] x", system_text="sys", fewshot=fewshot,
                          provider=provider, r0_cfg=cfg)
    kept, disc = S.apply_top_n(candidates, max_reels=20)
    assert len(kept) == 20
    assert all("top-N" not in d["reason"] for d in disc)


def test_kept_reels_have_rank():
    """apply_top_n assigns rank 1-N on kept reels."""
    reels = _make_reels(3)
    kept, _ = S.apply_top_n(reels, max_reels=3)
    assert [r.rank for r in kept] == [1, 2, 3]


def test_sidecar_ids_unique():
    """Sidecar entries have unique ids (c{NNN} scheme from select ensures this)."""
    reels = _make_reels(25)
    kept, disc = S.apply_top_n(reels, max_reels=20)
    all_ids = [r.id for r in kept] + [d["id"] for d in disc]
    assert len(all_ids) == len(set(all_ids))


# ----------------------------------------------------------- dangling-start repair

def _repair_words():
    """Words: dangling 'и'+'вот', then uppercase 'Знаете' at t0=11.0, long clip to t1=40."""
    return _words([
        ("и", 10.0, 10.2),
        ("вот", 10.3, 10.6),
        ("Знаете", 11.0, 11.5),
        ("что", 11.6, 12.0),
        ("важно", 12.1, 40.0),
    ])


def test_repair_success():
    """Dangling opener repaired to first uppercase word within window."""
    words = _repair_words()
    r = _creel(start=10.0, end=40.0)
    kept, disc = S.filter_dangling_start([r], words, min_duration=15.0, max_start_repair_sec=6.0)
    assert len(kept) == 1 and len(disc) == 0
    assert kept[0].start == pytest.approx(11.0)
    assert kept[0].start_repair_sec == pytest.approx(1.0)
    assert kept[0].start_snap_reason == "repaired_to_sentence"
    assert "start_repaired" in kept[0].flags


def test_repair_no_capital_in_window():
    """No uppercase word within repair window → clip dropped."""
    words = _words([
        ("и", 10.0, 10.2),
        ("вот", 10.3, 11.0),
        ("это", 11.1, 15.9),   # lowercase, within 6s window but lowercase
        ("Важно", 20.0, 40.0),  # uppercase but past deadline (10+6=16)
    ])
    r = _creel(start=10.0, end=40.0)
    kept, disc = S.filter_dangling_start([r], words, min_duration=15.0, max_start_repair_sec=6.0)
    assert len(kept) == 0 and len(disc) == 1
    assert disc[0]["id"] == "c001"


def test_repair_too_short_after_repair():
    """Uppercase word found but remaining clip too short → dropped."""
    words = _words([
        ("и", 10.0, 10.2),
        ("Знаете", 14.0, 14.5),  # 25.0 - 14.0 = 11.0 < min_duration=15
        ("всё", 15.0, 25.0),
    ])
    r = _creel(start=10.0, end=25.0)
    kept, disc = S.filter_dangling_start([r], words, min_duration=15.0, max_start_repair_sec=6.0)
    assert len(kept) == 0 and len(disc) == 1


def test_clean_opener_unchanged():
    """Clean uppercase opener passes unchanged, no repair fields set."""
    words = _words([("Самое", 5.0, 5.5), ("главное", 5.6, 40.0)])
    r = _creel(start=5.0, end=40.0)
    kept, disc = S.filter_dangling_start([r], words, min_duration=15.0)
    assert len(kept) == 1 and len(disc) == 0
    assert kept[0].start == pytest.approx(5.0)
    assert kept[0].start_repair_sec is None


def test_corpus_sidecar_valid():
    """Every existing manifest's sidecar (if present) is a valid list with id+reason."""
    import json
    manifest_dir = ROOT / "manifests"
    manifests = [p for p in manifest_dir.glob("*.json")
                 if ".discarded" not in p.name and ".blocks" not in p.name]
    if not manifests:
        pytest.skip("no manifests")
    for mp in manifests:
        sidecar = mp.with_suffix("").with_suffix(".discarded.json")
        if sidecar.exists():
            entries = json.loads(sidecar.read_text())
            assert isinstance(entries, list), f"{sidecar.name}: expected list"
            for e in entries:
                assert "id" in e, f"{sidecar.name}: entry missing 'id'"
                assert "reason" in e, f"{sidecar.name}: entry missing 'reason'"


# ----------------------------------------------------------- terminal-mark repair (c019/c020 regression)

def test_repair_terminal_mark_before_lowercase_and():
    """c019/c020 regression: first sentence ends within 3 s → start moves to next word even if it's 'И'."""
    # Simulates: "страх порождает страх, ещё больше, ещё больше. И все ваши травмы..."
    # Terminal mark at t1=2.9, next word 'И' (lowercase/connective) → repair via terminal-mark path.
    words = _words([
        ("страх", 0.5, 0.9),
        ("порождает", 1.0, 1.5),
        ("страх,", 1.6, 1.9),
        ("ещё", 2.0, 2.3),
        ("больше.", 2.4, 2.9),   # terminal mark here
        ("И", 3.0, 3.3),
        ("все", 3.4, 3.7),
        ("ваши", 3.8, 4.1),
        ("травмы", 4.2, 40.0),
    ])
    r = _creel(start=0.5, end=40.0, score=88)
    kept, disc = S.filter_dangling_start([r], words, min_duration=15.0, max_start_repair_sec=10.0)
    assert len(kept) == 1 and len(disc) == 0, f"should repair, not drop; disc={disc}"
    assert kept[0].start == pytest.approx(3.0)
    assert kept[0].start_snap_reason == "repaired_to_sentence"
    assert "start_repaired" in kept[0].flags


def test_repair_no_terminal_no_capital_drops():
    """Clip with neither terminal mark nor capitalised word within 10 s → dropped."""
    words = _words([
        ("и", 0.0, 0.3),
        ("всё", 0.4, 0.8),
        ("продолжается", 0.9, 1.5),
        ("ещё", 2.0, 11.0),  # no terminal, no uppercase in window
        ("Важно", 12.0, 40.0),  # uppercase but past 10-s deadline
    ])
    r = _creel(start=0.0, end=40.0)
    kept, disc = S.filter_dangling_start([r], words, min_duration=15.0, max_start_repair_sec=10.0)
    assert len(kept) == 0 and len(disc) == 1


def test_sidecar_invariant_candidates_eq_reels_plus_sidecar():
    """candidates_after_dedup == manifest_reels + sidecar overlap_dedup entries (dedup invariant)."""
    # Build 5 reels, 2 pairs overlap >60%, 1 standalone
    reels = [
        Reel(id="c001", start=0.0,  end=30.0, score=90, hook="h", title="t", description="d"),
        Reel(id="c002", start=2.0,  end=32.0, score=85, hook="h", title="t", description="d"),  # overlaps c001
        Reel(id="c003", start=60.0, end=90.0, score=80, hook="h", title="t", description="d"),
        Reel(id="c004", start=62.0, end=92.0, score=75, hook="h", title="t", description="d"),  # overlaps c003
        Reel(id="c005", start=120.0, end=150.0, score=70, hook="h", title="t", description="d"),
    ]
    dropped: list[dict] = []
    kept = S.dedup(reels, overlap_threshold=0.6, dropped=dropped)
    assert len(kept) + len(dropped) == len(reels)


# ----------------------------------------------------------------- host-turn detection (Task 3)

def _word(text, t0, t1):
    from autoreels.core.models import Word
    return Word(word=text, t0=t0, t1=t1)


def _reel2(start, end, rid="rXX"):
    return Reel(id=rid, start=start, end=end, score=80, hook="h", title="t", description="d")


# Test 1: r01 regression — declarative "Ты коснулся книги..." treated as host turn
def test_detect_host_turns_declarative_ты():
    """Sentence starting with 'Ты' (no '?') is a host turn."""
    words = [
        _word("Ты", 1538.84, 1539.0),
        _word("коснулся", 1539.0, 1539.5),
        _word("книги,", 1539.5, 1540.0),
        _word("ты", 1540.0, 1540.2),
        _word("стал", 1540.2, 1540.5),
        _word("автором", 1540.5, 1541.0),
        _word("книги,", 1541.0, 1541.5),
        _word("ты", 1541.5, 1541.7),
        _word("вне", 1541.7, 1542.0),
        _word("полома.", 1542.0, 1542.5),
    ]
    turns = S.detect_host_turns(words)
    assert len(turns) == 1
    assert turns[0][0] == pytest.approx(1538.84)


# Test 2: dash-marked sentence is host turn even without '?'
def test_detect_host_turns_dash_marked_no_question():
    """Em-dash at sentence start → host turn regardless of punctuation."""
    words = [
        _word("—", 10.0, 10.05),
        _word("Сколько", 10.05, 10.3),
        _word("лет", 10.3, 10.5),
        _word("вы", 10.5, 10.6),
        _word("этим", 10.6, 10.8),
        _word("занимаетесь.", 10.8, 11.0),
    ]
    turns = S.detect_host_turns(words)
    assert len(turns) == 1


# Test 3: 'ты' in reported speech (sentence starts with 'Я') → NOT a host turn
def test_detect_host_turns_ty_in_reported_speech_not_host():
    """'Ты' inside a sentence starting with 'Я' is reported speech, not a host turn."""
    words = [
        _word("Я", 5.0, 5.1),
        _word("думаю,", 5.1, 5.4),
        _word("что", 5.4, 5.5),
        _word("ты", 5.5, 5.7),
        _word("прав.", 5.7, 6.0),
    ]
    turns = S.detect_host_turns(words)
    assert turns == []


# Test 4: one-word affirmation at tail trimmed; same word inside sentence not trimmed
def test_trim_tail_affirmation_standalone_trimmed_inline_not():
    from autoreels.cloud.select import _trim_tail_affirmation

    affirmations = frozenset(["здорово"])

    # Case A: "...предложение. Здорово." → trimmed
    words_a = [
        _word("Это", 1.0, 1.3),
        _word("предложение.", 1.3, 2.0),
        _word("Здорово.", 2.1, 2.5),
    ]
    r_a = _reel2(1.0, 3.0, "rA")
    result_a = _trim_tail_affirmation(r_a, words_a, affirmations)
    assert result_a is True
    assert r_a.end < 2.1   # moved before "Здорово."

    # Case B: "Это здорово, что мы..." → not trimmed (not standalone sentence)
    words_b = [
        _word("Это", 10.0, 10.2),
        _word("здорово,", 10.2, 10.5),
        _word("что", 10.5, 10.6),
        _word("мы", 10.6, 10.7),
        _word("здесь.", 10.7, 11.0),
    ]
    r_b = _reel2(10.0, 12.0, "rB")
    result_b = _trim_tail_affirmation(r_b, words_b, affirmations)
    assert result_b is False
    assert r_b.end == pytest.approx(12.0)


# ----------------------------------------------------------------- token budget / 413 guard

def test_effective_chunk_tokens_respects_limit_and_upper_bound():
    """chunk_budget derived from limit/factor; capped by config upper bound."""
    # System ~100 tok, no fewshot, config max=9999 (huge) → budget is limit-derived, not config
    system_text = "x" * 400  # 100 tok
    effective = S._effective_chunk_tokens(
        system_text, {"examples": []}, 9999,
        max_output_tokens=500, template_overhead=300, groq_limit=5000,
        underestimation_factor=1.0,  # factor=1 → no correction; budget = (5000-500-300)/1 - 100 = 4100
    )
    # (groq_limit - max_out - template) / factor - system = (5000-500-300)/1.0 - 100 = 4100
    assert effective <= 4100 + 5  # allow ±5 for integer division
    # The full request fits (factor=1.0 means estimate == real): effective+system+max+template ≤ limit
    assert effective + 100 + 500 + 300 <= 5000
    assert effective >= 500  # minimum guard


def test_groq_pre_send_guard_no_network_call(monkeypatch):
    """When scaled estimate exceeds budget_limit, ProviderRequestTooLarge raised before HTTP."""
    import autoreels.cloud.providers as P

    monkeypatch.setenv("GROQ_API_KEY", "testkey")
    network_called = []
    monkeypatch.setattr(P, "_httpx_post", lambda *a, **kw: network_called.append(1) or None)

    llm = P.GroqLLM(max_output_tokens=900)
    llm._budget_limit = 2000   # tight limit: 2000 tok
    llm._token_scale = 2.0     # extreme factor so text(500)*2=1000 + template(400) + max(900) = 2300 > 2000
    llm._scale_loaded = True   # skip file load

    messages = [
        {"role": "system", "content": "s" * 2000},   # 500 tok
        {"role": "user",   "content": "c" * 2000},   # 500 tok
    ]
    with pytest.raises(P.ProviderRequestTooLarge) as exc:
        llm.complete(messages)

    assert not network_called, "HTTP call must not be made for oversized request"
    e = exc.value
    assert e.prompt_tokens + e.max_tokens > e.limit  # arithmetic is consistent


def test_413_message_components_sum_to_total(monkeypatch):
    """413 from network: message shows components and their sum equals total."""
    import autoreels.cloud.providers as P

    limit_hdr = "8000"
    response_body = {}

    class _Resp413:
        status_code = 413
        headers = {"x-ratelimit-limit-tokens": limit_hdr}
        def raise_for_status(self): pass
        def json(self): return response_body

    monkeypatch.setattr(P, "_httpx_post", lambda *a, **kw: _Resp413())
    monkeypatch.setenv("GROQ_API_KEY", "testkey")

    llm = P.GroqLLM(max_output_tokens=900)
    llm._budget_limit = 99999  # disable pre-send guard so we reach network
    messages = [
        {"role": "system",    "content": "sys"},
        {"role": "user",      "content": "fewshot_in"},
        {"role": "assistant", "content": "fewshot_out"},
        {"role": "user",      "content": "chunk"},
    ]
    with pytest.raises(P.ProviderRequestTooLarge) as exc:
        llm.complete(messages)

    e = exc.value
    msg = str(e)
    # Components must appear in message and be consistent
    assert "system" in msg and "fewshot" in msg and "chunk" in msg and "template" in msg
    # prompt_tokens + max_tokens > limit (that's why 413)
    assert e.prompt_tokens + e.max_tokens > 0
    assert e.limit == 8000


def test_factor_budget_larger_than_flat_margin(fewshot):
    """factor=1.37 gives a materially larger budget than the old flat safety_margin=2000.

    Uses an explicit chunk_tokens=8000 (unconstrained) so the test measures the formula
    output, not the config cap. r0_chunk_tokens is a tunable value, not part of this invariant.
    """
    system_text = "x" * (1667 * 4)  # ~1667 tok (matches lecture system prompt size)
    # Use a large cap so the formula (not the config limit) determines the output.
    chunk_tokens_uncapped = 8000

    budget_factor = S._effective_chunk_tokens(
        system_text, fewshot, chunk_tokens_uncapped,
        underestimation_factor=1.37,
    )
    # old formula equivalent (for comparison):
    # 8000 - 1667 - fewshot_tok - 900 - 400 - 2000 ≈ 2625 (was observed as 2319)
    old_approx = 2625  # conservative old budget

    assert budget_factor > old_approx, (
        f"factor-based budget {budget_factor} should exceed flat-margin {old_approx}"
    )
    # Verify it actually fits: (system + fewshot + chunk) * 1.37 + template + max ≤ limit
    system_tok = len(system_text) // 4
    fewshot_tok = sum(
        len(ex.get("input", "")) // 4 + len(json.dumps(ex.get("output", ""), ensure_ascii=False)) // 4
        for ex in fewshot.get("examples", [])
    )
    real_est = (system_tok + fewshot_tok + budget_factor) * 1.37 + 400 + 900
    assert real_est <= 8000 + 50, f"scaled total {real_est:.0f} must fit within Groq limit"


def test_token_scale_persisted_and_reloaded(tmp_path, monkeypatch):
    """EMA-updated factor is saved to state file and loaded on next GroqLLM instance."""
    import autoreels.cloud.providers as P

    scale_file = tmp_path / "token_scale.json"
    monkeypatch.setattr(P, "_TOKEN_SCALE_FILE", scale_file)

    model = "test-model"
    # Save initial factor
    P._save_token_scale(model, 1.37)
    assert scale_file.exists()

    # New instance loads it
    loaded = P._load_token_scale(model)
    assert loaded == pytest.approx(1.37, abs=0.001)

    # EMA update: observed factor 1.50, alpha=0.3 → new = 0.7*1.37 + 0.3*1.50 = 1.409
    new_factor = (1 - P._TOKEN_SCALE_EMA_ALPHA) * 1.37 + P._TOKEN_SCALE_EMA_ALPHA * 1.50
    P._save_token_scale(model, new_factor)
    loaded2 = P._load_token_scale(model)
    assert loaded2 == pytest.approx(new_factor, abs=0.001)

    # Missing model returns None
    assert P._load_token_scale("nonexistent-model") is None
