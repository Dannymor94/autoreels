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


def preset_preview(root, request=None):
    """Read the real CLI config; return only a restricted preview projection."""
    from autoreels.core.config import ConfigError, load_r0_config, load_render_config
    from . import pipeline_settings as view
    from . import preset_preview as presets

    folder = root / "config"
    r0 = folder / "r0.yaml"
    render_file = folder / "render.yaml"
    local = folder / "render.local.yaml"
    if (view._file_status(root, r0) != "configured"
            or view._file_status(root, render_file) != "configured"
            or view._file_status(root, local) not in ("configured", "missing")):
        raise ValueError("configured presets unavailable")
    try:
        analysis = load_r0_config(r0)
        render = load_render_config(render_file, local_path=local)
        values = presets.PresetValues(
            duration_preset=analysis.duration_preset,
            hook_rescue=analysis.autocut.hook_clauses_autocut,
            filler_word_cut=analysis.filler_word_cut,
            zoom=render.zoom.enabled,
            loudnorm=render.audio_processing.loudnorm_enabled,
            denoise=render.audio_processing.denoise_enabled,
            two_shot=render.two_shot,
            two_shot_auto=render.two_shot_auto,
        )
        choices = [presets.DurationChoice(name=name, min_sec=analysis.presets[name].min,
                                         max_sec=analysis.presets[name].max)
                   for name in ("shorts", "reels", "tiktok") if name in analysis.presets]
    except (ConfigError, OSError, ValueError):
        raise ValueError("configured presets invalid") from None
    return presets.preview(values, choices, request)
