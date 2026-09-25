"""Publish-package tests (task: give every clip its publication text).

1. d: text with punctuation and comma survives the round trip into description.
2. A line with both t: and d: parses; either alone parses; neither is required.
3. Hashtags are capped, deduplicated, and exclude stopwords.
4. Sidecars are written on render and rewritten when the reel changes.
5. index.md lists every reel in the manifest.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from autoreels.cloud.blocks import _parse_fields, parse_compact_answer
from autoreels.core.models import Crop, Manifest, Reel, SetupProfile, Word
from autoreels.local.hashtags import derive_hashtags
from autoreels.local.render import _write_index_md, _write_sidecar_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _word(w: str, t0: float = 0.0, t1: float = 0.5) -> Word:
    return Word(word=w, t0=t0, t1=t1)


def _reel(**kw) -> Reel:
    base = dict(
        id="r01", start=0.0, end=30.0, score=80,
        hook="hook", title="title", description="",
        subtitles=[],
    )
    base.update(kw)
    return Reel(**base)


def _manifest(reels) -> Manifest:
    setup = SetupProfile(
        setup_id="s", crop=Crop(x=0, y=0, w=960, h=1700),
        scale=[1080, 1920], frame=[1920, 1080],
    )
    return Manifest(
        source="v.mp4", source_sha256="a" * 64, duration_preset="shorts",
        setup=setup, run_key="rk", reels=reels,
    )


def _cfg(always=None, max_=5):
    return SimpleNamespace(hashtags_always=always or [], hashtags_max=max_)


# ---------------------------------------------------------------------------
# Test 1 — d: text with punctuation and comma survives the round trip
# ---------------------------------------------------------------------------

def test_description_roundtrip_punctuation():
    """d: text with commas, dashes, and terminal punctuation survives parse → description."""
    s, e, hook, title, filler, description, x_list, c_list, k_list, z_val, errors = _parse_fields(
        " d: Тело подаёт сигнал, а мы — принимаем его за страх."
    )
    assert errors == []
    assert description == "Тело подаёт сигнал, а мы — принимаем его за страх."
    assert title is None


def test_description_roundtrip_via_parse_compact_answer():
    """Full round trip: compact answer with d: → ReviewEntry.description."""
    content = "5 85 | t: Заголовок | d: Тело подаёт сигнал, а мы принимаем его за страх."
    _, entries, errors, _ = parse_compact_answer(content)
    assert errors == []
    assert len(entries) == 1
    assert entries[0].description == "Тело подаёт сигнал, а мы принимаем его за страх."


# ---------------------------------------------------------------------------
# Test 2 — both t: and d: parse; either alone; neither required
# ---------------------------------------------------------------------------

def test_both_t_and_d_parse():
    s, e, hook, title, filler, description, x_list, c_list, k_list, z_val, errors = _parse_fields(
        " t: Страх — это не страх, а сигнал | d: Второе предложение."
    )
    assert errors == []
    assert title == "Страх — это не страх, а сигнал"
    assert description == "Второе предложение."


def test_only_t_parses():
    s, e, hook, title, filler, description, x_list, c_list, k_list, z_val, errors = _parse_fields(" t: Только заголовок")
    assert errors == []
    assert title == "Только заголовок"
    assert description is None


def test_only_d_parses():
    s, e, hook, title, filler, description, x_list, c_list, k_list, z_val, errors = _parse_fields(" d: Только описание.")
    assert errors == []
    assert title is None
    assert description == "Только описание."


def test_neither_t_nor_d_is_fine():
    s, e, hook, title, filler, description, x_list, c_list, k_list, z_val, errors = _parse_fields(" s:2 e:5")
    assert errors == []
    assert title is None
    assert description is None
    assert s == 2 and e == 5


# ---------------------------------------------------------------------------
# Test 3 — hashtags capped, deduplicated, stopwords excluded
# ---------------------------------------------------------------------------

def test_hashtags_exclude_stopwords():
    words = [_word(w) for w in ["и", "в", "психология", "страха", "мы", "на", "психология"]]
    tags = derive_hashtags(words, hashtags_always=[], hashtags_max=5)
    tag_labels = [t.lstrip("#") for t in tags]
    assert all(t not in ("и", "в", "мы", "на") for t in tag_labels)
    assert any("психолог" in t for t in tag_labels)  # lemmatised form


def test_hashtags_capped():
    words = [_word(f"слово{i}") for i in range(20)]
    tags = derive_hashtags(words, hashtags_always=[], hashtags_max=3)
    assert len(tags) <= 3


def test_hashtags_deduplicated():
    """always-tags and derived tags don't duplicate."""
    words = [_word("психология") for _ in range(5)]
    tags = derive_hashtags(words, hashtags_always=["психология"], hashtags_max=5)
    seen = [t.lstrip("#") for t in tags]
    # The lemma of "психология" should appear at most once
    counts = {t: seen.count(t) for t in seen}
    assert all(v == 1 for v in counts.values()), f"duplicates: {tags}"


