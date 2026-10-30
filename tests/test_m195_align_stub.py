"""M195 (m191 disko_beach_p1 M4, m194 measurement): the aligner put «И», «в» of «И в моменте сталкивания» at 1019.29 /
1019.35 s — confident (0.94 / 0.89) but 20 ms each, inside «сталкивания» and 1.3 s after their Whisper time; the cold
open started there and the plan refused «seam inside word». Such stubs are dropped from the alignment (the word's time
comes from the speech map); a confident out-of-order word of normal length stays as before."""
from __future__ import annotations

from autoreels.cloud.plan import clean_alignment

REAL = [  # handoff/m194/diag_seam.txt (Whisper t0, aligned start/end, score)
    {"t0": 1017.752, "start": 1017.751, "end": 1018.051, "score": 0.89},    # другом.
    {"t0": 1018.032, "start": 1019.292, "end": 1019.312, "score": 0.937},   # И
    {"t0": 1018.432, "start": 1019.352, "end": 1019.372, "score": 0.893},   # в
    {"t0": 1018.532, "start": 1018.513, "end": 1018.874, "score": 0.988},   # моменте
    {"t0": 1018.952, "start": 1018.934, "end": 1019.654, "score": 0.963},   # сталкивания
    {"t0": 1019.672, "start": 1019.954, "end": 1020.355, "score": 0.81},    # ученые
]


def test_aligner_stubs_far_from_their_word_are_dropped():
    kept, rejected = clean_alignment(REAL)
    assert sorted(rejected) == [1018.032, 1018.432]
    assert [e["t0"] for e in kept] == [1017.752, 1018.532, 1018.952, 1019.672]


def test_confident_out_of_order_words_of_normal_length_stay():
    # Whisper wrote a phrase later than it sounds (M42): both words long and confident — kept as before
    e = [{"t0": 10.0, "start": 10.0, "end": 11.0, "score": 0.9},
         {"t0": 14.0, "start": 9.0, "end": 9.6, "score": 0.9}]
    kept, rejected = clean_alignment(e)
    assert rejected == [] and len(kept) == 2


def test_a_stub_near_its_whisper_time_stays():
    e = [{"t0": 10.0, "start": 10.0, "end": 11.0, "score": 0.9},
         {"t0": 10.9, "start": 10.9, "end": 10.92, "score": 0.9},     # «и» 20 ms, at its place
         {"t0": 10.95, "start": 10.95, "end": 11.4, "score": 0.9}]
    kept, rejected = clean_alignment(e)
    assert rejected == [] and len(kept) == 3
