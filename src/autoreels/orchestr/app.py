import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from starlette.responses import FileResponse

from .media import media_response, resolve_media_path
from . import clipinfo, manifests, pipeline_gateway, sourcemeta
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
    display_name: str | None  # owner-given name; the folder keeps its stem
    clip_count: int  # distinct clips across main and all variants
    variant_names: list[str]
    poster_clip: str | None  # first clip — its poster is the source thumbnail
    poster_variant: str


class SourceMetaIn(BaseModel):
    display_name: str | None


class SourceMetaOut(BaseModel):
    stem: str
    display_name: str | None


class ClipItem(BaseModel):
    clip: str
    variant: str
    size_bytes: int
    has_render_json: bool
    fingerprint: str | None
    duration_s: float | None
    title: str | None  # title plate (manifest title_overlay) or manifest reel title
    caption: str | None  # first line of r05.txt — publish caption with hashtags


# --- Helpers ---

def _thumbs_dir() -> Path:
    return _cfg.settings.root / "data" / "cache" / "ui" / "thumbs"


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
            # poster: the first clip id, main render if it exists, else its first variant
            first = min(found, key=lambda pv: (pv[0].stem, pv[1] != "", pv[1]))
            items.append(SourceItem(
                stem=stem_dir.name,
                display_name=sourcemeta.display_name(_cfg.settings.root, stem_dir.name),
                clip_count=len({p.stem for p, _ in found}),
                variant_names=sorted({v for _, v in found if v}),
                poster_clip=first[0].stem,
                poster_variant=first[1],
            ))
    return items


def _list_clips(stem: str) -> list[ClipItem]:
    items: list[ClipItem] = []
    found = _iter_clips(stem)  # validates the stem before anything else is read
    titles = manifests.reel_titles(_cfg.settings.root, stem)
    for mp4, variant in found:
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
            duration_s=clipinfo.duration_s(mp4),
            title=titles.get(mp4.stem),
            caption=clipinfo.caption(mp4),
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


@app.get("/api/thumb/{stem}/{clip}")
def thumb(stem: str, clip: str, variant: str = Query(default="")):
    path = resolve_media_path(_cfg.settings.root, stem, clip, variant)
    jpg = clipinfo.poster(path, _thumbs_dir())
    if jpg is None:
        raise HTTPException(status_code=404, detail="poster unavailable")
    return FileResponse(jpg, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@app.put("/api/sources/{stem}/meta", response_model=SourceMetaOut)
def set_source_meta(stem: str, body: SourceMetaIn) -> SourceMetaOut:
    _iter_clips(stem)  # 404 unless stem is a real source
    stored = sourcemeta.set_display_name(_cfg.settings.root, stem, body.display_name)
    return SourceMetaOut(stem=stem, display_name=stored)
