"""The ONLY module that will call the pipeline (arl … --json) — nothing else in orchestr imports cloud/local/core internals."""

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
