"""UI-204B: actual FFmpeg on generated fixtures, no owner media or providers."""
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import yaml

from autoreels.core.models import Crop, Manifest, Reel, SetupProfile, Word
from autoreels.orchestr import execution, staged_executor


def run(*args, binary="ffmpeg"):
    return subprocess.run([binary, *map(str, args)], check=True,
                          capture_output=True, timeout=60).stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stage_config(tmp_path, monkeypatch):
    # This test is intentionally mandatory in its dedicated CI job. Missing
    # tools are failures, not skips. Neither media generation nor render is mocked.
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    assert ffmpeg and ffprobe
    repo = Path(__file__).resolve().parents[2]
    for folder in ("config", "inputs", "reviews"):
        (tmp_path / folder).mkdir()
    for name in ("render.yaml", "subtitles.yaml", "r0.yaml"):
        shutil.copyfile(repo / "config" / name, tmp_path / "config" / name)
    # Test-only fixed features: no speech analysis, facial inference, music,
    # automatic camera work, tail generation or hardware-specific fallback.
    # This tests the legacy trim/crop/scale/subtitle/encode route, not every effect.
    overlay = {
        "ffmpeg": ffmpeg, "role": "both", "scale": [360, 640],
        "encoder": {"preset": "ultrafast"},
        "speech_map": False, "music": {"enabled": False},
        "zoom": {"enabled": False}, "reel_framing": False,
        "close_from_face": False, "framing_source_fallback": False,
        "two_shot": False, "two_shot_auto": False,
        "cover": False, "cover_face": False, "vaapi_soft_retry": False,
        "continue_plate": False, "ending_loop": False, "end_freeze_sec": 0,
        "synthetic_tail_cfg": {"enabled": False},
        "audio_processing": {"dynamic_ending": False, "loudnorm_enabled": False,
                             "denoise_enabled": False, "fade_enabled": False,
                             "tail_video_fade": False},
    }
    (tmp_path / "config" / "render.local.yaml").write_text(
        yaml.safe_dump(overlay), encoding="utf-8")
    subtitle_file = tmp_path / "config" / "subtitles.yaml"
    subtitle_cfg = yaml.safe_load(subtitle_file.read_text(encoding="utf-8"))
    subtitle_cfg.update(font="DejaVu Sans", font_metrics="", fade_in_ms=0, fade_out_ms=0)
    subtitle_file.write_text(yaml.safe_dump(subtitle_cfg), encoding="utf-8")
    for key in ("RENDER_FFMPEG", "RENDER_PROFILE", "RENDER_ENCODER", "RENDER_PALETTE"):
        monkeypatch.delenv(key, raising=False)

    return ffprobe


