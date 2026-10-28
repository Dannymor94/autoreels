"""M171: исходники под человеческими именами (владелец 2026-10-28). Без --do только показывает.
    .venv/bin/python handoff/m171/rename_sources.py [--do]
Для каждой пары «старый стем → новый»:
  видео (по содержимому, resolve_source) → <новое имя><расширение> в той же папке; ярлыки в inputs*/ перевешиваются;
  manifests/<старый>.json → <новый>.json (git mv) с полями source / source_path;
  transcripts/<старый>.*, transcripts/_archive/<старый>/, reviews/<старый>.* и <старый>_*, data/cache/<старый>.*,
  data/cache/scenario/<старый>.*, reels-out/<старый>/ → новое имя; в reviews — строки «# source:» и поле source в
  *.review.json. Ручной манифест PXL_20260729_085910095_34f06abf (исходника нет) не трогается: имя prew_isaev_danny
  получает рабочая сжатая копия PXL_20260729_copy."""
import json, os, subprocess, sys
from pathlib import Path

MAP = {
    "IMG_6848": "prew_isaev_anna",
    "PXL_20260729_copy": "prew_isaev_danny",
    "Pxl 20260621 122006193": "day_yoga_p1",
    "Pxl 20260621 112938952": "day_yoga_p2",
    "2026-08-08 10h 59m 38s": "disko_beach_p1",
    "2026-08-08 11h 42m 49s": "disko_beach_p2",
    "2026-08-08 09h 33m 14s": "disko_beach_p3",
}
DO = "--do" in sys.argv
sys.path.insert(0, "src")
from autoreels.core.models import Manifest  # noqa: E402
from autoreels.local.render import resolve_source  # noqa: E402

ops: list[tuple[str, Path, Path]] = []
edits: list[Path] = []


def plan_move(kind, a: Path, b: Path):
    if b.exists():
        sys.exit(f"СТОП: уже есть {b}")
    ops.append((kind, a, b))


for old, new in MAP.items():
    mp = Path(f"manifests/{old}.json")
    if not mp.is_file():
        sys.exit(f"СТОП: нет {mp}")
    m = Manifest.model_validate_json(mp.read_text(encoding="utf-8"))
    try:
        src = resolve_source(m, "inputs").resolve()
    except Exception as e:  # noqa: BLE001
        sys.exit(f"СТОП: {old}: исходник не найден ({e})")
    plan_move("видео", src, src.with_name(new + src.suffix))
    plan_move("манифест", mp, Path(f"manifests/{new}.json"))
    for d, pats in (("transcripts", [f"{old}.*"]), ("reviews", [f"{old}.*", f"{old}_*"]),
                    ("data/cache", [f"{old}.*"]), ("data/cache/scenario", [f"{old}.*"])):
        for pat in pats:
            for f in sorted(Path(d).glob(pat.replace("[", "[[]"))):
                if f.is_file():
                    plan_move(d, f, f.with_name(new + f.name[len(old):]))
    for d in (Path("transcripts/_archive") / old, Path("reels-out") / old, Path("reviews/_archive") / old):
        if d.is_dir():
            plan_move("папка", d, d.with_name(new))

for kind, a, b in ops:
    print(f"  {kind}: {a} → {b.name}")
print(f"=== операций: {len(ops)}")
if not DO:
    print("DRY RUN — ничего не изменено")
    sys.exit(0)

links = [p for d in ("inputs", "inputs-archive") for p in Path(d).iterdir() if p.is_symlink()] \
    if Path("inputs").is_dir() else []
targets = {p: Path(os.readlink(p)) for p in links}
for kind, a, b in ops:
    if kind == "манифест":
        subprocess.run(["git", "mv", str(a), str(b)], check=True)
    else:
        a.rename(b)
# manifests: source / source_path; reviews: «# source:» and review.json «source»
video_new = {a: b for k, a, b in ops if k == "видео"}
for old, new in MAP.items():
    mp = Path(f"manifests/{new}.json")
    d = json.loads(mp.read_text(encoding="utf-8"))
    oldsrc = Path(d.get("source", ""))
    d["source"] = str(oldsrc.with_name(new + oldsrc.suffix)) if oldsrc.name else new
    if d.get("source_path"):
        sp = Path(d["source_path"])
        d["source_path"] = str(sp.with_name(new + sp.suffix))
    mp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for f in Path("reviews").glob(f"{new}*"):
        if f.suffix == ".txt":
            t = f.read_text(encoding="utf-8")
            t2 = t.replace(f"# source: manifests/{old}.json", f"# source: manifests/{new}.json")
            if t2 != t:
                f.write_text(t2, encoding="utf-8"); edits.append(f)
        elif f.name.endswith(".review.json"):
            j = json.loads(f.read_text(encoding="utf-8"))
            s = Path(j.get("source", ""))
            if s.stem == old:
                j["source"] = d["source"]
                if j.get("source_path"):
                    j["source_path"] = d.get("source_path", j["source_path"])
                f.write_text(json.dumps(j, ensure_ascii=False) + "\n", encoding="utf-8"); edits.append(f)
# symlinks pointing at a renamed video → new name, same folder
for p, t in targets.items():
    tt = (p.parent / t).resolve() if not t.is_absolute() else t
    if tt in video_new:
        nb = video_new[tt]
        p.unlink()
        (p.parent / nb.name).symlink_to(nb)
        print(f"  ярлык: {p.name} → {nb.name}")
print(f"СДЕЛАНО: переименовано {len(ops)}, правок внутри файлов {len(edits)}")
