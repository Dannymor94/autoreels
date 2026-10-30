"""M181: advance widths of a font file → config/fonts/<name>.json for subtitle and plate line fitting
(local/subtitles.py font_metrics). Needs fontTools only here, once (`pip install fonttools` in any venv);
the project reads the JSON.

Usage: python tools/font_widths.py "/System/Library/Fonts/Supplemental/Arial Bold.ttf" config/fonts/Arial-Bold.json
"""
import json
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

CHARS = ("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
         "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя"
         "0123456789 .,:;!?…-–—«»\"'()/%+=№#&*")

src, dst = sys.argv[1], sys.argv[2]
font = TTFont(src)
cmap = font.getBestCmap()
hmtx = font["hmtx"]
widths = {}
for c in CHARS:
    g = cmap.get(ord(c))
    if g is not None:
        widths[c] = hmtx[g][0]
upm = font["head"].unitsPerEm
caps = [widths[c] for c in "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯ" if c in widths]
out = {"source": Path(src).name, "units_per_em": upm, "default": max(caps) if caps else upm, "widths": widths}
Path(dst).parent.mkdir(parents=True, exist_ok=True)
Path(dst).write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
print(f"{dst}: {len(widths)} glyphs, units_per_em {upm}, default {out['default']}")
