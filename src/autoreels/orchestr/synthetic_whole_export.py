"""Trusted foreground whole-source fixture export, not an HTTP worker."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from autoreels.core.models import Manifest
from . import execution, pipeline_gateway, staged_executor, synthetic_whole
from .pathguard import safe_path
from .saved_cut_runner import _validate_mp4

_STEM = "DEMO"
_GATE = "ui-whole-export"
_RECEIPT = "whole-export.json"
TONES = (330,550,770,990,1210)


@dataclass(frozen=True)
class PreparedWhole:
    editor_revision: int
    editor_plan_sha256: str
    staged_source_sha256: str
    bound: staged_executor.BoundStaged


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def prepare(editor_root: Path, workspace: Path, *, revision: int, digest: str,
            job_id: str, ffmpeg: str = "ffmpeg") -> PreparedWhole:
    """Generate only the fixed fixture in a fresh trusted local workspace."""
    for root in (editor_root,workspace):
        if not root.is_absolute() or not root.is_dir() or root.resolve()!=root:
            raise ValueError("canonical trusted directories required")
    if workspace==editor_root or workspace.is_relative_to(editor_root) or editor_root.is_relative_to(workspace):
        raise ValueError("separate isolated export workspace required")
    head=synthetic_whole.snapshot(editor_root,revision,digest)
    review,choices,_=synthetic_whole.fixture()
    if head.plan_bytes not in choices.values():
        raise ValueError("unsupported whole-source fixture")
    source=workspace/"inputs"/(_STEM+".mp4")
    plan=workspace/"reviews"/(_STEM+".review.json")
    receipt=workspace/_RECEIPT
    for path in (source,plan,receipt,workspace/"reels-out"):
        if not safe_path(workspace,path) or path.exists():
            raise ValueError("export workspace already used or blocked")
    for folder in (source.parent,plan.parent):
        if not safe_path(workspace,folder):
            raise ValueError("blocked staging directory")
        folder.mkdir(exist_ok=True)
    binary=shutil.which(ffmpeg)
    if not binary:
        raise ValueError("FFmpeg unavailable")
    args=[binary,"-v","error","-nostdin","-n","-f","lavfi","-i",
          "testsrc2=size=96x160:rate=30:duration=20"]
    filters=[]
    for i,(hz,row) in enumerate(zip(TONES,review.sentences),1):
        args+=["-f","lavfi","-i",f"sine=frequency={hz}:sample_rate=48000:duration={(row.end_ms-row.start_ms)/1000:.3f}"]
        filters.append(f"[{i}:a]adelay={row.start_ms}:all=1,apad=whole_dur=20[a{i}]")
    filters.append("".join(f"[a{i}]" for i in range(1,6))+"amix=inputs=5:normalize=0[a]")
    subprocess.run([*args,"-filter_complex",";".join(filters),"-map","0:v:0","-map","[a]",
        "-c:v","libx264","-threads","2","-preset","ultrafast","-pix_fmt","yuv420p",
        "-c:a","aac","-t","20",str(source)],check=True,capture_output=True,timeout=30)
    source_sha=pipeline_gateway._staged_file_identity(workspace,source)[0]
    original=head.manifest()
    staged=original.model_copy(update={"source_sha256":source_sha})
    raw=staged.model_dump_json().encode("utf-8")
    if Manifest.model_validate_json(raw).model_copy(update={"source_sha256":original.source_sha256})!=original:
        raise ValueError("staging changed the whole-source plan")
    with plan.open("xb") as handle:
        handle.write(raw)
    bound=staged_executor.bind(workspace,job_id=job_id,target_id="synthetic-desktop",
                               stem=_STEM,clip="r01",gate=_GATE)
    if bound.request.plan_sha256!=_sha(raw):
        raise ValueError("staged whole-source plan changed")
    with receipt.open("x",encoding="utf-8") as handle:
        json.dump({"editor_revision":revision,"editor_plan_sha256":digest,
                   "source_sha256":source_sha,"plan_sha256":bound.request.plan_sha256,
                   "config_sha256":bound.request.config_sha256,
                   "source_kind":"generated-whole-fixture-v1"},handle,sort_keys=True)
    return PreparedWhole(revision,digest,source_sha,bound)


def _bind(root: Path,job_id: str,plan_sha: str,config_sha: str):
    bound=staged_executor.bind(root,job_id=job_id,target_id="synthetic-desktop",
                               stem=_STEM,clip="r01",gate=_GATE)
    if (bound.request.plan_sha256,bound.request.config_sha256)!=(plan_sha,config_sha):
        raise execution.Conflict("whole-source export binding changed")
    receipt=root/_RECEIPT
    if not safe_path(root,receipt) or not receipt.is_file() or receipt.stat().st_size>4096:
        raise execution.Conflict("whole-source receipt unavailable")
    info=json.loads(receipt.read_text(encoding="utf-8"))
    plan=root/"reviews"/(_STEM+".review.json")
    source=root/"inputs"/(_STEM+".mp4")
    manifest=Manifest.model_validate_json(plan.read_bytes())
    original=manifest.model_copy(update={"source_sha256":"c"*64}).model_dump_json().encode("utf-8")
    _,choices,_=synthetic_whole.fixture()
    if (info["source_kind"]!="generated-whole-fixture-v1"
            or info["plan_sha256"]!=plan_sha or info["config_sha256"]!=config_sha
            or info["source_sha256"]!=manifest.source_sha256
            or pipeline_gateway._staged_file_identity(root,source)[0]!=manifest.source_sha256
            or original not in choices.values() or _sha(original)!=info["editor_plan_sha256"]):
        raise execution.Conflict("whole-source export receipt or fixture changed")
    return bound,manifest,info


def execute_prepared(prepared: PreparedWhole,ledger: execution.Ledger,*,worker_id: str,
                     ffmpeg: str="ffmpeg",ffprobe: str="ffprobe") -> execution.Job:
    req=prepared.bound.request
    root=prepared.bound.root
    bound,manifest,info=_bind(root,req.job_id,req.plan_sha256,req.config_sha256)
    if (bound!=prepared.bound or prepared.editor_revision!=info["editor_revision"]
            or prepared.editor_plan_sha256!=info["editor_plan_sha256"]
            or prepared.staged_source_sha256!=info["source_sha256"]):
        raise execution.Conflict("prepared whole-source export changed")
    ffmpeg_bin,ffprobe_bin=shutil.which(ffmpeg),shutil.which(ffprobe)
    if not ffmpeg_bin or not ffprobe_bin:
        raise ValueError("local media tools unavailable")
    reel=manifest.reels[0]
    ledger.submit(req)
    def verify(output):
        _validate_mp4(output,reel.playback_duration(),len(reel.playback_windows()),ffmpeg_bin,ffprobe_bin)
        if _bind(root,req.job_id,req.plan_sha256,req.config_sha256)!=(bound,manifest,info):
            raise execution.Conflict("whole-source export changed during validation")
    return staged_executor.run_supervised_bound(ledger,bound,worker_id=worker_id,
        clock_ms=lambda:time.monotonic_ns()//1_000_000,
        fixture_argv=(sys.executable,"-m","autoreels.orchestr.synthetic_whole_export",
                      str(root),req.job_id,req.plan_sha256,req.config_sha256),
        verify=verify,timeout_sec=60)


def _child(root: Path,job_id: str,plan_sha: str,config_sha: str):
    from autoreels import __main__ as cli
    bound,_,_=_bind(root,job_id,plan_sha,config_sha)
    def forbidden(*args,**kwargs):
        raise RuntimeError("unexpected pull or archive")
    cli._git_pull=forbidden
    cli._archive_video=forbidden
    pipeline_gateway.render_staged_clip(root,stem=_STEM,clip="r01",gate=_GATE,
                                      plan_sha256=bound.request.plan_sha256,run_render=cli.cmd_render)


if __name__=="__main__":
    if len(sys.argv)!=5:
        raise SystemExit("internal synthetic child only")
    _child(Path(sys.argv[1]),*sys.argv[2:])
