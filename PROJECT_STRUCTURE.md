# PROJECT_STRUCTURE.md — Авто-Рилс

Раскладка кодирует архитектуру: граница **ОБЛАКО / ЛОКАЛЬ** выражена физически (`src/cloud/` vs `src/local/`), а не только соглашением. Манифест — единственный мост между ними.

```
autoreels/
├── CLAUDE.md                 # агентские инварианты
├── PROJECT_GUIDE.md          # архитектура
├── R0_SPEC.md                # спецификация ядра
├── PLAN.md                   # план реализации (M0→v1.0)
├── PROJECT_STRUCTURE.md      # этот файл
├── pyproject.toml
├── README.md
│
├── config/                   # всё, что вынесено из кода (YAML)
│   ├── r0.yaml               # пресеты длины, пороги score, чанки, языки, OTPM-параметры
│   ├── render.yaml           # параметры ffmpeg, NVENC, путь шрифтов
│   ├── transcribe.yaml       # параметры Whisper и чанкинга аудио
│   └── subtitles.yaml        # стиль ASS-субтитров
│
├── profiles/                 # профили сетапа (калибровка кропа, один раз)
│   └── tearoom_main.json     # {crop:{x,y,w,h}, scale:[1080,1920]}
│
├── prompts/                  # РАНТАЙМ-инструкции LLM (≠ документация)
│   ├── r0_system.md          # рубрика виральности + кликбейт-формула (EN)
│   └── r0_fewshot.json       # эталонные сегменты с реального контента
│
├── scripts/                  # утилиты (не часть пайплайна)
│   └── probe_groq.py         # прямой пробник Groq/OpenRouter лимитов (OTPM-измерение)
│
├── docs/                     # аудиты и технические разборы
│   ├── audit-groq-413.md     # корень 429: OTPM = 1000 tok/min (не входной TPM)
│   ├── audit-groq-throttling.md
│   ├── audit-inputs-scanner.md
│   ├── audit-moment-selection.md
│   ├── audit-oom.md          # OOM-диагностика: Python-аллокации не виноваты; ffmpeg-декод
│   ├── audit-punctuation.md
│   └── audit-r0-budget.md
│
├── src/autoreels/
│   ├── __main__.py           # CLI: run / transcribe / select / render / calibrate /
│   │                         #      resnap / dump-clips / diagnose-cuts / models / ...
│   │
│   ├── core/                 # ОБЩЕЕ (оба тира)
│   │   ├── models.py         # Pydantic-схема манифеста — ЕДИНСТВЕННЫЙ контракт
│   │   ├── state.py          # статусы проекта + идемпотентность (хэши/кэш)
│   │   ├── config.py         # загрузка config/ + profiles/
│   │   ├── calibration.py    # работа с профилями сетапа
│   │   ├── env.py            # чтение .env / окружения
│   │   ├── memtrace.py       # opt-in трассировка памяти (AUTOREELS_MEMTRACE=1)
│   │   └── progress.py       # индикатор прогресса
│   │
│   ├── cloud/                # ОБЛАЧНЫЙ ТИР — только текст, никакого видео
│   │   ├── extract_audio.py  # ffmpeg -vn (готовит вход облаку)
│   │   ├── transcribe.py     # Whisper (Groq | faster-whisper) → word-level, кэш
│   │   ├── chunk_transcribe.py  # чанкинг аудио >15 мин для Whisper (VAD-границы)
│   │   ├── transcribe_formats.py  # конвертация word-level → srt/vtt/text
│   │   ├── compress.py       # word-level → sentence-level + таймкоды
│   │   ├── select.py         # R0: чанкинг → LLM → парсинг → валидация → дедуп
│   │   ├── snap.py           # snap границ к словам/паузам (R4-min)
│   │   ├── trim.py           # обрезка висячих слов на хвосте клипа
│   │   ├── diagnose.py       # классификация границ фраз (CLEAN/SOFT/HARD)
│   │   └── providers.py      # Groq → OpenRouter, троттлинг, бэкофф
│   │
│   ├── local/                # ЛОКАЛЬНЫЙ ТИР — рендер, исходник не уходит
│   │   ├── calibrate.py      # калибровка кропа по кадрам видео
│   │   ├── crop.py           # статичный прямоугольник из профиля
│   │   ├── subtitles.py      # word-level → ASS (стиль + группировка слов)
│   │   ├── scenes.py         # PySceneDetect (M1)
│   │   ├── render.py         # ffmpeg: cut → crop → burn ASS → mp4
│   │   └── archive.py        # перенос обработанных видео в inputs-archive/
│   │
│   └── orchestr/             # ОРКЕСТРАЦИЯ (M1+)
│       ├── api.py            # FastAPI: upload, status, approve (заглушки)
│       ├── queue.py          # очередь прогонов (заглушка)
│       └── ingest.py         # yt-dlp приём по ссылке (M2, заглушка)
│
├── tests/                    # TDD: детерминированный слой покрыт, LLM мокается (~1190 тестов)
│   ├── conftest.py
│   ├── fixtures/             # реальные ответы LLM, короткие транскрипты
│   └── test_*.py             # по одному файлу на модуль
│
├── inputs/                   # исходные видео (gitignored)
├── inputs-archive/           # обработанные видео после архивирования
├── manifests/                # JSON-манифесты прогонов (gitignored кроме dev-примеров)
├── reels-out/                # готовые mp4 (gitignored)
├── transcripts/              # текстовые транскрипты (gitignored)
├── calibrations/             # JSON + PNG кадров калибровки (gitignored)
└── data/                     # рантайм (gitignored)
    ├── cache/                # транскрипты по хэшу аудио
    └── token_scale.json      # EMA-калибровка оценки токенов
```

## Принципы раскладки

- **`cloud/` ⟂ `local/`** — несущая граница. Код в `cloud/` никогда не открывает видеоряд (только аудио/текст); код в `local/` никогда не ходит в API. `extract_audio.py` сидит на границе и потому в `cloud/` (готовит вход облаку), хотя физически гоняет локальный ffmpeg.
- **`prompts/` ≠ документация.** `prompts/` — рантайм-инструкции LLM. `CLAUDE.md`/`*_SPEC.md` — инварианты для агента/человека. Разделены физически.
- **`config/` + `profiles/`** — всё настраиваемое вынесено сюда. В коде — ноль магических чисел.
- **`core/models.py`** — единственное место схемы манифеста. Меняешь контракт между тирами — только здесь.
- **`orchestr/`** появляется в M1 (заглушки в репо); наполняется не раньше R2-review-UI.
