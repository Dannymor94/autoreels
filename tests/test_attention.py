"""M53: attention — the picture changes at least every max_static_sec in a montage clip (a
wide↔close switch, preferably on a k: keyword), k: words are highlighted in a montage clip, and the
review sheet points at the places to look: seams, cuts, shot changes, the end of the cold open,
stretches with no change of picture, the montage seam notes.
"""
import json
from types import SimpleNamespace

import pytest

from autoreels.cloud.plan import ManualPlanParams, build_manual_plan
from autoreels.core.models import Reel, Segment, Word, make_cold_open_segment
from autoreels.local.review_sheet import Card, attention_marks, build_sheet


def _w(text, t0, t1):
    return Word(word=text, t0=t0, t1=t1)


def _long_window(n=10, sent_dur=2.4, gap=0.6):
    """n sentences of two words, one window, 3 s per sentence."""
    sents, words, smap = [], [], []
    t = 0.0
    for i in range(n):
        a = _w(f"Слово{i}", t, t + 1.0)
        b = _w(f"дело{i}.", t + 1.2, t + sent_dur)
        sents.append([a, b])
        for x in (a, b):
            words.append(x)
            smap.append({"idx": len(smap), "t0": x.t0, "t1": x.t1, "audible_start": x.t0 + 0.02,
                         "audible_end": x.t1 - 0.02})
        t += sent_dur + gap
    return sents, words, {"words": smap, "boundaries": []}


def _shots(w):
    """[(start, end, shot)] window-relative."""
    dur = w.end - w.start
    if w.shot == "close":
        return [(0.0, dur, "close")]
    pts, out, cur = sorted({0.0, dur, *[x for c in w.close_intervals for x in c]}), [], None
    for a, b in zip(pts, pts[1:]):
        sh = "close" if any(c0 <= (a + b) / 2 < c1 for c0, c1 in w.close_intervals) else "wide"
        out.append((a, b, sh))
    return out


P = ManualPlanParams(seam_pad_sec=0.04, end_air_sec=0.30, onset_margin_sec=0.06)


def test_off_by_default_keeps_the_plan():
    sents, words, smap = _long_window()
    plan = build_manual_plan(sents, list(range(1, 11)), words=words, smap=smap, params=P)
    assert [(w.shot, w.close_intervals) for w in plan.body] == [("wide", [])]


def test_no_shot_longer_than_max_static_and_none_shorter_than_min_shot():
    sents, words, smap = _long_window()
    prm = ManualPlanParams(seam_pad_sec=0.04, end_air_sec=0.30, onset_margin_sec=0.06,
                           max_static_sec=6.0, min_shot_sec=3.0)
    plan = build_manual_plan(sents, list(range(1, 11)), words=words, smap=smap, params=prm)
    (w,) = plan.body
    shots = _shots(w)
    assert len(shots) >= 5
    assert all(b - a <= 6.0 + 1e-6 for a, b, _ in shots[:-1])
    assert all(b - a >= 3.0 - 1e-6 for a, b, _ in shots)
    assert [s for _, _, s in shots] == ["wide", "close"] * (len(shots) // 2) + (["wide"] if len(shots) % 2 else [])
    # every switch is at a sentence boundary: in the pause after a sentence's last word
    for a, _, _ in shots[1:]:
        t = a + w.start
        assert not any(x.t0 < t < x.t1 for x in words)
        assert any(s[-1].t1 <= t <= s[-1].t1 + 0.6 for s in sents)


def test_switch_lands_on_the_keyword():
    sents, words, smap = _long_window()
    prm = ManualPlanParams(seam_pad_sec=0.04, end_air_sec=0.30, onset_margin_sec=0.06,
                           max_static_sec=6.0, min_shot_sec=3.0)
    plan = build_manual_plan(sents, list(range(1, 11)), words=words, smap=smap, params=prm,
                             keys=[(2, ["дело1"])])
    (w,) = plan.body
    first_switch = _shots(w)[1][0] + w.start
    kw = sents[1][1]                      # «дело1.» starts at 4.2
    assert abs(first_switch - (kw.t0 - 0.1)) < 0.15     # the boundary right before the keyword


def _reel():
    segs = [Segment(start=10.0, end=20.0, shot="wide", close_intervals=[[0.0, 3.0]]),
            Segment(start=21.0, end=25.0, shot="close", window_cut=True),
            Segment(start=100.0, end=115.0, shot="wide")]
    r = Reel(id="r01", start=10.0, end=115.0, score=80, hook="h", title="", description="",
             segments=segs, cold_open=make_cold_open_segment(110.0, 112.0))
    r.marks = [{"t": 100.0, "kind": "seam", "text": "стык 1 (2.1-3→5.1-2): пауза 0.40 с",
                "warn": ["голос выше на 3.7 полутона — другое настроение"]}]
    return r


def test_attention_marks_in_clip_time():
    ev = attention_marks(_reel())
    by = [(e["t"], e["kind"]) for e in ev]
    # cold open 2 s, then body: 10 s (close 0–3), 4 s (cut), 15 s
    assert (2.0, "hook") in by and (5.0, "shot") in by and (12.0, "cut") in by
    seam = next(e for e in ev if e["t"] == 16.0)
    assert seam["kind"] == "seam" and seam["text"].startswith("стык 1") and seam["warn"]
    static = [e for e in ev if e["kind"] == "static"]
    assert [(e["t"], e["len"]) for e in static] == [(16.0, 15.0)]      # last window: 15 s, no change
    sped = _reel().model_copy(update={"speed": 1.25})
    sped.marks = _reel().marks
    assert next(e for e in attention_marks(sped) if e.get("text"))["t"] == pytest.approx(16.0 / 1.25, abs=0.01)


def test_sheet_shows_the_timeline_and_what_to_look_at():
    c = Card("r01", "r01.mp4", 31.0, seq=3, line="3 80", attention=attention_marks(_reel()))
    html = build_sheet("v", [c], review_ref="r", manifest_ref="m", key="k")
    assert 'class="tl"' in html and html.count('class="tk ') >= 5
    assert "на что смотреть: 2" in html and "стык 1 (2.1-3→5.1-2)" in html
    assert "15 с без смены картинки" in html and 'data-t="16.0"' in html
    plain = build_sheet("v", [Card("r02", "r02.mp4", 10.0, seq=4, line="4 80")], review_ref="r",
                        manifest_ref="m", key="k")
    assert 'class="att"' not in plain


def test_keyword_highlight_is_on_for_montage_clips_in_the_render_fingerprint():
    from autoreels import __main__ as cli
    from autoreels.core.models import Crop, SetupProfile
    setup = SetupProfile(setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700), scale=[1080, 1920], frame=[1920, 1080])
    r = Reel(id="r01", start=1.0, end=5.0, score=80, hook="h", title="", description="")
    fp = lambda x: cli._reel_render_fingerprint(x, setup=setup, palette="neutral", profile="h264",
                                                zoom_on=False, music_path=None, subtitle_keywords=False)
    plain = fp(r)
    m = r.model_copy(update={"montage": "M 80 | 1.1-2"})
    assert fp(m) != plain
    assert fp(r.model_copy(update={"marks": [{"t": 1.0}]})) == plain     # marks are not in the picture


