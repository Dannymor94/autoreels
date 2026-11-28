"""Read-only validator for suggested B-roll anchored to reviewed speech.

A proposer may supply only sentence numbers and registered asset digests.
Local deterministic code computes safe output placement; it never downloads
assets, calls a model, changes the saved plan or confirms an insertion.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field

from autoreels.core.models import GraphicLayer, ImageAsset, Manifest, VideoAsset, Word
from autoreels.core.playback_timing import build_window_timing
from .longform_review import build_review
from .sentence_edit import Unavailable, _speech_evidence


class InsertSuggestion(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True,frozen=True)
    sentence: int = Field(ge=1)
    asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class InsertProposal:
    suggestion: InsertSuggestion
    layer: GraphicLayer


@dataclass(frozen=True)
class InsertReview:
    plan_sha256: str
    review_sha256: str
    accepted: tuple[InsertProposal,...]
    rejected: tuple[tuple[InsertSuggestion,str],...]


def review_inserts(
    manifest: Manifest, *, clip_id: str, plan_sha256: str, review_sha256: str,
    sentences: Sequence[Sequence[Word]], words: Sequence[Word], smap: dict,
    source_duration_ms: int, catalog: Sequence[ImageAsset | VideoAsset],
    suggestions: Sequence[InsertSuggestion], min_duration_ms: int=300,
    max_duration_ms: int=1500, min_gap_ms: int=1000,
) -> InsertReview:
    """Trusted caller binds source, audio map and catalog to this exact revision.

    Suggestions are evaluated in supplied priority order. Conservative pilot:
    one photo and one video, four total visual layers, full-frame placement
    within a uniquely retained speech window. Existing manual layers win.
    Accepted results are proposals only, never automatic edit commands.
    """
    if (hashlib.sha256(manifest.model_dump_json().encode("utf-8")).hexdigest()!=plan_sha256
            or build_review(sentences,source_duration_ms).review_sha256!=review_sha256):
        raise Unavailable("insert review revision changed")
    if (len(suggestions)>16 or any(type(n) is not int for n in
                                  (min_duration_ms,max_duration_ms,min_gap_ms))
            or not 1<=min_duration_ms<=max_duration_ms<=3000 or not 0<=min_gap_ms<=10000):
        raise Unavailable("invalid insert review policy")
    matches=[r for r in manifest.reels if r.id==clip_id]
    if len(matches)!=1:
        raise Unavailable("unknown or ambiguous clip")
    base=matches[0]
    base.check_segments()
    windows=base.playback_windows()
    duration=source_duration_ms/1000
    if any(w.start<0 or w.end>duration for w in windows):
        raise Unavailable("clip outside reviewed source")
    timing=build_window_timing(windows,base.window_rates or [1.0]*len(windows))
    evidence=_speech_evidence(sentences,words,smap,duration)
    flattened=[w for sentence in sentences for w in sentence]
    if list(words)!=flattened or set(evidence)!={round(w.t0*1000) for w in flattened}:
        raise Unavailable("incomplete reviewed speech")
    assets={}
    for asset in catalog:
        if not isinstance(asset,(ImageAsset,VideoAsset)):
            raise Unavailable("invalid visual catalog entry")
        asset=type(asset).model_validate_json(asset.model_dump_json())
        if asset.sha256 in assets:
            raise Unavailable("ambiguous visual catalog identity")
        assets[asset.sha256]=asset
    layers=base.visual_layers()
    accepted,rejected=[],[]
    seen=set()
    for item in suggestions:
        item=InsertSuggestion.model_validate_json(item.model_dump_json())
        key=(item.sentence,item.asset_sha256)
        asset=assets.get(item.asset_sha256)
        reason=None
        if key in seen:
            reason="duplicate suggestion"
        elif not 1<=item.sentence<=len(sentences):
            reason="unknown sentence"
        elif asset is None or asset.rights!="synthetic":
            reason="asset unavailable or not enabled"
        else:
            spans=[evidence[round(w.t0*1000)] for w in sentences[item.sentence-1]]
            a,b=min(x[0] for x in spans),max(x[1] for x in spans)
            occurrences=[w for w in timing if w.source_start<=a and b<=w.source_end]
            if len(occurrences)!=1:
                reason="speech not uniquely retained"
            else:
                window=occurrences[0]
                start=math.ceil(window.to_output(a)*1000-1e-7)
                end=min(math.floor(window.to_output(b)*1000+1e-7),start+max_duration_ms)
                if isinstance(asset,VideoAsset):
                    end=min(end,start+asset.duration_ms)
                if end-start<min_duration_ms:
                    reason="insufficient retained duration"
                elif len(layers)>=4 or any(
                        (isinstance(asset,ImageAsset) and layer.image is not None)
                        or (isinstance(asset,VideoAsset) and layer.video is not None)
                        for layer in layers):
                    reason="media layer capacity"
                elif any(start<layer.end_ms+min_gap_ms and end+min_gap_ms>layer.start_ms
                         for layer in layers):
                    reason="conflict with existing or proposed layer"
                else:
                    layer=GraphicLayer(x_pct=0,y_pct=0,width_pct=100,height_pct=100,
                        start_ms=start,end_ms=end,image=asset if isinstance(asset,ImageAsset) else None,
                        video=asset if isinstance(asset,VideoAsset) else None)
                    candidate=base.model_copy(update={"graphic_layer":None,"graphic_layers":[*layers,layer]})
                    try:
                        candidate.check_segments()
                    except ValueError:
                        reason="unsupported montage"
                    else:
                        layers.append(layer)
                        accepted.append(InsertProposal(item,layer))
        seen.add(key)
        if reason is not None:
            rejected.append((item,reason))
    return InsertReview(plan_sha256,review_sha256,tuple(accepted),tuple(rejected))
