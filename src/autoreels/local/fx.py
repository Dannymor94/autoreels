"""M55: attention effects of a clip (Reel.fx) — smooth movement and sound instead of jumps.

* punch     — M103: a fast zoom into a close shot that comes inside a window (shot_transition: punch).
* push      — a slow push-in on every long shot: the frame comes push_pct % closer over the shot
              (scale with per-frame size + centre crop on the final 1080×1920 frame, before the
              subtitles, so the text stays sharp and still). Shots shorter than push_min_sec stay.
* karaoke   — subtitles light up word by word (local/subtitles.build_ass).
* callouts  — a phrase in big letters for a moment ([{"t": source seconds, "text": …}]).
* progress  — a thin bar at the bottom that fills over the clip.
* whoosh    — a soft whoosh under every seam (a finishing pass on the audio; video copied).

Times: the plan works in source seconds; the output clip is the windows (render's final `segs`)
played back to back, speed applied. `output_time` maps one onto the other; `timeline` lists the
seams and the shot changes in output seconds. Pure; `whoosh_cmd`/`whoosh_wav_cmd` only build argv.
"""
from __future__ import annotations

from typing import Sequence


def output_time(windows: Sequence, t_src: float, *, speed: float = 1.0, body0: int = 0) -> float | None:
    """Output seconds of a source moment: the first window from `body0` on that holds it (a cold
    open, window 0, replays a sentence the body also plays — callouts belong to the body). None
    when no window holds it."""
    speed = float(speed or 1.0)
    acc = 0.0
    starts = []
    for w in windows:
        starts.append(acc)
        acc += (w.end - w.start) / speed
    for i in range(body0, len(windows)):
        if windows[i].start - 1e-6 <= t_src < windows[i].end:
            return round(starts[i] + (t_src - windows[i].start) / speed, 3)
    return None


def timeline(windows: Sequence, *, speed: float = 1.0,
             xfades: Sequence[float] | None = None) -> tuple[list[float], list[float], float]:
    """(seams, picture changes, total) in output seconds. Seams: every window boundary that is not a
    filler cut (the cold open → body boundary included). Picture changes: every window boundary
    and the edges of close shots inside windows. `xfades[k]`: the dissolve at boundary k (source
    seconds, as render's concat graph) — the next window starts that much earlier."""
    speed = float(speed or 1.0)
    seams: list[float] = []
    changes: list[float] = []
    acc = 0.0
    for i, w in enumerate(windows):
        dur = (w.end - w.start) / speed
        if i > 0:
            acc -= (float(xfades[i - 1]) if xfades and i - 1 < len(xfades) else 0.0) / speed
            changes.append(acc)
            if not getattr(w, "window_cut", False):
                seams.append(acc)
        for c0, c1 in (getattr(w, "close_intervals", None) or []):
            for x in (c0, c1):
                if 0.05 < x / speed < dur - 0.05:
                    changes.append(acc + x / speed)
        acc += dur
    return [round(x, 3) for x in seams], sorted({round(c, 3) for c in changes}), round(acc, 3)


def plate_start(windows: Sequence, *, speed: float = 1.0, xfades: Sequence[float] | None = None,
                cold_open: bool = False) -> float:
    """M74: output second the plate t: appears at — the start of the body (the first seam, right after the
    cold open) when the clip has a cold open, else 0."""
    if not cold_open or len(windows) < 2:
        return 0.0
    seams = timeline(windows, speed=speed, xfades=xfades)[0]
    return seams[0] if seams else 0.0


