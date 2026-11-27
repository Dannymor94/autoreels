"""Read-only, revision-bound base manifest preview, not rendered-media timing."""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from autoreels.core.models import Manifest
from autoreels.core.playback_timing import build_window_timing

from .pathguard import safe_path

MAX_PLAN_BYTES = 8 * 1024 * 1024
MAX_WINDOWS = 500
MAX_WORDS = 5000
MAX_OCCURRENCES = 10000


class PlanWindow(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    index: int
    kind: str
    source_start: float
    source_end: float
    plan_start: float
    plan_end: float


class PlanWord(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    occurrence_id: str
    window_index: int
    word: str
    source_start: float
    source_end: float
    plan_start: float
    plan_end: float


class ClipPlanView(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    revision_sha256: str
    recorded_source_id: str
    clip_ref: str
    speed: float
    planned_duration_s: float
    windows: list[PlanWindow]
    words: list[PlanWord]


def _signature(st):
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def read_plan(root: Path, stem: str, clip: str) -> ClipPlanView:
    if (not stem or stem in (".", "..") or "/" in stem or "\\" in stem
            or not re.fullmatch(r"r\d{2,3}", clip)):
        raise HTTPException(404, "plan unavailable")
    path = root / "manifests" / (stem + ".json")
    if not safe_path(root, path) or not path.is_file():
        raise HTTPException(404, "plan unavailable")
    try:
        import os
        with path.open("rb") as handle:
            before = _signature(os.fstat(handle.fileno()))
            raw = handle.read(MAX_PLAN_BYTES + 1)
            if (len(raw) > MAX_PLAN_BYTES or len(raw) != before[2]
                    or before != _signature(os.fstat(handle.fileno()))
                    or before != _signature(path.stat())):
                raise ValueError("plan changed or too large")
        manifest = Manifest.model_validate_json(raw)
        if (Path(manifest.source.replace("\\", "/")).stem != stem
                or manifest.source_hash_scheme not in ("full", "partial-p1")
                or not re.fullmatch(r"[0-9a-f]{64}", manifest.source_sha256)):
            raise ValueError("ambiguous source identity")
        matches = [r for r in manifest.reels if r.id == clip]
        if len(matches) != 1:
            raise ValueError("ambiguous clip identity")
        reel = matches[0]
        reel.check_segments()
        speed = reel.speed
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("invalid speed")
        segments = reel.playback_windows()
        if len(segments) > MAX_WINDOWS or len(reel.subtitles) > MAX_WORDS:
            raise ValueError("preview too large")
        if any(not math.isfinite(w.t0) or not math.isfinite(w.t1) for w in reel.subtitles):
            raise ValueError("invalid subtitle times")
        revision = hashlib.sha256(raw).hexdigest()
        clip_ref = hashlib.sha256(("plan-v1:" + revision + ":" + clip).encode()).hexdigest()
        timing = (build_window_timing(segments, reel.window_rates)
                  if reel.window_rates is not None else None)
        windows, words = [], []
        offset = 0.0
        # Same base mapping as local.subtitles.remap_to_output: select by
        # word start, repeat cold-open occurrences, follow playback order.
        # No frame snapping, crossfades, speech-map or render-time changes.
        for i, seg in enumerate(segments):
            if (not math.isfinite(seg.start) or not math.isfinite(seg.end)
                    or seg.start < 0 or seg.end <= seg.start):
                raise ValueError("invalid window")
            duration = seg.end - seg.start
            wtime = timing[i] if timing is not None else None
            windows.append(PlanWindow(index=i, kind="hook" if i == 0 and reel.cold_open else "body",
                source_start=seg.start, source_end=seg.end,
                plan_start=wtime.output_start if wtime is not None else offset / speed,
                plan_end=wtime.output_end if wtime is not None else (offset + duration) / speed))
            for j, w in enumerate(reel.subtitles):
                if seg.start <= w.t0 < seg.end:
                    if len(words) >= MAX_OCCURRENCES:
                        raise ValueError("preview too large")
                    words.append(PlanWord(occurrence_id=f"{clip_ref}:{i}:{j}", window_index=i,
                        word=w.word, source_start=w.t0, source_end=w.t1,
                        plan_start=wtime.to_output(w.t0) if wtime is not None else (w.t0 - seg.start + offset) / speed,
                        plan_end=wtime.to_output(w.t1) if wtime is not None else (w.t1 - seg.start + offset) / speed))
            offset += duration
        return ClipPlanView(revision_sha256=revision,
            recorded_source_id=f"{manifest.source_hash_scheme}:{manifest.source_sha256}",
            clip_ref=clip_ref, speed=speed, planned_duration_s=timing[-1].output_end if timing is not None else offset / speed,
            windows=windows, words=words)
    except (OSError, ValueError, OverflowError):
        raise HTTPException(409, "plan unavailable or ambiguous") from None
