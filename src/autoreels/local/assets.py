"""Resolve explicitly selected local assets; no discovery, upload or network.

The trusted executor stages a content-addressed WAV under its canonical asset
directory. Rights declarations are metadata, not an automatic license check.
Only the isolated synthetic path has been accepted so far.
"""
from __future__ import annotations

import hashlib
import os
import stat
import struct
import zlib
from pathlib import Path

from autoreels.core.models import AudioAsset, ImageAsset, VideoAsset

MAX_AUDIO_BYTES = 128 * 1024 * 1024
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_VIDEO_BYTES = 64 * 1024 * 1024


def resolve_audio_asset(root: Path, asset: AudioAsset) -> Path:
    # Validate again for callers that use model_copy instead of construction.
    asset = AudioAsset.model_validate_json(asset.model_dump_json())
    return _resolve_asset(root, asset, MAX_AUDIO_BYTES, "audio")


def resolve_image_asset(root: Path, asset: ImageAsset) -> Path:
    """Check exact PNG bytes and bounded declared dimensions; no image decode.

    Before compositing, a trusted renderer must separately validate decoded
    frames. This is not an import endpoint or hostile-file decoder sandbox.
    """
    asset = ImageAsset.model_validate_json(asset.model_dump_json())
    return _resolve_asset(root, asset, MAX_IMAGE_BYTES, "image")


def resolve_video_asset(root: Path, asset: VideoAsset) -> Path:
    """Resolve the exact bytes; the trusted renderer separately checks codec and frames."""
    asset = VideoAsset.model_validate_json(asset.model_dump_json())
    return _resolve_asset(root, asset, MAX_VIDEO_BYTES, "video")


def _check_png_header(header: bytes, asset: ImageAsset) -> None:
    if (len(header) != 33 or header[:8] != b"\x89PNG\r\n\x1a\n"
            or header[8:16] != b"\x00\x00\x00\x0dIHDR"):
        raise ValueError("invalid local image PNG header")
    width, height = struct.unpack(">II", header[16:24])
    crc = struct.unpack(">I", header[29:33])[0]
    if ((width, height) != (asset.width, asset.height)
            or zlib.crc32(header[12:29]) != crc):
        raise ValueError("local image PNG dimensions or header mismatch")


def _resolve_asset(root: Path, asset: AudioAsset | ImageAsset | VideoAsset, limit: int, kind: str) -> Path:
    root = Path(root)
    if not root.is_absolute() or not root.is_dir() or root.resolve() != root:
        raise ValueError("canonical local asset directory required")
    path = root / (asset.sha256 + "." + asset.format)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("asset path unavailable")
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
                raise ValueError(f"invalid local {kind} asset size or type")
            digest = hashlib.sha256()
            count = 0
            if isinstance(asset, ImageAsset):
                header = handle.read(33)
                _check_png_header(header, asset)
                digest.update(header)
                count = len(header)
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
        raise ValueError(f"local {kind} asset unavailable") from exc
    return path