def punch_times(windows: Sequence, *, speed: float = 1.0, xfades: Sequence[float] | None = None) -> list[float]:
    """M103: output seconds where the picture goes from the wide to the close shot inside a window — the start of
    every close interval of a wide window (as `timeline` places its edges) — where a punch-in can lead into the
    cut. Window boundaries (seams, filler cuts) are not: a seam is a jump in the source, a filler cut is masked by
    the hard switch itself."""
    speed = float(speed or 1.0)
    out: list[float] = []
    acc = 0.0
    for i, w in enumerate(windows):
        dur = (w.end - w.start) / speed
        if i > 0:
            acc -= (float(xfades[i - 1]) if xfades and i - 1 < len(xfades) else 0.0) / speed
        if getattr(w, "shot", "wide") != "close":
            for c0, _c1 in (getattr(w, "close_intervals", None) or []):
                if 0.05 < c0 / speed < dur - 0.05:
                    out.append(round(acc + c0 / speed, 3))
        acc += dur
    return sorted(set(out))


def punch_point(wide, close) -> tuple[float, float, float] | None:
    """M103: the zoom that turns the wide frame into the close one — (ax, ay, Z): the fixed point as a share of the
    frame (the close rectangle is the wide frame scaled by 1/Z about it) and Z = wide width / close width. None when
    the close rectangle is not inside the wide one or not tighter."""
    if close.w >= wide.w or close.h >= wide.h:
        return None
    if not (wide.x <= close.x and close.x + close.w <= wide.x + wide.w
            and wide.y <= close.y and close.y + close.h <= wide.y + wide.h):
        return None
    ax = (close.x - wide.x) / (wide.w - close.w)
    ay = (close.y - wide.y) / (wide.h - close.h)
    return round(ax, 4), round(ay, 4), round(wide.w / close.w, 4)


def push_vf(changes: Sequence[float], total: float, *, pct: float = 4.0, min_sec: float = 6.0,
            size: tuple[int, int] = (1080, 1920), pop_pct: float = 0.0, pop_sec: float = 0.6,
            punches: Sequence[tuple[float, float, float, float]] = (), punch_sec: float = 0.3,
            fps: float = 30.0) -> str:
    """Filter for a slow push-in on every shot of at least min_sec ('' when none): the zoom grows
    linearly from 1 to 1 + pct/100 over the shot and starts again at 1 on the next shot.
    M70 `pop_pct`: the clip opens that much closer and eases back to the frame over pop_sec (a sharp
    start; added on top of the push).
    M103 `punches` [(t, ax, ay, Z)] (shot_transition: punch): over the punch_sec before a wide → close switch at
    output second t the wide frame zooms (ease-in) towards Z about its fixed point (ax, ay — punch_point), so the
    hard switch at t lands on what the zoom was heading for; the frame at t is the close shot itself (the zoom
    ends half a frame before it). The push of a shot ending in a punch stops where the punch starts, and the punch
    starts from the zoom it reached. A punch that would overlap the pop is left out. No punches — as before."""
    pops = pop_sec if (pop_pct > 0 and pop_sec > 0) else 0.0
    punches = [p for p in punches if p[0] - punch_sec >= pops and p[3] > 1.0] if punch_sec > 0 else []
    ends = {round(float(p[0]), 3) for p in punches}
    pts = [0.0, *sorted(c for c in changes if 0.0 < c < total), total]
    shots = []
    held: set[float] = set()          # punches whose wide shot was pushed in up to the punch: start from there
    if pct > 0:
        for a, b in zip(pts, pts[1:]):
            punch_end = round(b, 3) in ends
            b = b - punch_sec if punch_end else b
            if b - a >= min_sec:
                shots.append((a, b))
                if punch_end:
                    held.add(round(b + punch_sec, 3))
    parts = []
    if shots:
        k = pct / 100.0
        terms = "+".join(f"between(t\\,{a:.3f}\\,{b:.3f})*(t-{a:.3f})/{b - a:.3f}" for a, b in shots)
        parts.append(f"{k:.4f}*({terms})")
    if pops:
        # ease-out: (1 - t/pop_sec)^2 for t < pop_sec, 0 after
        parts.append(f"{pop_pct / 100.0:.4f}*pow(max(0\\,1-t/{pop_sec:.3f})\\,2)")
    ax_terms, ay_terms = [], []
    for t, ax, ay, zz in punches:
        # from the push the shot reached (held) to Z, ease-in; the fixed point moves from the centre (the push's) to
        # the punch's with the same progress — no jump at the start, the close rectangle exactly at the end
        t0, te = float(t) - punch_sec, float(t) - 0.5 / float(fps or 30.0)
        hold = pct / 100.0 if round(float(t), 3) in held else 0.0
        gate = f"gt(t\\,{t0:.3f})*lt(t\\,{te:.3f})"     # open at t0: the push's last frame is not counted twice
        prog = f"pow((t-{t0:.3f})/{punch_sec:.3f}\\,2)"
        parts.append(f"{gate}*({hold:.4f}+{zz - 1.0 - hold:.4f}*{prog})")
        ax_terms.append(f"{gate}*({ax - 0.5:.4f})*{prog}")
        ay_terms.append(f"{gate}*({ay - 0.5:.4f})*{prog}")
    if not parts:
        return ""
    z = "(1+" + "+".join(parts) + ")"
    w, h = size
    sw, sh = f"2*trunc({w}*{z}/2)", f"2*trunc({h}*{z}/2)"
    # M103 fix: the crop's position from the frame size of THIS moment (the scale's own expression). crop keeps the
    # iw/ih of the first frame — with (iw-w)/2 the push zoomed towards the top-left corner (the face drifted down
    # and right over a long shot) and the pop slid up-left while it eased back.
    ax = "0.5" + ("+" + "+".join(ax_terms) if ax_terms else "")
    ay = "0.5" + ("+" + "+".join(ay_terms) if ay_terms else "")
    return (f"scale=w='{sw}':h='{sh}':eval=frame:flags=bicubic,"
            f"crop={w}:{h}:'({sw}-{w})*({ax})':'({sh}-{h})*({ay})'")


