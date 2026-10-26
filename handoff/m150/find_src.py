"""M150: из какого файла разметки установлен клип r06 ручного манифеста. Ничего не меняет (review.json возвращается).
    .venv/bin/python handoff/m150/find_src.py "PXL_20260729_085910095_34f06abf" 'reviews/PXL_review*answer*.txt' 'reviews/PXL_review*.txt'
Печатает r06 манифеста (начало, конец, open_thought, предупреждения, последние слова), затем для каждого файла:
rc `arl blocks manifests/<S>.json --apply <файл>`, первая строка ошибки, есть ли r06 с началом ±1 с и концом ±1 с, его open_thought."""
import glob, json, pathlib, shutil, subprocess, sys

S, pats = sys.argv[1], sys.argv[2:]
H = pathlib.Path("handoff/m150")
man = json.load(open(f"manifests/{S}.json", encoding="utf-8"))
ref = {r["id"]: r for r in man["reels"]}.get("r06")
if ref is None:
    sys.exit(f"в manifests/{S}.json нет r06")
words = [w["word"] for w in (ref.get("subtitles") or [])]
print(f"манифест r06: {ref['start']:.2f}–{ref['end']:.2f}, open_thought={ref.get('open_thought')}, …{' '.join(words[-10:])}")
for w in ref.get("warnings") or []:
    print(f"   ⚠ {w}")
files = sorted({f for p in pats for f in glob.glob(p) if not f.endswith(".bak") and "_m150" not in f})
R = pathlib.Path(f"reviews/{S}.review.json"); B = H / f"{S}.review.json.find"
for f in files:
    had = R.is_file()
    if had: shutil.copy2(R, B)
    log = H / f"find.{pathlib.Path(f).stem}.txt"
    rc = subprocess.run([sys.executable, "-m", "autoreels", "blocks", f"manifests/{S}.json", "--apply", f],
                        stdout=open(log, "w"), stderr=subprocess.STDOUT).returncode
    res = ""
    if rc == 0 and R.is_file():
        reels = json.load(open(R, encoding="utf-8"))["reels"]
        m = [r for r in reels if abs(r["start"] - ref["start"]) <= 1.0 and abs(r["end"] - ref["end"]) <= 1.0]
        res = (f"клипов {len(reels)}; r06 манифеста ↔ {m[0]['id']} open_thought={m[0].get('open_thought')}" if m
               else f"клипов {len(reels)}; клипа как r06 манифеста нет")
    else:
        err = [l for l in log.read_text(encoding="utf-8", errors="replace").splitlines() if "error" in l.lower()]
        res = err[0][:160] if err else "(без строки error — смотреть лог)"
    if had:
        shutil.copy2(B, R)
        if R.read_bytes() != B.read_bytes(): sys.exit(f"!! {R} не возвращён — СТОП")
        B.unlink()
    elif R.is_file():
        R.unlink()
    print(f"{f}: rc={rc}; {res}")
