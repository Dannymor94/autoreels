#!/usr/bin/env python3
"""Verify rendered gate clips against golden expectations.

Usage:
    python scripts/verify_gate.py benchmarks/golden/montage.yaml

Exit code: 1 if any clip FAILs, 0 if all PASS.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "tools"))
sys.path.insert(0, str(PROJECT / "src"))
import flash_check  # noqa: E402
from autoreels.core.seams import is_jump_seam  # noqa: E402

TWO_SHOT_MIN_SEC = 2.5
TWO_SHOT_MIN_MIDDLE_SEC = 4.0
JUMP_SEAM_MIN_SEC = 1.0

_render_cfg_path = PROJECT / "config" / "render.yaml"
_render_cfg = yaml.safe_load(_render_cfg_path.read_text()) if _render_cfg_path.exists() else {}
JUMP_SEAM_GAP_SEC: float = _render_cfg.get("jump_seam_gap_sec", 2.0)
SHOT_TOLERANCE_FRAMES: int = _render_cfg.get("shot_tolerance_frames", 2)
SPEECH_MIN_INTERVAL_SEC: float = _render_cfg.get("speech_min_interval_sec", 0.1)
_DE_AP2 = _render_cfg.get("audio_processing", {})
_DYNAMIC_ENDING: bool = bool(_DE_AP2.get("dynamic_ending", False))
_END_AIR_SEC: float = float(_DE_AP2.get("end_air_sec", 0.30))


# ── ffmpeg helpers ─────────────────────────────────────────────────────────────

def _run(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _probe_duration(path: Path) -> float | None:
    r = _run(["ffprobe", "-v", "quiet", "-print_format", "json",
               "-show_streams", str(path)])
    try:
        for s in json.loads(r.stdout).get("streams", []):
            if s.get("codec_type") == "video":
                return float(s["duration"])
    except (json.JSONDecodeError, KeyError, ValueError):
        pass
    return None


def _volumedetect_mean(path: Path, duration: float = 1.0) -> float | None:
    """Return mean_volume dB for first `duration` seconds. None on failure."""
    r = _run(["ffmpeg", "-i", str(path), "-t", str(duration),
              "-af", "volumedetect", "-f", "null", "-"])
    for line in r.stderr.splitlines():
        if "mean_volume" in line:
            try:
                return float(line.split(":")[1].strip().replace(" dB", ""))
            except ValueError:
                pass
    return None


def _framemd5s(path: Path, ss: float, duration: float) -> list[str]:
    """Return per-frame md5 strings for [ss, ss+duration]."""
    r = _run(["ffmpeg", "-ss", f"{ss:.3f}", "-i", str(path),
              "-t", f"{duration:.3f}", "-f", "framemd5", "-an", "-"])
    out = []
    for line in r.stdout.splitlines():
        if line.startswith("#") or "," not in line:
            continue
        out.append(line.split(",")[-1].strip())
    return out


_DE_AP = _render_cfg.get("audio_processing", {})
_DE_VIDEO_FADE = (_DE_AP.get("dynamic_ending", False)
                  and _DE_AP.get("end_video_fade_sec", 0.0) > 0)


def _last_frame_yavg(mp4: Path) -> float | None:
    """Mean Y luma of the last frame via ffmpeg signalstats. None on failure."""
    r = _run(["ffmpeg", "-sseof", "-0.05", "-i", str(mp4),
              "-frames:v", "1", "-vf", "signalstats", "-f", "null", "-"])
    for line in reversed(r.stderr.splitlines()):
        if "YAVG:" in line:
            for tok in line.split():
                if tok.startswith("YAVG:"):
                    try:
                        return float(tok[5:])
                    except ValueError:
                        pass
    return None


def _check_last_frame_black(mp4: Path) -> list[str]:
    """When dynamic_ending + video fade is on: verify last frame is black (YAVG < 5)."""
    if not _DE_VIDEO_FADE:
        return []
    yavg = _last_frame_yavg(mp4)
    if yavg is None:
        return []  # signalstats unavailable — skip silently
    return [] if yavg < 5.0 else [f"last_frame_not_black(YAVG={yavg:.1f})"]


# ── word helpers ───────────────────────────────────────────────────────────────

def _normalize_words(text: str) -> list[str]:
    """Lowercase, ё→е, strip leading/trailing punctuation, keep hyphens inside words."""
    text = text.lower().replace("ё", "е")
    words = []
    for tok in text.split():
        clean = re.sub(r"[^\w\-]", "", tok, flags=re.UNICODE)
        clean = clean.strip("-")
        if clean:
            words.append(clean)
    return words


# ── shot span helpers ──────────────────────────────────────────────────────────

def _seg_output_ranges(reel: dict,
                       fps: float = flash_check.FPS) -> list[tuple]:
    """Return (out_start_1idx, out_end_1idx, src_start, src_end) per segment."""
    segs = list(reel.get("segments", []))
    co = reel.get("cold_open")
    if co:
        segs = [co] + segs
    ranges = []
    out_frame = 1
    for seg in segs:
        src_start = round(seg["start"] * fps) / fps
        snap_dur = round(seg["end"] * fps) / fps - src_start
        n_frames = round(snap_dur * fps)
        if n_frames <= 0:
            continue
        ranges.append((out_frame, out_frame + n_frames - 1, seg["start"], seg["end"]))
        out_frame += n_frames
    return ranges


def _jump_seam_frames(reel: dict,
                      fps: float = flash_check.FPS,
                      jump_seam_gap: float = JUMP_SEAM_GAP_SEC) -> set[int]:
    """Return 1-indexed frame positions that start a segment after a jump seam."""
    import types
    ranges = _seg_output_ranges(reel, fps)
    result = set()
    for i in range(1, len(ranges)):
        _, _, prev_src_start, prev_src_end = ranges[i - 1]
        out_start, _, src_start, src_end = ranges[i]
        prev_win = types.SimpleNamespace(start=prev_src_start, end=prev_src_end)
        next_win = types.SimpleNamespace(start=src_start, end=src_end)
        if is_jump_seam(prev_win, next_win, jump_seam_gap_sec=jump_seam_gap):
            result.add(out_start)
    return result


def _check_span_violations(runs: list, *, jump_seam_frames: set,
                            fps: float, min_shot: float, min_middle: float,
                            shot_tolerance_frames: int) -> list[str]:
    """Check span floors with tail exemption, jump-seam exemption, frame tolerance.

    Tail exemption: the last run is skipped entirely (same rule as
    flash_check._find_flashes skipping the final run).  A tail is only
    declared when its frame count is below FLASH_THRESH (10 fr); otherwise
    the last run is a real shot and participates in all checks.
    """
    if not runs:
        return []
    fails = []
    tol = shot_tolerance_frames / fps
    last = len(runs) - 1
    last_dur_fr = runs[last][2] - runs[last][1] + 1
    is_tail = last_dur_fr < flash_check.FLASH_THRESH

    for i, (lbl, s, e) in enumerate(runs):
        if is_tail and i == last:
            continue
        dur = (e - s + 1) / fps
        at_jump = any(s <= jf <= e for jf in jump_seam_frames)
        if dur + tol < min_shot and not (at_jump and dur >= JUMP_SEAM_MIN_SEC):
            fails.append(f"short_span:{lbl}_{dur:.2f}s<{min_shot}s")
        # A-B-A: both neighbours must exist and the next must not be the tail
        next_i = i + 1
        next_is_tail = is_tail and next_i == last
        if i > 0 and next_i <= last and not next_is_tail:
            prev_lbl = runs[i - 1][0]
            nxt_lbl = runs[next_i][0]
            if prev_lbl == nxt_lbl and lbl != prev_lbl and dur + tol < min_middle:
                _ljs = s in jump_seam_frames
                _rjs = (e + 1) in jump_seam_frames
                _eff = JUMP_SEAM_MIN_SEC if (_ljs and _rjs) else min_middle
                if dur + tol < _eff:
                    fails.append(f"aba_middle_short:{lbl}_{dur:.2f}s<{_eff}s")
    return fails


# ── per-clip checks ────────────────────────────────────────────────────────────

def _check_words(clip_dir: Path, clip_id: str, expected: dict) -> list[str]:
    txt = clip_dir / f"{clip_id}.transcript.txt"
    if not txt.exists():
        return ["transcript_txt_missing"]
    norm = _normalize_words(txt.read_text(encoding="utf-8"))
    fails = []
    for key, take_end in (("first_words", False), ("last_words", True)):
        exp_raw = expected.get(key, "")
        if not exp_raw:
            continue
        exp_norm = _normalize_words(exp_raw)
        n = len(exp_norm)  # count after normalization: dash tokens stripped to empty
        if not n:
            continue
        got = norm[-n:] if take_end else norm[:n]
        if got != exp_norm:
            fails.append(f"{key}:got='{' '.join(got)}'")
    return fails


def _check_audio_start(mp4: Path) -> list[str]:
    mean = _volumedetect_mean(mp4, 1.0)
    if mean is None:
        return ["volumedetect_failed"]
    if mean <= -45.0:
        return [f"no_audio_start:{mean:.1f}dB"]
    return []


def _check_web_safe(mp4: Path) -> list[str]:
    """Web-safe delivery check (Yandex Disk / social web players), reusing the renderer's
    canonical check.  require_h264=False: a gate clip may legitimately be HEVC (hevc stays an
    option); a non-H.264 video is a printed warning there, not a gate FAIL.  AAC audio, faststart,
    start_time=0, a/v sync and opening audio are hard failures.  Returns verify-style tokens."""
    try:
        from autoreels.local.render import _check_web_safe as _ws
    except ImportError:
        return []  # autoreels not importable (standalone run outside venv) — skip gracefully
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    errors = _ws(mp4, ffmpeg_bin, require_h264=False, fps=flash_check.FPS)
    return [e.replace("[ERROR] web-safe: ", "web_unsafe:") for e in errors]


def _check_foreign_tail_word_vg(speechmap_path: Path, reel: dict, source_end: float) -> list[str]:
    """[ERROR] when next speech onset after the last subtitle word starts before source_end."""
    subs = reel.get("subtitles", [])
    if not subs:
        return []
    if not speechmap_path.exists():
        return []
    last_sub = subs[-1]
    last_t0 = last_sub.get("t0", 0.0)
    last_t1 = last_sub.get("t1")
    with open(speechmap_path) as f:
        sm = json.load(f)
    try:
        from autoreels.local.render import _next_speech_onset_after, _smap_word_lookup
    except ImportError:
        return []
    lk = _smap_word_lookup(sm)
    _nso = _next_speech_onset_after(last_t0, sm, lk, last_t1=last_t1)
    if _nso is None or _nso.onset is None:
        return []
    if _nso.onset < source_end - 0.01:
        return [
            f"foreign_tail_word:onset={_nso.onset:.3f}<end={source_end:.3f}"
        ]
    return []


def _check_end_air_vg(speechmap_path: Path, reel: dict, source_end: float,
                      fps: float = 30.0) -> list[str]:
    """Permanent end-air check: source_end − last subtitle word audible_end ≤ end_air_sec + 1 frame.

    Only runs when dynamic_ending is on in render.yaml.
    """
    if not _DYNAMIC_ENDING:
        return []
    if not speechmap_path.exists():
        return []
    subs = reel.get("subtitles", [])
    if not subs:
        return []
    last_sub = subs[-1]
    with open(speechmap_path) as f:
        sm = json.load(f)
    last_t0 = last_sub.get("t0", 0.0)
    key = round(last_t0 * 1000)
    word = next((w for w in sm.get("words", []) if round(w.get("t0", 0.0) * 1000) == key), None)
    if word is None:
        return []
    ae = word.get("audible_end", last_t0)
    if ae < last_t0:
        return []
    tolerance = _END_AIR_SEC + 1.0 / fps
    air = source_end - ae
    if air > tolerance + 1e-4:
        return [f"end_air:{air:.3f}s>{tolerance:.3f}s(ae={ae:.3f},end={source_end:.3f})"]
    return []


def _check_tail_silence(speechmap_path: Path, reel_end: float,
                        own_tail_window_sec: float = 0.05) -> list[str]:
    """Fail if speech starts after the clip's last word + a small grace window.

    Own-word rule: an interval whose start is before
    max(last_audible_end, last_word_t1) + own_tail_window_sec belongs to the
    last word (Whisper's declared t1 span) and is exempt.
    """
    if not speechmap_path.exists():
        return [f"speechmap_missing:{speechmap_path.name}"]
    with open(speechmap_path) as f:
        sm = json.load(f)
    words_in_clip = [w for w in sm.get("words", []) if w.get("t0", 0.0) <= reel_end]
    last_audible_end = max(
        (w.get("audible_end", w.get("t0", 0.0)) for w in words_in_clip),
        default=0.0,
    )
    last_word_t1 = words_in_clip[-1].get("t1", last_audible_end) if words_in_clip else 0.0
    threshold = max(last_audible_end, last_word_t1) + own_tail_window_sec
    for ivl in sm.get("intervals", []):
        s, e = ivl[0], ivl[1]
        if e - s < SPEECH_MIN_INTERVAL_SEC:
            continue
        if threshold < s < reel_end:
            return [f"speech_in_tail:[{s:.2f},{e:.2f}]"]
    return []


def _check_tail_frames(mp4: Path, clip_duration: float) -> list[str]:
    """Verify tail integrity via framemd5.

    Identical frames → synthetic tail (expected, pass).
    Mixed frames → natural motion (expected, pass).
    Single hash repeated >80% but not 100% → suspect freeze artifact → fail.
    """
    window = 0.5
    hashes = _framemd5s(mp4, max(0.0, clip_duration - window), window)
    if len(hashes) < 3:
        return []  # too short to judge
    unique = set(hashes)
    if len(unique) <= 1:
        return []  # fully frozen synthetic tail — ok
    if len(unique) == 2:
        dominant = max(hashes.count(h) for h in unique)
        if dominant / len(hashes) > 0.80:
            return ["tail_frames_suspect_freeze"]
    return []


PLAN_SHOT_TOL_FRAMES = 3   # frames around a planned shot change / window start not judged


def _find_source(manifest: dict, src_dirs: list) -> "Path | None":
    """Source video for a manifest: recorded source_path, else the source file name in src_dirs."""
    rec = manifest.get("source_path") or ""
    if rec and Path(rec).is_file():
        return Path(rec)
    name = Path(manifest.get("source", "")).name
    for d in src_dirs:
        if name and (Path(d) / name).is_file():
            return Path(d) / name
    return None


def _planned_expected(seg: dict, n_frames: int, fps: float) -> list[str]:
    """Expected shot per output frame of one planned window (shot + window-relative close_intervals)."""
    base = seg.get("shot") or "wide"
    ci = seg.get("close_intervals") or []
    out = []
    for k in range(n_frames):
        t = (k + 0.5) / fps
        out.append("close" if base == "close" or any(a <= t < b for a, b in ci) else "wide")
    return out


def _check_planned_shots(mp4: Path, manifest: dict, reel: dict, src: Path,
                         fps: float = flash_check.FPS) -> list[str]:
    """REEL_SPEC §7.2 for planned reels: every judged frame shows the shot the plan says.

    Frames are classified against the source (flash_check), window by window; ambiguous frames and
    frames within PLAN_SHOT_TOL_FRAMES of a window start or a planned shot change are not judged.
    Span floors of the automatic path (2.5 s / 4 s) do not apply: REEL_SPEC §3.5.
    """
    setup = manifest.get("setup", {})
    wide_vf = flash_check._wide_vf(setup)
    close_vf = flash_check._close_vf(setup)
    segs = ([reel["cold_open"]] if reel.get("cold_open") else []) + list(reel.get("segments", []))
    durs = [flash_check._snap(sg["end"]) - flash_check._snap(sg["start"]) for sg in segs]
    file_dur = _probe_duration(mp4)
    # Seam transitions overlap neighbouring windows in the output: spread the measured shortfall
    # evenly over the seams so each window is read at its real output position.
    n_seams = max(0, len([d for d in durs if d > 0]) - 1)
    overlap = ((sum(d for d in durs if d > 0) - file_dur) / n_seams
               if (file_dur is not None and n_seams) else 0.0)
    overlap = max(0.0, overlap)
    # The closing fade to black is not a shot: frames in it are not judged.
    fade = float(_DE_AP2.get("end_video_fade_sec", 0.25)) if _DYNAMIC_ENDING else 0.0
    judge_until = (file_dur - fade - PLAN_SHOT_TOL_FRAMES / fps) if file_dur is not None else None
    fails = []
    out_t = 0.0
    judged = 0
    for i, (seg, dur) in enumerate(zip(segs, durs), 1):
        src_start = flash_check._snap(seg["start"])
        if dur <= 0:
            continue
        # Both sides resampled to the checker's fps, so a 25/60 fps clip is compared frame-to-frame.
        rendered = flash_check._frames(mp4, out_t, dur, "null", force_fps=True)
        sw = flash_check._frames(src, src_start, dur, wide_vf, force_fps=True)
        sc = flash_check._frames(src, src_start, dur, close_vf, force_fps=True)
        got = flash_check._classify(rendered, sw, sc)
        judged += sum(1 for g in got if g != "ambig")
        exp = _planned_expected(seg, len(got), fps)
        changes = {0, len(exp)} | {k for k in range(1, len(exp)) if exp[k] != exp[k - 1]}
        bad = [k for k, (g, e) in enumerate(zip(got, exp))
               if g != "ambig" and g != e
               and all(abs(k - c) > PLAN_SHOT_TOL_FRAMES for c in changes)
               and (judge_until is None or out_t + k / fps < judge_until)]
        if bad:
            fails.append(f"plan_shot_mismatch:window{i}:{len(bad)}fr(first@{out_t + bad[0] / fps:.2f}s)")
        out_t += dur - overlap
    if judged == 0:
        # Nothing could be told apart (no frames read, or every frame ambiguous): not a pass.
        fails.append("plan_shots_unjudged:0fr")
    return fails


ALIGN_TAIL_MAX_SEC = 0.30   # sound right after the aligned end may still be the word (plan.py _TAIL_MAX)


def _check_end_aligned(align_path: Path, reel: dict, source_end: float) -> list[str]:
    """Planned reels with transcripts/<stem>.align.json: judge the clip end by the AUDIO alignment
    (independent of Whisper times and of the plan code):
      - the last word is heard to its aligned end;
      - no next transcribed word starts before the clip end;
      - no untranscribed speech («ммм», «ну») starts between aligned end + 0.30 s and the clip end.
    """
    if not reel.get("planned") or not align_path.exists():
        return []
    try:
        al = json.loads(align_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["align_unreadable"]
    subs = reel.get("subtitles", [])
    if not subs:
        return []
    words = {round(w["t0"] * 1000): w for w in al.get("words", []) if w.get("start") is not None}
    hit = sum(1 for w in subs if round(w["t0"] * 1000) in words)
    if hit < 0.9 * len(subs):
        return [f"alignment_mismatch:{hit}/{len(subs)}"]
    last = words.get(round(subs[-1]["t0"] * 1000))
    if last is None:
        return ["last_word_not_aligned"]
    fails = []
    ae = float(last["end"])
    if source_end < ae - 0.02:
        fails.append(f"last_word_cut_aligned:end={source_end:.3f}<ae={ae:.3f}")
    nxt = [w for w in words.values() if w["start"] > ae + 1e-3]
    if nxt:
        ns = min(float(w["start"]) for w in nxt)
        if ns < source_end - 0.03:
            fails.append(f"next_word_in_clip:{ns:.3f}<end={source_end:.3f}")
    for a, b in al.get("untranscribed", []):
        if ae + ALIGN_TAIL_MAX_SEC <= a < source_end - 0.03:
            fails.append(f"untranscribed_speech_in_tail:{a:.3f}<end={source_end:.3f}")
            break
    return fails


def _check_shots(mp4: Path, manifest_path: Path, reel_id: str,
                 src_dir: Path) -> list[str]:
    """Check two-shot spans via flash_check.check_reel. Skips if source not found.

    Planned reels (REEL_SPEC) are checked frame by frame against their plan instead.
    """
    if not manifest_path.exists():
        return []
    try:
        manifest = json.load(open(manifest_path))
    except json.JSONDecodeError as exc:
        return [f"manifest_corrupt:{exc}"]

    _reel_p = next((r for r in manifest.get("reels", []) if r["id"] == reel_id), None)
    if _reel_p is not None and _reel_p.get("planned"):
        src_p = _find_source(manifest, [src_dir, src_dir.parent / "inputs"])
        if src_p is None:
            return ["plan_shots_unchecked:source_not_found"]
        return _check_planned_shots(mp4, manifest, _reel_p, src_p)

    setup = manifest.get("setup", {})
    stem = setup.get("setup_id", "")
    src = next(
        (src_dir / f"{stem}{ext}"
         for ext in (".mp4", ".MP4", ".mov")
         if (src_dir / f"{stem}{ext}").exists()),
        None,
    )
    if src is None:
        return []

    reel = next((r for r in manifest.get("reels", []) if r["id"] == reel_id), None)
    if reel is None:
        return [f"reel_{reel_id}_not_in_manifest"]

    wide_vf = flash_check._wide_vf(setup)
    close_vf = flash_check._close_vf(setup)
    labels, flashes = flash_check.check_reel(reel, mp4, src, wide_vf, close_vf)

    fails = []
    if flashes:
        fails.append(f"shot_flash:{len(flashes)}")

    runs = flash_check._runs([l for l in labels if l != "ambig"])
    js_frames = _jump_seam_frames(reel)
    fails.extend(_check_span_violations(
        runs,
        jump_seam_frames=js_frames,
        fps=flash_check.FPS,
        min_shot=TWO_SHOT_MIN_SEC,
        min_middle=TWO_SHOT_MIN_MIDDLE_SEC,
        shot_tolerance_frames=SHOT_TOLERANCE_FRAMES,
    ))
    return fails


# ── main ───────────────────────────────────────────────────────────────────────

def check_clip(entry: dict, project: Path) -> list[str]:
    clip_id = entry["clip_id"]
    stem = entry["stem"]
    clip_path = project / entry["path"]
    clip_dir = clip_path.parent
    reel_end = float(entry["reel_end"])
    speechmap = project / "transcripts" / f"{stem}.speechmap.json"
    manifest_path = project / "manifests" / f"{stem}.json"
    src_dir = project / "inputs-archive"

    if not clip_path.exists():
        return ["clip_missing"]

    # Read source_start / source_end from the renderer's sidecar (required; no fallback).
    render_json_path = clip_dir / f"{clip_id}.render.json"
    source_start = None
    source_end = None
    if render_json_path.exists():
        try:
            rd = json.loads(render_json_path.read_text(encoding="utf-8"))
            if "source_end" in rd:
                source_end = float(rd["source_end"])
            if "source_start" in rd:
                source_start = float(rd["source_start"])
        except (json.JSONDecodeError, ValueError, KeyError):
            pass

    fails = []

    if (clip_dir / f"{clip_id}.ERROR.mp4").exists():
        fails.append("error_mp4_present")

    fails.extend(_check_words(clip_dir, clip_id, entry))
    fails.extend(_check_audio_start(clip_path))
    fails.extend(_check_web_safe(clip_path))
    if source_end is None:
        fails.append("render_end_missing")
    else:
        fails.extend(_check_tail_silence(speechmap, source_end))
        if manifest_path.exists():
            try:
                _mf = json.loads(manifest_path.read_text(encoding="utf-8"))
                _reel = next((r for r in _mf.get("reels", []) if r["id"] == clip_id), None)
                if _reel is not None:
                    # REEL_SPEC §4.2 lower bound (planned reels): the file never ends before the
                    # last word's audible end as the plan resolved it.
                    _ae_p = _reel.get("tail_last_word_end") if _reel.get("planned") else None
                    if _ae_p is not None and source_end < float(_ae_p) - 0.002:
                        fails.append(f"last_word_cut:end={source_end:.3f}<ae={float(_ae_p):.3f}")
                    fails.extend(_check_end_air_vg(speechmap, _reel, source_end))
                    fails.extend(_check_end_aligned(project / "transcripts" / f"{stem}.align.json",
                                                    _reel, source_end))
                    fails.extend(_check_foreign_tail_word_vg(speechmap, _reel, source_end))
            except (json.JSONDecodeError, KeyError):
                pass

    duration = _probe_duration(clip_path)
    if duration is not None:
        fails.extend(_check_tail_frames(clip_path, duration))

    fails.extend(_check_shots(clip_path, manifest_path, clip_id, src_dir))
    fails.extend(_check_last_frame_black(clip_path))

    return fails


def main(yaml_path: str, project: Path = PROJECT) -> int:
    data = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8"))
    clips = data["clips"]

    rows = []
    for entry in clips:
        label = f"{entry['stem']}/{entry['clip_id']}"
        fails = check_clip(entry, project)
        status = "PASS" if not fails else "FAIL"
        rows.append((label, status, fails))

    col = max(len(r[0]) for r in rows)
    print(f"{'clip':<{col}}  status  failing checks")
    print("-" * (col + 40))
    for label, status, fails in rows:
        fail_str = ", ".join(fails) if fails else ""
        print(f"{label:<{col}}  {status:<6}  {fail_str}")

    any_fail = any(r[1] == "FAIL" for r in rows)
    return 1 if any_fail else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <golden.yaml>", file=sys.stderr)
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
