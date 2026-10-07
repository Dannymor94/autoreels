import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from starlette.responses import FileResponse

from .media import media_response, resolve_media_path
from . import pipeline_gateway
from . import settings as _cfg  # read _cfg.settings at call time (tests swap it)

app = FastAPI(title="Авто-Рилс UI", version="1")


# --- Response models ---

class HealthResponse(BaseModel):
    status: str
    root: str
    schema_version: int


class CapabilitiesResponse(BaseModel):
    source: str
    verdict_tags: list[str]


class SourceItem(BaseModel):
    stem: str
    clip_count: int
    variant_names: list[str]


class ClipItem(BaseModel):
    clip: str
    variant: str
    size_bytes: int
    has_render_json: bool
    fingerprint: str | None


# --- Helpers ---

def _reels_dir() -> Path:
    return _cfg.settings.root / "reels-out"


def _iter_clips(stem: str) -> list[tuple[Path, str]]:
    """(resolved mp4, variant) for every valid clip of a stem.

    Uses resolve_media_path for EVERY file, so listing obeys exactly the same rules as playback:
    stem whitelist, clip-name regex (skips r01.ERROR.mp4), variant regex, symlink guard.
    Raises HTTPException(404) if the stem itself is not a valid source.
    """
    reels = _reels_dir()
    valid_stems = {d.name for d in reels.iterdir() if d.is_dir()} if reels.exists() else set()
    if stem not in valid_stems:
        raise HTTPException(status_code=404, detail="stem not found")
    stem_dir = reels / stem
    folders: list[tuple[Path, str]] = [(stem_dir, "")]
    gate_dir = stem_dir / "_gate"
    if gate_dir.is_dir():
        folders += [(vd, f"_gate/{vd.name}") for vd in sorted(gate_dir.iterdir()) if vd.is_dir()]
    out: list[tuple[Path, str]] = []
    for folder, variant in folders:
        for mp4 in sorted(folder.glob("r*.mp4")):
            try:
                out.append((resolve_media_path(_cfg.settings.root, stem, mp4.stem, variant), variant))
            except HTTPException:
                continue
    return out


def _list_sources() -> list[SourceItem]:
    reels = _reels_dir()
    if not reels.exists():
        return []
    items = []
    for stem_dir in sorted(reels.iterdir()):
        if not stem_dir.is_dir():
            continue
        found = _iter_clips(stem_dir.name)
        if found:
            items.append(SourceItem(
                stem=stem_dir.name,
                clip_count=sum(1 for _, v in found if v == ""),
                variant_names=sorted({v for _, v in found if v}),
            ))
    return items


def _list_clips(stem: str) -> list[ClipItem]:
    items: list[ClipItem] = []
    for mp4, variant in _iter_clips(stem):
        rj = mp4.with_suffix(".render.json")
        fp = None
        has_rj = rj.exists()
        if has_rj:
            try:
                fp = json.loads(rj.read_text(encoding="utf-8")).get("fingerprint")
            except Exception:
                pass
        items.append(ClipItem(
            clip=mp4.stem,
            variant=variant,
            size_bytes=mp4.stat().st_size,
            has_render_json=has_rj,
            fingerprint=fp,
        ))
    return items


# --- Routes ---

@app.get("/api/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", root=str(_cfg.settings.root), schema_version=1)


@app.get("/api/capabilities", response_model=CapabilitiesResponse)
def capabilities():
    return pipeline_gateway.capabilities()


@app.get("/api/sources", response_model=list[SourceItem])
def sources():
    return _list_sources()


@app.get("/api/sources/{stem}/clips", response_model=list[ClipItem])
def clips(stem: str):
    return _list_clips(stem)


@app.get("/api/media/{stem}/{clip}")
def media(stem: str, clip: str, variant: str = Query(default="")):
    path = resolve_media_path(_cfg.settings.root, stem, clip, variant)
    return media_response(path)
