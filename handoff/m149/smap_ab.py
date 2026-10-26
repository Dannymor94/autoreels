"""M149: файлы ответов владельца, применённые в трёх состояниях — что изменила карта речи.

before — как сейчас (флаг выключен, карты у части источников нет);
off    — карта построена у всех, флаг выключен;
on     — карта построена, флаг speech_map включён.
Читает reviews/<S>_m149<state>.review.json и handoff/m149/apply.<state>.<T>.txt по списку handoff/m149/pairs.txt
(строки «T<TAB>S»: T — имя файла ответа без _answer.txt, S — стем манифеста).
Печатает по источнику: клипов, ошибок apply, изменившихся клипов и наибольший сдвиг границы;
пишет handoff/m149/render_list.txt: «S<TAB>номера» — до двух клипов с наибольшим сдвигом before→on.
"""
import json, pathlib, re, sys

H = pathlib.Path("handoff/m149")
STATES = ("before", "off", "on")


def load(S, st):
    p = pathlib.Path(f"reviews/{S}_m149{st}.review.json")
    if not p.is_file():
        return None
    return {r["id"]: r for r in json.loads(p.read_text(encoding="utf-8"))["reels"]}


def errors(T, st):
    p = H / f"apply.{st}.{T}.txt"
    if not p.is_file():
        return None
    return sum(1 for l in p.read_text(encoding="utf-8", errors="replace").splitlines()
               if "[ERROR]" in l or "error:" in l.lower())


def edges(r):
    segs = r.get("segments") or [{"start": r["start"], "end": r["end"]}]
    out = [round(s["start"], 3) for s in segs] + [round(s["end"], 3) for s in segs]
    for s in segs:
        for a, b in (s.get("close_intervals") or []):
            out += [round(a, 3), round(b, 3)]
    if r.get("subtitle_gate") is not None:
        out.append(round(r["subtitle_gate"], 3))
    return out


def diff(a, b):
    """(изменился ли, наибольший сдвиг, с), сравниваются ВСЕ клипы обеих сторон."""
    if a is None or b is None:
        return True, float("inf")
    ea, eb = edges(a), edges(b)
    if len(ea) != len(eb):
        return True, float("inf")
    sh = max((abs(x - y) for x, y in zip(ea, eb)), default=0.0)
    return sh > 0.0005, sh


tot = {"src": 0, "clips": 0, "chg_off": 0, "chg_on": 0, "worse": 0}
rl = []
for line in (H / "pairs.txt").read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    T, S = line.split("\t")
    d = {st: load(S, st) for st in STATES}
    e = {st: errors(T, st) for st in STATES}
    n = {st: (len(d[st]) if d[st] is not None else None) for st in STATES}
    tot["src"] += 1
    print(f"== {T}  ({S})")
    print(f"   клипов before/off/on: {n['before']}/{n['off']}/{n['on']};  ошибок apply: {e['before']}/{e['off']}/{e['on']}")
    if d["before"] is None or d["on"] is None:
        print("   нет сравнения (apply не дал review.json)")
        if d["before"] is not None and d["on"] is None:
            tot["worse"] += 1
        continue
    worse = (e["on"] or 0) > (e["before"] or 0) or n["on"] != n["before"]
    tot["worse"] += int(worse)
    tot["clips"] += n["before"]
    shifts = []
    for st, key in (("off", "chg_off"), ("on", "chg_on")):
        if d[st] is None:
            continue
        ids = sorted(set(d["before"]) | set(d[st]))
        ch = [(rid, *diff(d["before"].get(rid), d[st].get(rid))) for rid in ids]
        ch = [(rid, sh) for rid, c, sh in ch if c]
        tot[key] += len(ch)
        mx = max((sh for _, sh in ch), default=0.0)
        print(f"   before→{st}: изменилось {len(ch)} из {len(ids)}, наибольший сдвиг {mx:.3f} с"
              + ("" if not ch else "  [" + ", ".join(f"{rid} {sh:.2f}" for rid, sh in ch[:12]) + (" …" if len(ch) > 12 else "") + "]"))
        if st == "on":
            shifts = ch
    if worse:
        print("   ХУЖЕ: ошибок больше или клипов другое число")
    top = sorted(shifts, key=lambda x: -x[1])[:2]
    nums = [str(int(re.sub(r"\D", "", rid))) for rid, _ in top if re.sub(r"\D", "", rid)]
    if nums:
        rl.append(f"{S}\t{','.join(nums)}")
(H / "render_list.txt").write_text("\n".join(rl) + ("\n" if rl else ""), encoding="utf-8")
print(f"=== ВСЕГО: источников {tot['src']}, клипов {tot['clips']}; изменилось before→off {tot['chg_off']}, before→on {tot['chg_on']}; "
      f"источников хуже {tot['worse']}")
