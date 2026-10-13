"""M50 montage (cloud/montage.py, docs/REEL_SPEC.md §8): one clip from pieces of different blocks.

1. The montage line: pieces B.S-E, h:/c:/k:/f:/t:/d:, errors named, never read as a review line.
2. One sentence numbering for the pieces; pieces in source order; references checked.
3. The plan: a window always starts at a piece, both sides of that seam keep break_pad_sec of air
   (a natural pause), the shot flips; without breaks the plan is unchanged (invariant 8).
4. The seam report: short piece, too many seams, pace change, voice up before a seam, a piece
   starting on a word pointing back.
5. --apply end to end: the montage becomes one more planned reel after the review lines' reels.
"""
import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from autoreels import __main__ as cli
from autoreels.cloud.blocks import parse_compact_answer
from autoreels.cloud.montage import (
    MontageEntry, Piece, SeamParams, build_montage, is_montage_line, parse_montage, seam_report,
)
from autoreels.cloud.plan import ManualPlanParams, build_manual_plan
from autoreels.core.models import Manifest, Word

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── 1. the line ──────────────────────────────────────────────────────────────────────────────

def test_montage_line_fields():
    text = ("# header\n3 80 | s:2\n"
            "M 85 | 13.2-6 41.1-4 41.7 | h:41.3! | c:13.4,41.2 | k:41.2=слово,дело;13.3=мысль* | f:0 "
            "| t: Заголовок | с чертой | d: Подпись, с запятой\n"
            "M7 70@1.1 2.1-3\n")
    entries, errors = parse_montage(text)
    assert errors == []
    a, b = entries
    assert a.label == "M1" and a.score == 85 and a.lineno == 3
    assert a.pieces == (Piece(13, 2, 6), Piece(41, 1, 4), Piece(41, 7, 7))
    assert a.hook == (41, 3) and a.hook_keep and not a.hook_remove
    assert a.close == ((13, 4), (41, 2))
    assert a.keys == (((41, 2), ("слово", "дело")), ((13, 3), ("мысль*",)))
    assert a.filler is False and a.title == "Заголовок | с чертой" and a.description == "Подпись, с запятой"
    assert b.label == "M7" and b.speed == 1.1 and b.pieces == (Piece(2, 1, 3),)


@pytest.mark.parametrize("line, needle", [
    ("M 85 | 13.6-2", "end before start"),
    ("M 85 | h:13.2", "no pieces"),
    ("M 85+ | 13.2-4", "merge markers"),
    ("M 120 | 13.2-4", "out of range"),
    ("M 85 | 13.2-4 | x:3", "unrecognised"),
    ("M 85 | 13.2-4 | h:13", "expected h:B.N"),
])
def test_bad_montage_line_is_named(line, needle):
    entries, errors = parse_montage(line + "\n")
    assert entries == [] and len(errors) >= 1 and needle in errors[0][1]


def test_montage_line_is_not_a_review_line():
    text = "M 85 | 13.2-6 41.1-4 | t: Заголовок\n4 70\n"
    _, entries, errors, ignored = parse_compact_answer(text)
    assert [e.seq for e in entries] == [4] and errors == [] and ignored == 1
    assert is_montage_line("M2 85 | 1.1") and not is_montage_line("Maybe 85") and not is_montage_line("4 70")


def test_label_check_keeps_montage_lines_byte_for_byte():
    from autoreels.cloud.label import check_draft
    text = "# x\nM 85 | 13.2-6 41.1-4 | t: Заголовок\n"
    new, flagged = check_draft(text, [], [])
    assert new == text and flagged == []


# ── 2. one numbering ─────────────────────────────────────────────────────────────────────────

def _w(text, t0, t1):
    return Word(word=text, t0=t0, t1=t1)


def _block_sents(start: float, n: int):
    """n one-word sentences, 2 s apart."""
    return [[_w(f"Слово{int(start) + 2 * i}.", start + 2 * i, start + 2 * i + 1.0)] for i in range(n)]


def _blocks():
    sents = {1: _block_sents(0, 5), 2: _block_sents(100, 6), 3: _block_sents(200, 4)}
    blocks = {k: SimpleNamespace(seq=k) for k in sents}
    return blocks, (lambda b: sents[b.seq])