def test_hashtags_always_prepended():
    words = [_word("страх") for _ in range(5)]
    tags = derive_hashtags(words, hashtags_always=["психолог", "самопознание"], hashtags_max=5)
    assert tags[0] == "#психолог"
    assert tags[1] == "#самопознание"


# ---------------------------------------------------------------------------
# Test 4 — sidecars written on render and rewritten when reel changes
# ---------------------------------------------------------------------------

def test_sidecar_txt_written_on_render(tmp_path):
    """_write_sidecar_text writes <reel>.txt with caption + hashtags."""
    r = _reel(
        description="Подпись к клипу.",
        subtitles=[_word("страх"), _word("психология")],
    )
    clip = tmp_path / "r01.mp4"
    clip.write_bytes(b"x")
    _write_sidecar_text(clip, r, _cfg())
    txt = (tmp_path / "r01.txt").read_text(encoding="utf-8")
    assert "Подпись к клипу." in txt


def test_sidecar_transcript_written(tmp_path):
    """_write_sidecar_text writes <reel>.transcript.txt with spoken words."""
    r = _reel(subtitles=[_word("Первое"), _word("слово")])
    clip = tmp_path / "r01.mp4"
    clip.write_bytes(b"x")
    _write_sidecar_text(clip, r, _cfg())
    transcript = (tmp_path / "r01.transcript.txt").read_text(encoding="utf-8")
    assert "Первое слово" in transcript


def test_sidecar_rewritten_when_description_changes(tmp_path):
    """Calling _write_sidecar_text again with changed description overwrites the sidecar."""
    r1 = _reel(description="Старая подпись.", subtitles=[_word("слово")])
    clip = tmp_path / "r01.mp4"
    clip.write_bytes(b"x")
    _write_sidecar_text(clip, r1, _cfg())

    r2 = _reel(description="Новая подпись.", subtitles=[_word("слово")])
    _write_sidecar_text(clip, r2, _cfg())

    txt = (tmp_path / "r01.txt").read_text(encoding="utf-8")
    assert "Новая подпись." in txt
    assert "Старая подпись." not in txt


# ---------------------------------------------------------------------------
# Test 5 — index.md lists every reel
# ---------------------------------------------------------------------------

def test_index_md_lists_all_reels(tmp_path):
    """_write_index_md creates index.md with an entry for every reel."""
    reels = [
        _reel(id="r01", title_overlay="Заголовок 1", description="Подпись 1."),
        _reel(id="r02", title_overlay="Заголовок 2", description=""),
        _reel(id="r03", title_overlay="", description="Подпись 3."),
    ]
    m = _manifest(reels)
    _write_index_md(m, tmp_path, _cfg())
    md = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "r01" in md or "Заголовок 1" in md
    assert "r02" in md or "Заголовок 2" in md
    assert "Подпись 3." in md
    # All three reels appear
    assert md.count("##") == 3
