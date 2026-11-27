"""Read-only, allowlisted configured values and explicit dry-run overrides."""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .pathguard import safe_path

Profile = Literal["h264", "hevc", "av1"]
Status = Literal["configured", "missing", "invalid", "blocked"]
PROFILES = ("h264", "hevc", "av1")
_MAX_CONFIG_BYTES = 1024 * 1024


class AnalysisDefaults(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    base_clips: int
    clips_every_min: float
    min_sec: float
    target_sec: float
    max_sec: float
    configured_mode: Literal["autocut", "scenario"]
    label_min_sec: int
    label_max_sec: int


class RenderDefaults(BaseModel):
    width: int
    height: int
    profile: Profile | None
    profiles: list[Profile]
    role: Literal["analyze", "render", "both", "unknown"]
    loudnorm_enabled: bool
    denoise_enabled: bool
    music_enabled: bool


class PipelineSettings(BaseModel):
    schema_version: int
    analysis_status: Status
    analysis: AnalysisDefaults | None
    render_status: Status
    render: RenderDefaults | None
    draft_clips: int | None
    draft_profile: Profile | None
    preview_status: Literal["not_requested", "valid", "blocked"]
    execution_enabled: bool


def _file_status(root: Path, path: Path) -> Status:
    if not safe_path(root, path):
        return "blocked"
    try:
        if not path.exists():
            return "missing"
        if not path.is_file() or path.stat().st_size > _MAX_CONFIG_BYTES:
            return "blocked"
    except OSError:
        return "blocked"
    return "configured"
