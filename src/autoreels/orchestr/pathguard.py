"""Static local path containment; no symlink aliases or special files.

The local root and its processes are trusted. Not a defense against a malicious
local user racing filesystem operations; remote callers cannot write paths.
"""
from pathlib import Path


def safe_path(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
        if any(part in ("..", ".") for part in relative.parts) or root.is_symlink():
            return False
        cursor = root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                return False
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
