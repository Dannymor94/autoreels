"""Shared timing contract for independently retimed hard-cut playback windows.

Experimental opt-in only: no change to legacy Manifest serialization or
production render. Source windows remain the canonical edit plan; rates are
aligned with playback occurrences, not chronological source intervals.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from autoreels.core.models import Segment


@dataclass(frozen=True)
class WindowTiming:
    index: int
    source_start: float
    source_end: float
    rate: float
    output_start: float
    output_end: float

    def to_output(self, source: float) -> float:
        if not math.isfinite(source) or not self.source_start <= source <= self.source_end:
            raise ValueError("time outside source window")
        return self.output_start + (source - self.source_start) / self.rate

    def to_source(self, output: float) -> float:
        if not math.isfinite(output) or not self.output_start <= output <= self.output_end:
            raise ValueError("time outside output window")
        if output == self.output_end:
            return self.source_end
        return min(self.source_end, self.source_start + (output - self.output_start) * self.rate)


def build_window_timing(segments: Iterable[Segment], rates: Iterable[float]) -> tuple[WindowTiming, ...]:
    """Compile a hard-cut plan in playback order; repeat source occurrences independently.

    Rates 0.5–2.0 are the conservative experimental range for pitch-preserving
    FFmpeg atempo. Seam overlaps, effect retiming and frame/sample snapping
    are separate renderer gates, not silently approximated here.
    """
    segments, rates = tuple(segments), tuple(rates)
    if not segments or len(segments) != len(rates):
        raise ValueError("one rate required for every playback window")
    result = []
    offset = 0.0
    for i, (seg, rate) in enumerate(zip(segments, rates)):
        if (type(rate) not in (int, float) or not math.isfinite(rate)
                or not 0.5 <= rate <= 2.0):
            raise ValueError("unsupported playback rate")
        if (not math.isfinite(seg.start) or not math.isfinite(seg.end)
                or not 0 <= seg.start < seg.end):
            raise ValueError("invalid source window")
        end = offset + (seg.end - seg.start) / rate
        if not math.isfinite(end) or end <= offset:
            raise ValueError("invalid output duration")
        result.append(WindowTiming(i, seg.start, seg.end, float(rate), offset, end))
        offset = end
    return tuple(result)
