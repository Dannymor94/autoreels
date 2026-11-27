import re
from pathlib import Path

from fastapi import HTTPException
from starlette.responses import FileResponse

from .pathguard import safe_path

_CLIP_RE = re.compile(r"r\d{2,3}")
_VARIANT_RE = re.compile(r"_gate/[A-Za-z0-9_.+-]+")


def resolve_media_path(root: Path, stem: str, clip: str, variant: str) -> Path:
    reels = root / "reels-out"
    if not stem or stem in (".", "..") or "/" in stem or "\\" in stem:
        raise HTTPException(404, "invalid source")
    if not _CLIP_RE.fullmatch(clip):
        raise HTTPException(404, "invalid clip")
    if variant and (not _VARIANT_RE.fullmatch(variant) or variant.split("/")[-1] in (".", "..")):
        raise HTTPException(404, "invalid variant")
    path = reels / stem / variant / f"{clip}.mp4"
    if not safe_path(root, path) or not path.is_file():
        raise HTTPException(404, "file unavailable")
    return path


def media_response(path: Path) -> FileResponse:
    return FileResponse(path, media_type="video/mp4", headers={"Accept-Ranges": "bytes"})