def _entry(*pieces, **kw):
    return MontageEntry(label="M1", lineno=1, raw="M …", score=80, speed=None,
                        pieces=tuple(Piece(*p) for p in pieces), **kw)


def test_pieces_map_to_one_numbering_in_source_order():
    blocks, bs = _blocks()
    mb = build_montage(_entry((1, 2, 4), (3, 1, 2), hook=(2, 3), close=((3, 2),), keys=(((1, 3), ("x",)),)),
                       blocks, bs)
    assert mb.errors == []
    # blocks 1, 2 (hook only), 3 → offsets 0, 5, 11
    assert len(mb.sentences) == 15
    assert mb.play == [2, 3, 4, 12, 13] and mb.breaks == [12] and mb.pieces == [(2, 4), (12, 13)]
    assert mb.hook == 8 and mb.close == [13] and mb.keys == [(3, ("x",))]


@pytest.mark.parametrize("pieces, needle", [
    (((3, 1, 2), (1, 1, 2)), "source order"),
    (((1, 1, 3), (1, 3, 4)), "repeats a sentence"),
    (((1, 1, 9),), "has sentences 1-5"),
    (((7, 1, 2),), "not in the review numbering"),
])
def test_bad_pieces_are_refused(pieces, needle):
    blocks, bs = _blocks()
    mb = build_montage(_entry(*pieces), blocks, bs)
    assert any(needle in e for e in mb.errors), mb.errors


def test_close_on_a_block_without_a_piece_is_refused():
    blocks, bs = _blocks()
    mb = build_montage(_entry((1, 1, 2), close=((2, 1),)), blocks, bs)
    assert any("has no piece" in e for e in mb.errors)


# ── 3. the plan ──────────────────────────────────────────────────────────────────────────────

def _spec_sents():
    """Six sentences: 1-3 at 0…6 s, 4-6 at 100…106 s; audible span = middle of each 1.6 s word."""
    sents, words, smap = [], [], []
    for base in (0.0, 100.0):
        for i in range(3):
            t0 = base + 2 * i
            w = _w(f"Слово{int(t0)}.", t0, t0 + 1.6)
            sents.append([w])
            words.append(w)
            smap.append({"idx": len(smap), "t0": t0, "t1": t0 + 1.6,
                         "audible_start": t0 + 0.1, "audible_end": t0 + 1.5})
    return sents, words, {"words": smap, "boundaries": []}


P = ManualPlanParams(seam_pad_sec=0.04, end_air_sec=0.30, onset_margin_sec=0.06, break_pad_sec=0.20)


def test_piece_seam_keeps_a_natural_pause_and_flips_the_shot():
    sents, words, smap = _spec_sents()
    plain = build_manual_plan(sents, [2, 3, 4, 5], words=words, smap=smap, params=P)
    mont = build_manual_plan(sents, [2, 3, 4, 5], words=words, smap=smap, params=P, breaks=[4])
    a, b = mont.body
    assert a.sentences == [2, 3] and b.sentences == [4, 5]
    assert a.end == pytest.approx(5.5 + 0.20)            # audible end of s3 + break pad
    assert b.start == pytest.approx(100.1 - 0.20)        # audible start of s4 − break pad
    assert a.last_shot == "wide" and (b.shot == "close" or b.close_intervals[0][0] == 0.0)   # seam flips
    # the clip start (not a piece seam) keeps the ordinary seam pad
    assert a.start == pytest.approx(2.1 - 0.04)
    # without breaks, s3 → s4 (consecutive numbers, different blocks) would be ONE window playing
    # the 95 s between them — the reason a piece must start a window
    assert [w.sentences for w in plain.body] == [[2, 3, 4, 5]] and plain.body[0].end > 100


def test_break_inside_consecutive_numbers_starts_a_window():
    sents, words, smap = _spec_sents()
    # s3 → s4 are consecutive numbers but different pieces (adjacent blocks): a window starts at s4
    one = build_manual_plan(sents, [1, 2], words=words, smap=smap, params=P, breaks=[2])
    assert [w.sentences for w in one.body] == [[1], [2]]
    assert one.body[0].end == pytest.approx(1.5 + 0.20) and one.body[1].start == pytest.approx(2.1 - 0.20)


