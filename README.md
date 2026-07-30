# autoreels — Авто-Рилс

> CLI-инструмент: длинное горизонтальное talking-head видео → набор вертикальных
> **Reels 9:16** с выжженными субтитрами и кликбейт-заголовками. **Полностью автоматически.**
> Облако выбирает моменты (LLM по тексту), локаль рендерит (ffmpeg). Только бесплатные API.

<p>
<img alt="python" src="https://img.shields.io/badge/python-3.11%2B-blue">
<img alt="tests" src="https://img.shields.io/badge/tests-65%20passed-brightgreen">
<img alt="status" src="https://img.shields.io/badge/M0-R0%20готов-yellow">
</p>

---

## Идея

Длинная лекция/эфир (один человек, статичная камера) автоматически нарезается на
короткие вертикальные клипы — **без ручного монтажа**. Выбор «что резать» делает LLM
по транскрипту; границы, валидацию и рендер ставит детерминированный код.

### Несущая граница: ОБЛАКО / ЛОКАЛЬ

**Видео между тирами не передаётся.** Облако работает только с текстом, тяжёлое — локально.

| | ОБЛАКО (API) | ЛОКАЛЬ (железо) |
|---|---|---|
| Делает | транскрипция, выбор моментов | нарезка, кроп, субтитры, рендер |
| Инструменты | Groq (Whisper + Qwen) | ffmpeg |
| Стоимость | бесплатный тариф | бесплатно |
| На выходе | **JSON-манифест** (план) | mp4-рилсы |

Это выражено в коде физически: [`src/autoreels/cloud/`](src/autoreels/cloud/) ⟂
[`src/autoreels/local/`](src/autoreels/local/). Мост — манифест ([`core/models.py`](src/autoreels/core/models.py)).

## Конвейер

```
видео ──► extract_audio ──► transcribe ──► compress ──► select (R0) ──► манифест
         (ffmpeg -vn)      (Whisper,      (sentence-    (LLM ранжирует,
                            word-level)    level проекция) код решает)
                                                              │
                              манифест ──► cut + crop 9:16 ──► burn ASS субтитры ──► mp4
                                           (R1)                (R3)
```

**Determinism-first:** LLM только предлагает и ранжирует кандидатов; финальные границы,
отбор, чек-флаги (`too_long`/`too_short`/…) ставит код. Пустой результат — валиден.

## Требования

- **Python 3.11+** (закреплён в `.python-version` = 3.13; системный macOS Python 3.9 не подойдёт).
- **ffmpeg** в `PATH` — извлечение аудио и весь локальный рендер. macOS: `brew install ffmpeg`.
- **`GROQ_API_KEY`** в окружении (см. [`.env.example`](.env.example)) — Whisper + R0-выборка.

## Установка и тесты

```bash
python3.13 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest          # 65 passed
```

## Запуск (цель M0)

```bash
cp .env.example .env          # вписать GROQ_API_KEY
set -a; source .env; set +a
python -m autoreels run video.mp4 --setup tearoom_main
```

→ папка с mp4-рилсами + `manifest.json`.

## Короткие команды (`ar`)

Один раз на каждой машине:

```bash
autoreels install-aliases    # допишет source-строку в ~/.zshrc или ~/.bashrc
```

Или вручную добавь в `~/.zshrc` (Mac) / `~/.bashrc` (Windows Git Bash):

```bash
source /путь/к/autoreels/aliases.sh
```

После этого доступны короткие команды:

| Команда | Что делает |
|---|---|
| `ar` / `ar menu` | интерактивное меню (выбор цифрой) |
| `ar go` | run всех видео + git push манифестов (Mac) |
| `ar go --no-push` | run без push |
| `ar r` | git pull + render (системник) |
| `ar s` | status |
| `ar c` | calibrate --all |
| `ar h` | help |

`ar` без аргумента открывает **меню**: в шапке — состояние проекта,
▶ помечает рекомендуемый шаг, пункты запускаются цифрой. `ar run <путь|URL>`
(пункт 5 меню) принимает и файл вне `inputs/` (копируется внутрь).

**Энкодер и путь к ffmpeg** — в [`config/render.yaml`](config/render.yaml), не флаги:
```yaml
ffmpeg: ffmpeg                   # Mac; Windows: D:\ffmpeg\bin\ffmpeg.exe
encoder:
  codec: h264_amf                # Windows AMD; h264_nvenc NVIDIA; libx264 CPU
```

Алиасы обновляются через `git pull` — правишь [`aliases.sh`](aliases.sh), коммитишь.

## Статус

Идёт **M0** — вертикальный слайс «один клип end-to-end», по TDD.

| Этап | Состояние |
|---|---|
| Каркас + модели + конфиг | ✅ |
| Извлечение аудио (ffmpeg) | ✅ |
| Транскрипция (Groq Whisper, кэш) | ✅ |
| Сжатие транскрипта | ✅ |
| **R0 — выбор моментов (ядро)** | ✅ recall + планка + grounding проверены на реальном видео |
| R1 — нарезка + статичный кроп | ⏳ следующий (нужна калибровка профиля) |
| R3 — субтитры (ASS burn-in) | ⏳ |
| Склейка CLI | ⏳ |

Дальше — M1 (полный R0 на часовых видео + review-UI), M2 (приём по ссылке + SMM). См. [PLAN.md](PLAN.md).

## Документация

| Файл | О чём |
|---|---|
| [CLAUDE.md](CLAUDE.md) | агентские инварианты (читается каждую сессию) |
| [PROJECT_GUIDE.md](PROJECT_GUIDE.md) | архитектура, поток файлов, манифест |
| [R0_SPEC.md](R0_SPEC.md) | спецификация ядра (выбор моментов) |
| [PLAN.md](PLAN.md) | план реализации M0 → v1.0 |
| [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | раскладка репозитория |

## Технологии

Python 3.11+ · Pydantic · Groq (Whisper large-v3 + Qwen3-32B) · faster-whisper (опц. CPU-fallback) · ffmpeg · pytest

## Лицензия

[MIT](LICENSE) © 2026 Dannymor94
