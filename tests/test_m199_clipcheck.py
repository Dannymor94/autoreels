"""M199: the four clip checks (measurement only) — cold open cut off, plate words, a start with nothing to stand on,
seams of unrelated pieces. Morphology needs pymorphy3; without it check 3 is None and the others use word lists."""
from __future__ import annotations

import pytest

from autoreels.cloud import clipcheck as C


def _reel(words, segs, cold=None, title=""):
    return {"id": "r01", "start": segs[0][0], "end": segs[-1][1], "title_overlay": title,
            "segments": [{"start": a, "end": b, "window_cut": wc} for a, b, wc in segs],
            "cold_open": {"start": cold[0], "end": cold[1]} if cold else None,
            "subtitles": [{"word": w, "t0": t, "t1": t + 0.2} for w, t in words]}


def test_clip_parts_pieces_in_play_order_and_hook():
    words = [("Первая", 1.0), ("мысль.", 1.5), ("Вторая", 10.0), ("мысль.", 10.5), ("Тизер", 20.0), ("здесь.", 20.4)]
    r = _reel(words, [(0.9, 2.0, False), (9.9, 11.0, False)], cold=(19.9, 21.0))
    p = C.clip_parts(r)
    assert p["hook"] == ["Тизер", "здесь."] and p["pieces"] == [["Первая", "мысль."], ["Вторая", "мысль."]]
    r = _reel(words[:4], [(0.9, 2.0, False), (2.0, 11.0, True)])     # a filler cut continues the piece
    assert C.clip_parts(r)["pieces"] == [["Первая", "мысль.", "Вторая", "мысль."]]


def test_hook_hang_without_morphology(monkeypatch):
    monkeypatch.setattr(C, "_morph", lambda: None)
    C._parse.cache_clear()
    assert "Вы" in C.hook_hang("ты просто забыл свою силу, Вы".split())
    assert C.hook_hang("Ты не поломан, ты просто забыл свою силу.".split()) is None
    assert C.hook_hang([]) is None
    C._parse.cache_clear()


def test_plate_cover_counts_sentences_with_plate_words(monkeypatch):
    monkeypatch.setattr(C, "_morph", lambda: None)
    C._parse.cache_clear()
    body = "Нервная система уникальна. Она зажата. Никто не понимает. Система раскрывается сама.".split()
    pc = C.plate_cover("Уникальная нервная система", body)
    assert pc == {"share": 0.5, "core": True, "hits": 2, "sents": 4}
    assert C.plate_cover("", body) is None
    C._parse.cache_clear()


def test_seam_shared(monkeypatch):
    monkeypatch.setattr(C, "_morph", lambda: None)
    C._parse.cache_clear()
    assert C.seam_shared([["стресс", "выключает", "осознанность."], ["осознанность", "включается."], ["купите", "книгу."]]) == [1, 0]
    C._parse.cache_clear()


def test_start_morph():
    pytest.importorskip("pymorphy3")
    assert "без подлежащего" in C.start_morph("Всем говорит, и он стоит на этом.".split())
    assert "без подлежащего" in C.start_morph("Как было, так и было.".split())
    assert "о ком" in C.start_morph("Он надевает маски, он живет на автомате.".split())
    for ok in ("Каждая нервная система уникальна.", "Сначала нажимают родители, воспитатели в школе.",
               "Бывает, что человек приходит.", "Было интересно.", "Просто вспомните себя.",
               "Как вы отдыхаете?", "У меня был такой интересный момент.",
               "Знаете, когда ко мне приходит человек, он возбуждён."):
        assert C.start_morph(ok.split()) is None, ok
