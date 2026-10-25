# TASK M146 (окно MAIN, Mac): пред-ролл склеенного начала — сравнение на слух

Файлы — ветка `handoff`, папка `handoff/m146/`: `TASK-M146.md`, `m146-preroll.patch`. Около 40 минут, почти всё — два рендера. Без платных моделей.

## Зачем
m143–m145: у 46 из 59 начал черновиков перед первым словом нет паузы, поэтому выбором начала их не починить. Владелец: «не слышно первой буквы», и на приём монтажёров сказал «давай». Это исключение из инварианта 10 по его решению, записано в CLAUDE.md. Патч:
- `start_pause_min: 0.15` включается (m145: склеенных начал 59 → 46, покрытие 40/66 как было; владелец — «давай»);
- `r0.yaml start_preroll_sec` (0 = выкл): склеенное первое слово клипа (и холодного старта) начинается на столько раньше, в хвосте предыдущего слова;
- `render.yaml audio_processing.start_fade_in_sec` (0 = выкл): звук клипа нарастает за это время, и хвост чужого слова не слышен как слово;
- тесты `tests/test_m146_preroll.py` (4), записи в REEL_SPEC и CLAUDE.md.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. pytest только в шаге 1. `reviews/IMG_6848.review.json` сохранить и вернуть. `config/*.yaml` правятся только командами задачи и в конце шага 2 возвращаются как в коммите. `--install`, `arl auto` не запускать.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m146
git apply --check handoff/m146/m146-preroll.patch && git apply handoff/m146/m146-preroll.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests config docs CLAUDE.md && git commit -m "Plan (M146): the editor's pre-roll of a glued first word (start_preroll_sec + start_fade_in_sec, off; owner's exception to invariant 10); start_pause_min 0.15 on (m145)" && git push && git log --oneline -1
```
Ожидается: `applied`; pytest — все прошли; коммит запушен.

## Шаг 2. Один черновик (сценарист m126, его слушал владелец) — без пред-ролла и с ним
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m146
R=reviews/IMG_6848.review.json; B=handoff/m146/IMG_6848.review.json.before; rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
arl blocks --apply reviews/IMG_6848_auto_m126-scen.txt --labeler auto > handoff/m146/apply-a.txt 2>&1; echo "A rc=$?"
cp "$R" reviews/IMG_6848_m146a.review.json
sed -i '' 's/^start_preroll_sec: .*/start_preroll_sec: 0.06/' config/r0.yaml
arl blocks --apply reviews/IMG_6848_auto_m126-scen.txt --labeler auto > handoff/m146/apply-b.txt 2>&1; echo "B rc=$?"
cp "$R" reviews/IMG_6848_m146b.review.json
if [ -f "$B" ]; then cp "$B" "$R" && cmp "$B" "$R" && echo "review.json возвращён"; else rm -f "$R" && echo "review.json не было — убран"; fi
.venv/bin/python - <<'PY' | tee handoff/m146/starts.txt
import json
a = {r["id"]: r for r in json.load(open("reviews/IMG_6848_m146a.review.json"))["reels"]}
b = {r["id"]: r for r in json.load(open("reviews/IMG_6848_m146b.review.json"))["reels"]}
moved = 0
for rid in sorted(a):
    def first(r):
        co = r.get("cold_open"); s = r.get("segments") or [{"start": r["start"]}]
        return float(co["start"]) if co else float(s[0]["start"])
    d = first(a[rid]) - first(b[rid]) if rid in b else None
    moved += bool(d and d > 0.005)
    print(f"{rid}: начало раньше на {d:.3f} с" if d is not None else f"{rid}: нет в B")
print(f"сдвинуто начал: {moved} из {len(a)}")
PY
N=$(.venv/bin/python -c "import json;print(len(json.load(open('reviews/IMG_6848_m146a.review.json'))['reels']))"); echo "клипов: $N"
arl render --manifest reviews/IMG_6848_m146a.review.json --reels 1-$N --gate m146a --encoder hevc_videotoolbox 2>&1 | tail -4
sed -i '' 's/^  start_fade_in_sec: .*/  start_fade_in_sec: 0.03/' config/render.yaml
arl render --manifest reviews/IMG_6848_m146b.review.json --reels 1-$N --gate m146b --encoder hevc_videotoolbox 2>&1 | tail -4
git checkout config/r0.yaml config/render.yaml; git diff --stat config/
arl review-sheet IMG_6848 --review reviews/IMG_6848_auto_m126-scen.txt --manifest-file reviews/IMG_6848_m146b.review.json --gate m146b --preview none 2>&1 | tail -2
```
Ожидается: оба `rc=0`; `review.json возвращён`; `starts.txt` — у склеенных клипов «начало раньше на 0.0xx с» (до 0.06), итог «сдвинуто начал: N»; два рендера без ошибок; `git diff --stat config/` пуст; лист `reels-out/IMG_6848/_gate/m146b/_review.html`.

## Шаг 3. Отчёт
`handoff/m146/REPORT.md`: коммит, pytest, `starts.txt`, пути гейтов.
`bash handoff/bin/report.sh m146 starts.txt`
Владельцу — три строки:
- «пред-ролл сдвинул N начал из M»;
- «сравнить на слух начало клипов: reels-out/IMG_6848/_gate/m146a/ (как было) и …/m146b/ (пред-ролл) — r01, r04 и любые другие»;
- «если в m146b первая буква слышна и обрывка чужого слова не слышно — скажи “включай пред-ролл”».

Статус: IMPLEMENTED, GATE PENDING.
