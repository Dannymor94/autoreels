import re
from pathlib import Path

from fastapi import HTTPException
from starlette.responses import FileResponse

_CLIP_RE = re.compile(r"^r\d{2,3}$")
_VARIANT_RE = re.compile(r"^_gate/[A-Za-z0-9_.+-]+$")


def resolve_media_path(root: Path, stem: str, clip: str, variant: str) -> Path:
    reels = root / "reels-out"

    valid_stems = {d.name for d in reels.iterdir() if d.is_dir()} if reels.exists() else set()
    if stem not in valid_stems:
        raise HTTPException(status_code=404, detail="stem not found")

    if not _CLIP_RE.match(clip):
        raise HTTPException(status_code=404, detail="invalid clip")

    if variant != "" and not _VARIANT_RE.match(variant):
        raise HTTPException(status_code=404, detail="invalid variant")

    if variant:
        path = reels / stem / variant / f"{clip}.mp4"
    else:
        path = reels / stem / f"{clip}.mp4"

    resolved = path.resolve()

    # symlink guard: resolved path must still be inside reels-out
    if not resolved.is_relative_to(reels.resolve()):
        raise HTTPException(status_code=404, detail="path outside root")

    if not resolved.exists():
        raise HTTPException(status_code=404, detail="file not found")

    return resolved


def media_response(path: Path) -> FileResponse:
    # Starlette FileResponse handles Range natively (verified starlette>=0.20)
    return FileResponse(path, media_type="video/mp4", headers={"Accept-Ranges": "bytes"})
