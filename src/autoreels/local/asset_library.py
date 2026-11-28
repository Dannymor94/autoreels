"""Dedicated local synthetic asset catalog. No HTTP, network or owner-media intake."""
from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import TypeAdapter

from autoreels.core.models import AudioAsset, ImageAsset, VideoAsset
from .assets import (
    MAX_AUDIO_BYTES, MAX_IMAGE_BYTES, MAX_VIDEO_BYTES,
    resolve_audio_asset, resolve_image_asset, resolve_video_asset,
)

Asset = AudioAsset | ImageAsset | VideoAsset
_ADAPTER = TypeAdapter(Asset)
_LIMITS = {"wav": MAX_AUDIO_BYTES, "png": MAX_IMAGE_BYTES, "mp4": MAX_VIDEO_BYTES}
_RESOLVERS = {"wav": resolve_audio_asset, "png": resolve_image_asset, "mp4": resolve_video_asset}
_RECORD = re.compile(r"[0-9a-f]{64}\.(wav|png|mp4)\.asset\.json")


def _root(root: Path) -> Path:
    root = Path(root)
    if not root.is_absolute() or not root.is_dir() or root.resolve()!=root:
        raise ValueError("canonical dedicated asset library required")
    return root


def _descriptor(asset: Asset) -> Asset:
    asset = _ADAPTER.validate_json(asset.model_dump_json())
    if asset.rights != "synthetic":
        raise ValueError("only synthetic asset intake is enabled")
    return asset


def _name(asset: Asset) -> str:
    return asset.sha256+"."+asset.format


def _read_record(path: Path) -> Asset:
    if path.is_symlink() or not path.is_file() or path.stat().st_size>4096:
        raise ValueError("invalid asset catalog record")
    asset = _descriptor(_ADAPTER.validate_json(path.read_bytes()))
    if path.name != _name(asset)+".asset.json":
        raise ValueError("asset catalog identity mismatch")
    return asset


def list_assets(root: Path) -> tuple[Asset,...]:
    """Stable catalog of registered assets; validate bytes at every read."""
    root = _root(root)
    paths = sorted(p for p in root.iterdir() if _RECORD.fullmatch(p.name))
    result=[]
    for path in paths:
        asset=_read_record(path)
        _RESOLVERS[asset.format](root,asset)
        result.append(asset)
    return tuple(result)


def _signature(st):
    return st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns


def import_asset(root: Path, source: Path, asset: Asset) -> Asset:
    """Trusted local caller chooses one synthetic file and supplies its descriptor.

    Exact hash, size and PNG header are checked, not full decoding or legal
    rights. Never modify the source or overwrite registered bytes/metadata.
    """
    root=_root(root)
    asset=_descriptor(asset)
    source=Path(source)
    if (not source.is_absolute() or source.resolve()!=source
            or source.suffix.lower()!="."+asset.format or source.is_relative_to(root)):
        raise ValueError("explicit canonical external asset file required")
    name=_name(asset)
    record=root/(name+".asset.json")
    destination=root/name
    if record.exists() or record.is_symlink():
        if _read_record(record)!=asset:
            raise ValueError("asset descriptor already bound")
        _RESOLVERS[asset.format](root,asset)
        return asset
    flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0)
    try:
        # Same-filesystem exclusive hard links publish complete files only.
        with TemporaryDirectory(prefix=".intake-",dir=root) as temp:
            stage=Path(temp)
            staged=stage/name
            fd=os.open(source,flags)
            with os.fdopen(fd,"rb") as src, staged.open("xb") as dst:
                before=os.fstat(src.fileno())
                if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<=_LIMITS[asset.format]:
                    raise ValueError("invalid selected asset size or type")
                digest=hashlib.sha256()
                count=0
                while block:=src.read(1024*1024):
                    count+=len(block)
                    if count>before.st_size:
                        raise ValueError("selected asset changed")
                    digest.update(block)
                    dst.write(block)
                if (count!=before.st_size or digest.hexdigest()!=asset.sha256
                        or _signature(before)!=_signature(os.fstat(src.fileno()))
                        or _signature(before)!=_signature(source.lstat())):
                    raise ValueError("selected asset identity mismatch")
                dst.flush()
                os.fsync(dst.fileno())
            _RESOLVERS[asset.format](stage,asset)
            try:
                os.link(staged,destination,follow_symlinks=False)
            except FileExistsError:
                pass
            _RESOLVERS[asset.format](root,asset)
            metadata=stage/"descriptor.json"
            with metadata.open("x",encoding="utf-8") as handle:
                handle.write(asset.model_dump_json())
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(metadata,record,follow_symlinks=False)
            except FileExistsError:
                if _read_record(record)!=asset:
                    raise ValueError("asset descriptor already bound")
    except OSError as exc:
        raise ValueError("local asset intake unavailable") from exc
    return asset
