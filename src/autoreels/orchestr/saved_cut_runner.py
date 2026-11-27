"""Foreground local runner for the trusted synthetic saved-cut adapter.

Not an HTTP handler or an untrusted process API. Only the fixed synthetic
staged selector is supported. No remote transfer, publish or automatic retry.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

from autoreels.core.models import Manifest
from . import execution, pipeline_gateway, staged_executor
from .pathguard import safe_path
from .saved_cut_export import PREVIEW_SHA256, PreparedCut, _STEM

_GATE = "ui-editor-export"


def _bind(root: Path, job_id: str, plan_sha: str, config_sha: str):
    bound = staged_executor.bind(root, job_id=job_id, target_id="synthetic-desktop",
                                 stem=_STEM, clip="r01", gate=_GATE)
    if bound.request.plan_sha256 != plan_sha or bound.request.config_sha256 != config_sha:
        raise execution.Conflict("saved export binding changed")
    receipt = root / "editor-export.json"
    if not safe_path(root, receipt) or not receipt.is_file() or receipt.stat().st_size > 4096:
        raise execution.Conflict("saved export receipt unavailable")
    info = json.loads(receipt.read_text(encoding="utf-8"))
    if (info["staged_plan_sha256"] != plan_sha or info["config_sha256"] != config_sha
            or info["preview_sha256"] != PREVIEW_SHA256
            or info["audio_binding"] != "silent-aac-v1"):
        raise execution.Conflict("saved export receipt changed")
    plan = root / "reviews" / (_STEM + ".review.json")
    manifest = Manifest.model_validate_json(plan.read_bytes())
    original = root / "preview-original.mp4"
    source = root / "inputs" / (_STEM + ".mp4")
    if (manifest.source != source.name or manifest.source_path
            or manifest.source_sha256 != info["staged_source_sha256"]
            or pipeline_gateway._staged_file_identity(root, original)[0] != PREVIEW_SHA256
            or pipeline_gateway._staged_file_identity(root, source)[0] != manifest.source_sha256
            or len(manifest.reels) != 1 or manifest.reels[0].id != "r01"):
        raise execution.Conflict("saved export media changed")
    return bound, manifest, info


def _validate_mp4(path: Path, expected_duration: float, windows: int,
                  ffmpeg: str, ffprobe: str) -> None:
    meta = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(path)],
                          check=True, capture_output=True, timeout=10)
    streams = json.loads(meta.stdout)["streams"]
    video = [s for s in streams if s["codec_type"] == "video"]
    audio = [s for s in streams if s["codec_type"] == "audio"]
    if len(video) != 1 or len(audio) != 1 or len(streams) != 2:
        raise ValueError("unexpected staged MP4 streams")
    v, a = video[0], audio[0]
    vd, ad = float(v["duration"]), float(a["duration"])
    # The existing 15 fps source permits frame rounding on ordinary hard
    # cuts; bound drift by a conservative frame per window. Exact-rate
    # plans are additionally validated by the authoritative renderer.
    tolerance = max(0.15, windows / 15)
    if (v["codec_name"] != "h264" or a["codec_name"] != "aac"
            or not math.isfinite(vd) or not math.isfinite(ad)
            or vd <= 0 or ad <= 0 or abs(vd - expected_duration) > tolerance
            or abs(vd - ad) > 0.08):
        raise ValueError("invalid staged MP4 duration or codec")
    subprocess.run([ffmpeg, "-v", "error", "-xerror", "-nostdin", "-i", str(path),
                    "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
                   check=True, capture_output=True, timeout=15)


def execute_prepared(prepared: PreparedCut, ledger: execution.Ledger, *,
                     worker_id: str, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
                     timeout_sec: float = 30) -> execution.Job:
    """Claim the exact request, execute its fixed child and validate decoded MP4.

    One attempt; errors leave the existing reservation for reconciliation.
    No publication or arbitrary client arguments. The trusted caller owns
    the isolated workspace and ledger.
    """
    req = prepared.bound.request
    root = prepared.bound.root
    bound, manifest, info = _bind(root, req.job_id, req.plan_sha256, req.config_sha256)
    if (bound != prepared.bound or prepared.preview_sha256 != PREVIEW_SHA256
            or prepared.staged_plan_sha256 != req.plan_sha256
            or prepared.editor_revision != info["editor_revision"]
            or prepared.editor_plan_sha256 != info["editor_plan_sha256"]
            or prepared.staged_source_sha256 != info["staged_source_sha256"]):
        raise execution.Conflict("prepared export changed")
    ffmpeg_bin, ffprobe_bin = shutil.which(ffmpeg), shutil.which(ffprobe)
    if not ffmpeg_bin or not ffprobe_bin:
        raise ValueError("local media tools unavailable")
    if not math.isfinite(timeout_sec) or not 0 < timeout_sec <= 60:
        raise ValueError("invalid synthetic export timeout")
    reel = manifest.reels[0]
    windows = reel.playback_windows()
    duration = sum((s.end-s.start)/rate for s,rate in zip(
        windows,reel.window_rates or [1.0]*len(windows)))
    ledger.submit(req)

    def verify(output):
        _validate_mp4(output, duration, len(windows), ffmpeg_bin, ffprobe_bin)
        if _bind(root, req.job_id, req.plan_sha256, req.config_sha256) != (bound, manifest, info):
            raise execution.Conflict("saved export changed during validation")

    return staged_executor.run_supervised_bound(
        ledger,bound,worker_id=worker_id,clock_ms=lambda:time.monotonic_ns()//1_000_000,
        fixture_argv=(sys.executable,"-m","autoreels.orchestr.saved_cut_runner",
                      str(root),req.job_id,req.plan_sha256,req.config_sha256),
        verify=verify,timeout_sec=timeout_sec)


def _child(root: Path, job_id: str, plan_sha: str, config_sha: str):
    from autoreels import __main__ as cli
    bound, _, _ = _bind(root,job_id,plan_sha,config_sha)
    def forbidden(*args,**kwargs):
        raise RuntimeError("unexpected pull or archive")
    cli._git_pull = forbidden
    cli._archive_video = forbidden
    pipeline_gateway.render_staged_clip(root,stem=_STEM,clip="r01",gate=_GATE,
                                      plan_sha256=bound.request.plan_sha256,
                                      run_render=lambda **kwargs: cli.cmd_render(_allow_short_synthetic=True, **kwargs))


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit("internal synthetic child only")
    _child(Path(sys.argv[1]),*sys.argv[2:])
