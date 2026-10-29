# TASK M189 (окно MAIN, Mac): исправления по ревью кода и финальный чистовик в m189

Файлы — ветка `handoff`, папка `handoff/m189/`: `TASK-M189.md`, `m189-review.patch`, `seams.py`, `hooks.py`. Около 3 ч: патч и тесты 15 мин, перепрогон в фоне, выпуск 30 мин.

**Начни с новой сессии агента (`/clear`). Отчёт — только на русском.** Перед шагом 1: `git pull` и `bash handoff/bin/take.sh m189`.

m188 (линейка `tools/score_gate.py`) — отдельная задача, только замер. Порядок любой: если m188 уже выполнена, в шаге 4 есть сравнение гейтов; если нет — этот пункт пропускается.

## Зачем
Ревью кода перед выпуском нашло ошибки. Часть из них прямо видна на роликах:
1. **Шов без смены плана.** Если в окне была вырезка, закрытая сменой плана, следующий шов читал конец окна до вырезки. Получалось крупный → крупный на шве, то есть скачок кадра. То же бывало после подчистки коротких планов (M173): она шла позже, чем шов решал, каким планом начинать.
2. **Короткий крупный план снимался.** Иногда это был тот самый крупный, что закрывал шов или вырезку, или `c:` владельца. Теперь он удлиняется до порога.
3. **Крючок из части фразы показывал соседнее слово** в субтитрах, если Whisper начинал это слово внутри окна крючка.
4. **Длина крючка мерилась по Whisper, а не по звуку.** Отказ по длине не попадал в план, поэтому автоматика не брала следующий крючок, а в строке оставался `h:`, которого в ролике нет.

Мелочи:
- субтитры мерились строчными, а рисуются заглавными;
- учёт строк ломался после отсева клипов;
- пустой после отсева черновик считался успехом;
- после перенумерации у ролика оставался пост другого ролика;
- старая записка целостности переживала удачный рендер;
- кусок фразы мог кончаться на незаконченном предложении;
- бесплатный автомонтаж не получал крючков из части фразы и строгого начала;
- «мы» не считалось первым лицом, а «гость» было запрещено;
- перечисление имён («в Москве, Казани, Сочи») принималось за обращение;
- `combined_overlap_max: 0` выключал проверку вместо самого строгого режима;
- клип разметки мог получить крючок со склеенным началом.

Патч (поверх M187, 10 файлов):
- `cloud/plan.py`, `cloud/autocut.py`, `cloud/montage.py`, `cloud/postcopy.py`, `__main__.py`, `local/render.py`, `local/subtitles.py`, `docs/REEL_SPEC.md`;
- одна строка в `tests/test_m173_short_shot.py`: короткий крупный теперь удлиняется, а не снимается;
- новый `tests/test_m189_review.py` — 20 тестов, по одному на каждую ошибку. У ассистента каждый из них падает на коде M187 и проходит с патчем.

Выключенный `short_shot_sec` — прежний выход, кроме исправления 1. Шов после вырезки, закрытой сменой плана, теперь меняет план при любом флаге: это нарушение правила «на шве план меняется», а не новая фича. Весь прежний набор тестов проходит без изменений.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. `--install` не запускать. `reviews/*_answer*.txt` и `manifests/` не трогать. Гейт `m183` не трогать до шага 6.
3. Рендер один за раз. pytest — не во время рендера.
4. Псевдонима `arl` в оболочке агента нет: `arl() { .venv/bin/python -m autoreels "$@"; }` в начале каждого шага.

## Шаг 1. Замер до правки (по готовому m183)
```bash
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m189; mkdir -p handoff/m189
.venv/bin/python handoff/m189/seams.py reviews/*_m183.review.json | tee handoff/m189/seams_m183.txt | tail -1
```
Ожидается: строка `ВСЕГО: швов N, без смены плана K`. Любое K — результат замера, не СТОП.

