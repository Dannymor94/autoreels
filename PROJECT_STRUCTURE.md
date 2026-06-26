# PROJECT_STRUCTURE.md — Авто-Рилс

Раскладка кодирует архитектуру: граница **ОБЛАКО / ЛОКАЛЬ** выражена физически (`src/cloud/` vs `src/local/`), а не только соглашением. Манифест — единственный мост между ними.

```
auto-reels/
├── CLAUDE.md                 # агентские инварианты
├── PROJECT_GUIDE.md          # архитектура
├── R0_SPEC.md                # спецификация ядра
├── PLAN.md                   # план реализации (M0→v1.0)
├── PROJECT_STRUCTURE.md      # этот файл
├── pyproject.toml
├── README.md
│
├── config/                   # всё, что вынесено из кода (YAML)
│   ├── r0.yaml               # пресеты длины, пороги score, чанки, языки
│   └── render.yaml           # параметры ffmpeg, NVENC, путь шрифтов
│
├── profiles/                 # профили сетапа (калибровка кропа, один раз)
│   └── tearoom_main.json     # {crop:{x,y,w,h}, scale:[1080,1920]}
│
├── prompts/                  # РАНТАЙМ-инструкции LLM (≠ документация)
│   ├── r0_system.md          # рубрика виральности + кликбейт-формула (EN)
│   └── r0_fewshot.json       # эталонные сегменты с реального контента
│
├── src/autoreels/
│   ├── __main__.py           # CLI: run / transcribe / select / render
│   │
│   ├── core/                 # ОБЩЕЕ (оба тира)
│   │   ├── models.py         # Pydantic-схема манифеста — ЕДИНСТВЕННЫЙ контракт
│   │   ├── state.py          # статусы проекта + идемпотентность (хэши/кэш)
│   │   └── config.py         # загрузка config/ + profiles/
│   │
│   ├── cloud/                # ОБЛАЧНЫЙ ТИР — только текст, никакого видео
│   │   ├── extract_audio.py  # ffmpeg -vn (на границе: локальное действие, но готовит вход облаку)
│   │   ├── transcribe.py     # Whisper (Groq | faster-whisper) → word-level, кэш
│   │   ├── compress.py       # word-level → sentence-level + таймкоды
│   │   ├── select.py         # R0: чанкинг → LLM → парсинг → валидация → дедуп
│   │   └── providers.py      # Groq → OpenRouter, троттлинг, бэкофф, prompt-cache
│   │
│   ├── local/                # ЛОКАЛЬНЫЙ ТИР — рендер, исходник не уходит
│   │   ├── crop.py           # статичный прямоугольник из профиля
│   │   ├── subtitles.py      # word-level → ASS (стиль + группировка слов)
│   │   ├── scenes.py         # PySceneDetect, snap границ (M1)
│   │   └── render.py         # ffmpeg: cut → crop → burn ASS → mp4
│   │
│   └── orchestr/             # ОРКЕСТРАЦИЯ (M1+) — появляется не сразу
│       ├── api.py            # FastAPI: upload, status, approve
│       ├── queue.py          # очередь прогонов
│       └── ingest.py         # yt-dlp приём по ссылке (M2)
│
├── ui/                       # React review-UI (M1) — паттерн из Meeting→Tasks
│   └── ...
│
├── tests/                    # TDD: детерминированный слой покрыт, LLM мокается
│   ├── test_compress.py
│   ├── test_select_validate.py   # валидаторы, дедуп, snap
│   ├── test_models.py            # схема манифеста
│   ├── test_render.py            # разрешение/длительность выхода
│   └── fixtures/                 # реальные ответы LLM, короткие транскрипты
│
├── data/                     # рантайм (gitignored)
│   ├── cache/                # транскрипты по хэшу аудио
│   ├── runs/                 # манифесты прогонов
│   └── outputs/              # готовые mp4
└── ...
```

## Принципы раскладки

- **`cloud/` ⟂ `local/`** — несущая граница. Код в `cloud/` никогда не открывает видеоряд (только аудио/текст); код в `local/` никогда не ходит в API. `extract_audio.py` сидит на границе и потому в `cloud/` (готовит вход облаку), хотя физически гоняет локальный ffmpeg.
- **`prompts/` ≠ документация.** `prompts/` — рантайм-инструкции LLM. `CLAUDE.md`/`*_SPEC.md` — инварианты для агента/человека. Разделены физически (твой принцип из Meeting→Tasks).
- **`config/` + `profiles/`** — всё настраиваемое вынесено сюда. В коде — ноль магических чисел.
- **`core/models.py`** — единственное место схемы манифеста. Меняешь контракт между тирами — только здесь.
- **`orchestr/` и `ui/`** появляются в M1, не в M0. Структура заложена, но не наполняется раньше времени.
