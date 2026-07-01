"""Идемпотентность: хэш содержимого + путь кэша транскрипта (core/state.py).

R0_SPEC §9: транскрипт кэшируется по хэшу аудио → повторный прогон не перетранскрибирует.
"""
import hashlib
from pathlib import Path

from autoreels.core import state


def test_file_sha256_matches_hashlib(tmp_path):
    p = tmp_path / "blob.bin"
    payload = b"auto-reels deterministic hashing"
    p.write_bytes(payload)
    assert state.file_sha256(p) == hashlib.sha256(payload).hexdigest()


def test_audio_hash_is_content_sha256(tmp_path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"fake-wav")
    assert state.audio_hash(p) == state.file_sha256(p)
    assert len(state.audio_hash(p)) == 64


def test_file_sha256_cached_returns_correct_hash(tmp_path):
    p = tmp_path / "video.mp4"
    payload = b"fake-video-content"
    p.write_bytes(payload)
    cache_dir = tmp_path / "cache"
    result = state.file_sha256_cached(p, cache_dir)
    assert result == hashlib.sha256(payload).hexdigest()
    assert (cache_dir / "sha256").is_dir()


def test_file_sha256_cached_second_call_uses_cache(tmp_path, monkeypatch):
    """Второй вызов на тот же файл не вызывает file_sha256 (читает из кэша)."""
    p = tmp_path / "video.mp4"
    p.write_bytes(b"fake-video")
    cache_dir = tmp_path / "cache"

    # первый вызов — пишет кэш
    expected = state.file_sha256_cached(p, cache_dir)

    calls = []
    original = state.file_sha256
    monkeypatch.setattr(state, "file_sha256", lambda path: (calls.append(path), original(path))[1])

    result = state.file_sha256_cached(p, cache_dir)
    assert result == expected
    assert len(calls) == 0, "второй вызов не должен читать файл: кэш должен был сработать"


def test_file_sha256_cached_invalidates_on_content_change(tmp_path):
    """Кэш инвалидируется при изменении содержимого (mtime меняется)."""
    p = tmp_path / "video.mp4"
    p.write_bytes(b"original content")
    cache_dir = tmp_path / "cache"
    sha1 = state.file_sha256_cached(p, cache_dir)

    import time; time.sleep(0.01)  # гарантируем новый mtime
    p.write_bytes(b"changed content")
    sha2 = state.file_sha256_cached(p, cache_dir)
    assert sha1 != sha2


def test_transcript_cache_path_uses_audio_hash(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"fake-wav")
    cache_dir = tmp_path / "cache"
    path = state.transcript_cache_path(cache_dir, audio)
    assert path.parent == cache_dir
    assert path.name == f"{state.audio_hash(audio)}.transcript.json"


# ------------------------------------------------------ частичный хэш

def test_file_sha256_partial_returns_64_char_hex(tmp_path):
    p = tmp_path / "video.mp4"
    p.write_bytes(b"A" * 1024)
    h = state.file_sha256_partial(p)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_file_sha256_partial_different_from_full_sha256(tmp_path):
    # Частичный хэш ДОЛЖЕН отличаться от полного (разные алгоритмы → разные значения).
    p = tmp_path / "video.mp4"
    p.write_bytes(b"B" * 500_000)   # 500 КБ — меньше 8 МБ, но всё равно другой формат
    assert state.file_sha256_partial(p) != state.file_sha256(p)


def test_file_sha256_partial_detects_middle_difference(tmp_path):
    """Два файла с одинаковым началом и концом, но разной серединой → разные partial хэши."""
    size = 20 * 1024 * 1024   # 20 МБ — чтобы начало/середина/конец были в разных 8-МБ зонах
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    a.write_bytes(b"X" * size)
    # меняем только один байт в середине
    data = bytearray(b"X" * size)
    data[size // 2] = ord("Y")
    b.write_bytes(bytes(data))

    assert state.file_sha256_partial(a) != state.file_sha256_partial(b)


def test_file_sha256_partial_stable_for_same_content(tmp_path):
    p = tmp_path / "v.mp4"
    p.write_bytes(b"stable" * 100_000)
    assert state.file_sha256_partial(p) == state.file_sha256_partial(p)


def test_file_sha256_cached_fast_returns_64_char_hex(tmp_path):
    p = tmp_path / "v.mp4"
    p.write_bytes(b"C" * 1024)
    h = state.file_sha256_cached_fast(p, tmp_path / "cache")
    assert len(h) == 64


def test_file_sha256_cached_fast_cache_hit_no_recompute(tmp_path, monkeypatch):
    p = tmp_path / "v.mp4"
    p.write_bytes(b"D" * 1024)
    cache = tmp_path / "cache"
    state.file_sha256_cached_fast(p, cache)   # первый вызов — пишет кэш

    calls = []
    monkeypatch.setattr(state, "file_sha256_partial", lambda path: calls.append(path) or "x" * 64)
    state.file_sha256_cached_fast(p, cache)   # второй — из кэша
    assert calls == []


def test_file_sha256_cached_fast_cache_file_has_p1_marker(tmp_path):
    """Кэш-файл содержит 'p1:' — чтобы отличить от старых full-sha записей."""
    p = tmp_path / "v.mp4"
    p.write_bytes(b"E" * 1024)
    cache = tmp_path / "cache"
    state.file_sha256_cached_fast(p, cache)

    sha_cache = cache / "sha256"
    entries = list(sha_cache.glob("*.txt"))
    assert len(entries) == 1
    assert entries[0].read_text().startswith("p1:")
