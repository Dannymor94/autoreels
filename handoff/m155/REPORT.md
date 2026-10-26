# REPORT M155: рендер на gamebox

## probe.txt (полный вывод)

```
== система
Ubuntu 26.04.1 LTS
7.0.0-38-generic
16 CPU
Mem: 30 GB total, 29 GB available
/dev/sdb2: 218G, 51G занято
/mnt/data: 3.6T, 365G занято

== ffmpeg и libass
ffmpeg version 8.0.1-3ubuntu2
 .. ass               V->V       Render ASS subtitles onto input video using the libass library.
 .. subtitles         V->V       Render text subtitles onto input video using the libass library.

== кодеры
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V....D libx264rgb           ...
 V....D h264_vaapi           H.264/AVC (VAAPI) (codec h264)
 V....D libx265              libx265 H.265 / HEVC (codec hevc)
 V....D hevc_vaapi           H.265/HEVC (VAAPI) (codec hevc)

== GPU (VAAPI)
renderD128: Mesa Gallium 26.0.8 / AMD Radeon RX 580 (radeonsi, polaris10)
VAProfile H264: VAEntrypointEncSlice (encode поддерживается)
(HEVC encode в vainfo не появился — RX 580 не поддерживает HEVC encode через VAAPI)

== python, git, проект
Python 3.14.4 / git 2.53.0
Проект (autoreels) на gamebox не развёрнут.

== занятость
замок свободен / llama-server inactive / озвучки нет

== пробное кодирование 1080×1920, 10 с синтетики
hevc_vaapi 5M:    rc=0  1.9 с   (RX 580 через VAAPI — software path? см. примечание)
h264_vaapi 8M:    rc=0  3.7 с
libx265 medium 5M: rc=0  4.5 с
libx264 medium 8M: rc=0  1.4 с   ← fastest

== сеть Mac → gamebox (500 МБ)
16 МБ/с (31 с)

== Mac для сравнения (hevc_videotoolbox)
rc=0  2 с
```

---

## Ответы на три вопроса

**1. Фильтр `ass` есть?**
ДА — `ass` и `subtitles` оба доступны. Субтитры выжигаются стандартным способом.

**2. Какой кодер быстрее всего (секунды на 10 с видео) и как против videotoolbox на Mac?**

| Кодер | gamebox | Mac (videotoolbox) |
|---|---|---|
| libx264 medium 8M | **1.4 с** | — |
| hevc_vaapi 5M | 1.9 с | — |
| h264_vaapi 8M | 3.7 с | — |
| libx265 medium 5M | 4.5 с | — |
| hevc_videotoolbox 5M | — | **2.0 с** |

Примечание: `hevc_vaapi` выдаёт rc=0 и 1.9 с, но RX 580 (Polaris) в vainfo не показал HEVC encode entrypoint — возможно, это CPU fallback в software. Потребует проверки с `ffmpeg -loglevel verbose`. `libx264` — 1.4 с, быстрее Mac на 30%.

**3. Скорость сети Mac → gamebox**
16 МБ/с (LAN). Исходник 2 ГБ = ~2 мин передачи. Для пересылки манифестов (< 1 МБ) — мгновенно.

---

## Вывод

- Рендерить на gamebox **можно**: ffmpeg с libass есть, GPU доступен, кодер быстрее или сопоставим с Mac.
- Проект не развёрнут — потребуется `git clone` + `pip install`.
- Текущая архитектура — исходник живёт локально, через SSH надо либо монтировать диск Mac на gamebox (`sshfs`/`nfs`), либо копировать исходник (16 МБ/с — приемлемо для файлов до 1–2 ГБ).
- Узкое место: `hevc_vaapi` — под вопросом (реальный ли GPU encode?). `libx264` работает надёжно.
- Роль `render` в `config/render.local.yaml` на gamebox решает конфликт с существующей ролью `analyze` на Mac.
