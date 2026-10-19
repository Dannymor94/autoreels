#!/usr/bin/env python3
"""M114 (замер, ничего не пишет): где на самом деле кончаются предложения — точки whisper.cpp, точки модели (M113),
паузы (карта речи) и интонация (prosody) — против концов Groq на тех же словах.

    .venv/bin/python handoff/m114/ends_by_sound.py <манифест> <src> <src-lp> [--root .]

<src>     — расшифровка whisper.cpp: transcripts/<stem>.<src>.transcript.json
<src-lp>  — она же с точками модели (arl tx-punct --by llm): те же слова, другие знаки
Groq — расшифровка, на которой построен манифест (как в arl tx-compare). Оценка — только на словах, совпавших с Groq.
Пауза после слова — по карте речи (transcripts/<stem>.speechmap.json), а не по зазорам Whisper (инвариант 9).
Интонация — transcripts/<stem>.prosody.json (посчитана по словам Groq): совпавшее слово берёт тон своего слова Groq.
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from bisect import bisect_left
from pathlib import Path

from autoreels.__main__ import _resolve_cached_transcript
from autoreels.cloud.txcheck import _TERMINAL, _norm
from autoreels.core.models import Manifest, Transcript
from autoreels.local.prosody import classify

PAUSES = (0.15, 0.3, 0.5, 0.7, 1.0)
WIN = 0.25          # окно поиска паузы вокруг стыка слов: время слов whisper.cpp неточное


def ends(w) -> bool:
    return w.word.rstrip().endswith(_TERMINAL)


def gaps_of(intervals) -> list[tuple[float, float]]:
    iv = sorted((float(a), float(b)) for a, b in intervals)
    return [(iv[k][1], iv[k + 1][0]) for k in range(len(iv) - 1) if iv[k + 1][0] > iv[k][1]]


def pause_after(gaps, starts, a: float, b: float) -> float:
    """Длина самой длинной тишины карты речи, задевающей окно [a, b]."""
    best = 0.0
    k = max(0, bisect_left(starts, a) - 1)
    while k < len(gaps) and gaps[k][0] <= b:
        g0, g1 = gaps[k]
        if g1 >= a:
            best = max(best, g1 - g0)
        k += 1
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("src")
    ap.add_argument("lp")
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    root = Path(a.root)
    mpath = root / "manifests" / f"{a.manifest}.json"
    man = Manifest.model_validate_json(mpath.read_text(encoding="utf-8"))
    stem, sha = mpath.stem, man.source_sha256
    tr = lambda tag: Transcript.model_validate_json(  # noqa: E731
        (root / "transcripts" / f"{stem}.{tag}.transcript.json").read_text(encoding="utf-8")).words
    L, P = tr(a.src), tr(a.lp)
    if [_norm(w.word).strip(".") for w in L] != [_norm(w.word).strip(".") for w in P]:
        print("ошибка: в <src-lp> другие слова, чем в <src>")
        return 1
    g = _resolve_cached_transcript(man, root / "data" / "cache")
    if g is None:
        print("ошибка: расшифровки манифеста в кэше нет")
        return 1
    G = g.words
    print(f"=== {stem}: слов whisper.cpp {len(L)}, Groq {len(G)} (provider {g.provider})")

    sm = json.loads((root / "transcripts" / f"{stem}.speechmap.json").read_text(encoding="utf-8"))
    if sm.get("source_sha256") not in (None, sha):
        print("ошибка: карта речи от другого источника")
        return 1
    gaps = gaps_of(sm.get("intervals") or [])
    starts = [x[0] for x in gaps]
    pr_path = root / "transcripts" / f"{stem}.prosody.json"
    tone_by_t0 = {}
    if pr_path.is_file():
        pr = json.loads(pr_path.read_text(encoding="utf-8"))
        if pr.get("source_sha256") in (None, sha):
            tone_by_t0 = {round(float(e["t0"]), 3): classify(e) for e in pr.get("words") or []}

    A = [(_norm(w.word).strip("."), i) for i, w in enumerate(L)]
    B = [(_norm(w.word).strip("."), j) for j, w in enumerate(G)]
    A = [x for x in A if x[0]]
    B = [x for x in B if x[0]]
    sm_ = difflib.SequenceMatcher(None, [x[0] for x in A], [x[0] for x in B], autojunk=False)
    pairs = []
    for tag, i1, i2, j1, j2 in sm_.get_opcodes():
        if tag == "equal":
            pairs += [(A[i1 + k][1], B[j1 + k][1]) for k in range(i2 - i1)]
    pairs = [(i, j) for i, j in pairs if i + 1 < len(L)]
    rows = []
    for i, j in pairs:
        rows.append({"i": i, "truth": ends(G[j]), "W": ends(L[i]), "P": ends(P[i]),
                     "pause": pause_after(gaps, starts, L[i].t1 - WIN, L[i + 1].t0 + WIN),
                     "tone": tone_by_t0.get(round(float(G[j].t0), 3), "нет")})
    n = len(rows)
    nt = sum(r["truth"] for r in rows)
    covered = sum(r["tone"] != "нет" for r in rows)
    print(f"совпавших слов {n}; концов Groq на них {nt} ({100 * nt / n:.1f} на 100 слов); "
          f"интонация есть у {100 * covered / n:.0f}% слов, тишин в карте речи {len(gaps)}")

    print("\n-- насколько признак отличает конец предложения (доля среди концов Groq / среди остальных слов)")
    for T in PAUSES:
        e = sum(r["pause"] >= T for r in rows if r["truth"]) / max(1, nt)
        o = sum(r["pause"] >= T for r in rows if not r["truth"]) / max(1, n - nt)
        print(f"   пауза ≥ {T:.2f} с: {100 * e:5.1f}% / {100 * o:5.1f}%")
    for tone in ("final", "unsure", "open", None):
        e = sum(r["tone"] == tone for r in rows if r["truth"]) / max(1, nt)
        o = sum(r["tone"] == tone for r in rows if not r["truth"]) / max(1, n - nt)
        print(f"   тон {str(tone):6}: {100 * e:5.1f}% / {100 * o:5.1f}%")
    for nm in ("W", "P"):
        e = sum(r[nm] for r in rows if r["truth"]) / max(1, nt)
        o = sum(r[nm] for r in rows if not r["truth"]) / max(1, n - nt)
        print(f"   {'точка whisper.cpp' if nm == 'W' else 'точка модели (M113)':18}: {100 * e:5.1f}% / {100 * o:5.1f}%")

    fin = lambda r: r["tone"] == "final"  # noqa: E731
    rules = [("whisper.cpp", lambda r: r["W"]), ("whisper.cpp + модель (M113)", lambda r: r["P"])]
    for T in PAUSES:
        rules.append((f"W + пауза ≥ {T}", lambda r, T=T: r["W"] or r["pause"] >= T))
    for T in PAUSES[:3]:
        rules.append((f"W + пауза ≥ {T} и тон final", lambda r, T=T: r["W"] or (r["pause"] >= T and fin(r))))
    for T in PAUSES[:3]:
        rules.append((f"W + модель и пауза ≥ {T}", lambda r, T=T: r["W"] or (r["P"] and r["pause"] >= T)))
    rules.append(("W + модель и тон final", lambda r: r["W"] or (r["P"] and fin(r))))
    rules.append(("W + модель и (пауза ≥ 0.3 или final)", lambda r: r["W"] or (r["P"] and (r["pause"] >= 0.3 or fin(r)))))
    print(f"\n-- правила (на 100 слов; совп. — доля концов Groq; точн. — доля своих концов, что есть у Groq; "
          f"добавлено — сверх whisper.cpp, и сколько из них у Groq)")
    print(f"   {'правило':40} {'на 100':>6} {'совп.':>6} {'точн.':>6} {'добавлено':>9} {'из них у Groq':>13}")
    for name, f in rules:
        sel = [r for r in rows if f(r)]
        both = sum(r["truth"] for r in sel)
        add = [r for r in sel if not r["W"]]
        add_ok = sum(r["truth"] for r in add)
        print(f"   {name:40} {100 * len(sel) / n:6.1f} {100 * both / max(1, nt):5.1f}% {100 * both / max(1, len(sel)):5.1f}% "
              f"{len(add):9d} {100 * add_ok / max(1, len(add)):12.1f}%")

    def show(name, f, k=8):
        add = [r for r in rows if f(r) and not r["W"]]
        if not add:
            return
        step = max(1, len(add) // k)
        print(f"\n-- примеры: {name} (каждый {step}-й из {len(add)}; ✓ — у Groq тоже конец)")
        for r in add[::step][:k]:
            i = r["i"]
            left = " ".join(w.word.strip() for w in L[max(0, i - 6):i + 1])
            right = " ".join(w.word.strip() for w in L[i + 1:i + 6])
            print(f"   {'✓' if r['truth'] else '✗'} …{left} ‖ {right}…  (пауза {r['pause']:.2f} с, тон {r['tone']})")
    show("пауза ≥ 0.5", lambda r: r["pause"] >= 0.5)
    show("модель и пауза ≥ 0.3", lambda r: r["P"] and r["pause"] >= 0.3)
    show("модель без паузы (< 0.15)", lambda r: r["P"] and r["pause"] < 0.15)
    return 0


if __name__ == "__main__":
    sys.exit(main())