def test_break_pad_never_crosses_into_the_neighbouring_speech():
    sents, words, smap = _spec_sents()
    big = ManualPlanParams(seam_pad_sec=0.04, end_air_sec=0.30, onset_margin_sec=0.06, break_pad_sec=0.9)
    plan = build_manual_plan(sents, [1, 3], words=words, smap=smap, params=big, breaks=[3])
    a, b = plan.body
    assert a.end == pytest.approx((1.5 + 2.1) / 2)       # middle of the silence before s2
    assert b.start == pytest.approx((3.5 + 4.1) / 2)     # middle of the silence after s2


def test_removed_hook_at_a_piece_start_moves_the_break():
    sents, words, smap = _spec_sents()
    plan = build_manual_plan(sents, [1, 2, 4, 5, 6], words=words, smap=smap, params=P, hook=4,
                             hook_mode="-", breaks=[4])
    assert [w.sentences for w in plan.body] == [[1, 2], [5, 6]]
    assert plan.body[1].start == pytest.approx(102.1 - 0.20)


# ── 4. the seam report ───────────────────────────────────────────────────────────────────────

def test_seam_report_names_what_breaks_smoothness():
    sents, words, smap = _spec_sents()
    sents[3] = [_w("и", 100.0, 100.4)] + sents[3]           # piece 2 starts on «и»
    words = [w for s in sents for w in s]
    smap = {"words": [{"idx": i, "t0": w.t0, "t1": w.t1, "audible_start": w.t0 + 0.05,
                       "audible_end": w.t1 - 0.05} for i, w in enumerate(words)], "boundaries": []}
    plan = build_manual_plan(sents, [1, 2, 3, 4, 5], words=words, smap=smap, params=P, breaks=[4])
    mb = SimpleNamespace(sentences=sents, pieces=[(1, 3), (4, 5)])
    entry = _entry((1, 1, 3), (2, 1, 2))
    lines, warns = seam_report(plan, mb, entry, SeamParams(piece_min_sec=6.0, seams_per_min_max=3.0,
                                                           pace_ratio_max=1.2, seam_jump_warn=3.0),
                               tone=lambda w: ("open", "↗") if w.t0 == 4.0 else ("final", ""),
                               jump=lambda a, b: 4.5, weak_start_words={"и"})
    text = "\n".join(lines + warns)
    assert "seam 1  1.1-3→2.1-2" in lines[1] and "picture jump 4.5×" in lines[1] and "pause" in lines[1]
    assert any("too short" in w and "2.1-2" in w for w in warns)          # piece 2 ≈ 3.5 s
    assert any("picture jump 4.5×" in w for w in warns)
    assert any("voice up" in w for w in warns)
    assert any("starts on «и»" in w for w in warns)
    assert any("speech rate" in w for w in warns)
    assert "constant jumping" not in text                                 # one seam is always allowed


def test_seam_count_rule():
    # 1 seam is always allowed; 3 per minute → 4 seams in 60 s are reported
    sents, words, smap = _spec_sents()
    plan = build_manual_plan(sents, [1, 3, 5], words=words, smap=smap, params=P, breaks=[3, 5])
    mb = SimpleNamespace(sentences=sents, pieces=[(1, 1), (3, 3), (5, 5)])
    _, warns = seam_report(plan, mb, _entry((1, 1, 1), (1, 3, 3), (2, 2, 2)), SeamParams(seams_per_min_max=3.0))
    assert any("2 seams" in w for w in warns)


# ── 5. --apply end to end ────────────────────────────────────────────────────────────────────

