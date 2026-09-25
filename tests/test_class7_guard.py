"""Class 7 guard: bare Segment/Word construction outside authorized factory locations."""
import re
from pathlib import Path

_SRC = Path(__file__).parent.parent / "src" / "autoreels"

# Allowed (file_relative_to_src, optional line substring for disambiguation)
_ALLOWED = {
    "cloud/edit.py",
    "cloud/transcribe.py",
    "core/models.py",         # effective_segments default fallback
    "__main__.py:3947",       # reel.cold_open factory
}

_PATTERN = re.compile(r"(?<!\w)(Segment|Word|_Segment|_Seg)\s*\(")

# Lines that are clearly not constructions (import, class def, type hint, isinstance)
_SKIP = re.compile(r"^\s*(from |import |class |def |#|.*isinstance\(|.*Optional\[|.*type\[)")


def _violations():
    hits = []
    for py in sorted(_SRC.rglob("*.py")):
        rel = py.relative_to(_SRC).as_posix()
        # Whole-file allowlist
        if rel in _ALLOWED:
            continue
        for lineno, raw in enumerate(py.read_text().splitlines(), 1):
            line = raw.strip()
            if _SKIP.match(raw):
                continue
            # Strip inline comments
            code = raw.split("#")[0]
            if not _PATTERN.search(code):
                continue
            # Per-line allowlist
            key = f"{rel}:{lineno}"
            if key in _ALLOWED:
                continue
            hits.append(f"{rel}:{lineno}: {line}")
    return hits


def test_no_bare_model_construction_outside_factories():
    violations = _violations()
    assert not violations, (
        "Bare Segment/Word construction found outside allowed factories:\n"
        + "\n".join(f"  {v}" for v in violations)
    )
