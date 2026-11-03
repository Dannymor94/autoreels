# TASK M212B (окно MAIN, Mac): разбор клипа с «missing picture in access unit with size 12»; итог M211 в план

Файлы — ветка `handoff`, папка `handoff/m212b/`: `TASK-M212B.md`, `m212b-plan.patch` (только `PLAN.md`, ложится на `main` после M211, `726929d`).
Около 5 минут, только чтение + документация. Gamebox не нужен. Отчёт — только на русском.

## Зачем
1. **m212 нашла:** `reels-out/prew_isaev_anna/_gate/ab192/r03.integrity.txt` — «missing picture in access unit with size 12». Это ровно тот служебный пакет (AUD + EOS, 12 байт), который m179 предполагала, но не нашла. M180 сохраняет такой клип, а не удаляет, — теперь его можно разобрать. Правку делаем только по факту из файла, не по догадке.
2. **M211:** голос не отличает мысли из клипов владельца (AUC 0,47–0,55), сила по модели — 0,68. Этап M1.9 E закрывается замером.

## Правила
1. Команда упала → **СТОП**: команда и последние 40 строк. Ничего не чинить.
2. Только чтение в `reels-out/`: ничего не переименовывать, не удалять, не рендерить. `data/token_scale.json` не коммитить.
3. Итог — «MEASURED, DOCUMENTED».

## Часть 1. Что лежит рядом с тревогой
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1
bash handoff/bin/take.sh m212b
{ echo "== anna ab192"; ls -la reels-out/prew_isaev_anna/_gate/ab192/ | grep -E " r03|integrity|ERROR"
  echo "== danny ab192"; ls -la reels-out/prew_isaev_danny/_gate/ab192/ | grep -E " r01|integrity|ERROR"
  echo "== integrity.txt"; cat reels-out/prew_isaev_anna/_gate/ab192/r03.integrity.txt
  echo "== что ещё есть про r01 danny"; ls reels-out/prew_isaev_danny/_gate/ab192/ | grep -E "^r01\." ; grep -rh "r01" reels-out/prew_isaev_danny/_gate/ab192/*.log 2>/dev/null | head -5
  echo "== ffmpeg, кодек клипов"; for f in reels-out/prew_isaev_anna/_gate/ab192/r03*.mp4 reels-out/prew_isaev_danny/_gate/ab192/r01*.mp4; do [ -f "$f" ] && echo "$f: $(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,profile,nb_frames -show_entries format=duration,size -of csv=p=0 "$f" | tr '\n' ' ')"; done
} 2>&1 | tee handoff/m212b/ls.txt
```
Ожидается: видно, есть ли рядом с `r03.integrity.txt` сам клип (`r03.ERROR.mp4` или `r03.mp4`), даты файлов, кодек (`h264` = рендер gamebox `h264_vaapi`); у `r01.ERROR.mp4` danny — есть ли файл с причиной.

## Часть 2. Пакеты клипа (если клип r03 есть)
```bash
cd /Users/danny/Documents/autoreels
for f in reels-out/prew_isaev_anna/_gate/ab192/r03.ERROR.mp4 reels-out/prew_isaev_anna/_gate/ab192/r03.mp4 reels-out/prew_isaev_danny/_gate/ab192/r01.ERROR.mp4; do
  [ -f "$f" ] && sh handoff/m179/probe_au.sh "$f"
done 2>&1 | tee handoff/m212b/probe.txt
```
Ожидается: для каждого найденного клипа — ошибки проверки (copy), ошибки полного декодирования, пакеты < 64 байт с временем, число пакетов и кадров, NAL-единицы маленького пакета (`nal_unit_type`: 9 = AUD, 11 = EOS — так ли это?). Клипа нет — не СТОП, написать «клипа нет».

## Часть 3. Итог M211 в план
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m212b/m212b-plan.patch && git apply handoff/m212b/m212b-plan.patch && echo applied
git add PLAN.md
git commit -m "Plan (M212b): M1.9 E closed by M211 — the voice does not tell the owner's thoughts (AUC 0.47–0.55), the model's strength does (0.68); the gamebox integrity message came back (ab192/r03, size 12) — examined in m212b"
git push; git log --oneline -1
git status -s | grep -v "handoff/\|data/token_scale.json" || echo "всё закоммичено"
```
Ожидается: `applied`; коммит запушен; «всё закоммичено».

## Отчёт
`handoff/m212b/REPORT.md`:
```
M212B — MEASURED, DOCUMENTED
Коммит: <хэш>
anna ab192 r03: клип <есть: имя / нет>; дата integrity.txt <…>; кодек <…>
Пакеты (probe.txt): маленький пакет <время, размер, последний ли>; NAL <типы>; кадров/пакетов <…>; полное декодирование <ошибки/чисто>
danny ab192 r01.ERROR: <причина, если есть файл>; пакеты <кратко>
```
```bash
bash handoff/bin/report.sh m212b ls.txt probe.txt
```
Владельцу в чат — 2 строки:
1. «M212B: клип r03 <есть/нет>, маленький пакет — <типы NAL, где в потоке>»;
2. «M1.9 E закрыт: голос не отличает (AUC ~0,5), коммит <хэш>».
