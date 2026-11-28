"""UI-204B: actual FFmpeg on generated fixtures, no owner media or providers."""
import hashlib
import json
import shutil
import sqlite3

import pytest
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


@pytest.mark.parametrize("reorder,trim,rated", [(False, False, False), (True, False, False), (True, True, False), (True, False, True)])
def test_render_removed_sentence_audio_is_absent(tmp_path, monkeypatch, reorder, trim, rated):
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
    params = ManualPlanParams(seam_pad_sec=0.15) if trim else ManualPlanParams()
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
        if trim:
            before = reel.playback_duration()
            old = reel.effective_segments()[0]
            reel = sentence_edit.trim_silence(reel, play=(3,1), segment_index=0,
                                             start=max(old.start,4.125),
                                             end=min(old.end,5.875), **args)
            assert reel.playback_duration() < before - 0.10
            assert [w.word for w in reel.subtitles] == ["КОНЕЦ.","НАЧАЛО."]
    else:
        reel = reel.model_copy(update={"head_first_word_start":0.2,"subtitle_gate":cut.end})
    if rated:
        # Exact source/output frame grid, inside the verified 200 ms silence.
        segments = [s.model_copy(update={"start":st,"end":en})
                    for s,(st,en) in zip(reel.effective_segments(),[(4.1,5.9),(0.1,1.9)])]
        reel = reel.model_copy(update={"start":segments[0].start,"end":segments[-1].end,
            "segments":segments,"window_rates":[0.5,2.0]})
    segments = reel.effective_segments()
    reel.check_segments()
    manifest = Manifest(source=source.name,source_sha256=source_sha,
        duration_preset="shorts",run_key="synthetic-cut",
        setup=SetupProfile(setup_id="synthetic",crop=Crop(x=184,y=0,w=270,h=480),
                           frame=[640,480],scale=[360,640]),reels=[reel])
    plan = tmp_path / "reviews/DEMO.review.json"
    plan.write_text(manifest.model_dump_json(), encoding="utf-8")
    plan_sha = sha(plan)
    expected = sum((s.end-s.start)/rate for s,rate in zip(segments,reel.window_rates or [1]*len(segments)))

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
        split=round((segments[0].end-segments[0].start)/(reel.window_rates[0] if rated else 1)*48000) if rated else len(samples)//2
        first=peaks(samples[:split])
        last=peaks(samples[split:])
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
    print(f"UI-402D/402C/303E PASS: reorder={reorder}, trim={trim}, rated={rated}; cut fixture duration={observed['duration']:.3f}s; "
          f"removed/kept tone energy={observed['removed_ratio']:.8f}; "
          "kept tones in order; A/V decode and ledger success")


