"""Read-only configured module baseline and draft comparison (UI-203B)."""
from typing import Literal

from .pipeline_settings import Status
from .presets import Frozen, Module, Stage

Choice = Literal["on", "off"]


class ModuleOption(Frozen):
    module: Module
    kind: Literal["automation", "output"]
    configured: bool
    proposed: bool
    available: bool


class ModuleSettingsView(Frozen):
    schema_version: int
    status: Status
    modules: list[ModuleOption]
    invalidates: list[Stage]
    base_sha256: str | None
    apply_enabled: bool
