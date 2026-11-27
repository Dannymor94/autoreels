"""UI-201A: versioned discovery contract, not an execution or registration API."""
from typing import Literal

from pydantic import BaseModel

TargetKind = Literal["desktop", "remote", "mobile"]


class RenderMode(BaseModel):
    kind: TargetKind
    integration: Literal["cli_adapter_pending", "device_spike_pending"]


class RenderTarget(BaseModel):
    """A real registered executor, never a placeholder for a device category."""

    target_id: str
    kind: TargetKind
    platform: str
    availability: Literal["unverified", "unavailable", "ready"]
    authorized: bool
    adapter_version: str
    capabilities: list[Literal["render"]]


class RenderInventory(BaseModel):
    schema_version: int
    modes: list[RenderMode]
    targets: list[RenderTarget]
    execution_enabled: bool


def inventory() -> RenderInventory:
    # Legacy CLI exists but no registered UI worker has passed preflight.
    # Host OS, browser UA, private mode and configured SSH host are NOT proof
    # of a connected/authorized target. No probing, file IO or registration.
    return RenderInventory(
        schema_version=1,
        modes=[
            RenderMode(kind="desktop", integration="cli_adapter_pending"),
            RenderMode(kind="remote", integration="cli_adapter_pending"),
            RenderMode(kind="mobile", integration="device_spike_pending"),
        ],
        targets=[],
        execution_enabled=False,
    )
