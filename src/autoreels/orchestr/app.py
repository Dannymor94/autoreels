import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from starlette.responses import FileResponse

from .media import media_response, resolve_media_path
from . import catalog, clipinfo, manifests, module_settings, pipeline_gateway, pipeline_settings, plan_view, queue, render_targets, reviews, sourcemeta
from . import settings as _cfg  # read _cfg.settings at call time (tests swap it)
from .security import AccessBoundary
from .pathguard import safe_path

app = FastAPI(title="Авто-Рилс UI", version="1")
app.add_middleware(AccessBoundary)


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


class ProjectItem(SourceItem):
    status: Literal["unprocessed", "draft", "empty", "failed", "ready", "unknown"]
    detail: str
    can_review: bool


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
    root = _cfg.settings.root
    if not safe_path(root, reels):
        raise HTTPException(404, "source unavailable")
    valid_stems = {d.name for d in reels.iterdir() if d.is_dir() and not d.is_symlink()} if reels.is_dir() else set()
    if stem not in valid_stems:
        raise HTTPException(status_code=404, detail="stem not found")
    stem_dir = reels / stem
    folders: list[tuple[Path, str]] = [(stem_dir, "")]
    gate_dir = stem_dir / "_gate"
    if gate_dir.is_dir() and not gate_dir.is_symlink():
        folders += [(vd, f"_gate/{vd.name}") for vd in sorted(gate_dir.iterdir()) if vd.is_dir() and not vd.is_symlink()]
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
    if not safe_path(_cfg.settings.root, reels) or not reels.is_dir():
        return []
    items = []
    for stem_dir in sorted(reels.iterdir()):
        if not stem_dir.is_dir() or stem_dir.is_symlink():
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
        has_rj = rj.is_file() and not rj.is_symlink()
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
    return HealthResponse(status="ok", root="private" if _cfg.settings.private_origin else str(_cfg.settings.root), schema_version=1)


@app.get("/api/capabilities", response_model=CapabilitiesResponse)
def capabilities():
    return pipeline_gateway.capabilities()


@app.get("/api/jobs", response_model=queue.JobInventory)
def jobs():
    s = _cfg.settings
    return queue.inventory(s.root, s.synthetic_jobs)


@app.put("/api/jobs/{job_id}", response_model=queue.SyntheticJob)
def job_command(job_id: str, body: queue.JobCommand):
    s = _cfg.settings
    return queue.command(s.root, s.synthetic_jobs, job_id, body)


@app.get("/api/module-settings", response_model=module_settings.ModuleSettingsView)
def configured_modules(
    hook_rescue: module_settings.Choice | None = Query(default=None),
    filler_cut: module_settings.Choice | None = Query(default=None),
    two_shot: module_settings.Choice | None = Query(default=None),
    loudnorm: module_settings.Choice | None = Query(default=None),
    denoise: module_settings.Choice | None = Query(default=None),
    music: module_settings.Choice | None = Query(default=None),
):
    return pipeline_gateway.module_settings(_cfg.settings.root, {
        "hook_rescue": hook_rescue, "filler_cut": filler_cut, "two_shot": two_shot,
        "loudnorm": loudnorm, "denoise": denoise, "music": music,
    })


@app.get("/api/pipeline-settings", response_model=pipeline_settings.PipelineSettings)
def configured_settings(clips: int | None = Query(default=None, ge=1, le=1000),
                        profile: pipeline_settings.Profile | None = Query(default=None)):
    return pipeline_gateway.pipeline_settings(_cfg.settings.root, clips, profile)


@app.get("/api/render-targets", response_model=render_targets.RenderInventory)
def render_inventory():
    return pipeline_gateway.render_inventory()


@app.get("/api/projects", response_model=list[ProjectItem])
def projects():
    root = _cfg.settings.root
    rendered = [] if _reels_dir().is_symlink() else [item.model_dump() for item in _list_sources()]
    return catalog.list_projects(root, rendered)


@app.get("/api/sources", response_model=list[SourceItem])
def sources():
    return _list_sources()


@app.get("/api/sources/{stem}/clips", response_model=list[ClipItem])
def clips(stem: str):
    return _list_clips(stem)


@app.get("/api/clip-plan/{stem}/{clip}", response_model=plan_view.ClipPlanView)
def clip_plan(stem: str, clip: str):
    return plan_view.read_plan(_cfg.settings.root, stem, clip)


@app.get("/api/comparisons/{stem}/{clip}", response_model=reviews.ComparisonState)
def comparison_state(stem: str, clip: str, left: str, right: str):
    return reviews.compare(_cfg.settings.root, stem, clip, left, right)


@app.put("/api/comparisons/{stem}/{clip}", response_model=reviews.ComparisonState)
def save_comparison(stem: str, clip: str, left: str, right: str, body: reviews.ComparisonInput):
    return reviews.compare(_cfg.settings.root, stem, clip, left, right, body)


@app.get("/api/reviews/{stem}/{clip}", response_model=reviews.ReviewState)
def review_state(stem: str, clip: str, variant: str = Query(default="")):
    root = _cfg.settings.root
    path = resolve_media_path(root, stem, clip, variant)
    return reviews.get_state(root, path, stem, clip, variant)


@app.put("/api/reviews/{stem}/{clip}", response_model=reviews.ReviewState)
def save_review(stem: str, clip: str, body: reviews.ReviewInput, variant: str = Query(default="")):
    root = _cfg.settings.root
    path = resolve_media_path(root, stem, clip, variant)
    return reviews.save(root, path, stem, clip, variant, body)


@app.get("/api/media/{stem}/{clip}")
def media(stem: str, clip: str, request: Request, variant: str = Query(default=""),
          artifact: str | None = Query(default=None)):
    path = resolve_media_path(_cfg.settings.root, stem, clip, variant)
    if artifact is not None:
        return reviews.versioned_media(path, artifact, request)
    return media_response(path)


@app.get("/api/thumb/{stem}/{clip}")
def thumb(stem: str, clip: str, variant: str = Query(default="")):
    path = resolve_media_path(_cfg.settings.root, stem, clip, variant)
    cache = _thumbs_dir()
    if not safe_path(_cfg.settings.root, cache):
        raise HTTPException(404, "poster unavailable")
    jpg = clipinfo.poster(path, cache)
    if jpg is None:
        raise HTTPException(status_code=404, detail="poster unavailable")
    return FileResponse(jpg, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@app.put("/api/sources/{stem}/meta", response_model=SourceMetaOut)
def set_source_meta(stem: str, body: SourceMetaIn) -> SourceMetaOut:
    if not _iter_clips(stem):
        raise HTTPException(404, "source unavailable")
    stored = sourcemeta.set_display_name(_cfg.settings.root, stem, body.display_name)
    return SourceMetaOut(stem=stem, display_name=stored)