def test_montage_apply_writes_seam_marks_and_puts_the_close_shot_on_the_keyword(tmp_path):
    """M53c: no timed switches (owner: «каждые 6 с наплыв — часто»); the close shot comes on the k:
    keyword and at the seam."""
    from autoreels import __main__ as cli
    from autoreels.cloud.edit import merge_group_sentences
    from autoreels.core.models import Manifest as _M
    from tests.test_montage import _apply, _source
    (tmp_path / "probe").mkdir()
    mpath = _source(tmp_path / "probe")
    r0 = cli.load_r0_config(tmp_path / "probe" / "config" / "r0.yaml")
    tx = cli._resolve_cached_transcript(_M.model_validate_json(mpath.read_text()), tmp_path / "probe" / "cache")
    _, kept, _ = cli._review_block_set(tx, r0, "lecture")
    s3 = merge_group_sentences([kept[1]], tx.words)[2]
    kw = s3[1]
    word = kw.word.strip(".,!?").lower()
    rc, man, kept, tx = _apply(tmp_path, f"M 85 | 2.1-6 5.1-5 | k:2.3={word} | t: Сборка\n")
    assert rc == 0
    (mont,) = man.reels
    assert mont.marks and mont.marks[0]["kind"] == "seam" and mont.marks[0]["text"].startswith("стык 1 (2.1-6→5.1-5)")
    first = mont.effective_segments()[0]
    spans = [[first.start + a, first.start + b] for a, b in first.close_intervals] if first.shot != "close" else [[first.start, first.end]]
    assert any(abs(a - kw.t0) < 0.4 for a, _ in spans), (spans, kw.t0)       # close comes on the keyword
    assert len(spans) == 1                                                   # and nowhere else in piece 1
    ev = attention_marks(mont)
    assert any(e.get("text", "").startswith("стык 1") for e in ev)

