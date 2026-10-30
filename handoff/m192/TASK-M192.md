# TASK M192 (окно MAIN, Mac + gamebox): слепое сравнение «эталон ассистента против m183» — 20 клипов на лист ревью

Файлы — ветка `handoff`, папка `handoff/m192/`: `TASK-M192.md`, `ab.py` (отбор и черновики), `ab_score.py` (итог после оценок). Отчёт — только на русском.

Две части:
- **Часть A** — сейчас: отбор, применение без установки, рендер в гейт `ab192`, листы ревью. Около 40 минут, из них рендер — большая часть. LLM нет.
- **Часть B** — когда владелец вернёт файлы решений. Он скажет «m192 часть B».

## Зачем
По тексту (m191) нельзя сказать, чей выбор клипов лучше: эталон ассистента и m183 совпадают на 65 %, а текстовые метрики их не различают. Решает только взгляд владельца.

Берём:
- 10 клипов, которые есть **только** в эталоне `ref191` (сторона A);
- 10 клипов, которые есть **только** в `m183` (сторона B, только строки сборки `M`, чтобы по строке нельзя было узнать сторону).

Клипы рендерятся одним гейтом вперемешку, без пометки, чей клип. Оценки владельца дадут:
1. ответ, какой выбор лучше;
2. первые строки `reviews/verdicts.jsonl` — данные для будущего подбора весов формул.

Сборка, план и рендер не меняются. Кода в `src/` нет.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить.
   - **Исключение — шаг A3:** `--apply` отказал из-за конкретной строки `M` (названа метка `M<n>` или номер строки). Эту строку в `handoff/m192/<stem>_ab192.txt` закомментировать (`#! <строка>  ← apply: <причина>`) и повторить, не больше трёх раз. Строку в `key.csv` не трогать. Записать в отчёт.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`.
3. **НЕ МЕНЯТЬ:** `src/`, `config/`, `prompts/`, `tools/`, `manifests/`, `transcripts/`, чужие файлы в `reviews/`. Без `--install`. Коммитов в `main` нет.
4. **Слепота.** Владельцу не показывать `key.csv` и не писать в чат, какой клип чей. Сколько клипов каждой стороны в каком источнике — тоже не писать. В отчёт ключ не переписывать: `key.csv` уходит в ветку `handoff` файлом (ассистент читает его сам).
5. Рендер — только в `reels-out/<stem>/_gate/ab192/` (так делает `--gate`).
6. gamebox: озвучку не трогать, замок ждёт сам. Если ожидание замка дольше 30 минут или `--remote` падает до начала рендера (нет связи) — рендерить на Mac: та же команда без `--remote`, с `--encoder hevc_videotoolbox`. Так и написать в отчёте.
7. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.
8. Итог части A — «RENDERED, WAITING FOR OWNER». Части B — «MEASURED». Гейт не объявлять.

## Часть A

### A0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m192
bash handoff/bin/take.sh m191 >/dev/null; ls -1 handoff/m191/*_ref191.txt | wc -l
ls -1 reviews/*_ref191.review.json reviews/*_m183.review.json | wc -l
```
Ожидается:
- ветка `main`, рабочая копия чистая (кроме `handoff/`), последний коммит — M191 (`7ce87c9`) или новее;
- 7 файлов `_ref191.txt`;
- 14 файлов `review.json` (по 7 каждого гейта).

