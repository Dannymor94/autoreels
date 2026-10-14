"""M55: attention effects of a clip (local/fx.py, subtitles fx, montage o:, Reel.fx, render wiring).

Owner: «давай пробовать все» — slow push-in, word-by-word subtitles, a phrase/number in big letters,
music under the speech with ducking, a whoosh on a seam, a progress bar, speed 1.05–1.1."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from autoreels.core.config import MontageFx, load_subtitles_config
from autoreels.core.models import Reel, Segment, Word
from autoreels.local import fx
from autoreels.local.subtitles import build_ass

from tests.test_render import ROOT

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg/ffprobe not installed")


def _subs_cfg():
    return load_subtitles_config(ROOT / "config" / "subtitles.yaml")


def _words(text: str, t0: float = 0.0, step: float = 0.5, emph: str = "") -> list[Word]:
    return [Word(word=w, t0=round(t0 + i * step, 3), t1=round(t0 + i * step + step * 0.9, 3),
                 emph=(w.lower() == emph)) for i, w in enumerate(text.split())]


# ------------------------------------------------------------------ times

def test_output_time_and_timeline_follow_the_played_windows():
    wins = [Segment(start=100.0, end=104.0),                              # cold open
            Segment(start=10.0, end=20.0, close_intervals=[[2.0, 5.0]]),
            Segment(start=20.5, end=24.0, window_cut=True),               # filler cut: no seam
            Segment(start=50.0, end=60.0)]
    assert fx.output_time(wins, 12.0, body0=1) == pytest.approx(6.0)
    assert fx.output_time(wins, 102.0, body0=1) is None                   # the cold open is not the body
    assert fx.output_time(wins, 52.0, speed=2.0, body0=1) == pytest.approx((4 + 10 + 3.5 + 2) / 2)
    seams, changes, total = fx.timeline(wins)
    assert seams == [4.0, 17.5]                                           # not at the filler cut 14.0
    assert changes == [4.0, 6.0, 9.0, 14.0, 17.5]
    assert total == pytest.approx(27.5)
    assert fx.timeline(wins, speed=1.1)[0] == [round(4 / 1.1, 3), round(17.5 / 1.1, 3)]
    assert fx.timeline(wins, xfades=[0.5, 0.0, 0.25]) == ([3.5, 16.75], [3.5, 5.5, 8.5, 13.5, 16.75], 26.75)


def test_push_only_on_long_shots():
    assert fx.push_vf([3.0], 5.0, min_sec=6.0) == ""                     # no shot is long enough
    assert fx.push_vf([10.0], 20.0, pct=0.0) == ""
    vf = fx.push_vf([4.0, 12.0], 15.0, pct=4.0, min_sec=6.0)
    assert "between(t\\,4.000\\,12.000)" in vf and "0.000\\,4.000" not in vf and "12.000\\,15.000" not in vf
    assert "eval=frame" in vf and vf.endswith("crop=1080:1920:(iw-1080)/2:(ih-1920)/2")


@needs_ffmpeg
def test_push_keeps_size_and_length_and_moves_the_picture(tmp_path):
    src = tmp_path / "s.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:d=8:r=25",
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(src)], check=True)
    out = tmp_path / "p.mp4"
    vf = fx.push_vf([], 8.0, pct=8.0, min_sec=6.0)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(src), "-vf", vf, "-c:v", "libx264",
                    "-preset", "ultrafast", str(out)], check=True)
    probe = json.loads(subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-count_frames",
                                       "-show_entries", "stream=width,height,nb_read_frames", "-of", "json",
                                       str(out)], capture_output=True, text=True, check=True).stdout)["streams"][0]
    assert (probe["width"], probe["height"], int(probe["nb_read_frames"])) == (1080, 1920, 200)

    def frame(path, t):
        return subprocess.run([FFMPEG, "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                               "-vf", "scale=108:192", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                              capture_output=True, check=True).stdout
    diff = lambda a, b: sum(abs(x - y) for x, y in zip(a, b)) / len(a)
    assert diff(frame(src, 0.0), frame(out, 0.0)) < 3.0                 # starts at the plain frame
    assert diff(frame(src, 7.8), frame(out, 7.8)) > 3.0                 # ends pushed in


@needs_ffmpeg
def test_whoosh_lands_on_the_seam_and_keeps_the_video(tmp_path):
    src = tmp_path / "s.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:d=4:r=25",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "4", "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)
    wav, out = tmp_path / "w.wav", tmp_path / "o.mp4"
    subprocess.run(fx.whoosh_wav_cmd(FFMPEG, wav, volume=0.5), check=True)
    subprocess.run(fx.whoosh_cmd(FFMPEG, src, wav, [2.0], out), check=True)

    def dur(p, s):
        return float(subprocess.run([FFPROBE, "-v", "error", "-select_streams", s, "-show_entries",
                                     "stream=duration", "-of", "csv=p=0", str(p)],
                                    capture_output=True, text=True, check=True).stdout.strip())
    assert dur(out, "v:0") == pytest.approx(dur(src, "v:0"), abs=1e-3)   # video copied
    assert dur(out, "a:0") == pytest.approx(dur(src, "a:0"), abs=0.05)

    def peak(t0, t1):
        r = subprocess.run([FFMPEG, "-v", "info", "-ss", str(t0), "-t", str(t1 - t0), "-i", str(out),
                            "-vn", "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
        line = next(x for x in r.stderr.splitlines() if "max_volume" in x)
        return float(line.split("max_volume:")[1].split("dB")[0])
    assert peak(1.8, 2.2) > -40.0 and peak(0.2, 1.2) < -80.0


# ------------------------------------------------------------------ subtitles

def test_ass_without_fx_is_unchanged():
    cfg, ws = _subs_cfg(), _words("это был настоящий инсайт для меня", emph="инсайт")
    base = build_ass(ws, cfg=cfg, clip_start=0.0, title="T", enable_keywords=True)
    assert build_ass(ws, cfg=cfg, clip_start=0.0, title="T", enable_keywords=True, fx={}) == base
    assert build_ass(ws, cfg=cfg, clip_start=0.0, title="T", enable_keywords=True, fx=None) == base
    assert "Callout" not in base and "\\p1" not in base


def test_karaoke_one_line_per_word_abutting_with_the_current_word_coloured():
    cfg = _subs_cfg()
    ws = _words("раз два три", t0=1.0)
    ass = build_ass(ws, cfg=cfg, clip_start=0.0, fx={"karaoke": True})
    lines = [x for x in ass.splitlines() if x.startswith("Dialogue")]
    assert len(lines) == 3
    starts = [x.split(",")[1] for x in lines]
    ends = [x.split(",")[2] for x in lines]
    assert starts == ["0:00:01.00", "0:00:01.50", "0:00:02.00"] and ends[:2] == starts[1:]   # no blink
    assert ends[-1] == "0:00:02.45"
    col = "&H4CFF4C&"
    assert f"{{\\1c{col}}}РАЗ{{\\r}} ДВА ТРИ" in lines[0] and f"РАЗ {{\\1c{col}}}ДВА{{\\r}} ТРИ" in lines[1]
    assert "\\fad(" in lines[0] and "\\fad(" not in lines[1] and "\\fad(0," in lines[2]


def test_karaoke_survives_overlapping_whisper_times():
    cfg = _subs_cfg()
    ws = [Word(word="а", t0=1.0, t1=1.4), Word(word="б", t0=0.9, t1=1.5), Word(word="в", t0=1.5, t1=2.0)]
    lines = [x for x in build_ass(ws, cfg=cfg, clip_start=0.0, fx={"karaoke": True}).splitlines()
             if x.startswith("Dialogue")]
    assert [x.split(",")[1] for x in lines] == ["0:00:01.00", "0:00:01.50"]     # «б» merged, times monotonic


def test_callout_and_progress_events():
    cfg = _subs_cfg()
    ass = build_ass(_words("слово"), cfg=cfg, clip_start=0.0,
                    fx={"progress": True, "progress_sec": 30.0, "callout_sec": 2.0,
                        "callouts": [{"t": 4.0, "text": "3 года"}, {"t": 9.0, "text": "  "}]})
    assert "Style: Callout," in ass
    (co,) = [x for x in ass.splitlines() if ",Callout," in x]
    assert co.startswith("Dialogue: 2,0:00:04.00,0:00:06.00,Callout,") and co.endswith("}3 ГОДА")
    assert "\\t(0,200,\\fscx100\\fscy100)" in co
    (bar,) = [x for x in ass.splitlines() if "\\p1" in x]
    assert bar.startswith("Dialogue: 1,0:00:00.00,0:00:30.00,") and "\\t(0,30000,\\clip(0,1912,1080,1920))" in bar


# ------------------------------------------------------------------ montage o:

def test_montage_line_parses_callouts():
    from autoreels.cloud.montage import parse_montage
    (e,), errs = parse_montage("M 80 | 2.1-3 | o:2.2=Три года; 2.3@эмпатия=ЭМПАТИЯ | k:2.3=эмпатия | t: Заголовок\n")
    assert errs == [] and e.title == "Заголовок" and e.keys == (((2, 3), ("эмпатия",)),)
    assert e.callouts == (((2, 2), None, "Три года"), ((2, 3), "эмпатия", "ЭМПАТИЯ"))
    _, errs = parse_montage("M 80 | 2.1-3 | o:2.2\n")
    assert errs and "o:2.2" in errs[0][1]


def _build(callouts):
    from autoreels.cloud.montage import MontageBuild
    s1 = _words("Мы работали 3 года подряд.", t0=10.0)
    s2 = _words("Это была настоящая эмпатия.", t0=20.0)
    s3 = _words("Потом было 80% роста.", t0=40.0)
    return MontageBuild(sentences=[s1, s2, s3], play=[1, 2, 3], breaks=[3], pieces=[(1, 2), (3, 3)],
                        callouts=callouts)


def test_callout_times_from_the_clip_words_and_numbers():
    from autoreels.cloud.montage import callout_times
    mb = _build([(2, "эмпатия", "ЭМПАТИЯ"), (1, None, "Начало")])
    subs = [w.model_copy(update={"t0": w.t0 + 0.05}) for s in mb.sentences for w in s]
    got = callout_times(mb, subs)
    assert got == [{"t": 10.05, "text": "Начало"}, {"t": 21.55, "text": "ЭМПАТИЯ"}]
    got = callout_times(mb, subs, numbers=True, gap_sec=8.0)
    assert {"t": 41.05, "text": "80%"} in got                         # 80% far from the others
    assert not any(c["text"].startswith("3") for c in got)            # «3 года» within 8 s of «Начало»
    got = callout_times(_build([]), subs, numbers=True, gap_sec=8.0)
    assert got[0] == {"t": 11.05, "text": "3 года"} and len(got) == 2


def test_build_montage_checks_callout_refs():
    from autoreels.cloud.montage import build_montage, parse_montage
    from tests.test_montage import _spec_sents
    sents, _, _ = _spec_sents()
    blocks = {1: sents[:3], 2: sents[3:]}
    (e,), _ = parse_montage("M 80 | 1.1-2 2.1-3 | o:1.3=Нет; 2.1@нет=Нет\n")
    mb = build_montage(e, blocks, lambda b: b)
    assert any("o:1.3" in x and "not played" in x for x in mb.errors)
    assert any("o:2.1@нет" in x for x in mb.errors)


def test_montage_fx_from_config():
    assert MontageFx().reel_fx([{"t": 1.0, "text": "x"}]) == {}            # all off by default
    on = MontageFx(push=True, karaoke=True, progress=True, whoosh=True, callouts=True)
    assert on.reel_fx([]) == {"push": True, "push_pct": 4.0, "push_min_sec": 6.0, "karaoke": True,
                              "progress": True, "whoosh": True, "whoosh_volume": 0.25}
    assert on.reel_fx([{"t": 1.0, "text": "x"}])["callouts"] == [{"t": 1.0, "text": "x"}]


def test_montage_apply_writes_reel_fx(tmp_path):
    from autoreels.cloud.edit import merge_group_sentences
    from tests.test_montage import _apply, _source
    from autoreels import __main__ as cli
    from autoreels.core.models import Manifest as _M
    (tmp_path / "probe").mkdir()
    mpath = _source(tmp_path / "probe")
    r0 = cli.load_r0_config(tmp_path / "probe" / "config" / "r0.yaml")
    tx = cli._resolve_cached_transcript(_M.model_validate_json(mpath.read_text()), tmp_path / "probe" / "cache")
    _, kept, _ = cli._review_block_set(tx, r0, "lecture")
    s3 = merge_group_sentences([kept[1]], tx.words)[2]
    rc, man, _, _ = _apply(tmp_path, "2 80\nM 85 | 2.1-6 5.1-5 | o:2.3=Крупно | t: Сборка\n")
    assert rc == 0
    plain, mont = man.reels
    assert plain.fx == {}                                                   # ordinary clips unchanged
    assert mont.fx["push"] and mont.fx["karaoke"] and mont.fx["progress"] and mont.fx["whoosh"]
    (co,) = mont.fx["callouts"]
    assert co["text"] == "Крупно" and abs(co["t"] - s3[0].t0) < 0.6


# ------------------------------------------------------------------ render wiring

def test_fx_in_the_render_fingerprint():
    from autoreels import __main__ as cli
    from autoreels.core.models import Crop, SetupProfile
    setup = SetupProfile(setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700), scale=[1080, 1920], frame=[1920, 1080])
    r = Reel(id="r01", start=1.0, end=5.0, score=80, hook="h", title="", description="")
    fp = lambda x: cli._reel_render_fingerprint(x, setup=setup, palette="neutral", profile="h264",
                                                zoom_on=False, music_path=None)
    plain = fp(r)
    assert fp(r.model_copy(update={"fx": {}})) == plain
    assert fp(r.model_copy(update={"fx": {"karaoke": True}})) != plain
    sub = r.model_copy(update={"subtitles": [Word(word="а", t0=1.0, t1=1.5)]})
    assert fp(sub.model_copy(update={"speed": 1.1})) != fp(sub.model_copy(update={"speed": 1.1, "subtitles": []}))


def _render_argv(tmp_path, render_cfg, fake_ffmpeg, reel):
    from autoreels.local.render import render_crop
    from tests.test_render import _crop_setup, _make_source, _manifest
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"fx-video")
    m = _manifest("v.mp4", sha, [reel], setup=_crop_setup())
    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg, subtitles_cfg=_subs_cfg())
    return [" ".join(map(str, c)) for c in fake_ffmpeg]


@pytest.fixture
def render_cfg():
    from tests.test_render import RENDER_YAML, _NO_LOCAL
    from autoreels.core.config import load_render_config
    return load_render_config(RENDER_YAML, local_path=_NO_LOCAL)


from tests.test_render import fake_ffmpeg  # noqa: E402,F401  (fixture)


def _two_window_reel(**upd):
    r = Reel(id="r01", start=10.0, end=45.0, score=80, hook="h", title="t", description="d",
             segments=[Segment(start=10.0, end=20.0), Segment(start=30.0, end=45.0)],
             subtitles=[Word(word="слово", t0=11.0, t1=11.5)])
    return r.model_copy(update=upd)


def test_speed_with_subtitles_speeds_the_video_too(tmp_path, render_cfg, fake_ffmpeg):
    """Before M55 the ass filter replaced the chain that carried setpts: only the audio got faster."""
    (cmd,) = _render_argv(tmp_path, render_cfg, fake_ffmpeg, _two_window_reel(speed=1.1))
    assert "atempo=1.1" in cmd and "setpts=PTS/1.1" in cmd
    assert cmd.index("setpts=PTS/1.1") < cmd.index("ass=r01.ass")


def test_render_wires_push_before_the_subtitles(tmp_path, render_cfg, fake_ffmpeg):
    import re
    (plain,) = _render_argv(tmp_path, render_cfg, fake_ffmpeg, _two_window_reel())
    fake_ffmpeg.clear()
    (cmd,) = _render_argv(tmp_path, render_cfg, fake_ffmpeg,
                          _two_window_reel(fx={"push": True, "push_pct": 4.0, "push_min_sec": 6.0}))
    assert "eval=frame" not in plain
    # two shots, the second starting where the seam's short dissolve puts it (10 s − 2 frames)
    assert "between(t\\,0.000\\,9.933)" in cmd and "between(t\\,9.933\\,24.933)" in cmd
    assert cmd.index("eval=frame") < cmd.index("ass=r01.ass")
    assert re.sub(r"scale=w='[^ ]*?\(ih-1920\)/2,", "", cmd) == plain    # nothing else changes
