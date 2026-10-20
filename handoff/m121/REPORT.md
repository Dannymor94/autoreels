# REPORT M121

## 1. decide.txt

```
(a) без модели: X покрыто 35/66 (кандидатов 111), R 20/66 (кандидатов 54) → да
(b) с моделью: m120-mixed сборок 26 (покрыто 5/31), m120-montage 20 (покрыто 8/31) → да
mixed
```

## 2. Коммит и pytest

Коммит: `e96fb40 Autocut (M121): new autocut on by default — generator mixed, lean_depth 1, the jump rule, no start judge, clips by length`

pytest: `2456 passed, 9 deselected in 435.03s`

## 3. check.txt

```
сборок: до 10 (источник 35 мин ÷ 3.5)
autocut IMG_6848: предложено сборок 10 из 107 мыслей (без понятного начала: 1) (без крючка не взяты: 4) → reviews/IMG_6848_auto_m121-check.txt
```

N=10 > 6 (было 6). git status — только ранее существующие untracked файлы, новых строк от запуска нет.

Статус: IMPLEMENTED. Гейт — просмотр рендеров владельцем.
