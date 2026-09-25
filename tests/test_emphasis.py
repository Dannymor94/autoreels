"""M1.7 step 2: subtitle emphasis (k: field).

Tests:
1. No emphasis → output byte-identical to pre-M1.7 (same ASS string).
2. Emphasised words render in Emph style; non-emphasised in Default.
3. Timing, line breaks and grouping are unchanged by emphasis.
4. Parser: k: alongside all existing fields, no shadowing.
"""
from autoreels.cloud.blocks import parse_compact_answer
from autoreels.core.config import SubtitlesConfig
from autoreels.core.models import Word
from autoreels.local.subtitles import build_ass


def _cfg(**kw) -> SubtitlesConfig:
    base = dict(
        font="Arial", font_size=72, text_color="FFFFFF", bold=True, uppercase=True,
        outline_color="000000", outline_width=3, shadow=2,
        fill_enabled=False, fill_color="000000", fill_opacity=60,
        position_v=300, words_per_line=3, subtitle_break_pause_sec=0.4,
        fade_in_ms=0, fade_out_ms=0, alignment="center",
        char_width_ratio=0.55, max_text_width_px=1000,
    )
    base.update(kw)
    return SubtitlesConfig(**base)


def _words(*pairs) -> list[Word]:
    return [Word(word=w, t0=t0, t1=t1) for w, t0, t1 in pairs]


# ── Test 1: no emphasis → byte-identical output ───────────────────────────────

def test_no_emphasis_byte_identical():
    """emph_words=frozenset() → build_ass output identical to baseline (no emph arg)."""
    cfg = _cfg()
    words = _words(("страх", 1.0, 1.4), ("это", 1.5, 1.7), ("сигнал", 1.8, 2.2))

    baseline = build_ass(words, cfg=cfg, clip_start=0.0)
    with_empty = build_ass(words, cfg=cfg, clip_start=0.0, emph_words=frozenset())

    assert baseline == with_empty


# ── Test 2: emphasised words use Emph style; others stay Default ──────────────

def test_emph_words_use_emph_style():
    """Words in emph_words get {\\rEmph}...{\\r} tags; others are plain text."""
    cfg = _cfg()
    words = _words(("страх", 1.0, 1.4), ("это", 1.5, 1.7), ("сигнал", 1.8, 2.2))

    ass = build_ass(words, cfg=cfg, clip_start=0.0, emph_words=frozenset({"страх", "сигнал"}))

    # Emph style defined in header
    assert "Style: Emph," in ass

    # Each occurrence wrapped with style override
    assert "{\\rEmph}СТРАХ{\\r}" in ass
    assert "{\\rEmph}СИГНАЛ{\\r}" in ass

    # Non-emphasised word NOT wrapped
    assert "{\\rEmph}ЭТО{\\r}" not in ass


def test_non_emph_words_untagged():
    """Words not in emph_words appear without override tags."""
    cfg = _cfg()
    words = _words(("мозг", 0.5, 0.9), ("управляет", 1.0, 1.5), ("нами", 1.6, 2.0))

    ass = build_ass(words, cfg=cfg, clip_start=0.0, emph_words=frozenset({"мозг"}))

    # only мозг is tagged; управляет and нами are plain
    assert "{\\rEmph}МОЗГ{\\r}" in ass
    assert "\\rEmph}УПРАВЛЯЕТ" not in ass
    assert "\\rEmph}НАМИ" not in ass


# ── Test 3: timing and grouping unchanged ─────────────────────────────────────

def test_timing_unchanged_by_emphasis():
    """Dialogue start/end times are the same with and without emphasis."""
    import re
    cfg = _cfg()
    words = _words(("страх", 1.0, 1.4), ("это", 1.5, 1.7), ("сигнал", 1.8, 2.2))

    baseline = build_ass(words, cfg=cfg, clip_start=0.0)
    emph = build_ass(words, cfg=cfg, clip_start=0.0, emph_words=frozenset({"страх"}))

    _time_re = re.compile(r"Dialogue:.*?(\d:\d+:\d+\.\d+),(\d:\d+:\d+\.\d+)")
    base_times = _time_re.findall(baseline)
    emph_times = _time_re.findall(emph)

    assert base_times == emph_times, "Dialogue start/end times must be identical"


def test_group_count_unchanged_by_emphasis():
    """Number of Dialogue events is the same with and without emphasis."""
    cfg = _cfg(words_per_line=2)
    words = _words(
        ("раз", 0.0, 0.3), ("два", 0.4, 0.7),
        ("три", 0.8, 1.1), ("четыре", 1.2, 1.5),
    )

    baseline = build_ass(words, cfg=cfg, clip_start=0.0)
    emph = build_ass(words, cfg=cfg, clip_start=0.0, emph_words=frozenset({"раз", "три"}))

    assert baseline.count("Dialogue:") == emph.count("Dialogue:")


# ── Test 4: parser — k: alongside all existing fields, no shadowing ───────────

def test_parser_k_field_no_shadow():
    """k: is parsed correctly alongside s:, e:, h:, x:, c:, f:, t:, d:."""
    line = "3 85 | s:2 | e:9 | h:1 | x:5 | f:1 | c:3-5 | k: страх,сигнал | t: Заголовок | d: Описание."
    _, entries, errors, _ = parse_compact_answer(line)

    assert errors == [], f"unexpected errors: {errors}"
    assert len(entries) == 1
    e = entries[0]

    assert e.s == 2
    assert e.e == 9
    assert e.hook == 1
    assert e.x == (5,)
    assert e.c == (3, 4, 5)
    assert e.filler is True
    assert e.k == ("страх", "сигнал")
    assert e.title == "Заголовок"
    assert e.description == "Описание."


def test_emph_matches_through_punctuation():
    """Words with trailing punctuation in transcript still match k: (Whisper attaches commas)."""
    cfg = _cfg()
    # Whisper output: "себя," — with comma attached
    words = _words(("себя,", 1.0, 1.5), ("ты", 1.6, 1.8))

    ass = build_ass(words, cfg=cfg, clip_start=0.0, emph_words=frozenset({"себя"}))

    assert "{\\rEmph}СЕБЯ,{\\r}" in ass, "word with trailing comma must still be emphasised"
    assert "\\rEmph}ТЫ" not in ass


def test_parser_k_absent_gives_empty_tuple():
    """When k: is absent, _ReviewEntry.k is ()."""
    line = "5 90 | t: Без выделения"
    _, entries, errors, _ = parse_compact_answer(line)
    assert errors == []
    assert entries[0].k == ()