def whoosh_wav_cmd(ffmpeg: str, out, *, volume: float = 0.25, dur: float = 0.5) -> list[str]:
    """A soft whoosh: pink noise, band-limited, swelling in and out."""
    half = dur / 2
    return [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", f"anoisesrc=d={dur}:c=pink:a=1.0:r=48000",
            "-af", f"highpass=f=500,lowpass=f=5000,afade=t=in:st=0:d={half},afade=t=out:st={half}:d={half},"
                   f"volume={volume}",
            "-ac", "2", str(out)]


def whoosh_cmd(ffmpeg: str, src, wav, seams: Sequence[float], out, *, dur: float = 0.5,
               audio_bitrate: str = "192k", audio_sec: float | None = None) -> list[str]:
    """The clip with the whoosh mixed under every seam (centred on it); video stream copied, the
    clip length unchanged (amix duration=first, no normalisation of the speech). `audio_sec`: the
    clip's audio length — the re-encoded track is trimmed to it (AAC frames would add ~16 ms and
    break the a/v length check)."""
    n = len(seams)
    parts = [f"[1:a]asplit={n}" + "".join(f"[w{i}]" for i in range(n))] if n > 1 else ["[1:a]anull[w0]"]
    for i, t in enumerate(seams):
        ms = max(0, int(round((t - dur / 2) * 1000)))
        parts.append(f"[w{i}]adelay={ms}|{ms}[d{i}]")
    trim = f",atrim=end={audio_sec:.3f}" if audio_sec else ""
    parts.append("[0:a]" + "".join(f"[d{i}]" for i in range(n))
                 + f"amix=inputs={n + 1}:duration=first:normalize=0{trim}[a]")
    return [ffmpeg, "-v", "error", "-y", "-i", str(src), "-i", str(wav), "-filter_complex", ";".join(parts),
            "-map", "0:v", "-c:v", "copy", "-map", "[a]", "-c:a", "aac", "-b:a", audio_bitrate,
            "-movflags", "+faststart", str(out)]
