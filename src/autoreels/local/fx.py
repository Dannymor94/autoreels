"""M55: attention effects of a clip (Reel.fx) — smooth movement and sound instead of jumps.

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


def push_vf(changes: Sequence[float], total: float, *, pct: float = 4.0, min_sec: float = 6.0,
            size: tuple[int, int] = (1080, 1920), pop_pct: float = 0.0, pop_sec: float = 0.6) -> str:
    """Filter for a slow push-in on every shot of at least min_sec ('' when none): the zoom grows
    linearly from 1 to 1 + pct/100 over the shot and starts again at 1 on the next shot.
    M70 `pop_pct`: the clip opens that much closer and eases back to the frame over pop_sec (a sharp
    start; added on top of the push)."""
    pts = [0.0, *sorted(c for c in changes if 0.0 < c < total), total]
    shots = [(a, b) for a, b in zip(pts, pts[1:]) if b - a >= min_sec] if pct > 0 else []
    parts = []
    if shots:
        k = pct / 100.0
        terms = "+".join(f"between(t\\,{a:.3f}\\,{b:.3f})*(t-{a:.3f})/{b - a:.3f}" for a, b in shots)
        parts.append(f"{k:.4f}*({terms})")
    if pop_pct > 0 and pop_sec > 0:
        # ease-out: (1 - t/pop_sec)^2 for t < pop_sec, 0 after
        parts.append(f"{pop_pct / 100.0:.4f}*pow(max(0\\,1-t/{pop_sec:.3f})\\,2)")
    if not parts:
        return ""
    z = "(1+" + "+".join(parts) + ")"
    w, h = size
    return (f"scale=w='2*trunc({w}*{z}/2)':h='2*trunc({h}*{z}/2)':eval=frame:flags=bicubic,"
            f"crop={w}:{h}:(iw-{w})/2:(ih-{h})/2")


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
