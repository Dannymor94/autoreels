# REPORT M161: rендер с Mac на gamebox одной командой (H.264)

## Коммит
```
8a4f4ab Render (M161): arl render/auto --remote — render on gamebox (h264_vaapi under the shared lock) with the code, review, transcripts and cached transcript sent over, clips back
```

## pytest
```
2530 passed, 9 deselected in 273.17s
```

## render.txt
```
удалённый рендер: gamebox:/mnt/data/autoreels (h264_vaapi, профиль h264)
  отправлено: код, 31 путей данных
  ✓ клип 1/3: r01 (1:12) готово
  ✓ клип 2/3: r02 (1:05) готово
  ✓ клип 3/3: r03 (0:42) готово
готово: 3 клипов → /mnt/data/autoreels/reels-out/IMG_6848/_gate/m161
  клипы здесь: /Users/danny/Documents/autoreels/reels-out/IMG_6848/_gate/m161
258 с всего
```

Ни одного `seam inside word` и `[ERROR]`.

## probe.txt
```
reels-out/IMG_6848/_gate/m161/r01.mp4 h264,6916549 72.322000  ошибок 0
reels-out/IMG_6848/_gate/m161/r02.mp4 h264,6982385 65.448000  ошибок 0
reels-out/IMG_6848/_gate/m161/r03.mp4 h264,7050752 42.842000  ошибок 0
reels-out/IMG_6848/_gate/m146b/r01.mp4 hevc,4894303 72.322000  ошибок 0
reels-out/IMG_6848/_gate/m146b/r02.mp4 hevc,4893928 65.448000  ошибок 0
reels-out/IMG_6848/_gate/m146b/r03.mp4 hevc,4889017 42.842000  ошибок 0
```

m161: кодек `h264`, 0 ошибок, длительности совпадают с m146b.

## Итог

- **258 с** на 3 клипа (с отправкой кода и данных)
- **0 ошибок** декодирования — HEVC CABAC_MAX_BIN больше нет
- **0 `seam inside word`** — расшифровка исходника передаётся корректно

IMPLEMENTED, GATE PENDING (нужен визуальный просмотр).