def test_blocks_text_prints_the_review_numbering_and_finds_text(tmp_path, capsys):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    from autoreels.core.models import Manifest
    from autoreels.cloud.edit import merge_group_sentences
    mpath = _source(tmp_path)
    assert cli.cmd_blocks_text(str(mpath), root=tmp_path, cache_dir=str(tmp_path / "cache"), blocks="2") == 0
    out = capsys.readouterr().out
    r0 = cli.load_r0_config(tmp_path / "config" / "r0.yaml")
    tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), tmp_path / "cache")
    _, kept, _ = cli._review_block_set(tx, r0, "lecture")
    s2 = merge_group_sentences([kept[1]], tx.words)
    assert "[2] " in out and "[1] " not in out and "[3] " not in out
    third = " ".join(w.word for w in s2[2])
    assert f"2.3 " in out and third in out
    needle = " ".join(third.split()[:2])
    assert cli.cmd_blocks_text(str(mpath), root=tmp_path, cache_dir=str(tmp_path / "cache"),
                               find=[needle.upper(), "нет такого текста"]) == 0
    out = capsys.readouterr().out
    assert "→ 2.3 " in out and "«нет такого текста» → не найдено" in out
    assert cli._build_parser().parse_args(["blocks-text", "v", "--find", "a", "--find", "b"]).find == ["a", "b"]


def test_seam_marks_are_written_for_the_sheet_in_russian():
    from autoreels.cloud.montage import SeamParams, seam_report
    from autoreels.local.voice import Voice
    from tests.test_montage import P as MP, _entry, _spec_sents
    sents, words, smap = _spec_sents()
    plan = build_manual_plan(sents, [1, 2, 3, 4, 5, 6], words=words, smap=smap, params=MP, breaks=[4])
    mb = SimpleNamespace(sentences=sents, pieces=[(1, 3), (4, 6)])
    marks = []
    seam_report(plan, mb, _entry((1, 1, 3), (2, 1, 3)), SeamParams(), marks=marks,
                voice=lambda a, b: Voice(-20.0, 0.0) if a < 50 else Voice(-27.0, 4.5),
                tone=lambda w: ("open", "↗") if w.word == "Слово4." else ("final", ""))
    (m,) = marks
    assert m["t"] == pytest.approx(plan.body[1].start, abs=1e-3) and m["kind"] == "seam"
    assert m["text"].startswith("стык 1 (1.1-3→2.1-3): пропущено 94 с, пауза") and "громкость -7.0 дБ" in m["text"]
    assert any("тише на 7.0 дБ" in w for w in m["warn"]) and any("выше на 4.5 полутона" in w for w in m["warn"])
    assert any("голосом вверх" in w for w in m["warn"])


def test_montage_keeps_pauses_unless_the_line_asks_for_the_cut(tmp_path, monkeypatch):
    """M53b: owner — «сильно дёргается» (the pause/filler cuts) — a montage clip is planned without the
    filler cut; f:1 on the line (or --filler) turns it back on."""
    import numpy as np
    from autoreels.cloud import plan as plan_mod
    from autoreels.local import motion
    from tests.test_montage import _apply
    seen = []
    real = plan_mod.build_manual_plan

    def spy(*a, **kw):
        seen.append(kw["params"].filler_cut)
        return real(*a, **kw)
    monkeypatch.setattr(plan_mod, "build_manual_plan", spy)
    (tmp_path / "data" / "cache").mkdir(parents=True)
    motion.save(tmp_path / "data" / "cache" / "v.motion.npz", np.zeros((4000, 8, 8), dtype=np.uint8) + 1,
                "f" * 64, [960, 1700, 0, 0])
    rc, man, _, _ = _apply(tmp_path, "2 80\nM 85 | 2.1-3 5.1-3\nM2 84 | 3.1-3 6.1-3 | f:1\n")
    assert rc == 0 and len(man.reels) == 3
    # the review line keeps the config's filler cut (on); M1 off by default; M2 asked f:1
    assert seen == [True, False, True]


def test_emphasis_close_shot_on_the_keyword_only():
    sents, words, smap = _long_window()
    prm = ManualPlanParams(seam_pad_sec=0.04, end_air_sec=0.30, onset_margin_sec=0.06,
                           emphasis_keys=True, min_shot_sec=3.0)
    plan = build_manual_plan(sents, list(range(1, 11)), words=words, smap=smap, params=prm,
                             keys=[(4, ["дело3"]), (9, ["слово8"])])
    (w,) = plan.body
    shots = _shots(w)
    closes = [(a + w.start, b + w.start) for a, b, sh in shots if sh == "close"]
    assert len(closes) == 2
    kw = sents[3][1]                                    # «дело3.» at 10.2
    assert abs(closes[0][0] - (kw.t0 - 0.1)) < 0.15 and closes[0][1] - closes[0][0] >= 3.0 - 1e-6
    assert abs(closes[1][0] - (sents[8][0].t0 - 0.3)) < 0.35          # first word of s9: from the sentence start
    assert all(b - a >= 3.0 - 1e-6 for a, b, _ in shots)
    off = build_manual_plan(sents, list(range(1, 11)), words=words, smap=smap, params=P,
                            keys=[(4, ["дело3"])])
    assert off.body[0].close_intervals == []                          # emphasis off: the previous plan
