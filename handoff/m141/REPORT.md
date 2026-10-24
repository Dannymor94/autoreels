# M141 — Замер разделения говорящих (pyannote)

## Шаг 1. Окружение

```
pyannote.audio 4.0.7  torch 2.14.1
```

Версии установлены. Python 3.13 совместим.

## Шаг 2. Разделение голосов — СТОП

```
СТОП: нет HF_TOKEN (в окружении или .env). Владельцу: принять условия моделей
pyannote/speaker-diarization-3.1 и pyannote/segmentation-3.0 на huggingface.co,
создать токен (read) и дописать в .env строку HF_TOKEN=…
```

Шаги 3–4 не выполнялись (нет данных диаризации).

`git status` без новых изменений.

## Что нужно владельцу

1. Зайти на huggingface.co и принять условия двух моделей:
   - `pyannote/speaker-diarization-3.1`
   - `pyannote/segmentation-3.0`
2. Создать токен (тип **read**) в настройках аккаунта.
3. Дописать в `.env` строку `HF_TOKEN=<токен>`.
4. После этого повторить: `~/.venvs/m141/bin/python handoff/m141/diar.py`

Окружение `~/.venvs/m141` готово, повторная установка не нужна.
