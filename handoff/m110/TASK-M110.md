# TASK M110 (окно MAIN, Mac + gamebox, без патча): проверка `arl dictate` — gamebox против Groq на одной минуте речи

Файлы — в ветке `handoff`, папка `handoff/m110/` (только эта задача). Отчёт — `handoff/m110/REPORT.md` и `bash handoff/bin/report.sh m110 gamebox.txt groq.txt sample_groq.txt`.

**Ставится поверх M109** (8363892). Одна сессия, без фоновых задач. Код не меняется.

## Зачем
В M108 `arl dictate` на минуте звука выдал 13 слов. В минуте лекции обычно 120–180 слов. Возможны две причины: в том куске почти не было речи, или whisper.cpp с отсевом тишины (VAD) выбрасывает речь. Проверяем на минуте сплошной речи из IMG_6848 и на том же куске из M108: расшифровка на gamebox против Groq.

## Правила
1. Любой шаг упал → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить. Расхождение чисел — не СТОП, это замер.
2. Перед стартом на Mac не должно идти других `arl`. pytest не запускать.
3. gamebox: озвучку не трогать. Если замок занят — `arl` сам ждёт (строка «gamebox занят … жду»).
4. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию `arl`. Блок запускать целиком.
5. В репозитории ничего не меняется: файлы только в `/tmp/` и `handoff/m110/`.
6. Итог — «MEASURED».

## Шаг 1. Минута речи IMG_6848: gamebox и Groq
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m110
git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
SHA=$(.venv/bin/python -c "import json; print(json.load(open('manifests/IMG_6848.json'))['source_sha256'])")
A="data/cache/$SHA.mp3"; ls -l "$A"
ffmpeg -v error -y -ss 600 -t 60 -i "$A" /tmp/m110.m4a
{
echo "== gamebox (whisper.cpp)"; arl dictate /tmp/m110.m4a --no-copy; cp /tmp/m110.txt handoff/m110/gamebox.txt
echo "== Groq"; arl dictate /tmp/m110.m4a --groq --no-copy; cp /tmp/m110.txt handoff/m110/groq.txt
echo "слов: gamebox $(wc -w < handoff/m110/gamebox.txt), Groq $(wc -w < handoff/m110/groq.txt)"
} 2>&1 | tee handoff/m110/run.txt
```
Ожидается:
- `ls` показывает mp3 (если файла нет — **СТОП**: нужен другой источник);
- оба прогона: `готово: N слов`; у gamebox — `gamebox: замок взят` и `замок отпущен`;
- строка `слов: gamebox X, Groq Y`.

## Шаг 2. Кусок из M108: что там на самом деле
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
{
if [ -f /tmp/dictate_test.m4a ]; then
  echo "== M108-кусок через Groq"; arl dictate /tmp/dictate_test.m4a --groq --no-copy; cp /tmp/dictate_test.txt handoff/m110/sample_groq.txt
  echo "слов Groq: $(wc -w < handoff/m110/sample_groq.txt) (gamebox в M108: 13)"
  ffmpeg -hide_banner -i /tmp/dictate_test.m4a -af silencedetect=noise=-35dB:d=2 -f null - 2>&1 | grep -c silence_end | sed 's/^/пауз длиннее 2 с: /'
else
  echo "/tmp/dictate_test.m4a нет — шаг пропущен"; : > handoff/m110/sample_groq.txt
fi
} 2>&1 | tee -a handoff/m110/run.txt
git status --short
```
Ожидается: число слов Groq на куске из M108 и число длинных пауз в нём. Если файла уже нет — шаг пропущен, не СТОП.

## Шаг 3. Отчёт в ветку
Записать `handoff/m110/REPORT.md`:
1. `handoff/m110/run.txt` целиком;
2. первые 300 знаков `gamebox.txt` и `groq.txt`;
3. одна строка вывода: «слова близки (разница ≤ 15 %)» или «gamebox теряет X % слов».

```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/report.sh m110 gamebox.txt groq.txt sample_groq.txt run.txt
```
Ожидается `отчёт m110 отправлен в ветку handoff`. Владельцу в чат — одна строка: числа слов и «отчёт в ветке».

Статус: MEASURED.
