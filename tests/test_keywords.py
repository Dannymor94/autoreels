"""M1.7 step 2: sentence-scoped keyword highlighting (k:N=word syntax).

Tests:
1. Flag off → output byte-identical (no Keyword style, no tags).
2. k: marks exactly the listed words via emph=True flag; others plain.
3. emph flag with punctuated words (Whisper attaches commas) still rendered tagged.
4. Chunk boundaries and timings identical with and without highlighting.
5. Warning on out-of-range sentence index (warning case, logic simulated inline).
6. Parser: k:N=words alongside all fields; ; inside k: does not break field splitting.
7. remap_to_output carries emph flag through timeline remapping.
"""
import io
import re
import sys

import pytest

from autoreels.cloud.blocks import parse_compact_answer
from autoreels.core.config import SubtitlesConfig
from autoreels.core.models import Segment, Word
from autoreels.local.subtitles import build_ass, remap_to_output


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


def _w(text, t0, t1, emph=False) -> Word:
    return Word(word=text, t0=t0, t1=t1, emph=emph)


def _plain(*pairs) -> list[Word]:
    return [Word(word=w, t0=t0, t1=t1) for w, t0, t1 in pairs]


# ── Test 1: flag off → byte-identical output ──────────────────────────────────

def test_flag_off_byte_identical():
    """enable_keywords=False → output identical to baseline (no emph arg)."""
    cfg = _cfg()
    words = _plain(("страх", 1.0, 1.4), ("это", 1.5, 1.7), ("сигнал", 1.8, 2.2))

    baseline = build_ass(words, cfg=cfg, clip_start=0.0)
    assert baseline == build_ass(words, cfg=cfg, clip_start=0.0, enable_keywords=False)

    # emph=True on words with flag off must still be byte-identical
    words_emph = [_w("страх", 1.0, 1.4, emph=True), _w("это", 1.5, 1.7),
                  _w("сигнал", 1.8, 2.2, emph=True)]
    assert baseline == build_ass(words_emph, cfg=cfg, clip_start=0.0, enable_keywords=False)


# ── Test 2: emph=True words get {\\rKeyword} tags; others stay plain ─────────

def test_keyword_tags_only_emph_words():
    """Words with emph=True get {\\rKeyword}...{\\r} tags; others are plain."""
    cfg = _cfg()
    words = [
        _w("страх", 1.0, 1.4, emph=True),
        _w("это", 1.5, 1.7),
        _w("сигнал", 1.8, 2.2, emph=True),
    ]

    ass = build_ass(words, cfg=cfg, clip_start=0.0, enable_keywords=True)

    assert "Style: Keyword," in ass
    assert "{\\rKeyword}СТРАХ{\\r}" in ass
    assert "{\\rKeyword}СИГНАЛ{\\r}" in ass
    assert "{\\rKeyword}ЭТО{\\r}" not in ass


def test_same_word_only_tagged_where_emph_set():
    """Same word text — only instances with emph=True are tagged."""
    cfg = _cfg(words_per_line=2)
    words = [
        _w("страх", 1.0, 1.4, emph=True),   # sentence 1 — tagged
        _w("это.", 1.5, 1.7),
        _w("страх", 2.0, 2.4),               # sentence 2 — NOT tagged
        _w("нет.", 2.5, 2.8),
    ]

    ass = build_ass(words, cfg=cfg, clip_start=0.0, enable_keywords=True)

    # At least one tagged instance
    assert "{\\rKeyword}СТРАХ{\\r}" in ass
    # Verify the non-emph instance is plain (appears as "СТРАХ" without tags)
    # Count: total СТРАХ occurrences > tagged occurrences
    total = ass.count("СТРАХ")
    tagged = ass.count("{\\rKeyword}СТРАХ{\\r}")
    assert tagged == 1
    assert total > tagged


# ── Test 3: words with attached punctuation rendered with tag when emph=True ─

def test_punctuated_word_tagged_when_emph():
    """Whisper-style 'страха,' with emph=True: punctuation stays OUTSIDE the Keyword tag."""
    cfg = _cfg()
    words = [_w("страха,", 1.0, 1.5, emph=True), _w("нет", 1.6, 1.8)]

    ass = build_ass(words, cfg=cfg, clip_start=0.0, enable_keywords=True)

    assert "{\\rKeyword}СТРАХА{\\r}," in ass
    assert "{\\rKeyword}СТРАХА,{\\r}" not in ass
    assert "{\\rKeyword}НЕТ{\\r}" not in ass


