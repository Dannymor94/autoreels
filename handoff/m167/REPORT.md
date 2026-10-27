# REPORT M167

## Шаг 1: патч, тесты, коммит

Коммит `2c530c5`: `Plan/render (M166): the first word checked by the plan's own span; an automatic clip with no room after its last word is refused at --apply (m163 10h59 r13/r15, 11h42 r02)`

Изменено: `src/autoreels/core/models.py` (+поле `head_first_word_start`), `src/autoreels/__main__.py` (план записывает поле, --apply отклоняет авто-клип с «no room»), `src/autoreels/local/render.py` (проверка first word cut берёт `head_first_word_start`), `docs/REEL_SPEC.md` (+1 строка).

pytest: **2544 passed, 9 deselected** (tests/test_m166_edges.py::test_m166_first_word_reference_planned_uses_the_plan PASSED, test_m166_no_room_errors_only_planned_with_the_warning PASSED, test_m166_reel_model_has_head_first_word_start PASSED).

## Шаг 2: прогон (itog.txt)

```
=== auto: итог ===
  ✓ 2026-08-08 10h 59m 38s: готово — общий черновик не прошёл (rc=1) — взят только черновик сборок
  ✓ 2026-08-08 11h 42m 49s: готово
```

## Клипы (clips.txt)

```
2026-08-08 10h 59m 38s: клипов 8, с ошибкой 0, постов 8
2026-08-08 11h 42m 49s: клипов 6, с ошибкой 0, постов 6
```

У обоих источников `ERROR.mp4 = 0`. Было: 10h59 — 13 клипов (r13, r15 с ошибкой); 11h42 — 7 клипов (r02 с ошибкой). После патча сценарист предложил другие нарезки вместо отклонённых «no room».

## Сообщения «no room» в errors.txt

Строки `automatic clip needs another end` присутствуют — это штатная работа патча: план отклоняет авто-клип с концом после начала следующей речи и строит замену. Не ошибка.

## Статус: IMPLEMENTED, GATE PENDING
