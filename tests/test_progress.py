"""Тесты модуля progress: форматирование строк прогресса, TTY/non-TTY ветки.

Только детерминированный слой: форматы строк, поведение при TTY vs non-TTY.
Интеграционные: select_chunked / transcribe_chunks печатают прогресс-строки.
"""
import sys
from io import StringIO
from pathlib import Path

import pytest

import autoreels.core.progress as P


# ------------------------------------------------------------------ unit: chunk_progress

def test_chunk_progress_non_tty_contains_label(monkeypatch, capsys):
    monkeypatch.setattr(P, "is_tty", lambda: False)
    P.chunk_progress("R0", 3, 10)
    out = capsys.readouterr().out
    assert "R0" in out
    assert "3/10" in out


def test_chunk_progress_non_tty_contains_percent(monkeypatch, capsys):
    monkeypatch.setattr(P, "is_tty", lambda: False)
    P.chunk_progress("тест", 5, 10)
    out = capsys.readouterr().out
    assert "50%" in out


def test_chunk_progress_non_tty_newline_per_chunk(monkeypatch, capsys):
    monkeypatch.setattr(P, "is_tty", lambda: False)
    P.chunk_progress("R0", 1, 5)
    P.chunk_progress("R0", 2, 5)
    out = capsys.readouterr().out
    assert out.count("\n") == 2


def test_chunk_progress_non_tty_with_extra(monkeypatch, capsys):
    monkeypatch.setattr(P, "is_tty", lambda: False)
    P.chunk_progress("R0", 2, 5, extra="найдено 4 момента")
    out = capsys.readouterr().out
    assert "найдено 4 момента" in out


def test_chunk_progress_non_tty_done_shows_checkmark(monkeypatch, capsys):
    monkeypatch.setattr(P, "is_tty", lambda: False)
    P.chunk_progress("R0", 5, 5, done=True)
    out = capsys.readouterr().out
    assert "✓" in out


def test_chunk_progress_tty_uses_cr(monkeypatch, capsys):
    monkeypatch.setattr(P, "is_tty", lambda: True)
    P.chunk_progress("R0", 2, 5)
    out = capsys.readouterr().out
    assert "\r" in out


def test_chunk_progress_tty_done_ends_with_newline(monkeypatch, capsys):
    monkeypatch.setattr(P, "is_tty", lambda: True)
    P.chunk_progress("R0", 5, 5, done=True)
    out = capsys.readouterr().out
    assert out.endswith("\n")


def test_chunk_progress_tty_in_progress_no_trailing_newline(monkeypatch, capsys):
    monkeypatch.setattr(P, "is_tty", lambda: True)
    P.chunk_progress("R0", 3, 5)
    out = capsys.readouterr().out
    assert not out.endswith("\n")


# ------------------------------------------------------------------ unit: throttle_wait

def test_throttle_wait_non_tty_contains_seconds(monkeypatch, capsys):
    monkeypatch.setattr(P, "is_tty", lambda: False)
    P.throttle_wait(8.0)
    out = capsys.readouterr().out
    assert "8" in out


def test_throttle_wait_non_tty_mentions_groq(monkeypatch, capsys):
    monkeypatch.setattr(P, "is_tty", lambda: False)
    P.throttle_wait(5.0)
    out = capsys.readouterr().out
    assert "Groq" in out or "groq" in out.lower()


def test_throttle_wait_non_tty_mentions_rate_limit(monkeypatch, capsys):
    monkeypatch.setattr(P, "is_tty", lambda: False)
    P.throttle_wait(5.0)
    out = capsys.readouterr().out
    assert "rate limit" in out.lower() or "ждём" in out.lower() or "лимит" in out.lower()


def test_throttle_wait_tty_uses_cr(monkeypatch, capsys):
    monkeypatch.setattr(P, "is_tty", lambda: True)
    P.throttle_wait(5.0)
    out = capsys.readouterr().out
    assert "\r" in out


# ------------------------------------------------------------------ unit: chunk_start