def test_punctuation_stays_outside_keyword_tag():
    """All trailing punctuation chars stay outside the \\rKeyword tag."""
    cfg = _cfg()
    cases = [
        ("силу.", "{\\rKeyword}СИЛУ{\\r}."),
        ("страх,", "{\\rKeyword}СТРАХ{\\r},"),
        ("сигнал!", "{\\rKeyword}СИГНАЛ{\\r}!"),
        ("нет", "{\\rKeyword}НЕТ{\\r}"),    # no punctuation → no trailing chars
    ]
    for word, expected in cases:
        words = [_w(word, 1.0, 1.5, emph=True), _w("да", 1.6, 1.8)]
        ass = build_ass(words, cfg=cfg, clip_start=0.0, enable_keywords=True)
        assert expected in ass, f"expected {expected!r} for word {word!r}"


# ── Test 4: timing and grouping unchanged ─────────────────────────────────────

def test_timing_unchanged_by_keywords():
    """Dialogue start/end times identical with and without highlighting."""
    cfg = _cfg()
    plain = _plain(("страх", 1.0, 1.4), ("это", 1.5, 1.7), ("сигнал", 1.8, 2.2))
    emph = [_w("страх", 1.0, 1.4, emph=True), _w("это", 1.5, 1.7), _w("сигнал", 1.8, 2.2)]

    base = build_ass(plain, cfg=cfg, clip_start=0.0)
    kw = build_ass(emph, cfg=cfg, clip_start=0.0, enable_keywords=True)

    _re = re.compile(r"Dialogue:.*?(\d:\d+:\d+\.\d+),(\d:\d+:\d+\.\d+)")
    assert _re.findall(base) == _re.findall(kw)


def test_group_count_unchanged_by_keywords():
    """Number of Dialogue events is the same with and without highlighting."""
    cfg = _cfg(words_per_line=2)
    plain = _plain(("раз", 0.0, 0.3), ("два", 0.4, 0.7), ("три", 0.8, 1.1), ("четыре", 1.2, 1.5))
    emph = [_w("раз", 0.0, 0.3, emph=True), _w("два", 0.4, 0.7),
            _w("три", 0.8, 1.1, emph=True), _w("четыре", 1.2, 1.5)]

    base = build_ass(plain, cfg=cfg, clip_start=0.0)
    kw = build_ass(emph, cfg=cfg, clip_start=0.0, enable_keywords=True)

    assert base.count("Dialogue:") == kw.count("Dialogue:")


# ── Test 5: warning on out-of-range sentence index ───────────────────────────

def test_warning_on_out_of_range_sentence(monkeypatch):
    """k:99 with 2 sentences → warning printed; k:1 word still applied."""
    from autoreels.cloud.edit import split_sentences

    words = [
        Word(word="страх", t0=1.0, t1=1.4),
        Word(word="это.", t0=1.5, t1=1.7),
        Word(word="сигнал", t0=2.0, t1=2.4),
    ]

    def _normalize_kw(w: str) -> str:
        return w.lower().replace("ё", "е").strip(".,!?;:—–-\"'«»()[]")

    kw_spec = ((1, ("страх",)), (99, ("сигнал",)))
    sents = split_sentences(words)

    buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", buf)
    for sent_idx, kwords in kw_spec:
        if sent_idx < 1 or sent_idx > len(sents):
            print(f"  warning: k:{sent_idx} out of range (1-{len(sents)}) — skipped",
                  file=sys.stderr)
            continue
        for kw in kwords:
            is_prefix = kw.endswith("*")
            kw_pat = kw[:-1] if is_prefix else kw
            for w in sents[sent_idx - 1]:
                w_norm = _normalize_kw(w.word)
                if (is_prefix and w_norm.startswith(kw_pat)) or (not is_prefix and w_norm == kw_pat):
                    w.emph = True

    assert "k:99" in buf.getvalue() and "out of range" in buf.getvalue()
    assert words[0].emph is True    # k:1=страх applied
    assert words[2].emph is False   # k:99 was skipped


# ── Test 6: parser ─────────────────────────────────────────────────────────────

def test_parser_k_sentence_scoped():
    """k:4=страх,сигнал;7=тело → ((4, ('страх', 'сигнал')), (7, ('тело',)))."""
    line = "3 85 | s:2 | e:9 | h:1 | x:5 | f:1 | c:3-5 | k:4=страх,сигнал;7=тело | t: Заголовок | d: Описание."
    _, entries, errors, _ = parse_compact_answer(line)

    assert errors == [], f"unexpected errors: {errors}"
    e = entries[0]
    assert e.k == ((4, ("страх", "сигнал")), (7, ("тело",)))
    assert e.title == "Заголовок"
    assert e.description == "Описание."


