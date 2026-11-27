"""Read-only whole-video transcript review; times are not cut boundaries."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Literal, Sequence

from pydantic import BaseModel

from autoreels.cloud.repeat_candidates import find_repeat_candidates
from autoreels.core.models import Word


class LongformSentence(BaseModel):
    number: int
    text: str
    start_ms: int
    end_ms: int


class LongformCandidate(BaseModel):
    earlier: int
    later: int
    kind: Literal["exact_text", "possible_restart"]
    matched_tokens: int


class LongformReview(BaseModel):
    source_duration_ms: int
    review_sha256: str
    sentences: list[LongformSentence]
    candidates: list[LongformCandidate]


def build_review(sentences: Sequence[Sequence[Word]], source_duration_ms: int) -> LongformReview:
    if type(source_duration_ms) is not int or source_duration_ms <= 0:
        raise ValueError("whole-video duration required")
    rows = []
    previous_start = -1.0
    for i, sentence in enumerate(sentences, 1):
        if not sentence:
            raise ValueError("empty sentence unit")
        for w in sentence:
            if not (0 <= w.t0 < w.t1 <= source_duration_ms/1000 and w.t0 >= previous_start):
                raise ValueError("invalid transcript time")
            previous_start = w.t0
        start = round(sentence[0].t0*1000)
        end = round(max(w.t1 for w in sentence)*1000)
        if end <= start:
            raise ValueError("sentence shorter than millisecond projection")
        rows.append(LongformSentence(number=i,text=" ".join(w.word for w in sentence),
                                     start_ms=start,end_ms=end))
    # Bind the original sentence segmentation and exact word timestamps, not
    # only the rounded display projection. No source media hash is implied.
    payload = {"duration_ms":source_duration_ms,
               "sentences":[[w.model_dump(mode="json") for w in s] for s in sentences]}
    raw = json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False).encode("utf-8")
    return LongformReview(source_duration_ms=source_duration_ms,
        review_sha256=hashlib.sha256(raw).hexdigest(),sentences=rows,
        candidates=[LongformCandidate(**asdict(p)) for p in find_repeat_candidates(sentences)])


def synthetic_review() -> LongformReview:
    texts = ("Сегодня мы поговорим о внимании.",
             "Сегодня мы поговорим о внимании!",
             "Я хочу вам рассказать...",
             "Я хочу вам рассказать одну историю.",
             "Эту мысль важно сохранить.")
    sentences = [[Word(word=word,t0=i*4+0.2+j*0.5,t1=i*4+0.55+j*0.5)
                  for j,word in enumerate(text.split())] for i,text in enumerate(texts)]
    return build_review(sentences,20000)
