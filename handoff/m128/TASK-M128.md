# TASK M128 (окно MAIN, Mac): замер — что детектор лица находит на Pxl 112938952 (рамка «на чайнике»)

Файлы — в ветке `handoff`, папка `handoff/m128/`: `TASK-M128.md`, `face_probe.py`. Кода в проекте не меняем.

Около 5 минут. Без рендера, без модели, gamebox не нужен.

## Зачем
m127 сделал хуже: «баг остался, плюс теперь у всех видео». Лог m127: «лицо» найдено почти во всех роликах на x ≈ 880 (высота ≈ 650 px), рамка ушла туда, а там полки. Ролики 4, 6, 14, 15, которые владелец назвал правильными, в m125 «лица» не нашли и остались посередине.

Значит, детектор (каскад Хаара) находит не человека, а неподвижный предмет. Прежде чем чинить — посмотреть глазами: скрипт рисует на 12 кадрах, что находит Хаар (как в рендере), Хаар с проверкой глаз и нейросетевой детектор YuNet (модель ~300 КБ скачивается в `data/models/`).

## Правила
1. Упал шаг → **СТОП**: номер шага, команда, последние 40 строк.
2. Не трогать `reviews/`, `manifests/`, `reels-out/`, `config/`. Новое — только `handoff/m128/frames/` и `data/models/face_detection_yunet_2023mar.onnx`.
3. YuNet не скачался — не СТОП: скрипт напишет «YuNet: нет», остальное сделает.

## Шаг 1. Замер
```bash
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m128
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
.venv/bin/python handoff/m128/face_probe.py "Pxl 20260621 112938952" 12 2>&1 | tee handoff/m128/probe.txt
ls handoff/m128/frames | wc -l; du -sh handoff/m128/frames
git status --short
```
Ожидается: 12 строк в `probe.txt`, 12 файлов `f00.jpg`…`f11.jpg` (в сумме около 1 МБ), новых строк в `git status` нет.

## Шаг 2. Отчёт в ветку (с кадрами)
Записать `handoff/m128/REPORT.md`: `probe.txt` целиком.
```bash
cd /Users/danny/Documents/autoreels/handoff/m128 && bash ../bin/report.sh m128 probe.txt $(ls frames/*.jpg)
```
Владельцу в чат — одна строка: «замер лиц отправлен».
