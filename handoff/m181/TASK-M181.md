# TASK M181 (окно MAIN, Mac): плашка не вылезает за край + вернуть «похожие, но другие» клипы + замер крючков

Файлы — ветка `handoff`, папка `handoff/m181/`: `TASK-M181.md`, `m181-fonts.patch`, `hooks.py`. Около 20 минут, рендер одного клипа.

## Зачем
Владелец о prew_isaev_anna m176:
1. **r11** — плашка «КАК ПРИВИВАЮТСЯ ЖИЗНЕННЫЕ ЦЕННОСТИ» вылезла за оба края; «тексты могут вылезать за края, 1 раз появилось».
   - Причина: ширина строки считается как «число букв × 72 × 0,55» (`config/subtitles.yaml char_width_ratio`). Для жирных заглавных Arial это узко: 25 букв по оценке 990 px (влезает в 1000), на деле около 1300 px.
   - Патч: строки субтитров, плашки и выноски подгоняются по настоящим ширинам букв шрифта — таблица `config/fonts/Arial-Bold.json`, её пишет `tools/font_widths.py` из файла шрифта. Пустое `font_metrics` = прежняя оценка (тест).
2. **«Почему удалили ролики? Похожи, но идея другая».** В m177 убирались клипы разметки, у которых больше 30 % секунд звучат в другом клипе.
   - 15 из 22 совпадали на 82–100 % — это тот же самый кусок видео.
   - 7 совпадали на 32–67 % — общий кусок и другая мысль.
   - Порог → 0,8 (`autocut.combined_overlap_max`): эти 7 возвращаются.
3. **«r03 и r14 — начало пустое; раньше крючки были лучше, сейчас пустые».** Нужен замер: у каких клипов m176 нет крючка (холодного старта) и что было в m157/m163. Правка — после замера.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. `--install`, `arl auto` не запускать. `reviews/*_answer*.txt`, `manifests/` не трогать.
3. Ничего не удалять: только перенос из `_excluded/` обратно.
4. Рендер один за раз; pytest — не во время рендера.

## Шаг 1. Таблица ширин шрифта, патч, тесты, коммит
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m181; mkdir -p handoff/m181
git apply --check handoff/m181/m181-fonts.patch && git apply handoff/m181/m181-fonts.patch && echo applied
python3 -m venv /tmp/m181ft && /tmp/m181ft/bin/pip install -q fonttools && /tmp/m181ft/bin/python tools/font_widths.py "/System/Library/Fonts/Supplemental/Arial Bold.ttf" config/fonts/Arial-Bold.json
.venv/bin/python -c "
import json; m=json.load(open('config/fonts/Arial-Bold.json')); w=m['widths']; u=m['units_per_em']
for t in ('КАК ПРИВИВАЮТСЯ ЖИЗНЕННЫЕ','ЦЕННОСТИ'): print(t, round(sum(w.get(c,m['default']) for c in t)*72/u), 'px')"
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests config tools && git commit -m "Subtitles (M181): lines fitted by the font's real advance widths (config/fonts/Arial-Bold.json, tools/font_widths.py) — prew_isaev_anna r11's plate ran off both edges; autocut.combined_overlap_max 0.8 (owner: similar clips with another idea stay)" && git push && git log --oneline -1
rm -rf /tmp/m181ft
```
Ожидается:
- `applied`;
- `config/fonts/Arial-Bold.json: N glyphs` (N ≥ 150);
- «КАК ПРИВИВАЮТСЯ ЖИЗНЕННЫЕ» — больше 1000 px (подтверждает причину);
- pytest — всё прошло, кроме известных пяти (`test_menu_bash` под нагрузкой — отдельно);
- коммит запушен.

Файла шрифта по этому пути нет — найти: `fc-match -f '%{file}\n' 'Arial:bold'`. Не нашёлся — СТОП.

## Шаг 2. Вернуть 7 «похожих, но других»
```bash
.venv/bin/python handoff/m177/exclude.py m176 | tee handoff/m181/exclude_new.txt
.venv/bin/python - <<'PY' | tee handoff/m181/restore.txt
import re, shutil
from pathlib import Path
keep, cur = {}, None
for ln in Path("handoff/m181/exclude_new.txt").read_text(encoding="utf-8").splitlines():
    m = re.match(r"(\S+): клипов", ln)
    if m: cur = m.group(1); keep[cur] = set(); continue
    m = re.match(r"  (r\d+):", ln)
    if m and cur: keep[cur].add(m.group(1))
for S, still in keep.items():
    ex = Path("reels-out") / S / "_gate" / "m176" / "_excluded"
    if not ex.is_dir(): continue
    back = sorted({f.name.split(".")[0] for f in ex.glob("r*.mp4")} - still)
    for rid in back:
        for f in ex.glob(f"{rid}.*"):
            shutil.move(str(f), str(ex.parent / f.name))
    print(f"{S}: возвращены {', '.join(back) or '—'}; остались в _excluded: {', '.join(sorted(still)) or '—'}")
PY
```
Ожидается: возвращены 7 клипов:
- disko_beach_p3: r02, r13, r18, r20;
- day_yoga_p1: r02;
- prew_isaev_anna: r08, r10.

В `_excluded` остаются совпадающие на ≥ 80 % и с коротким планом.

## Шаг 3. Замер крючков
```bash
.venv/bin/python handoff/m181/hooks.py > handoff/m181/hooks.txt; grep -E "^######|^== " handoff/m181/hooks.txt
grep -A40 "######## prew_isaev_anna" handoff/m181/hooks.txt | head -80
```
Ожидается: по каждому источнику две строки «== m157/m163» и «== m176»: клипов, сборок / разметки, с крючком. Дальше по клипу: крючок, плашка, начало.

## Шаг 4. Проверка r11
```bash
arl render --manifest reviews/prew_isaev_anna_m176.review.json --reels 11 --gate m181 --encoder hevc_videotoolbox 2>&1 | tail -4 | tee handoff/m181/render.txt
grep -h "Title" reels-out/prew_isaev_anna/_gate/m181/*.ass 2>/dev/null | head -3
```
Ожидается: рендер без `[ERROR]`; в строке Title плашка разбита на строки (`\N`), каждая уже кадра.

## Шаг 5. Сетка
Вернувшиеся клипы — в сетку (`grid2.py` ставит их в конец):
- переставить в `export/crosspost/schedule.csv` по смыслу (правила m171, «связь» заполнить);
- `python handoff/m174/grid2.py m176 --from m176`;
- выгрузка `arl crosspost` для трёх источников, как в m177 шаг 3.

## Шаг 6. Отчёт
`handoff/m181/REPORT.md`: коммит, pytest, ширины из шага 1, `restore.txt`, итоги `hooks.txt` (строки «==» по всем источникам), `render.txt`, вывод `grid2.py`.
`bash handoff/bin/report.sh m181 hooks.txt restore.txt exclude_new.txt render.txt`

Владельцу — две строки:
- «плашка r11 — reels-out/prew_isaev_anna/_gate/m181/r11.mp4; 7 клипов вернулись в m176 и в сетку»;
- «замер крючков у ассистента».

Статус: IMPLEMENTED, GATE PENDING.
