"""The ONLY module that will call the pipeline (arl … --json) — nothing else in orchestr imports cloud/local/core internals."""

from . import render_targets

VERDICT_TAGS = [
    "cut_word",
    "foreign_speech_tail",
    "fade_on_word",
    "thought_unfinished",
    "start_cut",
    "start_context",
    "ends_on_filler",
    "jump_cut",
    "flicker",
    "squashed_frame",
    "video_freeze",
    "av_desync",
    "subtitle_mismatch",
    "keyword_missing",
    "tail_unnatural",
]


def capabilities() -> dict:
    return {
        "source": "fallback",
        "verdict_tags": VERDICT_TAGS,
    }


def render_inventory() -> render_targets.RenderInventory:
    return render_targets.inventory()


def catalog_history(root):
    """Read the existing local journal; never follow its stored source paths."""
    from autoreels.core.history import read_runs

    folder = root / "data"
    path = folder / "history.jsonl"
    if folder.is_symlink() or path.is_symlink():
        return []
    try:
        return [r for r in read_runs(path) if isinstance(r, dict)]
    except (OSError, UnicodeError):
        return []


def legacy_reviews(root, stem, clip):
    """Read unbound historical decisions only; do not activate them for review/export."""
    import json

    directory = root / "reviews"
    path = directory / "verdicts.jsonl"
    if directory.is_symlink() or path.is_symlink() or not path.is_file():
        return []
    rows = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or row.get("stem") != stem or row.get("rid") != clip:
                continue
            rows.append({
                "gate": str(row.get("gate") or ""),
                "verdict": str(row.get("verdict") or ""),
                "comment": str(row.get("note") or ""),
                "date": str(row.get("date") or ""),
            })
    except (OSError, UnicodeError):
        return []
    return rows[::-1]


def pipeline_settings(root, clips=None, profile=None):
    """Use the same validated loaders as CLI, never serialize their full models.

    This is a preview of two explicit overrides, not a fully effective job
    configuration. No process, provider, file mutation, or target discovery.
    """
    from autoreels.core.config import ConfigError, load_r0_config, load_render_config
    from . import pipeline_settings as view

    directory = root / "config"
    r0 = directory / "r0.yaml"
    render_file = directory / "render.yaml"
    local = directory / "render.local.yaml"
    analysis_status = view._file_status(root, r0)
    render_status = view._file_status(root, render_file)
    local_status = view._file_status(root, local)
    if local_status == "blocked":
        render_status = "blocked"

    analysis = None
    render = None
    if analysis_status == "configured":
        try:
            cfg = load_r0_config(r0)
            ac = cfg.autocut
            analysis = view.AnalysisDefaults(
                base_clips=ac.clips, clips_every_min=ac.clips_every_min,
                min_sec=ac.min_sec, target_sec=ac.target_sec, max_sec=ac.max_sec,
                configured_mode=ac.auto_mode,
                label_min_sec=cfg.min_duration, label_max_sec=cfg.max_duration,
            )
        except (ConfigError, OSError, ValueError):
            analysis_status = "invalid"
    if render_status == "configured":
        try:
            cfg = load_render_config(render_file, local_path=local)
            if len(cfg.scale) != 2 or any(x <= 0 for x in cfg.scale):
                raise ValueError("invalid render dimensions")
            profiles = [name for name in view.PROFILES if name in cfg.encoder.profiles]
            render = view.RenderDefaults(
                width=cfg.scale[0], height=cfg.scale[1],
                profile=cfg.encoder.profile if cfg.encoder.profile in profiles else None,
                profiles=profiles,
                role=cfg.role if cfg.role in ("analyze", "render", "both") else "unknown",
                loudnorm_enabled=cfg.audio_processing.loudnorm_enabled,
                denoise_enabled=cfg.audio_processing.denoise_enabled,
                music_enabled=cfg.music.enabled,
            )
        except (ConfigError, OSError, ValueError):
            render_status = "invalid"

    requested = clips is not None or profile is not None
    valid = (
        (clips is None or (type(clips) is int and 1 <= clips <= 1000 and analysis is not None))
        and (profile is None or (render is not None and profile in render.profiles))
    )
    return view.PipelineSettings(
        schema_version=1, analysis_status=analysis_status, analysis=analysis,
        render_status=render_status, render=render,
        draft_clips=clips if valid else None, draft_profile=profile if valid else None,
        preview_status=("valid" if valid else "blocked") if requested else "not_requested",
        execution_enabled=False,
    )



def configured_module_values(r0, render):
    """Project validated CLI config objects into the UI-203A module subset.

    Configured values are not proof of target support or actual run-time flags.
    Per-run overrides, stage prerequisites and manual edits stay separate.
    """
    from .presets import ModuleValue, Values

    return Values(
        hook_rescue=ModuleValue(automation_enabled=r0.autocut.hook_clauses_autocut),
        filler_cut=ModuleValue(output_enabled=r0.montage.filler_cut),
        two_shot=ModuleValue(output_enabled=render.two_shot),
        loudnorm=ModuleValue(output_enabled=render.audio_processing.loudnorm_enabled),
        denoise=ModuleValue(output_enabled=render.audio_processing.denoise_enabled),
        music=ModuleValue(output_enabled=render.music.enabled),
    )



def module_settings(root, choices):
    """Read the guarded CLI config; compare a draft without applying it.

    No real target is connected, so availability is false. No accepted project
    edits can be assessed without a bound revision. Applying is always disabled.
    """
    from autoreels.core.config import ConfigError, load_r0_config, load_render_config
    from . import module_settings as view, pipeline_settings as config_view, presets

    def unavailable(status):
        return view.ModuleSettingsView(
            schema_version=1, status=status, modules=[], invalidates=[],
            base_sha256=None, apply_enabled=False,
        )

    directory = root / "config"
    r0 = directory / "r0.yaml"
    render_file = directory / "render.yaml"
    local = directory / "render.local.yaml"
    required = [config_view._file_status(root, path) for path in (r0, render_file)]
    local_status = config_view._file_status(root, local)
    if "blocked" in required or local_status == "blocked":
        return unavailable("blocked")
    if "missing" in required:
        return unavailable("missing")
    try:
        baseline = configured_module_values(
            load_r0_config(r0), load_render_config(render_file, local_path=local)
        )
    except (ConfigError, OSError, ValueError):
        return unavailable("invalid")
    patches = {}
    for name in presets.MODULES:
        choice = choices.get(name)
        if choice is not None:
            flag = "automation_enabled" if name == "hook_rescue" else "output_enabled"
            patches[name] = {flag: choice == "on"}
    proposed = presets.overlay(baseline, presets.Overrides.model_validate(patches))
    diff = presets.preview(baseline, proposed, available=frozenset(),
                           accepted_output_modules=frozenset())
    rows = []
    for name in presets.MODULES:
        automation = name == "hook_rescue"
        flag = "automation_enabled" if automation else "output_enabled"
        rows.append(view.ModuleOption(
            module=name, kind="automation" if automation else "output",
            configured=getattr(getattr(baseline, name), flag),
            proposed=getattr(getattr(proposed, name), flag),
            available=False,
        ))
    return view.ModuleSettingsView(
        schema_version=1, status="configured", modules=rows,
        invalidates=list(diff.invalidates), base_sha256=diff.previous_sha256,
        apply_enabled=False,
    )