def test_variable_speed_ffmpeg_hard_cut_primitive(tmp_path):
    """Actual FFmpeg experiment, not yet a production-renderer integration."""
    import numpy as np
    from autoreels.core.models import Segment
    from autoreels.core.playback_timing import build_window_timing
    from autoreels.local.subtitles import remap_to_output

    windows=[Segment(start=2,end=4),Segment(start=0,end=2)]
    rates=(0.5,2.0)
    timing=build_window_timing(windows,rates)
    words=[Word(word="A",t0=0.5,t1=1),Word(word="B",t0=2.5,t1=3)]
    cues=remap_to_output(words,windows,window_rates=rates)
    assert [(w.word,w.t0,w.t1) for w in cues]==[("B",1,2),("A",4.25,4.5)]
    out=tmp_path/"variable-speed.mp4"
    filters=["[0:v]split=2[v0][v1]",
             "[1:a][2:a]concat=n=2:v=0:a=1[a]",
             "[a]asplit=2[a0][a1]"]
    for w in timing:
        i=w.index
        duration=w.output_end-w.output_start
        filters.extend([
            f"[v{i}]trim=start={w.source_start}:end={w.source_end},setpts=(PTS-STARTPTS)/{w.rate},"
            f"fps=30,tpad=stop_mode=clone:stop_duration=0.1,trim=duration={duration},setpts=PTS-STARTPTS[vo{i}]",
            f"[a{i}]atrim=start={w.source_start}:end={w.source_end},asetpts=PTS-STARTPTS,"
            f"atempo={w.rate},apad=pad_dur=0.1,atrim=duration={duration},asetpts=PTS-STARTPTS[ao{i}]",
        ])
    filters.append("[vo0][ao0][vo1][ao1]concat=n=2:v=1:a=1[vout][aout]")
    run("-hide_banner","-loglevel","error","-nostdin",
        "-f","lavfi","-i","testsrc2=size=160x96:rate=30:duration=4",
        "-f","lavfi","-i","sine=frequency=440:sample_rate=48000:duration=2",
        "-f","lavfi","-i","sine=frequency=880:sample_rate=48000:duration=2",
        "-filter_complex",";".join(filters),"-map","[vout]","-map","[aout]",
        "-c:v","libx264","-threads","2","-pix_fmt","yuv420p","-c:a","aac",out)
    info=json.loads(run("-v","error","-show_streams","-of","json",out,binary="ffprobe"))
    v=next(s for s in info["streams"] if s["codec_type"]=="video")
    a=next(s for s in info["streams"] if s["codec_type"]=="audio")
    vd,ad=float(v["duration"]),float(a["duration"])
    assert abs(vd-timing[-1].output_end)<=0.08
    assert abs(ad-vd)<=0.05
    run("-v","error","-xerror","-nostdin","-i",out,"-f","null","-")
    pcm=np.frombuffer(run("-v","error","-nostdin","-i",out,"-map","0:a:0",
                          "-ac","1","-ar","48000","-f","s16le","-"),dtype="<i2").astype(np.float64)
    def energy(at,hz):
        n=4800
        data=pcm[round(at*48000):round(at*48000)+n]
        assert len(data)==n
        fft=np.abs(np.fft.rfft(data*np.hanning(n)))**2
        k=round(hz*n/48000)
        return float(fft[k-1:k+2].sum())
    for at,hz,other in [(0.5,880,440),(3.5,880,440),(4.5,440,880)]:
        assert energy(at,hz)>100*max(energy(at,other),1)
    print(f"UI-403A PASS: independent 0.5x/2x hard-cut primitive, video={vd:.3f}s audio={ad:.3f}s; pitch/order preserved")


