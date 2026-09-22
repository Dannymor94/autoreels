"""A human selection is formatted, never second-guessed.

The manual review path must run only FORMATTING stages (snap, padding, subtitles) and never a
DECIDING stage (too-long trim, top-N, dedup, dangling-start drop, density split, duration floors).
Everything a deciding stage would have removed becomes a warning; nothing is dropped or shortened.

1. Every scored line produces a reel or an explicit conflict message; none disappear.
2. A human merge of ~126s arrives un-trimmed (not capped back to the 90s preset).
3. A human clip opening on "Это" is kept, with a dangling-start warning.
4. A human merge with a 6s internal pause is kept, with a pause warning, and not split.
5. A human clip of 15s is kept with a duration warning (collect_human_warnings unit).
6. The automatic path (_cmd_run_impl) still runs every deciding stage for model candidates.
7. No deciding stage is reachable from the manual path (_blocks_do_apply source assertion).
"""
import inspect
import json
import shutil
from pathlib import Path

from autoreels import __main__ as cli
from autoreels.cloud.transcribe import params_key
from autoreels.core import state
from autoreels.core.config import load_r0_config
from autoreels.core.models import Crop, Manifest, SetupProfile, Reel, Transcript, Word

REPO_ROOT = Path(__file__).resolve().parents[1]
_META = {"provider": "groq", "model": "whisper-large-v3", "prompt_hash": "phmb"}
KEY = params_key(_META)


def _group(offset, n=30, first_word=None):
    """n words, 1s spacing, 0.95s each, starting at offset."""
    out = []
    for i in range(n):
        w = first_word if (i == 0 and first_word) else f"слово{i}."
        out.append({"word": w, "t0": offset + i * 1.0, "t1": offset + i * 1.0 + 0.95})
    return out


def _setup(tmp_path, words):
    (tmp_path / "manifests").mkdir(exist_ok=True)
    (tmp_path / "reviews").mkdir(exist_ok=True)
    cfg = tmp_path / "config"
    cfg.mkdir(exist_ok=True)
    shutil.copy(REPO_ROOT / "config" / "r0.yaml", cfg / "r0.yaml")
    cache = tmp_path / "cache"
    cache.mkdir(exist_ok=True)
    sha = "e" * 64
    mp3 = cache / f"{sha}.mp3"
    mp3.write_bytes(b"AUDIO_BYPASS_TEST")
    ah = state.audio_hash(mp3)
    tpath = cache / f"{ah}.{KEY}.transcript.json"
    tpath.write_text(
        json.dumps({"language": "ru", "words": words, "source_sha256": sha, **_META}),
        encoding="utf-8",
    )
    m = Manifest(
        source="v.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
        source_path="/originals/v.mp4", duration_preset="shorts",
        setup=SetupProfile(setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700),
                           scale=[1080, 1920], frame=[1920, 1080]),
        run_key="rk_mb", transcript_params_key=KEY, source_kind="lecture", reels=[],
    )
    mpath = tmp_path / "manifests" / "v.json"
    mpath.write_text(m.model_dump_json(), encoding="utf-8")
    return cache, mpath


def _apply(tmp_path, review, *, stem, words, filler=None):
    cache, mpath = _setup(tmp_path, words)
    tmpath = tmp_path / "manifests" / f"{stem}.json"
    tmpath.write_text(mpath.read_text(), encoding="utf-8")
    rpath = tmp_path / "reviews" / f"{stem}.review.md"
    rpath.write_text(f"# source: {tmpath}\n{review}", encoding="utf-8")
    rc = cli._blocks_do_apply(str(rpath), root=tmp_path, cache_dir=str(cache), source=str(tmpath),
                              filler=filler)
    out = tmp_path / "reviews" / f"{stem}.review.json"
    return rc, out


# --- Test 1: every scored line is placed; none disappear -----------------------------------
def test_every_scored_line_placed(tmp_path, capsys):
    # Four standalone blocks; block 2 opens on a dangling word the old path could drop — now
    # repaired or warned, never dropped.
    words = (_group(30) + _group(78, first_word="Это") + _group(126) + _group(174)
             + _group(400))  # sentinel keeps block 4 out of the tail-skip zone
    rc, out = _apply(tmp_path, "1 80\n2 80\n3 80\n4 80\n", stem="mb1", words=words)
    assert rc == 0
    res = Manifest.model_validate_json(out.read_text())
    assert len(res.reels) == 4, f"all four selections must survive, got {len(res.reels)}"
    err = capsys.readouterr().out
    assert err.count("→ reel") >= 4, "each scored line must be accounted for"
    assert "NOT PLACED" not in err, "no scored line should be dropped"


