# TASK M190 (окно MAIN, Mac): выгрузка текстов 7 источников для эталонной разметки ассистента

Файл — ветка `handoff`, папка `handoff/m190/`: `TASK-M190.md`. Около 10 минут, без рендера, без LLM, без сети (кроме push). Код не меняется. Отчёт — только на русском.

## Зачем
Эталонную («ручную») разметку всех 7 источников делает ассистент в чате. Владелец, 2026-10-30: «ручную разметку будешь делать ты». По ней линейка M188 сравнит автоматику m183 с эталоном: что эталон берёт и автоматика теряет, по каким метрикам они расходятся.

Расшифровки, интонация и карта говорящих лежат только на Mac (не в git). Поэтому агент выгружает для каждого источника:
1. **Файл для разметки в компактном формате** — `arl blocks <stem> --review --compact --out …`. Это тот же формат, что для разметки в чате: нумерация предложений `N.k`, паузы `⏸`, тон конца `↗`, строка `# fingerprint:`.
2. **Нумерацию текстом** — `arl blocks-text <stem>`: время начала каждой фразы и отсеянные блоки `x1…`, которые можно брать в сборку.
3. **Карту говорящих** `transcripts/<stem>.speakers.json`, если она есть: в продакшн ролики идут без реплик ведущего.

Карту мыслей (`map.json`) и черновики автоматики m183 **не выгружать**: эталон делается независимо, без подсказок автоматики.

## Правила
1. Любая команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`.
3. **НЕ МЕНЯТЬ:** `src/`, `config/`, `prompts/`, `tools/`, `reviews/`, `transcripts/`.
   - `arl blocks` всегда переписывает `manifests/<stem>.blocks.json` (он в git). При тех же расшифровке и конфиге файл выходит тем же. Если после выгрузки `git status` показывает изменения в `manifests/` — вернуть их (`git checkout -- manifests/`) и написать в отчёте, какие файлы менялись (`git diff --stat`, первые 20 строк диффа одного из них).
   - Никаких коммитов в `main`.
4. Файлы пишутся только в `handoff/m190/`. `--out` обязателен, иначе команда перепишет `reviews/<stem>.review.md`.
5. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.
6. Итог — «EXPORTED». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m190
ls -1 manifests/{prew_isaev_anna,prew_isaev_danny,day_yoga_p1,day_yoga_p2,disko_beach_p1,disko_beach_p2,disko_beach_p3}.json
```
Ожидается:
- рабочая копия чистая (кроме `handoff/`), ветка `main`, последний коммит — M188 (`141fdfa`) или новее;
- семь манифестов на месте. Нет хотя бы одного — **СТОП**.

## Часть 1. Выгрузка
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
for S in prew_isaev_anna prew_isaev_danny day_yoga_p1 day_yoga_p2 disko_beach_p1 disko_beach_p2 disko_beach_p3; do
  echo "== $S"
  arl blocks "$S" --review --compact --out "handoff/m190/${S}.review.md" 2>&1 | tail -3
  arl blocks-text "$S" > "handoff/m190/${S}.text.txt" 2>"handoff/m190/${S}.text.err"; echo "blocks-text: код $?"
  [ -s "handoff/m190/${S}.text.err" ] || rm -f "handoff/m190/${S}.text.err"
  if [ -f "transcripts/${S}.speakers.json" ]; then cp "transcripts/${S}.speakers.json" "handoff/m190/${S}.speakers.json"; echo "speakers: есть"; else echo "speakers: нет"; fi
done 2>&1 | tee handoff/m190/export.txt
git status -sb | head -10
```
Ожидается:
- по каждому источнику: `handoff/m190/<stem>.review.md` и `handoff/m190/<stem>.text.txt`, оба непустые; `blocks-text: код 0`;
- в каждом `.review.md` есть строка `# fingerprint:` и строки вида `N | 40.1s | …`;
- `git status` не показывает изменений вне `handoff/` (иначе — правило 3).

Проверка:
```bash
cd /Users/danny/Documents/autoreels
for f in handoff/m190/*.review.md; do
  printf "%-40s fp:%s  блоков:%s  ↗:%s  строк текста:%s\n" "$(basename "$f")" \
    "$(grep -c '^# fingerprint:' "$f")" "$(grep -cE '^[0-9]+ \|' "$f")" "$(grep -o '↗' "$f" | wc -l | tr -d ' ')" \
    "$(wc -l < "${f%.review.md}.text.txt" | tr -d ' ')"
done | tee handoff/m190/check.txt
du -ch handoff/m190/* | tail -1
```
Ожидается:
- семь строк, `fp:1` у каждой, блоков больше 0;
- `↗` больше 0 там, где есть `transcripts/<stem>.prosody.json`. Где `↗` 0 — назвать в отчёте, есть ли у источника `prosody.json` (не СТОП).

## Часть 2. Отправка
```bash
cd /Users/danny/Documents/autoreels
cat > handoff/m190/REPORT.md <<'EOF'
M190 — EXPORTED
Коммит main: <git log --oneline -1>
Источники (файл | блоков | ↗ | speakers): <из check.txt и export.txt>
manifests/ после выгрузки: без изменений | изменились: <файлы>, возвращены
Размер выгрузки: <du>
Пропущено/не совпало: …
EOF
# заполнить REPORT.md фактическими значениями, затем:
bash handoff/bin/report.sh m190 $(cd handoff/m190 && ls *.review.md *.text.txt *.speakers.json *.err export.txt check.txt 2>/dev/null)
```
Ожидается: `отчёт m190 отправлен в ветку handoff`.

Владельцу в чат — одна строка: «m190: тексты 7 источников выгружены в handoff, ассистент может размечать».