def test_framed_render_uses_saved_source_rectangle(tmp_path, monkeypatch):
    """Actual renderer, fixed synthetic regions; verify position as well as output size."""
    import numpy as np
    from autoreels.core.config import load_render_config
    from autoreels.local.render import render_crop

    ffprobe = _stage_config(tmp_path, monkeypatch)
    source = tmp_path / "inputs" / "FRAME.mp4"
    run("-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", "testsrc2=size=96x160:rate=30:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
        "-vf", "drawbox=x=0:y=0:w=24:h=160:color=red:t=fill,drawbox=x=72:y=0:w=24:h=160:color=blue:t=fill",
        "-c:v", "libx264", "-threads", "2", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-t", "3", source)
    original = sha(source)
    base = Manifest(source=source.name, source_sha256=original,
        duration_preset="shorts", run_key="frame-fixture",
        setup=SetupProfile(setup_id="synthetic", crop=Crop(x=0,y=0,w=96,h=160),
                           frame=[96,160], scale=[360,640]),
        reels=[Reel(id="r01",start=0,end=3,score=80,hook="",title="",description="")])
    cfg=load_render_config(tmp_path/"config/render.yaml",local_path=tmp_path/"config/render.local.yaml")
    for name,x in (("left",0),("right",36)):
        setup=base.setup.model_copy(update={"crop":Crop(x=x,y=30,w=60,h=100)})
        manifest=base.model_copy(update={"setup":setup})
        manifest=Manifest.model_validate_json(manifest.model_dump_json())
        outputs=render_crop(manifest,inputs_dir=tmp_path/"inputs",out_dir=tmp_path/name,
                            render_cfg=cfg,encoder="libx264",zoom=False)
        assert len(outputs)==1
        path=outputs[0]
        info=json.loads(run("-v","error","-show_streams","-of","json",path,binary=ffprobe))
        v=next(s for s in info["streams"] if s["codec_type"]=="video")
        assert (v["width"],v["height"])==(360,640)
        raw=run("-v","error","-ss","1","-i",path,"-frames:v","1","-pix_fmt","rgb24",
                "-threads","1","-f","rawvideo","-")
        rgb=np.frombuffer(raw,dtype=np.uint8).reshape(640,360,3).astype(float)
        patch=rgb[80:240,:60] if name=="left" else rgb[80:240,-60:]
        mean=patch.mean(axis=(0,1))
        assert (mean[0]-mean[2] if name=="left" else mean[2]-mean[0])>80, mean
    assert sha(source)==original
    assert base.setup.crop.model_dump()==dict(x=0,y=0,w=96,h=160)


@pytest.mark.parametrize("dip,kind", [(None,"none"),(200,"solid"),(200,"image"),(200,"video")])
def test_bound_soundtrack_mixes_with_retimed_speech(tmp_path, monkeypatch, dip, kind):
    import numpy as np
    from autoreels.core.models import AudioAsset, BackgroundTrack, GraphicLayer, ImageAsset, Segment, VideoAsset
    from autoreels.core.config import load_render_config
    from autoreels.local.assets import resolve_audio_asset
    from autoreels.local.render import render_crop

    ffprobe=_stage_config(tmp_path,monkeypatch)
    cfg_path=tmp_path/"config/render.local.yaml"
    overlay=yaml.safe_load(cfg_path.read_text())
    overlay.update(same_shot_dissolve_frames=0,two_shot_xfade=False)
    overlay["audio_processing"]["video_xfade_sec"]=0
    cfg_path.write_text(yaml.safe_dump(overlay))
    cfg=load_render_config(tmp_path/"config/render.yaml",local_path=cfg_path)
    source=tmp_path/"inputs/DEMO.mp4"
    run("-hide_banner","-loglevel","error","-nostdin",
        "-f","lavfi","-i","testsrc2=size=96x160:rate=30:duration=5",
        "-f","lavfi","-i","sine=frequency=440:sample_rate=48000:duration=5",
        "-c:v","libx264","-threads","2","-pix_fmt","yuv420p","-c:a","aac","-t","5",source)
    assets=tmp_path/"assets"
    assets.mkdir()
    wav=assets/"tone.wav"
    run("-hide_banner","-loglevel","error","-nostdin","-f","lavfi","-i",
        "sine=frequency=880:sample_rate=48000:duration=1","-c:a","pcm_s16le",wav)
    asset=AudioAsset(sha256=sha(wav),label="Synthetic tone",rights="synthetic",rights_note="generated in CI")
    path=assets/(asset.sha256+".wav")
    wav.rename(path)
    assert resolve_audio_asset(assets,asset)==path
    track=BackgroundTrack(asset=asset,volume=0.25,fade_seconds=0.0,ducking=False,final_normalize=False)
    image = video = None
    if kind == "image":
        png = assets/"test.png"
        run("-v","error","-f","lavfi","-i","color=red:s=36x64",
            "-vf","drawbox=x=18:y=0:w=18:h=64:color=blue:t=fill",
            "-frames:v","1","-threads","1",png)
        image = ImageAsset(sha256=sha(png),label="Two color still",width=36,height=64,
                           rights="synthetic",rights_note="generated in CI")
        image_path = assets/(image.sha256+".png")
        png.rename(image_path)
    if kind == "video":
        clip = assets/"test.mp4"
        run("-v","error","-f","lavfi","-i","color=red:s=36x64:r=30:d=0.5",
            "-f","lavfi","-i","color=blue:s=36x64:r=30:d=0.5",
            "-filter_complex","[0:v][1:v]concat=n=2:v=1:a=0[v]","-map","[v]",
            "-c:v","libx264","-threads","2","-pix_fmt","yuv420p",clip)
        video=VideoAsset(sha256=sha(clip),label="Two color video",width=36,height=64,
                         duration_ms=1000,rights="synthetic",rights_note="generated in CI")
        video_path=assets/(video.sha256+".mp4")
        clip.rename(video_path)
        with pytest.raises(ValueError):
            GraphicLayer(x_pct=10,y_pct=10,width_pct=20,height_pct=20,
                         start_ms=1000,end_ms=2100,video=video)
    graphic = GraphicLayer(x_pct=10,y_pct=10,width_pct=20,height_pct=20,
                           start_ms=1000,end_ms=2000,color=None if image or video else "white",
                           image=image,video=video) if dip else None
    if image:
        with pytest.raises(ValueError):
            GraphicLayer(x_pct=10,y_pct=10,width_pct=20,height_pct=20,
                         start_ms=1000,end_ms=2000,color="white",image=image)
    reel=Reel(id="r01",start=0,end=5,score=80,hook="",title="",description="",
              planned=True,segments=[Segment(start=0,end=2),Segment(start=3,end=5)],
              window_rates=[0.5,2.0],background_track=track,seam_dip_ms=dip,graphic_layer=graphic)
    manifest=Manifest(source=source.name,source_sha256=sha(source),duration_preset="shorts",run_key="music-fixture",
        setup=SetupProfile(setup_id="synthetic",crop=Crop(x=0,y=0,w=96,h=160),
                           frame=[96,160],scale=[360,640]),reels=[reel])
    if graphic:
        from autoreels.__main__ import _reel_render_fingerprint
        def fingerprint(r):
            return _reel_render_fingerprint(r,setup=manifest.setup,palette="neutral",
                                            profile="h264",zoom_on=False,music_path=None)
        assert fingerprint(reel)!=fingerprint(reel.model_copy(update={"graphic_layer":None}))
        assert fingerprint(reel)!=fingerprint(reel.model_copy(
            update={"graphic_layer":graphic.model_copy(update={"start_ms":1100})}))
    plan=tmp_path/"reviews/DEMO.review.json"
    plan.write_text(manifest.model_dump_json())
    bound=staged_executor.bind(tmp_path,job_id="music",target_id="local",stem="DEMO",clip="r01",gate="ui-ffmpeg")
    observed={}
    def verify(output):
        info=json.loads(run("-v","error","-show_streams","-of","json",output,binary=ffprobe))
        v=next(s for s in info["streams"] if s["codec_type"]=="video")
        a=next(s for s in info["streams"] if s["codec_type"]=="audio")
        assert abs(float(v["duration"])-5.0)<=0.08
        assert abs(float(a["duration"])-float(v["duration"]))<=0.05
        pcm=np.frombuffer(run("-v","error","-i",output,"-map","0:a:0","-ac","1","-ar","48000",
                              "-f","s16le","-"),dtype="<i2").astype(float)
        for t in (0.5,1.2,1.7,2.5,4.4):
            chunk=pcm[round(t*48000):round(t*48000)+4800]
            assert len(chunk)==4800
            spec=np.abs(np.fft.rfft(chunk*np.hanning(4800)))**2
            voice=spec[43:46].sum()
            music=spec[87:90].sum()
            assert 0.01 < music/voice < 0.2,(t,voice,music)
        if dip:
            def brightness(t):
                frame=run("-v","error","-ss",str(t),"-i",output,"-frames:v","1",
                          "-vf","format=gray","-threads","1","-f","rawvideo","-")
                assert len(frame)==360*640
                return float(np.frombuffer(frame,dtype=np.uint8).mean())
            assert brightness(3.5)>35 and brightness(4.5)>35
            assert brightness(4.0)<25
        if graphic:
            def white_share(t):
                frame=run("-v","error","-ss",str(t),"-i",output,"-frames:v","1",
                          "-pix_fmt","rgb24","-threads","1","-f","rawvideo","-")
                rgb=np.frombuffer(frame,dtype=np.uint8).reshape(640,360,3)
                # Inner rectangle, away from chroma interpolation at its edges.
                if image:
                    left=rgb[72:184,42:64].astype(float)
                    right=rgb[72:184,80:102].astype(float)
                    return min(float((left[:,:,0]-left[:,:,2]>120).mean()),
                               float((right[:,:,2]-right[:,:,0]>120).mean()))
                patch=rgb[72:184,42:102].astype(float)
                if video:
                    return (float((patch[:,:,0]-patch[:,:,2]>120).mean()),
                            float((patch[:,:,2]-patch[:,:,0]>120).mean()))
                return float(np.all(patch>230,axis=2).mean())
            if video:
                assert white_share(1.2)[0]>0.95
                assert white_share(1.7)[1]>0.95
                assert max(white_share(0.5))<0.9 and max(white_share(2.5))<0.9
            else:
                assert white_share(1.5)>0.95
                assert white_share(0.5)<0.5 and white_share(2.5)<0.5
        observed["sha"]=sha(output)
    with closing(sqlite3.connect(tmp_path/"music-jobs.sqlite")) as db:
        ledger=execution.Ledger(db)
        ledger.submit(bound.request)
        job=staged_executor.run_supervised_bound(ledger,bound,worker_id="ci-worker",
            clock_ms=lambda:time.monotonic_ns()//1_000_000,
            fixture_argv=(sys.executable,str(Path(__file__).with_name("staged_fixture_child.py")),
                          str(tmp_path),"DEMO","r01","ui-ffmpeg"),verify=verify,timeout_sec=30)
        assert job.status=="success" and job.artifact_sha256==observed["sha"]
    if image:
        original_image=image_path.read_bytes()
        image_path.write_bytes(original_image+b"changed")
        with pytest.raises(ValueError):
            staged_executor.bind(tmp_path,job_id="music",target_id="local",stem="DEMO",clip="r01",gate="ui-ffmpeg")
        image_path.write_bytes(original_image)
    if video:
        original_video=video_path.read_bytes()
        video_path.write_bytes(original_video+b"changed")
        with pytest.raises(ValueError):
            staged_executor.bind(tmp_path,job_id="music",target_id="local",stem="DEMO",clip="r01",gate="ui-ffmpeg")
        video_path.write_bytes(original_video)
    old=path.read_bytes()
    path.write_bytes(old+b"changed")
    with pytest.raises(ValueError):
        staged_executor.bind(tmp_path,job_id="music",target_id="local",stem="DEMO",clip="r01",gate="ui-ffmpeg")
    path.unlink()
    replacement=assets/"replacement.wav"
    replacement.write_bytes(old)
    path.symlink_to(replacement)
    with pytest.raises(ValueError):
        resolve_audio_asset(assets,asset)
    print(f"UI-501/502/503A PASS: dip={dip}; exact soundtrack asset, retained tones, loop, A/V sync, stale and symlink rejection")


@pytest.mark.parametrize("with_broll", [False, True])
def test_export_exact_saved_editor_revision(tmp_path, monkeypatch, with_broll):
    """Actual editor command -> immutable snapshot -> existing staged renderer."""
    from autoreels.orchestr import saved_cut_export, saved_cut_runner, synthetic_cut, editor_revisions
    editor=tmp_path/"editor"
    editor.mkdir()
    stage=tmp_path/"stage"
    stage.mkdir()
    ffprobe=_stage_config(stage,monkeypatch)
    cfg=stage/"config/render.local.yaml"
    overlay=yaml.safe_load(cfg.read_text())
    overlay.update(same_shot_dissolve_frames=0,two_shot_xfade=False)
    overlay["audio_processing"]["video_xfade_sec"]=0.0
    cfg.write_text(yaml.safe_dump(overlay),encoding="utf-8")
    public=Path(__file__).resolve().parents[2]/"ui/public"
    assert sha(public/"synthetic-editor-preview.mp4")==saved_cut_export.PREVIEW_SHA256

    def choose(view,target,op_id):
        return synthetic_cut.command(editor,True,synthetic_cut.CutCommand(
            op_id=op_id,base_revision=view.revision,base_plan_sha256=view.plan_sha256,
            clip_uid=view.clip_uid,candidate_plan_sha256=target.plan_sha256,
            removed=target.removed,order=target.order if target.order!=sorted(target.order) else None,
            crop=target.crop,trim=target.trim,rates=target.rates,music=target.music,dip_ms=target.dip_ms,graphic=target.graphic))

    view=synthetic_cut.view(editor,True)
    base=next(p for p in view.plans if p.plan_sha256==view.plan_sha256)
    cut=next(p for p in view.plans if p.removed==[2] and p.order==[3,1]
             and not p.rates and not p.trim and not p.music and not p.crop)
    view=choose(view,cut,"export-reorder")
    framed=next(p for p in view.plans if p.removed==[2] and p.order==[3,1]
                and p.crop==[18,30,60,100] and not p.rates and not p.trim and not p.music)
    view=choose(view,framed,"export-frame")
    music=next(p for p in view.plans if p.removed==[2] and p.order==[3,1]
               and p.crop==framed.crop and p.music==[1,20,0,0] and not p.rates and not p.trim)
    view=choose(view,music,"export-music")
    dip=next(p for p in view.plans if p.dip_ms==200 and p.music==music.music
             and p.crop==framed.crop and p.order==[3,1] and p.removed==[2]
             and not p.rates and not p.trim)
    view=choose(view,dip,"export-transition")
    from autoreels.orchestr.synthetic_image import IMAGE, IMAGE_NAME
    assert sha(public/IMAGE_NAME)==IMAGE.sha256
    from autoreels.orchestr.synthetic_video import VIDEO, VIDEO_NAME
    assert sha(public/VIDEO_NAME)==VIDEO.sha256
    code=[10,10,25,25,0,1000,4] if with_broll else [10,10,25,25,0,500,3]
    graphic=next(p for p in view.plans if p.graphic==code)
    view=choose(view,graphic,"export-graphic")
    assert synthetic_cut.view(editor,True)==view
    db_path=editor/".ui-synthetic-editor.sqlite3"
    db_before=sha(db_path)
    with pytest.raises(editor_revisions.Conflict):
        saved_cut_export.prepare_saved_cut(editor,stage,public,revision=0,
            plan_sha256=base.plan_sha256,job_id="stale")
    assert not (stage/"preview-original.mp4").exists()
    prepared=saved_cut_export.prepare_saved_cut(editor,stage,public,revision=view.revision,
        plan_sha256=view.plan_sha256,job_id="saved-cut-export")
    assert prepared.editor_plan_sha256==view.plan_sha256
    assert prepared.editor_revision==5
    assert sha(db_path)==db_before
    plan=stage/"reviews/SYNTHETIC_CUT.review.json"
    manifest=Manifest.model_validate_json(plan.read_bytes())
    assert manifest.source_sha256==prepared.staged_source_sha256
    assert manifest.setup.crop.model_dump()==dict(x=18,y=30,w=60,h=100)
    reel=manifest.reels[0]
    assert [w.word for w in reel.subtitles]==["Продолжение.","Начало."]
    assert reel.background_track.volume==0.2 and reel.seam_dip_ms==200
    assert reel.graphic_layer.color is None
    if with_broll:
        assert reel.graphic_layer.video==VIDEO
        assert sha(stage/"assets"/(VIDEO.sha256+".mp4"))==VIDEO.sha256
    else:
        assert reel.graphic_layer.image==IMAGE
        assert sha(stage/"assets"/(IMAGE.sha256+".png"))==IMAGE.sha256
    assert sha(plan)==prepared.staged_plan_sha256
    with pytest.raises(ValueError):
        saved_cut_export.prepare_saved_cut(editor,stage,public,revision=view.revision,
            plan_sha256=view.plan_sha256,job_id="duplicate")

    with closing(sqlite3.connect(stage/"saved-cut-jobs.sqlite")) as db:
        ledger=execution.Ledger(db)
        job=saved_cut_runner.execute_prepared(prepared,ledger,worker_id="ci-worker",ffprobe=ffprobe)
        output=stage/"reels-out/SYNTHETIC_CUT/_gate/ui-editor-export/r01.mp4"
        assert job.status=="success" and job.artifact_sha256==sha(output)
        pcm=run("-v","error","-nostdin","-i",output,"-map","0:a:0","-ac","1","-ar","48000","-f","s16le","-")
        assert any(pcm),"selected background track must be audible"
        import numpy as np
        frame=run("-v","error","-ss","0.2","-i",output,"-frames:v","1",
                  "-vf","scale=360:640","-pix_fmt","rgb24","-threads","1","-f","rawvideo","-")
        rgb=np.frombuffer(frame,dtype=np.uint8).reshape(640,360,3)
        left=rgb[80:200,45:65].astype(float)
        # At native 96x160, scaling and 4:2:0 edge chroma spread across
        # several comparison pixels. Sample the interior, not the letterbox edge.
        right=rgb[80:200,90:105].astype(float)
        assert (left[:,:,0]-left[:,:,2]>120).mean()>0.9
        if with_broll:
            assert (right[:,:,0]-right[:,:,2]>120).mean()>0.9
            frame=run("-v","error","-ss","0.7","-i",output,"-frames:v","1",
                      "-vf","scale=360:640","-pix_fmt","rgb24","-threads","1","-f","rawvideo","-")
            patch=np.frombuffer(frame,dtype=np.uint8).reshape(640,360,3)[80:200,55:100].astype(float)
            assert (patch[:,:,2]-patch[:,:,0]>120).mean()>0.9
        else:
            assert (right[:,:,2]-right[:,:,0]>120).mean()>0.9
        assert ledger.get("saved-cut-export")==job
    assert not (stage/"inputs-archive").exists()
    assert sha(db_path)==db_before
    assert synthetic_cut.view(editor,True)==view
    assert sha(plan)==prepared.staged_plan_sha256
    assert sha(public/"synthetic-editor-preview.mp4")==prepared.preview_sha256
    print("UI-504A PASS: saved revision 5, cut+reorder+crop+music+dip+graphic -> actual decoded MP4; editor unchanged")

def test_whole_source_saved_revision_actual_export(tmp_path,monkeypatch):
    """20-second source, two nonadjacent confirmed removals, real A/V output."""
    import numpy as np
    from autoreels.orchestr import synthetic_whole as whole, synthetic_whole_export as exporter
    editor=tmp_path/"editor"
    editor.mkdir()
    stage=tmp_path/"stage"
    stage.mkdir()
    ffprobe=_stage_config(stage,monkeypatch)
    cfg=stage/"config/render.local.yaml"
    overlay=yaml.safe_load(cfg.read_text())
    overlay.update(same_shot_dissolve_frames=0,two_shot_xfade=False)
    overlay["audio_processing"]["video_xfade_sec"]=0.0
    cfg.write_text(yaml.safe_dump(overlay),encoding="utf-8")
    initial=whole.view(editor,True)
    target=next(p for p in initial.plans if p.removed==[2,4])
    state=whole.command(editor,True,whole.WholeCommand(op_id="whole-export",base_revision=0,
        base_plan_sha256=initial.plan_sha256,clip_uid=initial.clip_uid,
        candidate_plan_sha256=target.plan_sha256,removed=[2,4]))
    original=whole.snapshot(editor,state.revision,state.plan_sha256).manifest()
    db_path=editor/".ui-synthetic-editor.sqlite3"
    db_before=sha(db_path)
    with pytest.raises(whole.revisions.Conflict):
        exporter.prepare(editor,stage,revision=0,digest=initial.plan_sha256,job_id="stale")
    assert not (stage/"inputs/DEMO.mp4").exists()
    from fastapi.testclient import TestClient
    from autoreels.orchestr import settings
    from autoreels.orchestr.settings import Settings
    from autoreels.orchestr.app import app
    monkeypatch.setattr(settings,"settings",Settings(root=editor,synthetic_editor=True,synthetic_export_workspace=stage))
    client=TestClient(app,base_url="http://127.0.0.1:8765")
    endpoint="/api/synthetic-whole-export"
    assert client.get(endpoint).json()["status"]=="ready"
    assert client.put(endpoint,json={"revision":0,"plan_sha256":initial.plan_sha256}).status_code==409
    assert client.get(endpoint).json()["status"]=="ready"
    body={"revision":state.revision,"plan_sha256":state.plan_sha256}
    response=client.put(endpoint,json=body)
    assert response.status_code==200,response.text
    result=response.json()
    assert result["status"]=="success" and result["editor_revision"]==state.revision
    assert client.put(endpoint,json=body).json()==result
    assert client.get(endpoint).json()==result
    source=stage/"inputs/DEMO.mp4"
    source_digest=sha(source)
    plan=stage/"reviews/DEMO.review.json"
    plan_digest=sha(plan)
    assert Manifest.model_validate_json(plan.read_bytes()).model_copy(
        update={"source_sha256":original.source_sha256})==original
    tones=exporter.TONES
    observed={}
    def energy(path):
        pcm=run("-v","error","-i",path,"-map","0:a:0","-ac","1","-ar","48000","-f","s16le","-")
        samples=np.frombuffer(pcm,dtype="<i2").astype(float)
        result=np.zeros(5)
        window=np.hanning(4800)
        for offset in range(0,len(samples)-4799,2400):
            spectrum=np.abs(np.fft.rfft(samples[offset:offset+4800]*window))**2
            result += [spectrum[round(hz/10)-1:round(hz/10)+2].sum() for hz in tones]
        return result
    reference=energy(source)
    def validate(output):
        info=json.loads(run("-v","error","-show_streams","-of","json",output,binary=ffprobe))
        v=next(s for s in info["streams"] if s["codec_type"]=="video")
        a=next(s for s in info["streams"] if s["codec_type"]=="audio")
        assert abs(float(v["duration"])-target.duration)<0.15
        assert abs(float(v["duration"])-float(a["duration"]))<0.05
        run("-v","error","-xerror","-i",output,"-f","null","-")
        actual=energy(output)
        assert all(actual[i]>0.25*reference[i] for i in (0,2,4))
        assert max(actual[1],actual[3])<0.001*min(actual[0],actual[2],actual[4])
        assert sha(source)==source_digest and sha(plan)==plan_digest
        observed["sha"]=sha(output)
    output=stage/"reels-out/DEMO/_gate/ui-whole-export/r01.mp4"
    validate(output)
    assert result["artifact_sha256"]==observed["sha"]
    download=client.get(endpoint+"/media")
    assert download.status_code==200 and download.content==output.read_bytes()
    assert client.put(endpoint,json={"revision":0,"plan_sha256":initial.plan_sha256}).status_code==409
    assert sha(db_path)==db_before and whole.view(editor,True)==state
    assert not (stage/"inputs-archive").exists()
    print(f"UI-504G PASS: 20s -> {target.duration:.3f}s; two confirmed removals, retained tones and immutable saved revision")
