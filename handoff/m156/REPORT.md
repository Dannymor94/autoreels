# REPORT M156: рендер на видеокарте gamebox (VAAPI)

## gb.txt

```
Ubuntu 26.04.1 LTS / Python 3.14.4
sudo без пароля: НЕТ — владелец поставил пакеты вручную

vainfo: Mesa Gallium 26.0.8 / AMD Radeon RX 580 (radeonsi, polaris10)
  VAProfileH264: VAEntrypointEncSlice ✓
  VAProfileHEVCMain: VAEntrypointEncSlice ✓   (m155 обрезал head -8, сейчас head -10 — видно)
  ass filter: ✓
  hevc_vaapi, h264_vaapi: ✓

Пробное кодирование 1080x1920, 10 с:
  hevc_vaapi 5M: 2.1 с
  h264_vaapi 8M: 3.7 с
```

## Патч, тесты, коммит

- `git apply` — applied
- `tests/test_m156_vaapi.py`: **10/10 passed**
- Прочие падения в worktree:
  - `test_cli.py` (4) — conftest guard: m154 рендерил параллельно в `reels-out/`
  - `test_providers.py`, `test_map.py`, `test_montage.py` (3) — локальные данные (`data/runs/r0_live_response.json`) не в git, в worktree отсутствуют; scipy pitch-тесты — в main venv проходят
  - `test_calibration_face.py` (1) — аналогично: нет модели в worktree
  - Все эти тесты проходят в main venv; ни один не трогает VAAPI-код
- Коммит: `0ad229b`
- Push `origin/main`: прошёл

## render.txt (последние строки)

```
клип 1/3: r01 (1:12)… ✓ готово
клип 2/3: r02 (1:05)… ✓ готово
клип 3/3: r03 (0:42)… ✓ готово
warning: web-safe: video codec is hevc — web players may transcode
кадр rXX: лицо не искалось (нет OpenCV или кадров) — рамка источника
готово: 3 клипов → /mnt/data/autoreels/reels-out/IMG_6848/_gate/m156
112 с (с ожиданием замка)
```

Кодер: `hevc_vaapi` (не fallback — в выводе нет слова «fallback»; в логе заголовок `h264/hevc_vaapi`).

Замечания:
- **OpenCV на gamebox не установлен** → детектор лица не работает, кроп по рамке источника. Для нормального кропа нужно поставить `opencv-python` в venv.
- Web-safe warning ожидаем: HEVC всегда предупреждает.

## probe.txt (сравнение с m146b)

| Файл | Кодек | Разрешение | Длительность |
|---|---|---|---|
| m156/r01 | hevc | 1080×1920 | 72.322 с |
| m156/r02 | hevc | 1080×1920 | 65.448 с |
| m156/r03 | hevc | 1080×1920 | 42.842 с |
| m146b/r01 | hevc | 1080×1920 | 72.322 с |
| m146b/r02 | hevc | 1080×1920 | 65.448 с |
| m146b/r03 | hevc | 1080×1920 | 42.842 с |

Длительности совпадают точно (±0 с). Битрейт видео у m156 ~7 Мбит/с, у m146b ~4.9 Мбит/с — VAAPI менее точно держит целевой битрейт, чем videotoolbox, но это в допустимых пределах.

## Скорость

| Задача | Время |
|---|---|
| gamebox hevc_vaapi: 3 клипа (42–72 с) | **112 с** (~37 с/клип) |
| Mac hevc_videotoolbox: 10 с синтетики | 2.0 с (~5× realtime) |
| gamebox hevc_vaapi: 10 с синтетики | 2.1 с (~5× realtime) |

На синтетических данных равны. На реальном рендере (полный пайплайн: декод, ASS-субтитры, кроп, loudnorm, VAAPI-encode) gamebox даёт ~37 с на клип. Данные для прямого сравнения с Mac по реальным клипам нет (m154 рендерил параллельно), но по синтетике паритет.

## Итог

IMPLEMENTED, GATE PENDING.

- gamebox рендерит на видеокарте VAAPI, кодер hevc_vaapi работает
- Длительности клипов совпадают с Mac (m146b) точно
- Нужно сравнить визуально: `reels-out/IMG_6848/_gate/m156` (gamebox) и `_gate/m146b` (Mac)
- OpenCV на gamebox не установлен — лицо не ищется, кроп по кадру источника
