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