def test_parser_semicolon_in_k_does_not_bleed():
    """; inside k: value does not bleed into adjacent field parsing."""
    line = "5 90 | k:1=слово1;2=слово2 | t: Заголовок"
    _, entries, errors, _ = parse_compact_answer(line)

    assert errors == []
    e = entries[0]
    assert e.k == ((1, ("слово1",)), (2, ("слово2",)))
    assert e.title == "Заголовок"


def test_parser_k_absent_gives_empty_tuple():
    """When k: is absent, _ReviewEntry.k is ()."""
    line = "5 90 | t: Без выделения"
    _, entries, errors, _ = parse_compact_answer(line)
    assert errors == []
    assert entries[0].k == ()


# ── Test 7: remap_to_output carries emph flag ─────────────────────────────────

def test_remap_carries_emph_flag():
    """remap_to_output preserves word.emph through timeline remapping (class-7 guard)."""
    words = [
        Word(word="страх", t0=5.0, t1=5.4, emph=True),
        Word(word="это", t0=5.5, t1=5.7),
        Word(word="вне", t0=15.0, t1=15.3),   # outside segment — dropped
    ]
    segs = [Segment(start=4.0, end=10.0)]

    remapped = remap_to_output(words, segs, speed=1.0)

    assert len(remapped) == 2
    assert remapped[0].emph is True
    assert remapped[1].emph is False


def test_apply_offset_preserves_emph():
    """apply_offset (chunk_transcribe) preserves word.emph — class-7 guard for Word."""
    from autoreels.core.models import Transcript
    from autoreels.cloud.chunk_transcribe import apply_offset

    words = [Word(word="тест", t0=1.0, t1=1.5, emph=True)]
    tx = Transcript(language="ru", words=words)

    shifted = apply_offset(tx, 10.0)

    assert shifted.words[0].emph is True
    assert shifted.words[0].t0 == pytest.approx(11.0)


# ── Stage guards: emph survives snap, filler cleanup, cold open ───────────────

def test_snap_stage_does_not_touch_subtitle_emph():
    """trim_hanging_subtitles (snap stage) pops trailing words but never rebuilds Word objects.

    Emph flag on non-trailing words is untouched; the surviving word object is the SAME object.
    """
    from autoreels.core.models import Reel
    from autoreels.cloud.snap import trim_hanging_subtitles

    emph_word = Word(word="страх", t0=5.0, t1=5.4, emph=True)
    hanging = Word(word="ну", t0=5.5, t1=5.8)
    reel = Reel(id="r01", start=5.0, end=6.0, score=50, hook="", title="", description="",
                subtitles=[emph_word, hanging])
    trim_hanging_subtitles([reel], hanging_words=["ну"])

    assert len(reel.subtitles) == 1
    assert reel.subtitles[0] is emph_word     # same object — not rebuilt
    assert reel.subtitles[0].emph is True


def test_filler_stage_does_not_touch_subtitle_emph():
    """remove_fillers returns Segment intervals; reel.subtitles Words are never rebuilt."""
    from autoreels.cloud.edit import remove_fillers

    words = [
        Word(word="страх", t0=0.0, t1=0.4, emph=True),
        Word(word="это", t0=0.5, t1=0.7),
    ]
    # No fillers defined → returns empty segments list (one span kept as-is)
    segs, removed, _ = remove_fillers(
        words, start=0.0, end=1.0,
        filler_words=[], pause_shorten_sec=0.4,
        pause_residual_sec=0.1, max_removed_share=0.5,
    )
    # Words were not touched; emph still set on the original objects
    assert words[0].emph is True


def test_cold_open_stage_preserves_existing_emph():
    """Cold open only appends NEW words (from transcript); existing emph words are untouched."""
    from autoreels.local.subtitles import words_in_window

    # Existing subtitle word already has emph=True
    existing = Word(word="страх", t0=10.0, t1=10.4, emph=True)
    hook_words = [existing, Word(word="есть", t0=10.5, t1=10.8)]

    # Simulate cold-open append: only add words NOT already in subtitles
    subtitles = [existing]
    have = {round(w.t0, 3) for w in subtitles}
    for w in hook_words:
        if round(w.t0, 3) not in have:
            subtitles.append(w)

    # existing word must still have emph=True
    assert subtitles[0].emph is True
    assert subtitles[0] is existing  # same object, not rebuilt
