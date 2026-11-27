"""UI-203A: immutable, allowlisted preview. Never modifies accepted edits."""
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PresetName = Literal["shorts", "reels", "tiktok"]
Stage = Literal["selection", "plan", "render"]


class PresetValues(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    duration_preset: PresetName
    hook_rescue: bool
    filler_word_cut: bool
    zoom: bool
    loudnorm: bool
    denoise: bool
    two_shot: bool
    two_shot_auto: bool


class PresetLayer(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    duration_preset: PresetName | None = None
    hook_rescue: bool | None = None
    filler_word_cut: bool | None = None
    zoom: bool | None = None
    loudnorm: bool | None = None
    denoise: bool | None = None
    two_shot: bool | None = None
    two_shot_auto: bool | None = None


class DurationChoice(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    name: PresetName
    min_sec: int = Field(gt=0)
    max_sec: int = Field(gt=0)


class PresetRequest(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    base_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    global_layer: PresetLayer
    project_layer: PresetLayer
    clip_layer: PresetLayer


class PresetPreview(BaseModel):
    schema_version: int
    base_revision: str
    base: PresetValues
    effective: PresetValues
    presets: list[DurationChoice]
    changed_fields: list[str]
    invalidates: list[Stage]
    two_shot_auto_active: bool
    execution_enabled: bool


class StalePreview(ValueError):
    pass


def preview(base: PresetValues, choices: list[DurationChoice],
            request: PresetRequest | None = None) -> PresetPreview:
    # Only the allowlisted projection is hashed, not a complete job config.
    choices = sorted(choices, key=lambda x: x.name)
    names = {p.name for p in choices}
    if (len(names) != len(choices) or base.duration_preset not in names
            or any(p.min_sec > p.max_sec for p in choices)):
        raise ValueError("invalid configured presets")
    snapshot = {"schema_version": 1, "base": base.model_dump(),
                "presets": [p.model_dump() for p in choices]}
    revision = hashlib.sha256(json.dumps(snapshot, sort_keys=True,
                                         separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    values = base.model_dump()
    if request is not None:
        if request.base_revision != revision:
            raise StalePreview("configured settings changed")
        for layer in (request.global_layer, request.project_layer, request.clip_layer):
            values.update(layer.model_dump(exclude_none=True))
    effective = PresetValues.model_validate(values)
    if effective.duration_preset not in names:
        raise ValueError("preset not configured")
    changed = [key for key, value in values.items() if value != snapshot["base"][key]]
    affected = set()
    if "duration_preset" in changed:
        affected.update(("selection", "plan", "render"))
    if {"hook_rescue", "filler_word_cut"}.intersection(changed):
        affected.update(("plan", "render"))
    if changed:
        affected.add("render")
    return PresetPreview(
        schema_version=1, base_revision=revision, base=base, effective=effective,
        presets=choices, changed_fields=sorted(changed),
        invalidates=[stage for stage in ("selection", "plan", "render") if stage in affected],
        two_shot_auto_active=effective.two_shot and effective.two_shot_auto,
        execution_enabled=False,
    )
