"""M179 diagnosis (run on gamebox from /mnt/data/autoreels): arl render with the integrity check recording its
stderr instead of deleting the clip. Usage: .venv/bin/python keep_render.py <arl render args…>
Prints «INTEGRITY <file>: <stderr>» for every clip the check would have deleted; the clips stay in the gate."""
import sys
import autoreels.local.render as R
from autoreels.__main__ import main

_orig = R._check_integrity
hits = []


def _keep(path, ffmpeg_bin):
    err = _orig(path, ffmpeg_bin)
    if err:
        hits.append((str(path), err))
    return ""


R._check_integrity = _keep
try:
    rc = main(["render", *sys.argv[1:]])
finally:
    for p, e in hits:
        print(f"INTEGRITY {p}: {e[:300]}")
    print(f"INTEGRITY total: {len(hits)}")
sys.exit(rc or 0)
