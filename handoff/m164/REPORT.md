# REPORT M164

## Шаг 1: замер (count.txt)

```
speech_map в config/render.yaml: True
=== копий разметки 47, клипов 509, без плана 0, с пробой хвоста 0
```

N=0 — ни одному клипу проба не нужна. Все 509 клипов имеют план (`planned: true`), карты речи есть, флаг `speech_map: True`.

## Шаг 2: рендер ДО правки (before.txt)

```
клипы здесь: /Users/danny/Documents/autoreels/reels-out/IMG_6848/_gate/m164a
```

Без ошибок, строк «нет карты» нет.

## Шаг 3: патч, тесты, коммит

Патч применён. pytest: **2541 passed, 9 deselected** (4 мин 39 с).

Коммит: `f8ed4c2 Render (M164, M1.8 stage C): the tail is placed by the speech map only — the point silencedetect probe is removed (m164: clips needing it N=0)`

## Шаг 4: рендер ПОСЛЕ правки и сравнение (compare.txt)

```
r01: render.json совпал | длительность 48.280000 → 48.280000
r02: render.json совпал | длительность 58.992000 → 58.992000
r03: render.json совпал | длительность 59.542000 → 59.542000
```

Все три: `render.json совпал`, длительности идентичны, строк «нет карты» нет.

## Статус: DONE

Проба `_tail_find_word_end` удалена. Клипов, которым она была нужна, — 0. Рендер до/после совпал побайтово.
