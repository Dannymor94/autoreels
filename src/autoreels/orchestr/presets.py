"""UI-203A: immutable module settings, scoped inheritance and proposed diff.

No execution, storage, media, manifest mutation or acceptance of edit operations.
The subset digest is not a full execution config hash.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

Module = Literal["hook_rescue", "filler_cut", "two_shot", "loudnorm", "denoise", "music"]
Flag = Literal["visible", "automation_enabled", "output_enabled"]
Stage = Literal["proposals", "plan", "render"]
MODULES = ("hook_rescue", "filler_cut", "two_shot", "loudnorm", "denoise", "music")
FLAGS = ("visible", "automation_enabled", "output_enabled")
# Only hook rescue is a proposal switch in this initial subset.
# Filler cut changes actual played windows; it is NOT proposal-only.
OUTPUT_STAGES = {
    "filler_cut": ("plan", "render"),
    "two_shot": ("render",),
    "loudnorm": ("render",),
    "denoise": ("render",),
    "music": ("render",),
}


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ModuleValue(Frozen):
    visible: bool = True
    automation_enabled: bool | None = None
    output_enabled: bool | None = None


class Values(Frozen):
    hook_rescue: ModuleValue
    filler_cut: ModuleValue
    two_shot: ModuleValue
    loudnorm: ModuleValue
    denoise: ModuleValue
    music: ModuleValue

    @model_validator(mode="after")
    def applicable_dimensions(self):
        for name in MODULES:
            value = getattr(self, name)
            if name == "hook_rescue":
                if value.automation_enabled is None or value.output_enabled is not None:
                    raise ValueError("hook_rescue supports automation, not output")
            elif value.automation_enabled is not None or value.output_enabled is None:
                raise ValueError("output module does not expose a proposal switch")
        return self


class ModuleOverride(Frozen):
    # None means inherit, not disable. False is always explicit.
    visible: bool | None = None
    automation_enabled: bool | None = None
    output_enabled: bool | None = None


class Overrides(Frozen):
    hook_rescue: ModuleOverride = ModuleOverride()
    filler_cut: ModuleOverride = ModuleOverride()
    two_shot: ModuleOverride = ModuleOverride()
    loudnorm: ModuleOverride = ModuleOverride()
    denoise: ModuleOverride = ModuleOverride()
    music: ModuleOverride = ModuleOverride()

    @model_validator(mode="after")
    def applicable_dimensions(self):
        for name in MODULES:
            patch = getattr(self, name)
            if name == "hook_rescue" and patch.output_enabled is not None:
                raise ValueError("hook_rescue output is not independently supported")
            if name != "hook_rescue" and patch.automation_enabled is not None:
                raise ValueError("module automation is not independently supported")
        return self


def overlay(base: Values, overrides: Overrides) -> Values:
    data = {}
    for name in MODULES:
        value = getattr(base, name)
        patch = getattr(overrides, name)
        data[name] = ModuleValue.model_validate({
            **value.model_dump(), **patch.model_dump(exclude_none=True)
        })
    return Values(**data)


class ProjectPreset(Frozen):
    # Store the actual immutable global values at project creation, not a
    # mutable pointer to the user's current default.
    global_snapshot: Values
    overrides: Overrides = Overrides()

    def effective(self, clip: Overrides = Overrides()) -> Values:
        return overlay(overlay(self.global_snapshot, self.overrides), clip)


def module_options_sha256(values: Values) -> str:
    """Versioned digest of this subset only; presentation is excluded."""
    payload = {
        "schema_version": 1,
        "modules": {
            name: getattr(values, name).model_dump(exclude={"visible"}, exclude_none=True)
            for name in MODULES
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ModuleChange(Frozen):
    module: Module
    field: Flag
    before: bool
    after: bool


class Preview(Frozen):
    changes: tuple[ModuleChange, ...]
    invalidates: tuple[Stage, ...]
    blocked_unavailable: tuple[Module, ...]
    blocked_accepted_edits: tuple[Module, ...]
    previous_sha256: str
    proposed_sha256: str

    @property
    def allowed(self) -> bool:
        return not (self.blocked_unavailable or self.blocked_accepted_edits)


def preview(
    before: Values,
    after: Values,
    *,
    available: frozenset[Module],
    accepted_output_modules: frozenset[Module],
) -> Preview:
    """Advisory diff, not permission to change a project or accepted edit.

    Capabilities are supplied independently by a trusted adapter. Hiding a
    module never changes output. Proposal changes never delete accepted work.
    Actual output changes touching protected edits must be resolved separately.
    """
    if not available.issubset(MODULES) or not accepted_output_modules.issubset(MODULES):
        raise ValueError("unknown module")
    changes = []
    stages = set()
    unavailable = set()
    protected = set()
    for name in MODULES:
        old, new = getattr(before, name), getattr(after, name)
        for flag in FLAGS:
            a, b = getattr(old, flag), getattr(new, flag)
            if a == b:
                continue
            changes.append(ModuleChange(module=name, field=flag, before=a, after=b))
            if flag == "visible":
                continue
            if name not in available:
                unavailable.add(name)
            if flag == "automation_enabled":
                stages.add("proposals")
            else:
                stages.update(OUTPUT_STAGES[name])
                if name in accepted_output_modules:
                    protected.add(name)
    return Preview(
        changes=tuple(changes),
        invalidates=tuple(s for s in ("proposals", "plan", "render") if s in stages),
        blocked_unavailable=tuple(n for n in MODULES if n in unavailable),
        blocked_accepted_edits=tuple(n for n in MODULES if n in protected),
        previous_sha256=module_options_sha256(before),
        proposed_sha256=module_options_sha256(after),
    )
