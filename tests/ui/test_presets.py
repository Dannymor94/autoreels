"""Focused UI-203A contract tests, no media or real pipeline invocation."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoreels.core.config import load_r0_config, load_render_config
from autoreels.orchestr import pipeline_gateway, presets as p


def configured():
    root = Path(__file__).resolve().parents[2]
    r0 = load_r0_config(root / "config" / "r0.yaml")
    render = load_render_config(root / "config" / "render.yaml",
                                local_path=root / "config" / "nonexistent-test-overlay.yaml")
    return r0, render, pipeline_gateway.configured_module_values(r0, render)


def test_configured_values_match_existing_cli():
    r0, render, base = configured()
    assert base.hook_rescue.automation_enabled == r0.autocut.hook_clauses_autocut
    assert base.filler_cut.output_enabled == r0.montage.filler_cut
    assert base.two_shot.output_enabled == render.two_shot
    assert base.loudnorm.output_enabled == render.audio_processing.loudnorm_enabled
    assert base.denoise.output_enabled == render.audio_processing.denoise_enabled
    assert base.music.output_enabled == render.music.enabled
    assert p.overlay(base, p.Overrides()) == base


def test_precedence_and_pinned_project_snapshot():
    _, _, base = configured()
    project = p.ProjectPreset(global_snapshot=base, overrides=p.Overrides(
        music=p.ModuleOverride(output_enabled=True),
        loudnorm=p.ModuleOverride(visible=False),
    ))
    clip = p.Overrides(music=p.ModuleOverride(output_enabled=False))
    result = project.effective(clip)
    assert project.effective().music.output_enabled is True
    assert result.music.output_enabled is False
    assert result.loudnorm.visible is False
    assert result.loudnorm.output_enabled == base.loudnorm.output_enabled
    changed_global = p.overlay(base, p.Overrides(music=p.ModuleOverride(output_enabled=False)))
    assert project.global_snapshot == base
    assert p.ProjectPreset.model_validate_json(project.model_dump_json()).effective(clip) == result
    assert p.ProjectPreset(global_snapshot=changed_global).effective().music.output_enabled is False
    with pytest.raises(ValidationError):
        project.global_snapshot.music.output_enabled = False


def test_visibility_and_automation_are_not_output_edits():
    _, _, base = configured()
    base = p.overlay(base, p.Overrides(hook_rescue=p.ModuleOverride(automation_enabled=True)))
    hidden = p.overlay(base, p.Overrides(hook_rescue=p.ModuleOverride(visible=False)))
    diff = p.preview(base, hidden, available=frozenset(), accepted_output_modules=frozenset({"hook_rescue"}))
    assert diff.allowed and diff.invalidates == ()
    assert diff.previous_sha256 == diff.proposed_sha256
    disabled = p.overlay(hidden, p.Overrides(hook_rescue=p.ModuleOverride(automation_enabled=False)))
    diff = p.preview(hidden, disabled, available=frozenset({"hook_rescue"}),
                     accepted_output_modules=frozenset({"hook_rescue"}))
    assert diff.allowed and diff.invalidates == ("proposals",)
    assert diff.previous_sha256 != diff.proposed_sha256
    assert base.hook_rescue.automation_enabled is True


def test_output_dependencies_protection_and_noop():
    _, _, base = configured()
    base = p.overlay(base, p.Overrides(music=p.ModuleOverride(output_enabled=True),
                                      filler_cut=p.ModuleOverride(output_enabled=True)))
    output = p.overlay(base, p.Overrides(music=p.ModuleOverride(output_enabled=False)))
    diff = p.preview(base, output, available=frozenset({"music"}), accepted_output_modules=frozenset({"music"}))
    assert not diff.allowed and diff.blocked_accepted_edits == ("music",)
    assert diff.invalidates == ("render",)
    diff = p.preview(base, output, available=frozenset(), accepted_output_modules=frozenset())
    assert not diff.allowed and diff.blocked_unavailable == ("music",)
    assert p.preview(base, output, available=frozenset({"music"}), accepted_output_modules=frozenset()).allowed
    cut = p.overlay(base, p.Overrides(filler_cut=p.ModuleOverride(output_enabled=False)))
    assert p.preview(base, cut, available=frozenset({"filler_cut"}),
                     accepted_output_modules=frozenset()).invalidates == ("plan", "render")
    noop = p.preview(base, p.overlay(base, p.Overrides()), available=frozenset(),
                     accepted_output_modules=frozenset())
    assert noop.allowed and noop.changes == () and noop.invalidates == ()
    assert noop.previous_sha256 == noop.proposed_sha256


def test_reject_unsupported_dimensions_and_coercion():
    for value in ({"hook_rescue":{"output_enabled":False}},
                  {"music":{"automation_enabled":True}},
                  {"music":{"output_enabled":"false"}},
                  {"unknown":{"visible":True}}):
        with pytest.raises(ValidationError):
            p.Overrides.model_validate(value)