def test_merge_conflict_reported_naming_both(tmp_path, capsys):
    # Line 1 merges 1+2+3; line 3 also scored separately → conflict, earliest anchors.
    words = _group(30) + _group(78) + _group(126) + _group(400)
    rc, out = _apply(tmp_path, "1 80++\n3 90\n", stem="mbc", words=words)
    assert rc == 0
    out_txt = capsys.readouterr().out
    assert "conflict:" in out_txt, "a double-scored merge must be reported, not silently folded"
    assert "3" in out_txt and "1" in out_txt, "conflict must name both lines"


# --- Test 2: a ~126s human merge is not trimmed --------------------------------------------
def test_human_merge_not_trimmed(tmp_path):
    words = _group(30) + _group(78) + _group(126) + _group(400)
    rc, out = _apply(tmp_path, "1 80++\n", stem="mb2", words=words)
    assert rc == 0
    res = Manifest.model_validate_json(out.read_text())
    assert len(res.reels) == 1
    span = res.reels[0].end - res.reels[0].start
    assert span > 100.0, f"126s merge must not be trimmed to the 90s preset; got {span:.1f}s"
    assert res.reels[0].speed == 1.0, "126s < 180s manual ceiling → no speed-up"


# --- Test 3a: a repairable dangling start is MOVED forward, no warning ----------------------
def test_dangling_start_repaired(tmp_path):
    # Opens on "Это" but a sentence ends one word in ("фраза."); a >1s gap then a new sentence
    # ("Новое …"). Repair moves the start to "Новое"; the 0.3s lead-pad does not reach back to
    # "фраза.". Formatting half runs on the human path; no dangling warning remains.
    lead = [
        {"word": "Это", "t0": 30.0, "t1": 30.9},
        {"word": "фраза.", "t0": 31.0, "t1": 31.9},
    ]
    rest = [{"word": ("Новое" if i == 0 else f"мысль{i}"), "t0": 33.0 + i, "t1": 33.0 + i + 0.9}
            for i in range(30)]
    words = lead + rest + _group(400)
    rc, out = _apply(tmp_path, "1 80\n", stem="mb3a", words=words)
    assert rc == 0
    res = Manifest.model_validate_json(out.read_text())
    assert len(res.reels) == 1
    r = res.reels[0]
    assert r.start > 32.0, f"start should move past «Это фраза.» to «Новое», got {r.start}"
    assert not any("dangling" in w for w in r.warnings), f"repaired → no warning: {r.warnings}"


# --- Test 3b: an unrepairable dangling start is kept, with a warning ------------------------
def test_dangling_start_unrepairable_warned(tmp_path):
    # Unique lowercase words, no sentence marks → nothing to repair to → kept + warned.
    words = ([{"word": ("это" if i == 0 else f"мысль{i}"), "t0": 30.0 + i, "t1": 30.0 + i + 0.9}
              for i in range(30)] + _group(400))
    rc, out = _apply(tmp_path, "1 80\n", stem="mb3b", words=words)
    assert rc == 0
    res = Manifest.model_validate_json(out.read_text())
    assert len(res.reels) == 1, "an unrepairable dangling-start clip must be kept, not dropped"
    assert any("dangling" in w for w in res.reels[0].warnings), res.reels[0].warnings


# --- Test 3c: repair is bounded — never crosses a merge boundary (unit) ---------------------
def test_repair_bounded_by_merge_boundary():
    from autoreels.cloud.select import filter_dangling_start
    # Sentence boundary ("Новое") sits at t=20, but the merge boundary is at t=10 → repair may
    # not cross it; the start stays and the clip is kept (repair_only), to be warned by caller.
    words = ([{"word": "это", "t0": 0.0, "t1": 0.9}]
             + [{"word": "слово", "t0": float(i), "t1": i + 0.9} for i in range(1, 20)]
             + [{"word": "конец.", "t0": 19.0, "t1": 19.9}]
             + [{"word": "Новое", "t0": 20.0, "t1": 20.9}]
             + [{"word": "слово", "t0": float(i), "t1": i + 0.9} for i in range(21, 60)])
    tx_words = [Word(**w) for w in words]
    reel = Reel(id="m", start=0.0, end=59.0, score=80, hook="h", title="", description="")
    reel._merge_boundary = 10.0
    kept, disc = filter_dangling_start(tx_words and [reel], tx_words, min_duration=5.0,
                                       repair_only=True, max_start_fraction=1.0 / 3.0)
    assert kept and not disc, "repair_only must keep the clip"
    assert reel.start == 0.0, f"start must not cross the merge boundary at 10s; got {reel.start}"


