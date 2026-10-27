# REPORT M165: голос ведущего — карта говорящих и переключатель

## Коммит
```
1d65a3d Speakers (M165): the speaker map (arl speakers, pyannote or m141 import) and autocut.interviewer on|off — the host's lines as context/exchange or none
```

## pytest
```
2541 passed, 9 deselected in 269.16s
```

## speakers.txt
```
✓ 2026-08-08 09h 33m 14s.speakers.json: реплик 392, говорящих 1 — SPEAKER_00 100%; главный SPEAKER_00
✓ 2026-08-08 10h 59m 38s.speakers.json: реплик 555, говорящих 2 — SPEAKER_01 97%, SPEAKER_00 3%; главный SPEAKER_01
✓ 2026-08-08 11h 42m 49s.speakers.json: реплик 184, говорящих 2 — SPEAKER_00 99%, SPEAKER_01 1%; главный SPEAKER_00
✓ IMG_6848.speakers.json: реплик 470, говорящих 4 — SPEAKER_03 87%, SPEAKER_01 10%, SPEAKER_00 2%, SPEAKER_02 1%; главный SPEAKER_03
✓ Pxl 20260621 112938952.speakers.json: реплик 494, говорящих 2 — SPEAKER_00 100%, SPEAKER_01 0%; главный SPEAKER_00
✓ Pxl 20260621 122006193.speakers.json: реплик 151, говорящих 2 — SPEAKER_00 100%, SPEAKER_01 0%; главный SPEAKER_00
✓ PXL_20260729_copy.speakers.json: реплик 485, говорящих 2 — SPEAKER_01 86%, SPEAKER_00 14%; главный SPEAKER_01
```

## itog.txt
```
=== auto: итог ===
  ✓ IMG_6848: готово — после листа: arl export IMG_6848 --gate m165 --decisions <файл решений>
  ✓ PXL_20260729_copy: готово — после листа: arl export PXL_20260729_copy --gate m165 --decisions <файл решений>
```

## host.txt (фразы ведущего в контексте)
```
   1   ведущий: фраз 61 из 524, interviewer: on
   1   ведущий: фраз 70 из 356, interviewer: on
reviews/PXL_20260729_copy_auto_m165.txt:6
reviews/IMG_6848_auto_m165.txt:4
```

Примеры строк «ведущий:» в листах ревью:
- `IMG_6848`: `ведущий: 19.2`, `ведущий: 17.4`, `ведущий: x4.3`, `ведущий: 8.7-9`
- `PXL_copy`: `ведущий: 46.1-2`, `ведущий: 11.13`, `ведущий: 14.10-11`, `ведущий: 24.7 24.9 24.12`

## clips.txt
```
IMG_6848: клипов 18, постов 18, с ошибкой 0
PXL_20260729_copy: клипов 10, постов 10, с ошибкой 0
```

## Замечание по integrity check
Во время рендера на gamebox несколько клипов дали `integrity check failed — missing picture in access unit with size 12`. Проверка на Mac (`ffmpeg -v error`): **все 28 клипов — 0 ошибок**. Это ложное срабатывание gamebox-ffmpeg; в битстриме H.264 ошибок нет.

## Итог

- **7 карт говорящих** импортированы из m141
- **IMG_6848**: 61 фраза ведущего из 524, 4 ролика с пометкой «ведущий:», 18 клипов
- **PXL_copy**: 70 фраз ведущего из 356, 6 роликов с пометкой «ведущий:», 10 клипов
- **0 ошибок** декодирования на Mac

IMPLEMENTED, GATE PENDING.
