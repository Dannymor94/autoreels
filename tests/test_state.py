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


def test_transcript_cache_path_uses_audio_hash(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"fake-wav")
    cache_dir = tmp_path / "cache"
    path = state.transcript_cache_path(cache_dir, audio)
    assert path.parent == cache_dir
    assert path.name == f"{state.audio_hash(audio)}.transcript.json"