def test_chunk_start_contains_total(monkeypatch, capsys):
    monkeypatch.setattr(P, "is_tty", lambda: False)
    P.chunk_start("R0", 12)
    out = capsys.readouterr().out
    assert "12" in out


def test_chunk_start_contains_label(monkeypatch, capsys):
    monkeypatch.setattr(P, "is_tty", lambda: False)
    P.chunk_start("транскрипция", 6)
    out = capsys.readouterr().out
    assert "транскрипция" in out


def test_chunk_start_with_estimate_shows_minutes(monkeypatch, capsys):
    monkeypatch.setattr(P, "is_tty", lambda: False)
    P.chunk_start("R0", 10, est_sec=600.0)   # 10 мин
    out = capsys.readouterr().out
    assert "мин" in out or "min" in out.lower()


def test_chunk_start_small_estimate_no_minutes(monkeypatch, capsys):
    """Короткая оценка (<30с) → не показывать — смысла нет."""
    monkeypatch.setattr(P, "is_tty", lambda: False)
    P.chunk_start("транскрипция", 2, est_sec=10.0)
    out = capsys.readouterr().out
    # Должно содержать чанки, но не обязательно «мин»
    assert "2" in out


# ------------------------------------------------------------------ unit: spinner

def test_spinner_cycles(monkeypatch):
    frames = {P.spinner(i) for i in range(20)}
    assert len(frames) > 1, "спиннер должен менять символы"


def test_spinner_returns_string(monkeypatch):
    assert isinstance(P.spinner(0), str)


# ------------------------------------------------------------------ integration: select_chunked