### A1. Отбор и черновики
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python handoff/m192/ab.py 2>&1 | tee handoff/m192/ab.txt
grep -c '^M' handoff/m192/*_ab192.txt
```
Ожидается:
- `кандидатов: только в эталоне ~22, только в m183 (строки M) …` — второе число не меньше 10. Если меньше 10 — не СТОП: скрипт возьмёт сколько есть, назвать в отчёте;
- `выбрано: 20 (сторона A 10, сторона B 10)`;
- черновики только для источников, где есть выбранные клипы; сумма строк `M` = 20.

### A2. Сохранить прежние файлы
```bash
cd /Users/danny/Documents/autoreels
mkdir -p handoff/m192/bak; touch handoff/m192/.t0; sleep 1
for f in handoff/m192/*_ab192.txt; do S=$(basename "$f" _ab192.txt)
  for g in reviews/"$S".review*; do [ -e "$g" ] && cp -p "$g" handoff/m192/bak/ && echo "сохранён $g"; done
done
```

### A3. Применить без установки
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
for f in handoff/m192/*_ab192.txt; do S=$(basename "$f" _ab192.txt)
  echo "== $S"
  arl blocks --apply "$f" > "handoff/m192/apply_${S}.txt" 2>&1; echo "код $?"
  grep -E '^manifest →|\[ERROR\]' "handoff/m192/apply_${S}.txt" | head -8
  if [ -f "reviews/${S}.review.json" ]; then
    mv "reviews/${S}.review.json" "reviews/${S}_ab192.review.json"
    find reviews -maxdepth 1 -name "$S.review.*" -newer handoff/m192/.t0 -type f | while read -r g; do mv "$g" "${g/.review./_ab192.review.}"; done
  fi
done 2>&1 | tee handoff/m192/apply_all.txt
for g in handoff/m192/bak/*; do [ -e "$g" ] && cp -p "$g" reviews/ && echo "возвращён $(basename "$g")"; done
find reviews manifests transcripts calibrations -newer handoff/m192/.t0 -type f | sort
git status -sb | head -5
```
Ожидается:
- по каждому источнику `код 0` и `manifest → … (N reels, selection_source=human)`, где N — число строк `M` в его черновике (минус закомментированные по правилу 1);
- в списке «изменено» только `reviews/<stem>_ab192.review*`;
- `git status` чистый вне `handoff/`.

### A4. Рендер в гейт `ab192`
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
for f in handoff/m192/*_ab192.txt; do S=$(basename "$f" _ab192.txt)
  N=$(.venv/bin/python -c "import json,sys;print(len(json.load(open(sys.argv[1]))['reels']))" "reviews/${S}_ab192.review.json")
  echo "== $S: $N клипов"
  arl render --manifest "reviews/${S}_ab192.review.json" --gate ab192 --reels "1-$N" --remote 2>&1 | tail -6
  ls -1 "reels-out/$S/_gate/ab192/"*.mp4 2>/dev/null | wc -l
done 2>&1 | tee handoff/m192/render.txt
```
Ожидается:
- по каждому источнику число `.mp4` в `_gate/ab192/` равно N;
- в выводе рендера нет `[ERROR]` и `FAILED`.

Рендер одного клипа упал → не СТОП: перерендерить только его (`--reels <k>`) один раз; снова упал — записать в отчёт и идти дальше. `--remote` недоступен → правило 6.

### A5. Листы ревью
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
for f in handoff/m192/*_ab192.txt; do S=$(basename "$f" _ab192.txt)
  echo "== $S"
  arl review-sheet "$S" --review "$f" --manifest-file "reviews/${S}_ab192.review.json" --gate ab192 --preview none 2>&1 | tail -4
  ls -la "reels-out/$S/_gate/ab192/_review.html"
done 2>&1 | tee handoff/m192/sheets.txt
```
Ожидается:
- по каждому источнику файл `_review.html`;
- в выводе нет клипов «без строки» (без кнопок решения). Если есть — назвать в отчёте, какие (это проверка привязки клипа к строке).

### A6. Отчёт части A
`handoff/m192/REPORT.md`:
```
M192 часть A — RENDERED, WAITING FOR OWNER
Отбор: кандидатов A <n>, B <n>; выбрано 20 (по 10) | иначе: …
Применено: <источники>, клипов <N>; закомментировано по правилу 1: <stem M<n> — причина> | нет
Рендер: <где — gamebox / Mac (почему)>; клипов <N>/<N>; упавшие: … | нет
Листы: <пути _review.html по источникам>; клипы без кнопок: … | нет
reviews/ после: только *_ab192.review* — да/нет
```
```bash
bash handoff/bin/report.sh m192 ab.txt key.csv apply_all.txt render.txt sheets.txt $(cd handoff/m192 && ls *_ab192.txt)
```
**Владельцу в чат — только это** (без ключа и без разбивки по сторонам):
```
m192: 20 клипов готовы к слепой оценке, листы:
<путь _review.html по каждому источнику>
На каждом клипе — «оставить / убрать / переделать», причины одним касанием, при желании — замечание.
Скачайте файл решений с каждого листа (<stem>_decisions.txt) и скажите «m192 часть B».
```

## Часть B (после слов владельца «m192 часть B»)
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
ls -1 ~/Downloads/*_decisions*.txt
for f in handoff/m192/*_ab192.txt; do S=$(basename "$f" _ab192.txt)
  D=$(ls -t ~/Downloads/"${S}"_decisions*.txt 2>/dev/null | head -1)
  if [ -n "$D" ]; then echo "== $S ← $D"; arl review-apply "$D" 2>&1 | tail -4; else echo "== $S: файла решений нет"; fi
done 2>&1 | tee handoff/m192/apply_decisions.txt
.venv/bin/python handoff/m192/ab_score.py 2>&1 | tee handoff/m192/ab_score.txt
wc -l reviews/verdicts.jsonl
```
Ожидается:
- по каждому источнику `review-apply` пишет `оценки: записано N → reviews/verdicts.jsonl`;
- `ab_score.txt`: `оценок ab192: K из 20`, две строки сторон A и B с долей «оставить», список по клипам.

Файла решений для источника нет → не СТОП, назвать его в отчёте. `review-apply` отказал → **СТОП** с выводом.

Дописать в `handoff/m192/REPORT.md`:
```
M192 часть B — MEASURED
Решения применены: <источники>; нет файла: …
<вывод ab_score.txt целиком>
verdicts.jsonl: <строк>
```
```bash
bash handoff/bin/report.sh m192 apply_decisions.txt ab_score.txt
```
Владельцу в чат — 2 строки: «m192: оставлено A x из 10, B y из 10» (теперь ключ раскрывается) и одна главная причина «убрать» у каждой стороны.
