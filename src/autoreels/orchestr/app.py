import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from starlette.responses import FileResponse

from .media import media_response, resolve_media_path
from . import pipeline_gateway
from .settings import settings

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
    return settings.root / "reels-out"


def _list_sources() -> list[SourceItem]:
    reels = _reels_dir()
    if not reels.exists():
        return []
    items = []
    for stem_dir in sorted(reels.iterdir()):
        if not stem_dir.is_dir():
            continue
        clips = list(stem_dir.glob("r*.mp4"))
        variant_names: list[str] = []
        gate_dir = stem_dir / "_gate"
        if gate_dir.is_dir():
            for vd in sorted(gate_dir.iterdir()):
                if vd.is_dir() and list(vd.glob("r*.mp4")):
                    variant_names.append(f"_gate/{vd.name}")
                    clips.extend(vd.glob("r*.mp4"))
        if clips:
            items.append(SourceItem(
                stem=stem_dir.name,
                clip_count=len(list(stem_dir.glob("r*.mp4"))),
                variant_names=variant_names,
            ))
    return items


def _list_clips(stem: str) -> list[ClipItem]:
    reels = _reels_dir()
    stem_dir = reels / stem
    if not stem_dir.exists():
        raise HTTPException(status_code=404, detail="stem not found")

    items: list[ClipItem] = []

    def _clip_item(mp4: Path, variant: str) -> ClipItem:
        rj = mp4.with_suffix(".render.json")
        fp = None
        has_rj = rj.exists()
        if has_rj:
            try:
                fp = json.loads(rj.read_text()).get("fingerprint")
            except Exception:
                pass
        return ClipItem(
            clip=mp4.stem,
            variant=variant,
            size_bytes=mp4.stat().st_size,
            has_render_json=has_rj,
            fingerprint=fp,
        )

    for mp4 in sorted(stem_dir.glob("r*.mp4")):
        items.append(_clip_item(mp4, ""))

    gate_dir = stem_dir / "_gate"
    if gate_dir.is_dir():
        for vd in sorted(gate_dir.iterdir()):
            if vd.is_dir():
                for mp4 in sorted(vd.glob("r*.mp4")):
                    items.append(_clip_item(mp4, f"_gate/{vd.name}"))

    return items


# --- Routes ---

@app.get("/api/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", root=str(settings.root), schema_version=1)


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
    path = resolve_media_path(settings.root, stem, clip, variant)
    return media_response(path)