def test_actual_staged_render(tmp_path, monkeypatch):
    ffprobe = _stage_config(tmp_path, monkeypatch)

    # Moving upper half (freeze detection has a real signal); solid black lower
    # half makes a burned subtitle independently detectable as bright pixels.
    source = tmp_path / "inputs" / "DEMO.mp4"
    run("-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", "testsrc2=size=640x240:rate=30:duration=4",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
        "-vf", "pad=640:480:0:0:black", "-c:v", "libx264", "-threads", "2",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-ar", "48000", "-t", "4", "-movflags", "+faststart", source)
    source_sha = sha(source)
    manifest = Manifest(
        source=source.name, source_sha256=source_sha,
        duration_preset="shorts", run_key="synthetic",
        setup=SetupProfile(setup_id="synthetic", crop=Crop(x=184, y=0, w=270, h=480),
                           frame=[640, 480], scale=[360, 640]),
        reels=[
            Reel(id="r01", start=0.5, end=3.5, score=80, hook="h",
                 title="synthetic", description="synthetic",
                 subtitles=[Word(word="ПРИВЕТ", t0=0.9, t1=2.8)]),
            Reel(id="r02", start=0.0, end=3.0, score=70, hook="h",
                 title="unused", description="unused"),
        ],
    )
    plan = tmp_path / "reviews" / "DEMO.review.json"
    plan.write_text(manifest.model_dump_json(), encoding="utf-8")
    plan_sha = sha(plan)
    config_before = {p.name: sha(p) for p in (tmp_path / "config").iterdir()}

    bound = staged_executor.bind(tmp_path, job_id="fixture-job", target_id="ci-desktop",
                                 stem="DEMO", clip="r01", gate="ui-ffmpeg")
    assert bound.request.plan_sha256 == plan_sha
    observed = {}

    def validate(output):
        assert output == tmp_path / "reels-out/DEMO/_gate/ui-ffmpeg/r01.mp4"
        assert sha(source) == source_sha and sha(plan) == plan_sha
        assert {p.name: sha(p) for p in (tmp_path / "config").iterdir()} == config_before
        assert not (tmp_path / "inputs-archive").exists()
        assert sorted(p.name for p in output.parent.glob("*.mp4")) == ["r01.mp4"]

        info = json.loads(run("-v", "error", "-show_streams", "-show_format",
                              "-of", "json", output, binary=ffprobe))
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
        assert video["codec_name"] == "h264" and audio["codec_name"] == "aac"
        assert (video["width"], video["height"]) == (360, 640)
        vd, ad = float(video["duration"]), float(audio["duration"])
        assert abs(vd - 3.0) <= 0.10
        assert abs(ad - vd) <= 0.05
        # All video and audio packets must decode, not just container metadata.
        run("-v", "error", "-xerror", "-nostdin", "-i", output,
            "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-")
        def bright_pixels(at):
            data = run("-v", "error", "-nostdin", "-ss", str(at), "-i", output,
                       "-frames:v", "1", "-vf", "crop=360:280:0:360,format=gray",
                       "-threads", "1", "-f", "rawvideo", "-")
            assert len(data) == 360 * 280
            return sum(x > 200 for x in data)
        before, during = bright_pixels(0.1), bright_pixels(1.0)
        assert during > before + 50, (before, during)
        observed.update(video=vd, audio=ad, before=before, during=during, sha=sha(output))

    with closing(sqlite3.connect(tmp_path / "fixture-jobs.sqlite")) as db:
        ledger = execution.Ledger(db)
        queued = ledger.submit(bound.request)
        assert queued.status == "queued"
        job = staged_executor.run_supervised_bound(
            ledger, bound, worker_id="ci-worker", clock_ms=lambda: time.monotonic_ns() // 1_000_000,
            fixture_argv=(sys.executable, str(Path(__file__).with_name("staged_fixture_child.py")),
                          str(tmp_path), "DEMO", "r01", "ui-ffmpeg"),
            verify=validate, timeout_sec=30,
        )
        assert job.status == "success" and job.artifact_sha256 == observed["sha"]
        assert ledger.get("fixture-job") == job
        assert ledger.submit(bound.request) == job
    print(f"UI-204B PASS: 360x640 H264/AAC; video={observed['video']:.3f}s "
          f"audio={observed['audio']:.3f}s; full decode; subtitle pixels "
          f"{observed['before']}->{observed['during']}; source/plan/config unchanged; "
          f"artifact_sha256={observed['sha']}; supervised child and ledger success")


def test_static_synthetic_preview_asset():
    # Fixed generated three-second fixture, not user media. Verify the exact
    # bytes, duration and full decoder acceptance once in the existing job.
    path = Path(__file__).resolve().parents[2] / "ui/public/synthetic-editor-preview.mp4"
    assert sha(path) == "c87ea2fffefd6d17905ec71cef3ad94659ff1fbee110fb670aab2ac1e43d3848"
    info = json.loads(run("-v","error","-show_streams","-of","json",path,binary="ffprobe"))
    video, = info["streams"]
    assert video["codec_name"] == "h264"
    assert (video["width"],video["height"],int(video["nb_frames"])) == (96,160,45)
    assert float(video["duration"]) == 3.0
    run("-v","error","-xerror","-nostdin","-i",path,"-f","null","-")


@pytest.mark.parametrize("reorder", [False, True])
def test_render_removed_sentence_audio_is_absent(tmp_path, monkeypatch, reorder):
    """Planner-selected audio cut reaches actual decoded FFmpeg output.

    Three generated audio tones represent distinct artificial sentences.
    No recorded speech or owner footage. Verify the omitted middle tone
    against both retained tones, not merely plan metadata or subtitles.
    """
    import numpy as np
    from autoreels.cloud.plan import ManualPlanParams, build_manual_plan
    from autoreels.orchestr import sentence_edit

    ffprobe = _stage_config(tmp_path, monkeypatch)
    # Disable optional seam dissolves for a measurable hard-cut fixture.
    cfg = tmp_path / "config/render.local.yaml"
    overlay = yaml.safe_load(cfg.read_text())
    overlay.update(same_shot_dissolve_frames=0, two_shot_xfade=False)
    overlay["audio_processing"]["video_xfade_sec"] = 0.0
    cfg.write_text(yaml.safe_dump(overlay), encoding="utf-8")
    source = tmp_path / "inputs/DEMO.mp4"
    tones = (440, 880, 1320)
    args = ["-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "lavfi", "-i", "testsrc2=size=640x240:rate=30:duration=6"]
    for hz in tones:
        args += ["-f", "lavfi", "-i", f"sine=frequency={hz}:sample_rate=48000:duration=1.6"]
    filters = ";".join(
        f"[{i}:a]adelay=200:all=1,apad=pad_dur=0.2[a{i}]" for i in range(1,4)
    ) + ";[a1][a2][a3]concat=n=3:v=0:a=1[a]"
    run(*args, "-filter_complex", filters, "-map", "0:v:0", "-map", "[a]",
        "-vf", "pad=640:480:0:0:black", "-c:v", "libx264", "-threads", "2",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-ar", "48000", "-t", "6", "-movflags", "+faststart", source)
    source_sha = sha(source)

    words = [Word(word=text,t0=i*2.0,t1=i*2.0+1.9)
             for i,text in enumerate(("НАЧАЛО.","УБИРАЕМ.","КОНЕЦ."))]
    sentences = [[w] for w in words]
    smap = {"words":[{"idx":i,"t0":w.t0,"t1":w.t1,"audible_start":i*2.0+0.2,
                      "audible_end":i*2.0+1.8} for i,w in enumerate(words)], "boundaries":[]}
    params = ManualPlanParams()
    order = (1,2,3)
    args = dict(sentences=sentences,words=words,smap=smap,params=params,source_duration=6.0)
    baseline = build_manual_plan(**args,play=order)
    base = Reel(id="r01",start=baseline.start,end=baseline.end,score=80,hook="",
                title="fixture",description="fixture",planned=True,
                segments=[s for w in baseline.body for s in w.segments()],
                subtitles=baseline.subtitles, tail_last_word_end=baseline.last_audible_end,
                tail_next_word_start=baseline.next_onset)
    proposal = sentence_edit.remove_sentences(base,play=order,selected=(2,),**args)
    cut = proposal.plan
    segments = [s for w in cut.body for s in w.segments()]
    assert len(segments)==2 and [w.word for w in cut.subtitles]==["НАЧАЛО.","КОНЕЦ."]
    reel = base.model_copy(update={"start":cut.start,"end":cut.end,
        "segments":segments,"subtitles":cut.subtitles,
        "tail_last_word_end":cut.last_audible_end,"tail_next_word_start":cut.next_onset})
    if reorder:
        reel = sentence_edit.reorder_sentences(reel, play=(1,3), order=(3,1), **args)
        assert [w.word for w in reel.subtitles] == ["КОНЕЦ.","НАЧАЛО."]
    else:
        reel = reel.model_copy(update={"head_first_word_start":0.2,"subtitle_gate":cut.end})
    segments = reel.effective_segments()
    reel.check_segments()
    manifest = Manifest(source=source.name,source_sha256=source_sha,
        duration_preset="shorts",run_key="synthetic-cut",
        setup=SetupProfile(setup_id="synthetic",crop=Crop(x=184,y=0,w=270,h=480),
                           frame=[640,480],scale=[360,640]),reels=[reel])
    plan = tmp_path / "reviews/DEMO.review.json"
    plan.write_text(manifest.model_dump_json(), encoding="utf-8")
    plan_sha = sha(plan)
    expected = sum(s.end-s.start for s in segments)

    def decode(path):
        pcm = run("-v","error","-nostdin","-i",path,"-map","0:a:0",
                  "-ac","1","-ar","48000","-f","s16le","-")
        return np.frombuffer(pcm,dtype="<i2").astype(np.float64)/32768

    def peaks(samples):
        # Integrate energy close to each tone across overlapping 100 ms
        # analysis windows, rather than a single FFT across cut boundaries.
        n = 4800
        win = np.hanning(n)
        bins = [round(hz*n/48000) for hz in tones]
        energy = np.zeros(3)
        for start in range(0,len(samples)-n+1,n//2):
            spec = np.abs(np.fft.rfft(samples[start:start+n]*win))**2
            energy += [float(spec[k-1:k+2].sum()) for k in bins]
        return energy

    source_energy = peaks(decode(source))
    assert min(source_energy)>0.1*max(source_energy), source_energy
    bound = staged_executor.bind(tmp_path,job_id="cut-fixture",target_id="ci-desktop",
                                stem="DEMO",clip="r01",gate="ui-ffmpeg")
    observed={}
    def validate(output):
        info=json.loads(run("-v","error","-show_streams","-of","json",output,binary=ffprobe))
        v=next(s for s in info["streams"] if s["codec_type"]=="video")
        a=next(s for s in info["streams"] if s["codec_type"]=="audio")
        assert v["codec_name"]=="h264" and a["codec_name"]=="aac"
        vd,ad=float(v["duration"]),float(a["duration"])
        assert abs(vd-expected)<=0.15, (vd,expected)
        assert abs(vd-ad)<=0.05, (vd,ad)
        run("-v","error","-xerror","-nostdin","-i",output,"-map","0:v:0","-map","0:a:0","-f","null","-")
        samples=decode(output)
        energy=peaks(samples)
        # Both kept tones must be substantially present. Check the first and
        # last half separately as well, so reorder/duplication cannot pass.
        assert energy[0]>0.25*source_energy[0] and energy[2]>0.25*source_energy[2], energy
        assert energy[1]<0.001*min(energy[0],energy[2]), energy
        first=peaks(samples[:len(samples)//2])
        last=peaks(samples[len(samples)//2:])
        a_idx,b_idx=(2,0) if reorder else (0,2)
        assert first[a_idx]>10*first[b_idx] and last[b_idx]>10*last[a_idx], (first,last)
        assert sha(source)==source_sha and sha(plan)==plan_sha
        assert not (tmp_path/"inputs-archive").exists()
        observed.update(duration=vd,removed_ratio=float(energy[1]/min(energy[0],energy[2])),
                        artifact=sha(output))

    with closing(sqlite3.connect(tmp_path/"cut-jobs.sqlite")) as db:
        ledger=execution.Ledger(db)
        ledger.submit(bound.request)
        job=staged_executor.run_supervised_bound(
            ledger,bound,worker_id="ci-worker",clock_ms=lambda:time.monotonic_ns()//1_000_000,
            fixture_argv=(sys.executable,str(Path(__file__).with_name("staged_fixture_child.py")),
                          str(tmp_path),"DEMO","r01","ui-ffmpeg"),
            verify=validate,timeout_sec=30)
        assert job.status=="success" and job.artifact_sha256==observed["artifact"]
    print(f"UI-402C/303E PASS: reorder={reorder}; cut fixture duration={observed['duration']:.3f}s; "
          f"removed/kept tone energy={observed['removed_ratio']:.8f}; "
          "kept tones in order; A/V decode and ledger success")
