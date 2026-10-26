"""M149: какой манифест у файла ответа без '# source:'. Пробует кандидатов (по имени), применяет файл ответа
к каждому (`arl blocks <манифест> --apply <файл>`), сравнивает клипы с ручным манифестом manifests/<S>.json
(он и был установлен из этого файла): доля клипов манифеста, у которых в результате есть клип с началом ±3 с.
review.json каждого кандидата сохраняется до и возвращается после. Пишет handoff/m149/pairs.txt («T<TAB>S»)
для лучшего совпадения ≥ 0.6, остальное — в вывод.
    .venv/bin/python handoff/m149/pairs.py
"""
import glob, json, pathlib, re, shutil, subprocess, sys

H = pathlib.Path("handoff/m149")
mans = {}
for p in glob.glob("manifests/*.json"):
    S = pathlib.Path(p).stem
    if re.search(r"\.(blocks|discarded|failed)", S) or "copy" in S:
        continue
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    if d.get("selection_source") == "human" or any(r.get("selection_source") == "human" for r in d.get("reels", [])):
        mans[S] = [r["start"] for r in d.get("reels", [])]
print("ручные манифесты:", ", ".join(f"{S} ({len(v)})" for S, v in sorted(mans.items())))


def digits(s):
    return re.sub(r"\D", "", s)


def candidates(T):
    t = T.lower()
    out = []
    for S in mans:
        sl, sd = S.lower(), digits(S)
        if t.startswith("img") and digits(T) and digits(T) in sd: out.append(S)
        elif t.startswith("pxl") and "review" in t and S.startswith("PXL_"): out.append(S)
        elif t.startswith("pxl") and digits(T) and (digits(T) in sd) and sl.startswith("pxl "): out.append(S)
        elif t.startswith("lec") and digits(T) and digits(T)[:2] + "h " + digits(T)[2:] in S: out.append(S)
    if not out:   # нет подсказки в имени: все Pxl/лекции соответствующего вида
        if t.startswith("pxl"): out = [S for S in mans if S.lower().startswith("pxl")]
        elif t.startswith("lec"): out = [S for S in mans if S.startswith("20")]
    if t.startswith("pxl") and digits(T) == "0621":   # 0621 — дата, не время: оба Pxl этого дня
        out = [S for S in mans if S.lower().startswith("pxl 20260621")]
    return out


def apply(T, S):
    R = pathlib.Path(f"reviews/{S}.review.json"); B = H / f"{S}.review.json.pairs"
    had = R.is_file()
    if had: shutil.copy2(R, B)
    log = H / f"pairs.{T}.{re.sub(r'[^A-Za-z0-9]', '_', S)}.txt"
    rc = subprocess.run([sys.executable, "-m", "autoreels", "blocks", f"manifests/{S}.json", "--apply",
                         f"reviews/{T}_answer.txt"], stdout=open(log, "w"), stderr=subprocess.STDOUT).returncode
    starts = None
    if rc == 0 and R.is_file():
        starts = [r["start"] for r in json.load(open(R, encoding="utf-8"))["reels"]]
    if had:
        shutil.copy2(B, R)
        if R.read_bytes() != B.read_bytes(): sys.exit(f'!! {R} не возвращён — СТОП')
        B.unlink()
    elif R.is_file():
        R.unlink()
    return rc, starts


pairs = []
for A in sorted(glob.glob("reviews/*_answer.txt")):
    T = pathlib.Path(A).name[: -len("_answer.txt")]
    best = (0.0, None)
    for S in candidates(T):
        rc, st = apply(T, S)
        if st is None:
            print(f"  {T} → {S}: rc={rc}"); continue
        ref = mans[S]
        hit = sum(1 for a in ref if any(abs(a - b) <= 3.0 for b in st)) / max(1, len(ref))
        print(f"  {T} → {S}: rc=0, клипов {len(st)} (в манифесте {len(ref)}), совпало начал {hit:.0%}")
        if hit > best[0]: best = (hit, S)
    if best[1] and best[0] >= 0.6:
        pairs.append(f"{T}\t{best[1]}"); print(f"{T}: → {best[1]}")
    else:
        print(f"{T}: пары нет (лучшее {best[0]:.0%})")
(H / "pairs.txt").write_text("\n".join(pairs) + ("\n" if pairs else ""), encoding="utf-8")
print(f"=== пар: {len(pairs)}")
