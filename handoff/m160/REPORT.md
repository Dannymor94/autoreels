# REPORT M160: зелёные блоки — где именно ломается

## diag.txt — полный вывод

```
== reels-out/IMG_6848/_gate/m158/r01.mp4
[hevc @ 0x12c633030] CABAC_MAX_BIN : 27
[hevc @ 0x12c60f940] CABAC_MAX_BIN : 30
[hevc @ 0x12660ea70] CABAC_MAX_BIN : 27
[hevc @ 0x12660ea70] CABAC_MAX_BIN : 30
1,0.000000,I
1,2.002000,I
1,4.004000,I
...
== reels-out/IMG_6848/_gate/m156/r02.mp4
[hevc @ 0x15b1063a0] CABAC_MAX_BIN : 28
[hevc @ 0x120e0ee80] CABAC_MAX_BIN : 28
1,0.000000,I
1,2.002000,I
...

total 270824
-rw-r--r-- 44499257 r01_from5s.mp4
-rw-r--r-- 47076049 r01_hev1.mp4
-rw-r--r-- 47076049 r01_hvc1_remux.mp4

[ERROR] r01: seam inside word (... × 13 — pre-existing, manifest validation)
✓ клип 1/1: r01 (1:12) готово
готово: 1 клипов → .../m160h264
m160h264: ошибок 0, I-кадров 37

[ERROR] r01: seam inside word (... × 13)
✓ клип 1/1: r01 (1:12) готово
готово: 1 клипов → .../m160hevc
[hevc @ 0x5f2172943c80] CABAC_MAX_BIN : 27
[hevc @ 0x5f2172943c80] CABAC_MAX_BIN : 30
m160hevc: ошибок 2, I-кадров 37

Mac decode check:
  /tmp/m160/r01_hev1.mp4: ошибок 2
  /tmp/m160/r01_hvc1_remux.mp4: ошибок 2
  /tmp/m160/r01_from5s.mp4: ошибок 2
  reels-out/IMG_6848/_gate/m160h264/r01.mp4: ошибок 0
  reels-out/IMG_6848/_gate/m160hevc/r01.mp4: ошибок 2
```

## Выводы

**m156 тоже повреждён** (r02 — CABAC_MAX_BIN). Ошибка не в VBR и не в новых флагах m158 — воспроизводится на свежем рендере `hevc_vaapi` без каких-либо изменений.

**Ошибка в битстриме HEVC**: `CABAC_MAX_BIN` — кодировщик hevc_vaapi на RX 580 / Mesa создаёт битстрим, нарушающий спецификацию HEVC (переполнение CABAC-бинов). Это не проблема контейнера: перепаковка (hev1/hvc1, faststart, срез от 5 с) не устраняет ошибок — они в самих кадрах.

**H.264 VAAPI работает чисто**: `m160h264` — 0 ошибок на gamebox и на Mac. I-кадров столько же (37), рендер завершился без [ERROR] по кодеку.

**Рекомендация**: переключить gamebox на `h264_vaapi --profile h264` (7 Мбит/с). hevc_vaapi на этой связке Mesa/RX 580 выдаёт некорректный HEVC-битстрим; флаги (VBR, bf0, bufsize) на результат не влияют.

**Для глаз** (открыть в QuickTime):
- `/tmp/m160/r01_hev1.mp4` — перепакованный m158 (ожидается зелень)
- `reels-out/IMG_6848/_gate/m160h264/r01.mp4` — тот же клип, H.264 (ожидается нормальная картинка)
- `reels-out/IMG_6848/_gate/m160hevc/r01.mp4` — свежий hevc_vaapi (ожидается зелень)

IMPLEMENTED, GATE PENDING (нужен визуальный просмотр).
