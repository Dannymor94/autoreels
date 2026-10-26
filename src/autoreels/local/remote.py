"""M161: render on another machine over ssh (gamebox, RX 580 → h264_vaapi) and bring the clips back.

The Mac stays the machine of record: the code, the review copy, the transcripts and the source live here. One call
sends the rest a render needs (tracked code, the review.json, transcripts/<stem>.*, the cached transcript of the
source — without it the remote render falls back to a coarse seam check and reports false «seam inside word» errors,
m158/m160 — the face model, the music track and, only when the remote cannot find it by content, the source), runs
`arl render` there under the shared gamebox lock with the remote's encoder and profile, and copies
reels-out/<stem>/_gate/<gate>/ back. HEVC on the RX 580 breaks long clips (CABAC errors, green blocks — m160), so the
remote encoder is H.264 (config/render.yaml `remote:`).

`run` (argv, **kw) → CompletedProcess is the injection point for tests: no ssh, no rsync.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Callable


class RemoteRenderError(RuntimeError):
    """A step of the remote render failed; the message names the step."""


def transcript_cache_files(cache_dir: Path, source_sha256: str) -> list[Path]:
    """The cached transcripts of this source (data/cache/*.transcript.json stamped with its sha256)."""
    out: list[Path] = []
    if not source_sha256 or not Path(cache_dir).is_dir():
        return out
    for p in sorted(Path(cache_dir).glob("*.transcript.json")):
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("source_sha256") == source_sha256:
                out.append(p)
        except (OSError, ValueError):
            continue
    return out


def data_files(root: Path, review: Path, stem: str, source_sha256: str, music: str | None = None) -> list[str]:
    """Paths relative to `root` that a render of this review needs besides the tracked code."""
    rel = [str(review.resolve().relative_to(root.resolve()))]
    rel += sorted(str(p.relative_to(root)) for p in (root / "transcripts").glob(f"{_glob_escape(stem)}.*") if p.is_file())
    rel += [str(p.relative_to(root)) for p in transcript_cache_files(root / "data" / "cache", source_sha256)]
    if (root / "data" / "models").is_dir():
        rel.append("data/models")
    if music:
        m = root / "music" / music
        if m.is_file():
            rel.append(str(m.relative_to(root)))
    return rel


def _glob_escape(s: str) -> str:
    return "".join(f"[{c}]" if c in "*?[" else c for c in s)


def remote_render_cmd(cfg, review_rel: str, *, reels: str, gate: str, music: str | None = None) -> str:
    """The shell line run on the remote: arl render under the shared lock with the remote encoder and profile."""
    argv = [".venv/bin/python", "-m", "autoreels", "render", "--manifest", review_rel, "--reels", reels,
            "--gate", gate, "--encoder", cfg.encoder, "--profile", cfg.profile]
    if music:
        argv += ["--music", music]
    line = " ".join(shlex.quote(a) for a in argv)
    if cfg.lock:
        line = f"flock {shlex.quote(cfg.lock)} {line}"
    return f"cd {shlex.quote(cfg.root)} && {line}"


def render_remote(cfg, *, root: Path, review: Path, stem: str, source_sha256: str, local_source: Path | None,
                  reels: str, gate: str, music: str | None = None, run: Callable | None = None,
                  log: Callable[[str], None] = print) -> Path:
    """Send, render there, bring back. Returns the local gate folder. Raises RemoteRenderError naming the step."""
    run = run or (lambda argv, **kw: subprocess.run(argv, **kw))
    host, rroot = cfg.host, cfg.root.rstrip("/")
    root = Path(root)

    def step(name: str, argv: list[str], **kw):
        r = run(argv, **kw)
        if getattr(r, "returncode", 1) != 0:
            err = (getattr(r, "stderr", "") or "").strip().splitlines()[-3:]
            raise RemoteRenderError(f"{name}: код {getattr(r, 'returncode', '?')}" + (f" — {' | '.join(err)}" if err else ""))
        return r

    log(f"  удалённый рендер: {host}:{rroot} ({cfg.encoder}, профиль {cfg.profile})")
    step("ssh", ["ssh", host, f"test -x {shlex.quote(rroot)}/.venv/bin/python && echo ok"],
         capture_output=True, text=True)
    # 1. tracked code (same version as here)
    files = step("git ls-files", ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, text=True).stdout
    with tempfile.NamedTemporaryFile("w", suffix=".files", delete=False, encoding="utf-8") as fh:
        fh.write(files.replace("\0", "\n"))
        flist = fh.name
    step("код", ["rsync", "-a", f"--files-from={flist}", f"{root}/", f"{host}:{rroot}/"], capture_output=True, text=True)
    # 2. the render's data (relative paths keep the layout; names with spaces travel inside the protocol)
    rel = data_files(root, review, stem, source_sha256, music)
    step("данные", ["rsync", "-aR", *rel, f"{host}:{rroot}/"], capture_output=True, text=True, cwd=str(root))
    log(f"  отправлено: код, {len(rel)} путей данных")
    # 3. the source — only when the remote cannot find it by content
    review_rel = rel[0]
    probe = (f"cd {shlex.quote(rroot)} && .venv/bin/python -c "
             + shlex.quote("import sys; from pathlib import Path; from autoreels.core.models import Manifest; "
                           "from autoreels.local.render import resolve_source; "
                           f"m = Manifest.model_validate_json(Path({review_rel!r}).read_text(encoding='utf-8')); "
                           "print(resolve_source(m, 'inputs'))"))
    r = run(["ssh", host, probe], capture_output=True, text=True)
    if getattr(r, "returncode", 1) != 0:
        if local_source is None or not Path(local_source).is_file():
            raise RemoteRenderError("исходник: нет ни там, ни здесь")
        log(f"  исходник: копирую {Path(local_source).name} …")
        step("исходник", ["rsync", "-a", "--partial", str(local_source), f"{host}:{rroot}/inputs/"])
    # 4. render there (output streams to this terminal)
    step("рендер", ["ssh", host, remote_render_cmd(cfg, review_rel, reels=reels, gate=gate, music=music)])
    # 5. clips back (tar over ssh: the stem may contain spaces)
    local_gate = root / "reels-out" / stem / "_gate" / gate
    local_gate.mkdir(parents=True, exist_ok=True)
    pull = (f"ssh {shlex.quote(host)} "
            + shlex.quote(f"cd {shlex.quote(rroot + '/reels-out/' + stem + '/_gate/' + gate)} && tar -cf - .")
            + f" | tar -xf - -C {shlex.quote(str(local_gate))}")
    step("назад", ["sh", "-c", pull], capture_output=True, text=True)
    log(f"  клипы здесь: {local_gate}")
    return local_gate
