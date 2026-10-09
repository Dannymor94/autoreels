"""M2.1 forced alignment (local/align.py) — pure parts, with a fake aligner backend (no torch)."""
import json

from autoreels.cloud.plan import load_alignment
from autoreels.core.models import Word
from autoreels.local.align import (
    align_transcript, plan_chunks, romanize, untranscribed_speech, write_alignment,
)


def test_romanize_cyrillic_to_mms_letters():
    assert romanize("Жизнь.") == "zhizn"
    assert romanize("что-нибудь,") == "chtonibud"
    assert romanize("—") == ""
    assert romanize("DimaTorzok") == "dimatorzok"


def test_plan_chunks_split_by_span_and_skip_unusable():
    spans = [(float(i), i + 0.8) for i in range(60)]
    use = [i != 5 for i in range(60)]
    chunks = plan_chunks(spans, use, max_chunk_sec=25.0, margin_sec=1.5, total_sec=61.0)
    assert all(5 not in c.idx for c in chunks)
    assert sum(len(c.idx) for c in chunks) == 59
    for c in chunks:
        assert spans[c.idx[-1]][1] - spans[c.idx[0]][0] <= 25.0
        assert c.start == max(0.0, spans[c.idx[0]][0] - 1.5)
        assert c.end <= 61.0


def test_untranscribed_is_wildcard_and_energy_minus_words():
    stars = [(10.0, 12.0)]
    energy = [[9.0, 10.5], [10.6, 11.0], [11.5, 13.0]]
    words = [(11.8, 12.4)]
    # 10.0–10.5 and 10.6–11.0 are speech in the wildcard; 11.5–11.8 too; 11.8–12.0 is a word
    assert untranscribed_speech(stars, energy, words) == [[10.0, 10.5], [10.6, 11.0], [11.5, 11.8]]
    # pieces shorter than min_len are dropped
    assert untranscribed_speech([(10.0, 10.05)], energy, []) == []


class FakeBackend:
    """Aligns token k to frames [40k, 40k+20) (20 ms frames at ratio 1/50 s) — deterministic."""

    def align(self, audio, seq):
        n_frames = len(audio) // 320
        return n_frames, [[(40 * k, 40 * k + 20, 0.9)] for k in range(len(seq))]


def test_align_transcript_maps_tokens_to_source_times():
    words = [Word(word="Мне", t0=1.0, t1=1.2), Word(word="—", t0=1.2, t1=1.2),
             Word(word="пришлось", t0=1.2, t1=1.7)]
    read = lambda start, dur: __import__("numpy").zeros(int(dur * 16000), dtype="float32")
    out = align_transcript(words, [True, True, True], read, energy=[[0.0, 5.0]], backend=FakeBackend(),
                           margin_sec=1.0)
    # chunk audio starts at 0.0 (1.0 − margin); seq = * Мне * пришлось *  → tokens 1 and 3
    by_t0 = {w["t0"]: w for w in out["words"]}
    assert set(by_t0) == {1.0, 1.2}                      # «—» has no letters → not aligned
    assert by_t0[1.0]["start"] == 0.8 and by_t0[1.0]["end"] == 1.2
    assert by_t0[1.2]["start"] == 2.4 and by_t0[1.2]["end"] == 2.8
    assert out["version"] == 1
    # wildcard spans ∩ energy − words → untranscribed speech
    assert [0.0, 0.4] in out["untranscribed"]


def test_word_far_from_whisper_is_not_taken():
    words = [Word(word="да", t0=10.0, t1=10.2)]
    read = lambda start, dur: __import__("numpy").zeros(int(dur * 16000), dtype="float32")

    class Far:
        def align(self, audio, seq):
            return len(audio) // 320, [[(0, 1, 0.5)], [(1000, 1010, 0.5)], [(1010, 1011, 0.5)]]

    out = align_transcript(words, [True], read, energy=[], backend=Far(), margin_sec=30.0)
    (w,) = out["words"]
    assert w.get("far") is True and w["start"] is None


def test_alignment_file_roundtrip_and_source_check(tmp_path):
    p = tmp_path / "x.align.json"
    write_alignment(p, {"version": 1, "words": [], "untranscribed": []}, "sha1")
    assert load_alignment(p, "sha1")["source_sha256"] == "sha1"
    assert load_alignment(p, "other") is None
    assert load_alignment(tmp_path / "missing.json", "sha1") is None
    p.write_text(json.dumps({"version": 99}))
    assert load_alignment(p) is None


def test_numbers_are_not_aligned_and_not_untranscribed():
    words = [Word(word="в", t0=1.0, t1=1.1), Word(word="90-х", t0=1.1, t1=1.8), Word(word="годах.", t0=1.8, t1=2.3)]
    read = lambda start, dur: __import__("numpy").zeros(int(dur * 16000), dtype="float32")
    out = align_transcript(words, [True, True, True], read, energy=[[0.0, 5.0]], backend=FakeBackend(),
                           margin_sec=1.0)
    assert {w["t0"] for w in out["words"]} == {1.0, 1.8}
    for a, b in out["untranscribed"]:
        assert b <= 1.1 or a >= 1.8                          # the number's own span is not «foreign»


def test_failed_chunk_is_recorded_not_fatal():
    words = [Word(word="а", t0=float(i), t1=i + 0.5) for i in range(60)]
    read = lambda start, dur: __import__("numpy").zeros(int(dur * 16000), dtype="float32")

    class Flaky(FakeBackend):
        calls = 0

        def align(self, audio, seq):
            Flaky.calls += 1
            if Flaky.calls == 2:
                raise RuntimeError("targets length is too long for CTC")
            return super().align(audio, seq)

    out = align_transcript(words, [True] * 60, read, energy=[], backend=Flaky(), max_chunk_sec=25.0)
    assert len(out["failed_chunks"]) == 1 and "CTC" in out["failed_chunks"][0]["error"]
    assert 0 < len(out["words"]) < 60


def test_chunks_cover_long_pauses_between_them():
    spans = [(0.0, 0.5), (1.0, 20.0), (40.0, 40.5)]
    chunks = plan_chunks(spans, [True] * 3, max_chunk_sec=25.0, margin_sec=1.5, max_fill_sec=10.0)
    assert len(chunks) == 2
    assert chunks[0].end == 21.5 + 10.0                       # filled toward the next chunk, ≤ 10 s


def test_transcript_identity_changes_with_whisper_times():
    from autoreels.local.align import transcript_identity
    a = [Word(word="а", t0=1.0, t1=1.2)]
    b = [Word(word="а", t0=1.01, t1=1.2)]
    assert transcript_identity(a) != transcript_identity(b)
    assert transcript_identity(a)["n_words"] == 1