def _source(tmp_path, *, montage_on=True):
    rnd = random.Random(11)
    syll = ["ка", "ро", "ми", "ту", "ле", "на", "во", "си", "да", "жу"]
    words, t = [], 40.0
    for i in range(80):
        n = rnd.randint(5, 9)
        for k in range(n):
            tok = "".join(rnd.choice(syll) for _ in range(rnd.randint(2, 4)))
            if k == 0:
                tok = tok.capitalize()
            words.append({"word": tok + ("." if k == n - 1 else ""), "t0": round(t, 2), "t1": round(t + 0.4, 2)})
            t += 0.5
        t += 2.0 if i % 8 == 7 else 0.6
    from autoreels.cloud.transcribe import params_key
    from autoreels.core import state
    from autoreels.core.models import Crop, SetupProfile
    meta = {"provider": "groq", "model": "whisper-large-v3", "prompt_hash": "pm50"}
    for d in ("manifests", "reviews", "config", "cache"):
        (tmp_path / d).mkdir(exist_ok=True)
    r0 = (REPO_ROOT / "config" / "r0.yaml").read_text(encoding="utf-8")
    r0 = r0.replace("intonation_check: true", "intonation_check: false")
    if not montage_on:
        r0 = r0.replace("montage:\n  enabled: true", "montage:\n  enabled: false")
    (tmp_path / "config" / "r0.yaml").write_text(r0, encoding="utf-8")
    sha = "f" * 64
    mp3 = tmp_path / "cache" / f"{sha}.mp3"
    mp3.write_bytes(b"AUDIO_M50")
    key = params_key(meta)
    (tmp_path / "cache" / f"{state.audio_hash(mp3)}.{key}.transcript.json").write_text(
        json.dumps({"language": "ru", "words": words, "source_sha256": sha, **meta}), encoding="utf-8")
    m = Manifest(source="v.mp4", source_sha256=sha, source_hash_scheme="partial-p1", source_path="/v.mp4",
                 duration_preset="shorts",
                 setup=__import__("autoreels.core.models", fromlist=["SetupProfile"]).SetupProfile(
                     setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700), scale=[1080, 1920], frame=[1920, 1080]),
                 run_key="rk", transcript_params_key=key, source_kind="lecture", reels=[])
    mpath = tmp_path / "manifests" / "v.json"
    mpath.write_text(m.model_dump_json(), encoding="utf-8")
    return mpath


def _apply(tmp_path, body, **kw):
    mpath = _source(tmp_path, **kw)
    r0 = cli.load_r0_config(tmp_path / "config" / "r0.yaml")
    tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), tmp_path / "cache")
    _, kept, _ = cli._review_block_set(tx, r0, "lecture")
    from autoreels.cloud.blocks import _block_fingerprint
    rpath = tmp_path / "reviews" / "v_auto.txt"
    rpath.write_text(f"# source: {mpath}\n# fingerprint: {_block_fingerprint(kept)}\n# blocks: {len(kept)}\n"
                     f"# format: compact\n{body}", encoding="utf-8")
    rc = cli._blocks_do_apply(str(rpath), root=tmp_path, cache_dir=str(tmp_path / "cache"), labeler="auto")
    out = tmp_path / "reviews" / "v.review.json"
    return rc, (Manifest.model_validate_json(out.read_text()) if out.exists() else None), kept, tx


def test_apply_builds_the_montage_as_one_more_planned_reel(tmp_path, capsys):
    rc, man, kept, tx = _apply(tmp_path, "2 80\nM 85 | 2.2-4 5.1-3 | k:5.2=" + "x" + " | t: Сборка | d: Подпись\n")
    out = capsys.readouterr()
    assert rc == 0, out.err[-2000:]
    assert len(kept) >= 5 and len(man.reels) == 2
    plain, mont = man.reels
    assert plain.montage is None and "montage" not in plain.flags
    assert mont.id == "r02" and mont.planned and mont.montage.startswith("M 85") and "montage" in mont.flags
    assert mont.title_overlay == "Сборка" and mont.description == "Подпись" and mont.score == 85
    # two pieces far apart: two body windows, in source order, the second starting block 5's sentence 1
    from autoreels.cloud.edit import merge_group_sentences
    s2 = merge_group_sentences([kept[1]], tx.words)
    s5 = merge_group_sentences([kept[4]], tx.words)
    wins = mont.effective_segments()
    assert len(wins) >= 2 and wins[0].start < s2[1][0].t0 < wins[0].end
    starts = [w.start for w in wins]
    assert any(abs(a - (s5[0][0].t0 - 0.20)) < 0.05 for a in starts)
    # subtitles = exactly the played sentences of both pieces
    want = [w.word for s in s2[1:4] + s5[0:3] for w in s]
    assert [w.word for w in mont.subtitles] == want
    assert "montage M1: 2 pieces 2.2-4 5.1-3, 1 seam(s)" in out.out and "seam 1  2.2-4→5.1-3" in out.out


