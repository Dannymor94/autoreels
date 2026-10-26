# TASK M161 (окно MAIN, Mac + gamebox): рендер с Mac на gamebox одной командой (H.264 на видеокарте)

Файлы — ветка `handoff`, папка `handoff/m161/`: `TASK-M161.md`, `m161-remote.patch`. Около 20 минут.

## Зачем
По m160 видеокарта gamebox пишет H.264 чисто, а HEVC портит длинные клипы; владелец: «H.264 нормальный».

Патч `local/remote.py`:
- `arl render --manifest <копия> --gate <имя> --remote` и `arl auto … --remote` сами отправляют на gamebox отслеживаемый код, копию разметки, `transcripts/<ист>.*`, **кэшированную расшифровку источника** (без неё в m158/m160 печатались ложные «seam inside word»), модель лиц и музыку;
- исходник уходит, только если gamebox не находит его по содержимому;
- рендер идёт там под общим замком с `h264_vaapi`, профиль `h264` (`config/render.yaml remote:`), папка гейта возвращается на Mac;
- только в гейт: настоящие клипы с другой машины не пишутся;
- тесты `tests/test_m161_remote.py` (9), `docs/GAMEBOX.md`, CLAUDE.md, README.

## Правила
1. Шаг упал → **СТОП**: шаг, команда, последние 40 строк.
2. pytest — только когда на Mac нет рендера. Озвучку книги не трогать: рендер на gamebox ждёт замок сам.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m161
git apply --check handoff/m161/m161-remote.patch && git apply handoff/m161/m161-remote.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests config docs README.md CLAUDE.md && git commit -m "Render (M161): arl render/auto --remote — render on gamebox (h264_vaapi under the shared lock) with the code, review, transcripts and cached transcript sent over, clips back" && git push && git log --oneline -1
```

## Шаг 2. Те же три клипа с Mac на gamebox
```bash
s=$(date +%s); .venv/bin/python -m autoreels render --manifest reviews/IMG_6848_m146b.review.json --reels 1-3 --gate m161 --remote 2>&1 | tee handoff/m161/render.txt | grep -E "удалённый|отправлено|исходник|ERROR|готово|клипы здесь|ошибка"; echo "$(( $(date +%s) - s )) с всего" | tee -a handoff/m161/render.txt
for g in m161 m146b; do for f in reels-out/IMG_6848/_gate/$g/r0[1-3].mp4; do echo "$f $(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,bit_rate -show_entries format=duration -of csv=p=0 "$f" | tr '\n' ' ') ошибок $(ffmpeg -v error -i "$f" -f null - 2>&1 | wc -l | tr -d ' ')"; done; done | tee handoff/m161/probe.txt
```
Ожидается:
- в `render.txt` нет ни одного `seam inside word` и `[ERROR]`, есть «клипы здесь: …/_gate/m161»;
- в `probe.txt` у m161 `h264`, ошибок 0, длительности как у m146b.

`seam inside word` всё равно есть — **СТОП**: значит, дело не в расшифровке. Строки в отчёт.

## Шаг 3. Отчёт
`handoff/m161/REPORT.md`: коммит, pytest, `render.txt`, `probe.txt`, секунд на 3 клипа (вместе с отправкой).
`bash handoff/bin/report.sh m161 render.txt probe.txt`
Владельцу — одна строка: «сравни в QuickTime reels-out/IMG_6848/_gate/m161 (gamebox, H.264) и _gate/m146b (Mac): кадр, рамка по лицу, субтитры».

Статус: IMPLEMENTED, GATE PENDING.
