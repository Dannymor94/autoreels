# REPORT M158: VAAPI VBR + полные зависимости gamebox

## Коммит

`a385bb1` — "Render (M158): VAAPI gets -rc_mode VBR (RX 580 ignored the profile bitrate: 7.0 vs 4.9 Mbit/s on m156)"

## Патч и тесты (worktree)

- `git apply` — applied
- `tests/test_m156_vaapi.py` (в т.ч. `test_m158_vaapi_gets_vbr_rate_control_others_do_not`): **11/11 passed**
- Прочие падения в worktree: те же, что в m156 (локальные данные Mac `data/runs/r0_live_response.json`, conftest guard); к VAAPI не относятся
- `git push origin HEAD:main` — прошёл

## pip.txt — зависимости на gamebox

Первый `pip install -e ".[dev]"` не поставил cv2 и parselmouth (wheel-кэш или старая venv). После явного:
```
pip install "opencv-python-headless>=4.8,<5" "praat-parselmouth==0.4.7"
```
все модули `ok`:
```
pip check: No broken requirements found.
ok  cv2 4.14.0
ok  numpy 2.5.4
ok  parselmouth 0.4.7
ok  httpx 0.28.1
ok  pydantic 2.14.1
ok  yaml 6.0.3
ok  autoreels.local.render
ok  autoreels.cloud.plan
```

Замечание: cv2 и parselmouth не попали в первую установку — вероятно, extras `[dev]` их не включает как обязательные. Нужна явная доустановка или добавление в основные зависимости `pyproject.toml`.

## pytest_gamebox.txt — тесты на gamebox

**2511 passed, 5 failed, 5 skipped, 9 deselected**

Ожидаемые падения (нет ключей/локальных данных Mac):
- `test_cli.py::test_run_dispatch_bad_path_returns_error`
- `test_cli.py::test_run_dispatch_url_calls_download`
- `test_cli.py::test_run_dispatch_url_download_error_returns_1`
- `test_cli.py::test_run_dispatch_yandex_calls_yandex_downloader`
- `test_providers.py::test_r0_output_parsing_survives_lower_max_tokens`

## render.txt — рендер трёх клипов с hevc_vaapi + --profile hevc

Замечание по битрейту: `--encoder hevc_vaapi` без `--profile hevc` берёт дефолтный профиль `h264` (7 Мбит/с). VBR теперь точно держит этот таргет — 7,2 Мбит/с. Для сравнения с m146b (hevc-профиль, 5 Мбит/с) нужен `--profile hevc`. Рендер сделан с `--profile hevc`.

```
лицо источника: x 953.4, в 40 из 40 кадров
кадр r01: лицо в 15 из 15 кадров (x 953.9, высота 168.5) — в центре рамки
✓ клип 1/3: r01 (1:12) готово
кадр r02: лицо в 15 из 15 кадров (x 948.6, высота 166.9) — в центре рамки
✓ клип 2/3: r02 (1:05) готово
кадр r03: лицо в 15 из 15 кадров (x 948.9, высота 171.3) — в центре рамки
✓ клип 3/3: r03 (0:42) готово
готово: 3 клипов → /mnt/data/autoreels/reels-out/IMG_6848/_gate/m158
137 с
```

Лица найдены во всех клипах — OpenCV работает. Строк «лицо не искалось» нет.

`[ERROR] seam inside word` — предупреждения валидации манифеста, присутствовали в m156, к VAAPI не относятся; рендер не останавливается.

## probe.txt — сравнение m158 и m146b

| Файл | Длительность | Размер | Реальный битрейт |
|---|---|---|---|
| m158/r01 | 72.322 с | 44 МБ | **5,2 Мбит/с** |
| m158/r02 | 65.448 с | 40 МБ | **5,2 Мбит/с** |
| m158/r03 | 42.842 с | 26 МБ | **5,3 Мбит/с** |
| m146b/r01 | 72.322 с | 43 МБ | 5,1 Мбит/с |
| m146b/r02 | 65.448 с | 39 МБ | 5,1 Мбит/с |
| m146b/r03 | 42.842 с | 25 МБ | 5,2 Мбит/с |

Длительности совпадают точно. Битрейт m158 (~5,2) vs m146b (~5,1) — расхождение <3%, в пределах нормы.

## Итог

IMPLEMENTED, GATE PENDING.

- `-rc_mode VBR` + `--profile hevc` → gamebox hevc_vaapi выдаёт 5,2 Мбит/с vs 5,1 у Mac
- OpenCV установлен (cv2 4.14.0), лица находятся во всех клипах
- Все 2511 тестов проходят на gamebox (5 падений — локальные данные Mac, ожидаемо)
- Нужно сравнить визуально: `reels-out/IMG_6848/_gate/m158` (gamebox) и `_gate/m146b` (Mac)
