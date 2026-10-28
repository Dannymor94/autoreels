"""M177: the m176 clips the new arl auto rules would not have built — a label clip repeating a kept one (more than
autocut.combined_overlap_max of its seconds, montage first) or a label clip with a short shot. Same functions as
arl auto (autoreels.__main__._auto_repeats, the plan's «short shot» warnings). Dry run by default: prints the list;
--do moves those clips' files (rNN.* — video, post, caption, transcript) into reels-out/<S>/_gate/<gate>/_excluded/.
Usage (project root): python exclude.py GATE [--do]"""
import shutil, sys
from pathlib import Path

from autoreels import __main__ as cli
from autoreels.core.models import Manifest

gate, do = sys.argv[1], "--do" in sys.argv
r0 = cli.load_r0_config(Path("config/r0.yaml"))
mx = r0.autocut.combined_overlap_max
total = 0
for S in ("disko_beach_p1", "disko_beach_p2", "disko_beach_p3", "day_yoga_p1", "day_yoga_p2",
          "prew_isaev_anna", "prew_isaev_danny"):
    reels = Manifest.model_validate_json(Path(f"reviews/{S}_{gate}.review.json").read_text(encoding="utf-8")).reels
    short = [(r.id, w) for r in reels if "montage" not in (r.flags or [])
             for w in (r.warnings or []) if w.startswith("short shot")][:]
    seen = {i for i, _ in short}
    rep = cli._auto_repeats([r for r in reels if r.id not in seen], mx)
    out = sorted({i: w for i, w in short + rep}.items())
    vdir = Path("reels-out") / S / "_gate" / gate
    print(f"{S}: клипов {len(reels)}, убрать {len(out)}")
    for rid, why in out:
        print(f"  {rid}: {why[:120]}")
        if do:
            (vdir / "_excluded").mkdir(exist_ok=True)
            for f in vdir.glob(f"{rid}.*"):
                shutil.move(str(f), str(vdir / "_excluded" / f.name))
    total += len(out)
print(f"ВСЕГО убрать: {total}" + (" — перенесены в _excluded/" if do else " (пробный прогон, --do переносит)"))
