#!/usr/bin/env python3
"""M141 step A (its own venv): who speaks when — pyannote speaker diarization of each source with owner clips.

→ data/cache/m141/<stem>.diar.json  {"turns": [[start, end, "SPEAKER_00"], …]}  (kept; a rerun skips it).
The Hugging Face token is read from HF_TOKEN (environment or the project's .env) and never printed.
    ~/.venvs/m141/bin/python handoff/m141/diar.py [stem ...]
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

OUT = Path("data/cache/m141")


def token() -> str | None:
    if os.environ.get("HF_TOKEN"):
        return os.environ["HF_TOKEN"]
    env = Path(".env")
    if env.is_file():
        for ln in env.read_text(encoding="utf-8").splitlines():
            if ln.strip().startswith("HF_TOKEN="):
                return ln.split("=", 1)[1].strip().strip("'\"") or None
    return None


def find_source(name: str) -> Path | None:
    for d in ("inputs", "inputs-archive"):
        for p in Path(d).rglob("*"):
            if p.is_file() and p.name == Path(name).name:
                return p
    return None


def main(only) -> int:
    tok = token()
    if not tok:
        print("СТОП: нет HF_TOKEN (в окружении или .env). Владельцу: принять условия моделей "
              "pyannote/speaker-diarization-3.1 и pyannote/segmentation-3.0 на huggingface.co, создать токен "
              "(read) и дописать в .env строку HF_TOKEN=…")
        return 2
    import torch
    from pyannote.audio import Pipeline
    try:
        pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=tok)
    except TypeError:
        pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=tok)
    if pipe is None:
        print("СТОП: модель не выдана — условия на huggingface.co не приняты или токен без доступа")
        return 2
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    pipe.to(torch.device(dev))
    print(f"pyannote на {dev}")
    OUT.mkdir(parents=True, exist_ok=True)
    mans = []
    for mp in sorted(glob.glob("manifests/*.json")):
        try:
            m = json.load(open(mp, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(m, dict) and m.get("selection_source") == "human":
            mans.append((Path(mp).stem, m))
    for stem, m in mans:
        if only and stem not in only:
            continue
        dst = OUT / f"{stem}.diar.json"
        if dst.is_file():
            print(f"{stem}: уже есть")
            continue
        src = find_source(m.get("source", ""))
        if src is None:
            print(f"skip {stem}: source not found in inputs*/")
            continue
        wav = OUT / f"{stem}.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                       check=True)
        t = time.time()
        res = pipe(str(wav))
        ann = getattr(res, "speaker_diarization", res)
        turns = [[round(seg.start, 2), round(seg.end, 2), str(spk)] for seg, _, spk in ann.itertracks(yield_label=True)]
        dst.write_text(json.dumps({"stem": stem, "source_kind": m.get("source_kind"), "turns": turns}), encoding="utf-8")
        wav.unlink()
        print(f"{stem}: {len(turns)} реплик, говорящих {len({x[2] for x in turns})}, {time.time() - t:.0f} с")
    return 0


if __name__ == "__main__":
    sys.exit(main(set(sys.argv[1:])))
