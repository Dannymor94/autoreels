"""M166: почему рендер отбросил клип («last word cut» / «first word cut»). Ничего не пишет.
    .venv/bin/python handoff/m166/edges.py "<источник>" <тег> r13 r15 …
Для каждого клипа: первое и последнее слово субтитров, границы плана (первое окно, последнее окно, prerolled),
что о тех же словах говорит карта речи (audible_start / audible_end) и выравнивание, начало следующей речи."""
import json, sys
from pathlib import Path

S, tag, rids = sys.argv[1], sys.argv[2], sys.argv[3:]
rv = json.loads(Path(f"reviews/{S}_{tag}.review.json").read_text(encoding="utf-8"))
sm = json.loads(Path(f"transcripts/{S}.speechmap.json").read_text(encoding="utf-8"))
words = {round(w["t0"] * 1000): w for w in sm.get("words", [])}
al = {}
ap = Path(f"transcripts/{S}.align.json")
if ap.is_file():
    for w in json.loads(ap.read_text(encoding="utf-8")).get("words", []):
        if w.get("t0") is not None:
            al[round(float(w["t0"]) * 1000)] = w
for r in rv["reels"]:
    if r["id"] not in rids:
        continue
    subs = [w for w in (r.get("subtitles") or []) if any(c.isalnum() for c in w["word"])]
    segs = r.get("segments") or [{"start": r["start"], "end": r["end"]}]
    f, l = subs[0], subs[-1]
    print(f"== {S} {r['id']}: planned={r.get('planned')} окон {len(segs)} | первое окно {segs[0]['start']:.3f}–{segs[0]['end']:.3f}"
          f" prerolled={segs[0].get('prerolled')} | последнее окно {segs[-1]['start']:.3f}–{segs[-1]['end']:.3f}")
    for tag2, w in (("первое", f), ("последнее", l)):
        m = words.get(round(w["t0"] * 1000)) or {}
        a = al.get(round(w["t0"] * 1000)) or {}
        print(f"   {tag2} «{w['word']}»: whisper {w['t0']:.3f}–{w['t1']:.3f} | карта as={m.get('audible_start')} ae={m.get('audible_end')}"
              f" | выравнивание {a.get('start')}–{a.get('end')}")
    print(f"   план: tail_last_word_end={r.get('tail_last_word_end')} tail_next_word_start={r.get('tail_next_word_start')}"
          f" subtitle_gate={r.get('subtitle_gate')} | предупреждения: {r.get('warnings')}")
