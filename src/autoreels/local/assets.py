"""Resolve an explicitly selected local audio asset; no discovery, upload or network.

The trusted executor stages a content-addressed WAV under its canonical asset
directory. Rights declarations are metadata, not an automatic license check.
Only the isolated synthetic path has been accepted so far.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from autoreels.core.models import AudioAsset

MAX_AUDIO_BYTES = 128 * 1024 * 1024


def resolve_audio_asset(root: Path, asset: AudioAsset) -> Path:
    root = Path(root)
    if not root.is_absolute() or not root.is_dir() or root.resolve() != root:
        raise ValueError("canonical local asset directory required")
    # Validate again for callers that use model_copy instead of construction.
    asset = AudioAsset.model_validate_json(asset.model_dump_json())
    path = root / (asset.sha256 + "." + asset.format)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("asset path unavailable")
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_AUDIO_BYTES:
                raise ValueError("invalid local audio asset size or type")
            digest = hashlib.sha256()
            count = 0
            while block := handle.read(1024 * 1024):
                count += len(block)
                if count > before.st_size:
                    raise ValueError("local asset changed")
                digest.update(block)
            def signature(st):
                return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns
            if (count != before.st_size or signature(before) != signature(os.fstat(handle.fileno()))
                    or signature(before) != signature(path.lstat())
                    or digest.hexdigest() != asset.sha256):
                raise ValueError("local asset content mismatch")
    except OSError as exc:
        raise ValueError("local audio asset unavailable") from exc
    return path
