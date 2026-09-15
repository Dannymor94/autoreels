"""Tests for memtrace cross-platform safety and import-sweep for Unix-only modules."""
from __future__ import annotations

import importlib
import pkgutil
import sys
import types
from unittest.mock import patch


# ---------------------------------------------------------------------------
# memtrace: safe when `resource` is absent
# ---------------------------------------------------------------------------

def test_memtrace_imports_without_resource():
    """Importing core.memtrace with resource absent must not raise."""
    # Remove cached module so the import runs fresh
    for key in list(sys.modules):
        if "memtrace" in key:
            del sys.modules[key]

    with patch.dict(sys.modules, {"resource": None}):
        import autoreels.core.memtrace  # noqa: F401  must not raise


def test_mark_noop_when_disabled(monkeypatch):
    """mark() is a no-op (returns None, no output) when AUTOREELS_MEMTRACE is unset."""
    monkeypatch.delenv("AUTOREELS_MEMTRACE", raising=False)

    for key in list(sys.modules):
        if "memtrace" in key:
            del sys.modules[key]

    import autoreels.core.memtrace as mt
    # Reload so _ENABLED is re-evaluated against the monkeypatched env
    importlib.reload(mt)

    result = mt.mark("test-label")
    assert result is None


def test_mark_returns_none_when_resource_absent(monkeypatch):
    """mark() degrades to a no-op (0 RSS) when resource is unavailable."""
    monkeypatch.setenv("AUTOREELS_MEMTRACE", "1")

    for key in list(sys.modules):
        if "memtrace" in key:
            del sys.modules[key]

    with patch.dict(sys.modules, {"resource": None}):
        import autoreels.core.memtrace as mt
        importlib.reload(mt)
        result = mt.mark("test-label")  # must not raise, returns None

    assert result is None


# ---------------------------------------------------------------------------
# Import sweep: every autoreels module imports cleanly with Unix-only modules
# blocked. If this fails on CI/Windows, it means a new unconditional Unix-only
# import was added — fix it before merging.
# ---------------------------------------------------------------------------

_UNIX_ONLY = {
    "resource", "fcntl", "termios", "pwd", "grp",
    "curses", "readline", "pty", "tty", "crypt",
}


def test_no_unix_only_imports_on_main_path():
    """All autoreels modules import without Unix-only stdlib modules available."""
    # Build a fake-absent mapping for every Unix-only module
    blocked = {name: None for name in _UNIX_ONLY}

    # Remove all autoreels modules from cache so imports run fresh
    for key in list(sys.modules):
        if key.startswith("autoreels"):
            del sys.modules[key]

    failed = []
    with patch.dict(sys.modules, blocked):
        import autoreels
        pkg_path = autoreels.__path__
        for info in pkgutil.walk_packages(pkg_path, prefix="autoreels."):
            try:
                importlib.import_module(info.name)
            except ImportError as exc:
                # Only flag if the error names a blocked module
                if any(name in str(exc) for name in _UNIX_ONLY):
                    failed.append((info.name, str(exc)))
            except Exception:
                # Other errors (missing env vars, etc.) are not our concern here
                pass

    assert not failed, "Unix-only imports found:\n" + "\n".join(
        f"  {mod}: {err}" for mod, err in failed
    )
