"""Diagnostic-only memory trace at pipeline stage boundaries.

OFF by default. Enabled with env AUTOREELS_MEMTRACE=1 — then `mark(label)` prints
peak process RSS, the delta since the previous mark, and (AUTOREELS_MEMTRACE=full)
the top-5 tracemalloc allocation sites. Zero behaviour change when disabled: `mark`
is a no-op returning None and tracemalloc is never started.

Rationale: OOM on long lecture runs (docs/audit-oom.md). This adds a cheap, opt-in
probe to locate which stage grows RSS, without touching the pipeline's logic.
"""
from __future__ import annotations

import os
import sys
import tracemalloc

_ENABLED = os.environ.get("AUTOREELS_MEMTRACE", "") not in ("", "0")
_FULL = os.environ.get("AUTOREELS_MEMTRACE", "") == "full"

_prev_rss = 0
_started = False


def _peak_rss_bytes() -> int:
    """Peak RSS in bytes, or 0 on platforms without resource (Windows)."""
    try:
        import resource  # noqa: PLC0415 — lazy: Unix-only
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return rss if sys.platform == "darwin" else rss * 1024
    except ImportError:
        return 0


def mark(label: str) -> None:
    """Log peak RSS + delta at a stage boundary. No-op unless AUTOREELS_MEMTRACE is set."""
    global _prev_rss, _started
    if not _ENABLED:
        return
    if not _started:
        if _FULL:
            tracemalloc.start(10)
        _started = True

    peak = _peak_rss_bytes()
    delta = peak - _prev_rss
    mb = 1 << 20
    print(
        f"[memtrace] {label:<28} peak_rss={peak / mb:8.1f} MB  Δ={delta / mb:+8.1f} MB",
        file=sys.stderr, flush=True,
    )
    _prev_rss = peak

    if _FULL:
        snap = tracemalloc.take_snapshot()
        for i, stat in enumerate(snap.statistics("lineno")[:5], 1):
            print(f"[memtrace]   #{i} {stat}", file=sys.stderr, flush=True)