def test_apply_refuses_a_broken_montage_line(tmp_path, capsys):
    rc, _, _, _ = _apply(tmp_path, "2 80\nM 85 | 5.1-3 2.2-4\n")
    assert rc == 1 and "source order" in capsys.readouterr().err


def test_montage_off_ignores_the_lines(tmp_path, capsys):
    rc, man, _, _ = _apply(tmp_path, "2 80\nM 85 | 2.2-4 5.1-3\n", montage_on=False)
    assert rc == 0 and len(man.reels) == 1
    assert "montage line(s) (M …) ignored" in capsys.readouterr().err


def test_review_sheet_shows_montage_without_stealing_a_line():
    from autoreels.local.review_sheet import Card, build_sheet
    html = build_sheet("v", [Card(rid="r02", video=None, duration=40.0, montage="M 85 | 2.2-4 5.1-3")],
                       review_ref="reviews/v_auto.txt", manifest_ref="manifests/v.json", key="k")
    assert "сборка" in html.lower() and "M 85 | 2.2-4 5.1-3" in html and "Без строки черновика" not in html


# ── 6. loudness and pitch on each side of a seam ─────────────────────────────────────────────

def test_voice_level_and_pitch_of_a_stretch():
    import numpy as np
    from autoreels.local.voice import SR, measure
    t = np.arange(int(SR * 2.0)) / SR
    gate = (np.sin(2 * np.pi * 2 * t) > 0)                      # speech half the time, silence between
    loud = 0.5 * np.sin(2 * np.pi * 150 * t) * gate
    quiet = 0.125 * np.sin(2 * np.pi * 200 * t) * gate
    a = measure(loud, ref_f0=150.0, threshold_db=-40.0)
    b = measure(quiet, ref_f0=150.0, threshold_db=-40.0)
    assert a.level_db - b.level_db == pytest.approx(12.0, abs=0.5)  # ×4 amplitude; silences not counted
    assert a.pitch_st == pytest.approx(0.0, abs=0.3)
    assert b.pitch_st == pytest.approx(12 * np.log2(200 / 150), abs=0.3)


def test_seam_report_measures_loudness_and_pitch_on_both_sides():
    from autoreels.local.voice import Voice
    sents, words, smap = _spec_sents()
    plan = build_manual_plan(sents, [1, 2, 3, 4, 5, 6], words=words, smap=smap, params=P, breaks=[4])
    mb = SimpleNamespace(sentences=sents, pieces=[(1, 3), (4, 6)])
    asked = []

    def voice(a, b):
        asked.append((round(a, 2), round(b, 2)))
        return Voice(-20.0, 0.5) if a < 50 else Voice(-27.0, 4.5)

    lines, warns = seam_report(plan, mb, _entry((1, 1, 3), (2, 1, 3)), SeamParams(side_sec=4.0), voice=voice,
                               tone=lambda w: ("final", ""))
    left, right = plan.body
    assert asked == [(round(left.end - 4.0, 2), round(left.end, 2)), (round(right.start, 2), round(right.start + 4.0, 2))]
    assert "loudness -20→-27 dB" in lines[1] and "pitch +0.5→+4.5 st" in lines[1] and "end final" in lines[1]
    assert any("quieter by 7.0 dB" in w for w in warns)
    assert any("higher by 4.0 semitones" in w for w in warns)
    _, calm = seam_report(plan, mb, _entry((1, 1, 3), (2, 1, 3)), SeamParams(),
                          voice=lambda a, b: Voice(-20.0, 0.0))
    assert not any("dB" in w or "semitones" in w for w in calm)
