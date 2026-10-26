# TASK M147 (окно MAIN, Mac): пред-ролл включён; громкость одним усилением на источник — сравнение на слух

Файлы — ветка `handoff`, папка `handoff/m147/`: `TASK-M147.md`, `m147-loudness.patch`. Нужен `handoff/m143/ramp.py` и манифест `reviews/IMG_6848_m146b.review.json` (из m146). Около 20 минут, один рендер.

## Зачем
Владелец о m146: «как будто разницы особо нет, но B ровнее (плавнее)». Поэтому пред-ролл включается: `start_preroll_sec 0.06`, `start_fade_in_sec 0.03`. Вторая причина «тихого начала» по m143: однопроходный `loudnorm` подстраивается в первую секунду клипа, у IMG_6848 первые 0.3 с тише на 2.4 dB. Патч добавляет `render.yaml audio_processing.loudnorm_mode`:
- `dynamic` — как раньше, по умолчанию;
- `source` — громкость всего источника измеряется один раз, все его клипы получают одно усиление до `target_lufs` и ограничитель пика.
Тесты `tests/test_m147_loudness.py` (3), запись в REEL_SPEC.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. pytest только в шаге 1. `config/render.yaml` для рендера правится только командой задачи и потом возвращается. `--install`, `arl auto` не запускать.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m147
git apply --check handoff/m147/m147-loudness.patch && git apply handoff/m147/m147-loudness.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests config docs && git commit -m "Render (M147): pre-roll on (owner on m146b: «ровнее»); loudnorm_mode source — one gain per source + a peak limiter (dynamic stays the default)" && git push && git log --oneline -1
```
Ожидается: `applied`; pytest — все прошли; коммит запушен.

## Шаг 2. Тот же манифест m146b — громкость одним усилением, рендер в `_gate/m147/`
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m147
N=$(.venv/bin/python -c "import json;print(len(json.load(open('reviews/IMG_6848_m146b.review.json'))['reels']))"); echo "клипов: $N"
sed -i '' 's/^  loudnorm_mode: .*/  loudnorm_mode: source/' config/render.yaml
arl render --manifest reviews/IMG_6848_m146b.review.json --reels 1-$N --gate m147 --encoder hevc_videotoolbox 2>&1 | tee handoff/m147/render.txt | grep -E "громкость источника|ERROR|ошибка" ; tail -3 handoff/m147/render.txt
git checkout config/render.yaml; git diff --stat config/
.venv/bin/python handoff/m143/ramp.py reviews/IMG_6848_m146b.review.json reels-out/IMG_6848/_gate/m146b 2>&1 | tail -1 | sed 's/^/m146b (dynamic): /' | tee handoff/m147/ramp.txt
.venv/bin/python handoff/m143/ramp.py reviews/IMG_6848_m146b.review.json reels-out/IMG_6848/_gate/m147 2>&1 | tail -1 | sed 's/^/m147 (source):  /' | tee -a handoff/m147/ramp.txt
arl review-sheet IMG_6848 --review reviews/IMG_6848_auto_m126-scen.txt --manifest-file reviews/IMG_6848_m146b.review.json --gate m147 --preview none 2>&1 | tail -2
```
Ожидается: строка «громкость источника: … LUFS → усиление …»; рендер без ошибок; `git diff --stat config/` пуст; в `ramp.txt` две строки «медиана по клипам: 0–0.3 с … dB». У m147 провала начала быть не должно (около 0 dB). Лист `reels-out/IMG_6848/_gate/m147/_review.html`.

## Шаг 3. Отчёт
`handoff/m147/REPORT.md`: коммит, pytest, строка громкости источника, `ramp.txt`, путь листа.
`bash handoff/bin/report.sh m147 ramp.txt`
Владельцу — три строки:
- «пред-ролл включён»;
- «провал начала: dynamic X dB → source Y dB»;
- «сравнить на слух начало клипов: _gate/m146b (как сейчас) и _gate/m147 (одно усиление на источник) — если в m147 первая фраза слышнее и громкость ровная, скажи “включай громкость по источнику”».

Статус: IMPLEMENTED, GATE PENDING.