# --- Test 4: internal pause kept, warned, not split ----------------------------------------
def test_internal_pause_kept_not_split(tmp_path):
    # Two blocks separated by a 6s gap, merged → one clip with a 6s internal pause.
    # Filler removal off (--no-filler) isolates the warn-not-split behaviour: with it on the
    # pause would be shortened (Part 3), which test_internal_pause_shortened_by_filler covers.
    words = _group(30, n=30) + _group(66, n=30) + _group(300)
    rc, out = _apply(tmp_path, "1 80+\n", stem="mb4", words=words, filler=False)
    assert rc == 0
    res = Manifest.model_validate_json(out.read_text())
    assert len(res.reels) == 1, "a clip with a long internal pause must not be split into two"
    assert any("pause" in w for w in res.reels[0].warnings), res.reels[0].warnings


# --- Part 3: with filler removal on, a long internal pause is shortened into a segment gap -----
def test_internal_pause_shortened_by_filler(tmp_path):
    # Same 6s-gap merge, but filler removal on (default): the pause is shortened to the residual,
    # the clip stays ONE reel with two playback segments, and no pause warning remains.
    words = _group(30, n=30) + _group(66, n=30) + _group(300)
    rc, out = _apply(tmp_path, "1 80+\n", stem="mb4f", words=words, filler=True)
    assert rc == 0
    res = Manifest.model_validate_json(out.read_text())
    assert len(res.reels) == 1, "shortening a pause must not split the clip into two reels"
    assert len(res.reels[0].segments) == 2, "the 6s pause becomes one internal segment gap"
    assert not any("pause" in w for w in res.reels[0].warnings), res.reels[0].warnings


# --- Test 5: short clip kept, warned (unit on collect_human_warnings) -----------------------
def test_short_clip_warned_not_dropped():
    r0 = load_r0_config(REPO_ROOT / "config" / "r0.yaml")
    words = [Word(word=f"w{i}.", t0=i * 1.0, t1=i * 1.0 + 0.9) for i in range(15)]
    tx = Transcript(language="ru", words=words)
    reel = Reel(id="short1", start=0.0, end=15.0, score=80, hook="h", title="", description="")
    warns = cli.collect_human_warnings([reel], tx, r0_cfg=r0)
    assert any("short clip" in m for _, m in warns), warns
    assert any("short clip" in w for w in reel.warnings), "warning must be recorded on the reel"


# --- Test 6: automatic path still runs every deciding stage --------------------------------
def test_automatic_path_still_decides():
    # The deciding stages still run for model candidates: in _cmd_run_impl's pipeline, and
    # (dedup) inside select. Scan both modules — this must stay true even as the manual path
    # sheds them.
    from autoreels.cloud import select as _sel
    src = inspect.getsource(cli) + inspect.getsource(_sel)
    for name in cli._DECIDING_STAGES:
        assert f"{name}(" in src, f"automatic path must still run {name}"


# --- Test 7: no pure deciding stage reachable; split stages run repair-only ------------------
def test_manual_bypass():
    assert set(cli._MANUAL_FORMATTING_STAGES).isdisjoint(cli._DECIDING_STAGES)
    assert set(cli._MANUAL_REPAIR_STAGES).isdisjoint(cli._DECIDING_STAGES)
    src = inspect.getsource(cli._blocks_do_apply)
    for name in cli._DECIDING_STAGES:
        assert f"{name}(" not in src, (
            f"manual path must not call the deciding stage {name}; "
            f"format a human selection, never second-guess it"
        )
    # The split stages DO run here, but only their repair half (the no-drop flag must be present).
    for name, flag in cli._MANUAL_REPAIR_STAGES.items():
        assert f"{name}(" in src, f"manual path must run the repair half of {name}"
        assert flag in src, f"manual path must call {name} with {flag} (repair half only)"
