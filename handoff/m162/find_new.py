"""M162: видео, которых ещё нет ни в одном манифесте (сравнение по содержимому, как у рендера). Ничего не пишет.
Ищет в inputs/, inputs-archive/ и в папках, откуда читались исходники (`source_path` манифестов, внешний диск).
    .venv/bin/python handoff/m162/find_new.py [доп. папка …]   → список путей новых видео в handoff/m162/new.txt"""
import glob, json, sys
from pathlib import Path
from autoreels.core import state

EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts"}
known_partial, known_full, dirs = set(), set(), {Path("inputs"), Path("inputs-archive")}
for p in glob.glob("manifests/*.json"):
    if any(s in p for s in (".blocks", ".discarded", ".failed")):
        continue
    try:
        m = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    sha = m.get("source_sha256") or ""
    (known_partial if m.get("source_hash_scheme") == "partial-p1" else known_full).add(sha)
    if m.get("source_path"):
        dirs.add(Path(m["source_path"]).parent)
dirs |= {Path(a) for a in sys.argv[1:]}
print("папки:", ", ".join(str(d) for d in sorted(dirs)))
new, seen = [], set()
for d in sorted(dirs):
    if not d.is_dir():
        print(f"  нет папки (диск не подключён?): {d}")
        continue
    for f in sorted(d.iterdir()):
        if f.suffix.lower() not in EXT or not f.is_file():
            continue
        r = f.resolve()
        if r in seen or r.stat().st_size < 10 * 1024 * 1024:     # ярлыки и копии одного файла — мимо
            continue
        seen.add(r)
        if state.file_sha256_partial(r) in known_partial:
            continue
        if known_full and state.file_sha256(r) in known_full:
            continue
        new.append(str(r))
        print(f"  НОВОЕ: {r}  ({r.stat().st_size // 2**20} МБ)")
Path("handoff/m162/new.txt").write_text("\n".join(new) + ("\n" if new else ""), encoding="utf-8")
print(f"=== новых видео: {len(new)}")