## Шаг 2. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
shasum -a 256 handoff/m189/m189-review.patch | cut -c1-12          # c73f3455dc10
git apply --check handoff/m189/m189-review.patch && git apply handoff/m189/m189-review.patch && echo applied
.venv/bin/python -m pytest -q tests/test_m189_review.py | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -3
.venv/bin/python - <<'EOF'
from pathlib import Path
p = Path("PLAN.md"); s = p.read_text(encoding="utf-8")
row = ("| Ревью кода (M189) | перед чистовиком: на шве и на вырезке, закрытой сменой плана, план всегда меняется (планы окна "
       "и его вырезки считаются до следующего шва; короткий крупный удлиняется, не снимается); крючок из части фразы не "
       "показывает соседнее слово; `h:…@i-j-` — ошибка; длина крючка — по звуку, отказ виден автоматике; субтитры меряются "
       "заглавными; учёт строк после отсева, пустой черновик — ошибка; старый пост и записка целостности не переживают "
       "перерендер; бесплатный автомонтаж получает крючки из части фразы и строгое начало; «мы» — первое лицо, «гость» "
       "разрешён; перечисление имён — не обращение. Тесты `tests/test_m189_review.py` | M189 |\n")
key = "| Продакшн 2026-10-29 |"
assert key in s and "(M189)" not in s
p.write_text(s.replace(key, row + key, 1), encoding="utf-8"); print("PLAN.md: строка добавлена")
EOF
git add src tests docs PLAN.md && git commit -m "Review (M189): a seam or a masked cut always changes the shot (window spans tidied and cuts made before the next seam reads the end; a short close span is lengthened, never dropped); a clause hook shows only its words; h:@i-j- refused; hook cap on the sound, visible to the M61 fallback; capitals measured; accounting after the drop, an empty draft fails; stale post and integrity note go; clause hooks and strict starts on the free autocut path; «мы» first person; a list of names is no address" && git push && git log --oneline -1
```
Ожидается:
- хэш `c73f3455dc10`;
- `applied`;
- `test_m189_review.py`: **20 passed**;
- весь pytest прошёл. Число прошедших = было в m187 (2583) + 20 + тесты m188, если она выполнена. Упал хоть один — СТОП;
- `PLAN.md: строка добавлена`; коммит запушен.

## Шаг 3. Перепрогон всего в m189 (в фоне)
```bash
cd /Users/danny/Documents/autoreels
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
nohup .venv/bin/python -m autoreels auto "${S7[@]}" --gate m189 --tag m189 --encoder hevc_videotoolbox > handoff/m189/auto.txt 2>&1 &
echo "pid $!"
```
Проверять раз в 10 минут, пока в `auto.txt` не появится `=== auto: итог`. pytest в это время не запускать.

## Шаг 4. Замер после
```bash
cd /Users/danny/Documents/autoreels
sed -n '/=== auto: итог/,$p' handoff/m189/auto.txt | tee handoff/m189/itog.txt
.venv/bin/python handoff/m189/seams.py reviews/*_m189.review.json | tee handoff/m189/seams_m189.txt | tail -1
.venv/bin/python tools/measure_shots.py reviews/*_m189.review.json | tail -1 | tee handoff/m189/shots.txt
.venv/bin/python handoff/m189/hooks.py > handoff/m189/hooks.txt; grep -E "^######|^== " handoff/m189/hooks.txt
grep -c "убран из черновика" handoff/m189/auto.txt
[ -f tools/score_gate.py ] && .venv/bin/python tools/score_gate.py m189 --compare m183 2>&1 | tee handoff/m189/compare.txt || echo "m188 не выполнена — сравнение пропущено"
```
Ожидается:
- у всех 7 источников ✓ в итоге;
- `seams_m189.txt`: **без смены плана 0**. Не 0 — не СТОП: перечислить клипы из строки и проверить каждый глазами (`reels-out/<ист>/_gate/m189/rNN.mp4`, секунда шва);
- SLIVER 0;
- в `hooks.txt` у m189 «с крючком» не меньше, чем у m183 в сумме (32 из 69). Меньше — не СТОП, написать, у каких источников;
- номера клипов в каждой папке подряд: r01, r02, …

## Шаг 5. Посты, выгрузка, сетка, общий каталог
```bash
cd /Users/danny/Documents/autoreels; arl() { .venv/bin/python -m autoreels "$@"; }
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
for S in "${S7[@]}"; do d="reels-out/$S/_gate/m189"
  for k in 1 2; do miss=$(for f in "$d"/r[0-9]*.mp4; do b=$(basename "$f" .mp4); [ -f "$d/$b.post.txt" ] || echo "$b"; done | paste -sd, -)
    [ -z "$miss" ] && break; arl describe "$S" --gate m189 --reels "$miss" --force --llm sonnet 2>&1 | grep -E "^describe|не принято"; done
  echo "$S: клипов $(ls "$d"/r[0-9]*.mp4 | grep -v ERROR | wc -l), без поста: $(for f in "$d"/r[0-9]*.mp4; do b=$(basename "$f" .mp4); [ -f "$d/$b.post.txt" ] || echo "$b"; done | paste -sd, -)"
done | tee handoff/m189/posts.txt
mkdir -p ~/.Trash/autoreels-m189/export && mv export/crosspost/* ~/.Trash/autoreels-m189/export/ && cp ~/.Trash/autoreels-m189/export/schedule.csv export/crosspost/
for S in "${S7[@]}"; do d="reels-out/$S/_gate/m189"; R=$(ls "$d"/r[0-9]*.mp4 | grep -v ERROR | xargs -n1 basename | sed 's/\.mp4$//' | paste -sd, -)
  arl crosspost "$S" --gate m189 --reels "$R" 2>&1 | grep -E "клипов|пропущ"; done | tee handoff/m189/export.txt
.venv/bin/python tools/grid.py m189 --from m183 | tee handoff/m189/grid.txt
```
Ожидается:
- у каждого источника «без поста:» пусто, иначе перечислить;
- 7 строк «клипов N»;
- `grid.txt`: «в третьем лице: 0», «с хэштегом в заголовке: 0»; «выпали» и «новые» перечислены.

Новые клипы `grid.py` ставит в конец. Если новых больше 0: прочитать их посты и переставить каждый в `export/crosspost/schedule.csv` на место по смыслу (рядом с близким по теме, не больше трёх подряд из одного источника), заполнить «связь». Затем:
```bash
.venv/bin/python tools/grid.py m189 --from m189 | tee -a handoff/m189/grid.txt
[ -d export/publish ] && mv export/publish ~/.Trash/autoreels-m189/publish-m183
.venv/bin/python tools/publish_dir.py m189 --do | tee handoff/m189/publish.txt
cp export/crosspost/grid.csv handoff/m189/grid.csv
```
Ожидается:
- после второго `grid.py`: у каждого клипа «на месте», выпавших 0;
- `publish.txt`: «нет файла: 0», в `export/publish/` видео = числу строк сетки, постов столько же.

## Шаг 6. Старые гейты — в Корзину (только если шаги 3–5 прошли)
```bash
cd /Users/danny/Documents/autoreels
for d in reels-out/*/_gate/*; do [ "$(basename "$d")" = m189 ] && continue; S=$(basename "$(dirname "$(dirname "$d")")"); mkdir -p ~/.Trash/autoreels-m189/$S; mv "$d" ~/.Trash/autoreels-m189/$S/; done
ls reels-out/*/_gate/ | sort | uniq -c | tee handoff/m189/gates_after.txt
```
Ожидается: в `reels-out/<источник>/_gate/` у всех 7 осталась только `m189`. Корзину не очищать.

Затем в `PLAN.md`, в строке «Продакшн 2026-10-29»:
- дату заменить на 2026-10-30;
- `_gate/m183` → `_gate/m189`;
- числа клипов и крючков — на итоговые m189;
- `~/.Trash/autoreels-m183` → `~/.Trash/autoreels-m189`;
- в конце `M183, M185, M186` → `M189`.

```bash
git add PLAN.md && git commit -m "Docs (M189): production is _gate/m189" && git push && git log --oneline -1
```

## Шаг 7. Отчёт (на русском)
`handoff/m189/REPORT.md`:
- коммиты, число тестов (`test_m189_review.py` и всего);
- швы без смены плана: m183 → m189 (итоговые строки обоих `seams_*.txt`);
- `itog.txt`;
- клипов по источникам m183 → m189;
- крючки: строки «==» из `hooks.txt`;
- сколько клипов убрано из черновиков и по каким причинам (виды строк «убран из черновика»);
- вспышки (`shots.txt`);
- `compare.txt` или «пропущено»;
- `posts.txt`, `export.txt`, `grid.txt` (выпали, новые, куда поставлены), `publish.txt`;
- `gates_after.txt`.

```bash
bash handoff/bin/report.sh m189 seams_m183.txt seams_m189.txt itog.txt shots.txt hooks.txt grid.txt publish.txt gates_after.txt grid.csv
```

Владельцу — три строки:
- «чистовик: N клипов в reels-out/<источник>/_gate/m189, крючок у X из N; швов без смены плана K (в m183 — K0)»;
- «общий каталог — export/publish/, сетка — export/crosspost/grid.csv (с 2026-10-28)»;
- «старые гейты — в Корзине (~/.Trash/autoreels-m189)».

Статус: IMPLEMENTED, GATE PENDING.
