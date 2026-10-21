# REPORT M126

## 1. Коммит и pytest

| Шаг | Коммит | Описание |
|-----|--------|----------|
| Шаг 1 | `3218041` | Plan (M126): standalone filler words hidden from the subtitles and, rarely, cut from the sound under the filler-cut rules; the scenarist avoids them (owner: on) |

pytest (шаг 1): `2468 passed, 9 deselected` — 3 новых теста в `tests/test_filler_cut.py`.

## 2. run.txt — сценарист IMG_6848

(см. handoff/m126/run.txt)

```
сценарист: anthropic:claude-sonnet-5-5, фраз 356, до 18 роликов …
Claude claude-sonnet-5-5: запросов 1, вход 13525, ответ 6896 токенов ≈ $0.0960
сценарист: строк 13, принято кодом 12, не принято 1
autocut IMG_6848: предложено сборок 12 из 107 мыслей → reviews/IMG_6848_auto_m126-scen.txt
Claude claude-sonnet-5-5: запросов 36, вход 21662, ответ 8397 токенов ≈ $0.1273
```

## 3. fillers.txt — вырезы и остатки паразитов

(см. handoff/m126/fillers.txt)

```
r01: вырезов внутри кусков (паузы и паразиты) 2, слов «ну/вот/значит…» в субтитрах 1, длина 68 с
r02: вырезов внутри кусков (паузы и паразиты) 2, слов «ну/вот/значит…» в субтитрах 5, длина 64 с
r03: вырезов внутри кусков (паузы и паразиты) 6, слов «ну/вот/значит…» в субтитрах 0, длина 38 с
r04: вырезов внутри кусков (паузы и паразиты) 0, слов «ну/вот/значит…» в субтитрах 0, длина 55 с
r05: вырезов внутри кусков (паузы и паразиты) 3, слов «ну/вот/значит…» в субтитрах 3, длина 52 с
r06: вырезов внутри кусков (паузы и паразиты) 3, слов «ну/вот/значит…» в субтитрах 1, длина 42 с
r07: вырезов внутри кусков (паузы и паразиты) 2, слов «ну/вот/значит…» в субтитрах 1, длина 41 с
r08: вырезов внутри кусков (паузы и паразиты) 5, слов «ну/вот/значит…» в субтитрах 0, длина 52 с
r09: вырезов внутри кусков (паузы и паразиты) 7, слов «ну/вот/значит…» в субтитрах 4, длина 73 с
r10: вырезов внутри кусков (паузы и паразиты) 1, слов «ну/вот/значит…» в субтитрах 5, длина 42 с
r11: вырезов внутри кусков (паузы и паразиты) 1, слов «ну/вот/значит…» в субтитрах 0, длина 42 с
r12: вырезов внутри кусков (паузы и паразиты) 4, слов «ну/вот/значит…» в субтитрах 0, длина 29 с
```

Паразиты остались в субтитрах только там, где они не отдельно стоящие (например, «вот этот», «вот как»).

apply.txt (строки о вырезах):
```
cuts      2 fillers/pauses removed, 1.4s; 2 masked by a shot switch; 14 left in (too close to another change)
cuts      2 fillers/pauses removed, 2.8s; 7 left in; 1 long pause(s) always cut
cuts      6 fillers/pauses removed, 11.3s; 1 masked; 2 left in; 5 long pause(s) always cut
cuts      0 fillers/pauses removed; 11 left in (too close to another change)
cuts      3 fillers/pauses removed, 16.2s; 1 masked; 13 left in; 2 long pause(s) always cut
cuts      3 fillers/pauses removed, 4.9s; 2 masked; 9 left in; 2 long pause(s) always cut
cuts      2 fillers/pauses removed, 4.6s; 1 masked; 10 left in; 1 long pause(s) always cut
cuts      5 fillers/pauses removed, 8.0s; 1 masked; 9 left in; 3 long pause(s) always cut
```

## 4. Рендер и лист

review.json возвращён ✓  
клипов: 12

render.txt:
```
r01.mp4 72.255000
r02.mp4 65.398000
r03.mp4 42.759000
r04.mp4 58.358000
r05.mp4 54.621000
r06.mp4 46.463000
r07.mp4 44.160000
r08.mp4 53.937000
r09.mp4 75.992000
r10.mp4 42.475767
r11.mp4 42.208000
r12.mp4 29.445750
```

Лист ревью: `reels-out/IMG_6848/_gate/m126/_review.html`