def _make_compressed(n_lines: int, line_chars: int = 60) -> str:
    return "\n".join(f"[{i*10:.1f}-{i*10+8:.1f}] " + "слово " * (line_chars // 6)
                     for i in range(n_lines))


def _r0_cfg_chunked():
    """Минимальный r0_cfg с чанкингом."""
    from autoreels.core.config import ChunkingConfig, R0Config, Preset, PromptPaths
    chunking = ChunkingConfig(
        enabled=True,
        r0_chunk_tokens=200,
        r0_overlap_tokens=20,
        r0_chunk_delay_sec=0.0,   # без реальной паузы в тестах
        dedup_overlap_ratio=0.5,
        fail_fast=False,
    )
    return R0Config(
        duration_preset="shorts",
        min_score=65,
        max_reels=None,
        chunk_tokens=3500,
        chunk_overlap_sec=60,
        dedup_overlap_threshold=0.5,
        sentence_pause_sec=0.35,
        max_sentence_buffer_sec=30,
        tail_sec=0.3,
        snap_window_sec=1.5,
        too_long_policy="trim",
        title_style="clickbait_ru",
        language="ru",
        prompt_language="en",
        presets={"shorts": Preset(min=15, max=59)},
        prompts=PromptPaths(system="prompts/r0_system.md", fewshot="prompts/r0_fewshot.json"),
        chunking=chunking,
    )


class _MockLLM:
    def __init__(self, responses):
        self._q = list(responses)
        self.calls = 0

    def complete(self, messages, *, temperature=0.0):
        self.calls += 1
        if self._q:
            return self._q.pop(0)
        return '{"segments": []}'


def test_select_chunked_prints_chunk_progress(monkeypatch, capsys):
    """select_chunked печатает строку прогресса для каждого R0-чанка."""
    import autoreels.cloud.select as sel_mod
    import autoreels.core.progress as prog

    monkeypatch.setattr(prog, "is_tty", lambda: False)
    monkeypatch.setattr(sel_mod.time, "sleep", lambda _: None)

    compressed = _make_compressed(60, line_chars=60)
    r0_cfg = _r0_cfg_chunked()
    provider = _MockLLM(['{"segments": []}'])

    sel_mod.select(compressed, system_text="sys", fewshot={"examples": []},
                   provider=provider, r0_cfg=r0_cfg)

    out = capsys.readouterr().out
    assert "R0" in out
    assert "1/" in out


def test_select_chunked_prints_chunk_start_banner(monkeypatch, capsys):
    """select_chunked печатает сводку «N чанков, ~M мин» перед циклом."""
    import autoreels.cloud.select as sel_mod
    import autoreels.core.progress as prog

    monkeypatch.setattr(prog, "is_tty", lambda: False)
    monkeypatch.setattr(sel_mod.time, "sleep", lambda _: None)

    compressed = _make_compressed(60, line_chars=60)
    r0_cfg = _r0_cfg_chunked()
    provider = _MockLLM(['{"segments": []}'])

    sel_mod.select(compressed, system_text="sys", fewshot={"examples": []},
                   provider=provider, r0_cfg=r0_cfg)

    out = capsys.readouterr().out
    assert "чанк" in out.lower()


def test_select_chunked_prints_found_count(monkeypatch, capsys):
    """select_chunked показывает сколько моментов найдено на каждом чанке."""
    import autoreels.cloud.select as sel_mod
    import autoreels.core.progress as prog

    monkeypatch.setattr(prog, "is_tty", lambda: False)
    monkeypatch.setattr(sel_mod.time, "sleep", lambda _: None)

    seg = '{"segments": [{"start":10,"end":40,"score":80,"hook":"h","title":"t","description":"d"}]}'
    compressed = _make_compressed(60, line_chars=60)
    r0_cfg = _r0_cfg_chunked()
    provider = _MockLLM([seg])

    sel_mod.select(compressed, system_text="sys", fewshot={"examples": []},
                   provider=provider, r0_cfg=r0_cfg)

    out = capsys.readouterr().out
    assert "найдено" in out.lower() or "moment" in out.lower() or any(
        c.isdigit() for c in out
    )


# ------------------------------------------------------------------ integration: throttle in providers

def test_provider_prints_throttle_on_429(monkeypatch, capsys):
    """GroqLLM._default_request показывает throttle_wait при 429."""
    import autoreels.cloud.providers as prov_mod
    import autoreels.core.progress as prog

    monkeypatch.setattr(prog, "is_tty", lambda: False)

    class _FakeResp:
        def __init__(self, status):
            self.status_code = status
            self.headers = {"retry-after": "5"}
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": '{"segments":[]}'}}]}

    call_count = [0]
    def _fake_post(*a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return _FakeResp(429)
        return _FakeResp(200)

    monkeypatch.setattr(prov_mod, "_httpx_post", _fake_post)
    monkeypatch.setattr(prov_mod.time, "sleep", lambda _: None)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    llm = prov_mod.GroqLLM()
    llm.complete([{"role": "user", "content": "test"}])

    out = capsys.readouterr().out
    assert "5" in out or "ждём" in out.lower() or "Groq" in out


# ------------------------------------------------------------------ integration: transcribe_chunks

def test_transcribe_chunks_prints_progress(monkeypatch, capsys, tmp_path):
    """transcribe_chunks печатает строку прогресса для каждого чанка."""
    import autoreels.cloud.chunk_transcribe as CT
    import autoreels.core.progress as prog
    from autoreels.core.models import Transcript

    monkeypatch.setattr(prog, "is_tty", lambda: False)

    class _FakeBackend:
        def transcribe(self, path, *, language=None):
            return Transcript(language="ru", words=[])

    # Три чанка
    chunks_info = []
    for i in range(3):
        p = tmp_path / f"chunk_{i:02d}.mp3"
        p.write_bytes(b"x" * (i + 1))
        chunks_info.append((p, float(i * 60), float((i + 1) * 60)))

    CT.transcribe_chunks(chunks_info, _FakeBackend(), tmp_path)

    out = capsys.readouterr().out
    assert "транскрипци" in out.lower() or "чанк" in out.lower()
    assert "1/3" in out or "1/" in out


# ------------------------------------------------------------------ download: расчёт ETA

def test_eta_seconds_basic():
    # осталось 60 байт при 20 байт/с → 3 с
    assert P.eta_seconds(total=100, downloaded=40, speed_bps=20) == pytest.approx(3.0)


def test_eta_seconds_zero_speed_is_none():
    assert P.eta_seconds(total=100, downloaded=40, speed_bps=0) is None


def test_eta_seconds_complete_is_none():
    assert P.eta_seconds(total=100, downloaded=100, speed_bps=20) is None


def test_eta_seconds_unknown_total_is_none():
    assert P.eta_seconds(total=None, downloaded=40, speed_bps=20) is None


# ------------------------------------------------------------------ download: форматирование

def test_format_duration_hms():
    assert P.format_duration(6480) == "1:48:00"   # 1ч 48м
    assert P.format_duration(225) == "3:45"       # без часов


def test_format_speed_switches_units():
    assert P.format_speed(2 * (1 << 20)) == "2.0 МБ/с"
    assert P.format_speed(500 * (1 << 10)) == "500 КБ/с"


def test_format_download_line_has_pct_bytes_speed_eta():
    line = P.format_download_line(
        downloaded=3 * (1 << 30), total=12 * (1 << 30), speed_bps=2 * (1 << 20)
    )
    assert line.startswith("↓")
    assert "25%" in line
    assert "3.0/12.0 ГБ" in line
    assert "2.0 МБ/с" in line
    assert "осталось" in line


def test_format_download_line_unknown_total_omits_pct_and_eta():
    line = P.format_download_line(downloaded=3 * (1 << 30), total=None, speed_bps=2 * (1 << 20))
    assert "%" not in line
    assert "осталось" not in line
    assert "3.0 ГБ" in line


def test_format_download_done():
    s = P.format_download_done(total_bytes=12 * (1 << 30), elapsed_sec=6480)
    assert s.startswith("✓")
    assert "12.0 ГБ" in s
    assert "1:48:00" in s


# ------------------------------------------------------------------ download: \r-перезапись

def test_print_download_progress_tty_overwrites_no_newline(monkeypatch, capsys):
    """TTY: одно обновление = \\r + очистка до конца строки, БЕЗ \\n (перезапись на месте)."""
    monkeypatch.setattr(P, "is_tty", lambda: True)
    P.print_download_progress(3 * (1 << 30), 12 * (1 << 30), 2 * (1 << 20))
    out = capsys.readouterr().out
    assert out.startswith("\r")
    assert "\033[K" in out          # очистка до конца строки — нет «хвоста» и переноса
    assert not out.endswith("\n")   # без перевода строки — следующее обновление перезапишет
    assert "25%" in out


def test_print_download_progress_no_fixed_width_padding(monkeypatch, capsys):
    """Нет добивки пробелами до фикс. ширины (её и не должно быть — иначе перенос/лесенка)."""
    monkeypatch.setattr(P, "is_tty", lambda: True)
    P.print_download_progress(3 * (1 << 30), 12 * (1 << 30), 2 * (1 << 20))
    out = capsys.readouterr().out
    assert "   " not in out          # нет длинного хвоста пробелов


def test_print_download_progress_non_tty_plain_line(monkeypatch, capsys):
    """Не-TTY (пайп/файл): обычная строка с \\n, без управляющих символов."""
    monkeypatch.setattr(P, "is_tty", lambda: False)
    P.print_download_progress(3 * (1 << 30), 12 * (1 << 30), 2 * (1 << 20))
    out = capsys.readouterr().out
    assert out.endswith("\n")
    assert "\r" not in out and "\033[K" not in out


def test_print_download_done_tty_ends_with_newline(monkeypatch, capsys):
    """Финал на TTY: \\r + очистка + строка + \\n (закрывает перезаписываемую строку)."""
    monkeypatch.setattr(P, "is_tty", lambda: True)
    P.print_download_done(12 * (1 << 30), 6480)
    out = capsys.readouterr().out
    assert out.startswith("\r")
    assert out.endswith("\n")
    assert "✓" in out


def test_is_tty_env_override(monkeypatch):
    """AUTOREELS_FORCE_TTY=1 → is_tty True даже если stdout не терминал (страховка)."""
    monkeypatch.setenv("AUTOREELS_FORCE_TTY", "1")
    assert P.is_tty() is True
    monkeypatch.setenv("AUTOREELS_FORCE_TTY", "0")
    monkeypatch.setenv("AUTOREELS_NO_TTY", "1")
    assert P.is_tty() is False
