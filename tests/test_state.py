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
