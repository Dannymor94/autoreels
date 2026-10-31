# PROJECT_STRUCTURE.md — Авто-Рилс

Раскладка кодирует архитектуру: граница **ОБЛАКО / ЛОКАЛЬ** выражена физически (`src/cloud/` vs `src/local/`), а не только соглашением. Манифест — единственный мост между ними.

```
autoreels/
├── CLAUDE.md                 # агентские инварианты
├── PROJECT_GUIDE.md          # архитектура
├── R0_SPEC.md                # спецификация ядра (выбор моментов, карта, автомонтаж)
├── PLAN.md                   # план реализации и статус
├── PROJECT_STRUCTURE.md      # этот файл
├── README.md
├── pyproject.toml
├── start.sh / start.command / start.bat   # окружение + меню одной командой
├── aliases.sh                # короткие команды `arl`
├── .env.example              # GROQ_API_KEY, OPENROUTER_API_KEY; ANTHROPIC_API_KEY — платный, только по имени
│
├── config/                   # всё, что вынесено из кода (YAML)
│   ├── r0.yaml               # отбор: пресеты длины, пороги, чанки, провайдеры, `autocut:`, `anthropic:` цены, heavy_lock
│   ├── render.yaml           # ffmpeg, планы, приёмы M1.7/M55, рамка по лицу (face_model, framing_*)
│   ├── render.local.yaml.example  # машинные отличия (роль машины, путь ffmpeg) → render.local.yaml (не в git)
│   ├── transcribe.yaml       # Whisper: провайдер, чанкинг, groq.dual, whisper.cpp на gamebox
│   └── subtitles.yaml        # стиль ASS-субтитров
│
├── profiles/                 # профили сетапа (калибровка кропа, один раз)
│   └── tearoom_main.json
│
├── prompts/                  # РАНТАЙМ-инструкции LLM (≠ документация)
│   ├── r0_system.md          # рубрика виральности + кликбейт-формула (классический R0)
│   ├── r0_fewshot.json       # эталонные сегменты с реального контента
│   ├── map_system.md         # паспорта мыслей для карты источника (`arl map`)
│   ├── label_system.md, label_rank.md, label_interview.md  # авторазметка `arl label`
│   └── label_fewshot.json    # реальные строки, принятые владельцем (scripts/make_label_fewshot.py)
│                             # промпты автомонтажа, сценариста и постов живут в модулях cloud/
│
├── scripts/                  # утилиты (не часть пайплайна)
│   ├── probe_groq.py         # пробник лимитов Groq/OpenRouter (OTPM)
│   ├── eval_scores.py        # оценка модели против человека (AUC, P@K)
│   ├── make_label_fewshot.py # few-shot для `arl label` из реальной разметки
│   ├── verify_gate.py        # проверка гейт-клипов против эталонных ожиданий
│   └── gc.py                 # уборка рабочего пространства
│
├── tools/flash_check.py      # поиск мигания в готовых клипах двух планов (сверка с исходником)
├── tools/diarize.py          # M165: pyannote — разделение голосов (своё окружение с torch, `arl speakers --python`)
├── tools/font_widths.py      # M181: ширины букв шрифта → config/fonts/*.json (подгонка строк субтитров и плашки)
├── tools/grid.py             # M174/M187: сетка публикаций по смыслу после перепрогона (export/crosspost/)
├── tools/publish_dir.py      # M186/M187: общий каталог export/publish/NNN_rXX_<источник>.mp4 в порядке сетки
├── tools/measure_shots.py    # M173/M187: короткие планы и вспышки готовых клипов по review.json
├── tools/score_gate.py       # M188: таблица гейта по источникам (`score_gate.py <гейт> [--compare] [--ref <эталон>]`, M191)
├── tools/clip_checks.py      # M199: четыре проверки клипа по готовому гейту (крючок, плашка, начало без опоры, стыки) → _score/<гейт>_checks.json
├── benchmarks/golden/        # эталонные ожидания гейт-рендеров для scripts/verify_gate.py (в git)
│
├── docs/
│   ├── REEL_SPEC.md          # как собирается клип: звук, крючок, план, конец, файл, субтитры, рамка;
│   │                         #   §8 «где это в коде» с заметками по вехам
│   ├── PLAN-M1.7.md          # подача: два плана, авторитм, перестановка, ключевые слова…
│   ├── PLAN-M1.9.md          # карта интонации
│   ├── GAMEBOX.md            # локальные модели, общий замок с озвучкой книги
│   ├── pipeline-order.md     # порядок стадий сборки клипа
│   └── audit-*.md            # разборы: классы багов, 413/OTPM, нулевой урожай, концовки, пунктуация, OOM…
│
├── src/autoreels/
│   ├── __main__.py           # CLI `autoreels` / `arl`: run, auto, prepare, map, autocut, blocks, label,
│   │                         #   render, review-sheet, review-apply, describe, article, crosspost, export,
│   │                         #   tx-check/tx-compare/tx-punct/tx-use, speech-map, prosody, motion,
│   │                         #   judge-bench, gamebox, models, history, status, menu …
│   ├── prepare.py            # `arl prepare`: карта речи → выравнивание → интонация → движение → черновик → план
│   │
│   ├── core/                 # ОБЩЕЕ (оба тира)
│   │   ├── models.py         # Pydantic-схема манифеста — ЕДИНСТВЕННЫЙ контракт
│   │   ├── state.py          # статусы проекта + идемпотентность (хэши/кэш)
│   │   ├── config.py         # загрузка config/ + profiles/ (R0Config, AutocutConfig, RenderConfig…)
│   │   ├── calibration.py    # профили сетапа, кроп ролика по лицу и пути лица (reel_crop, reel_face_span)
│   │   ├── seams.py          # единое определение «шва-прыжка»
│   │   ├── heavy_lock.py     # один замок flock на тяжёлые задачи gamebox
│   │   ├── history.py        # история прогонов (data/history.jsonl)
│   │   ├── env.py            # .env / окружение
│   │   ├── memtrace.py       # opt-in трассировка памяти
│   │   └── progress.py       # индикатор прогресса
│   │
│   ├── cloud/                # ОБЛАЧНЫЙ ТИР — только текст и звук, никакого видео
│   │   ├── extract_audio.py  # ffmpeg -vn (готовит вход облаку)
│   │   ├── transcribe.py     # Whisper: Groq (в т.ч. два прохода GroqDualBackend), whisper.cpp, faster-whisper; кэш
│   │   ├── chunk_transcribe.py, transcribe_formats.py
│   │   ├── txcheck.py        # `arl tx-check`: выдумки Whisper, повторы, звук без слов
│   │   ├── compress.py       # word-level → sentence-level
│   │   ├── speechmap.py      # M1.8: карта речи по звуку
│   │   ├── select.py         # классический R0: чанки → LLM → валидация → дедуп
│   │   ├── blocks.py         # M1.6: блоки-кандидаты, отсев, выгрузка/разбор разметки
│   │   ├── label.py          # `arl label`: авторазметка блоков бесплатной LLM, проверка кодом
│   │   ├── thoughtmap.py     # M54: карта мыслей источника (`arl map`)
│   │   ├── autocut.py        # M56+: автомонтаж — генераторы, ритм прыжков, крючок, плашка, судьи
│   │   ├── scenario.py       # M123: сценарист — промпт, разбор строк, предложения
│   │   ├── speakers.py       # M165: карта говорящих (кто когда говорит), реплики ведущего
│   │   ├── taste.py          # M138: вкус владельца — модель по его клипам, только порядок предложений
│   │   ├── montage.py        # M50: клип из кусков разных блоков
│   │   ├── plan.py           # план ручного пути как одна чистая функция (REEL_SPEC §1–§4), паразиты (M126)
│   │   ├── edit.py           # сегментная модель: филлеры, x:, h:, такты `>` → окна (фабрика Segment)
│   │   ├── snap.py, trim.py, diagnose.py   # границы, висячие хвосты, классы границ
│   │   ├── postcopy.py       # M94: пост под роликом (`arl describe`)
│   │   ├── article.py        # M100: лонгрид по теме карты (`arl article`)
│   │   ├── gatescore.py      # M188: числа гейта — крючки, начала, тон конца, стыки, планы, роли мыслей, покрытие; только замер
│   │   └── providers.py      # Groq → OpenRouter, Claude (haiku/sonnet), локальная LLM; троттлинг, бэкофф
│   │
│   ├── local/                # ЛОКАЛЬНЫЙ ТИР — видео и рендер, исходник не уходит
│   │   ├── calibrate.py, crop.py           # калибровка кропа, статичный прямоугольник
│   │   ├── autocrop.py       # лица: YuNet (Haar — запасной), лицо ближе к говорящему, группы по месту
│   │   ├── render.py         # ffmpeg: окна → кроп ролика (общий/крупный) → склейка → ASS → хвост → mp4;
│   │   │                     #   обложка, атомарная запись, целостность, freezedetect, блокировка папки
│   │   ├── fx.py             # M55/M103: наезд, punch, выноски, шум на швах, полоса прогресса
│   │   ├── subtitles.py      # word-level → ASS (стиль Keyword, скрытые паразиты)
│   │   ├── align.py          # принудительное выравнивание слов по звуку
│   │   ├── prosody.py        # интонация конца предложения (↘ / →)
│   │   ├── voice.py          # громкость и тон участка — для швов монтажа
│   │   ├── motion.py         # насколько виден рез (разница картинки)
│   │   ├── scenes.py         # PySceneDetect
│   │   ├── review_sheet.py   # лист ревью `_review.html`
│   │   ├── map_page.py       # страница карты `_map.html`
│   │   └── hashtags.py       # хэштеги из сказанных слов (архивация исходников — _archive_video в __main__)
│   │
│   └── orchestr/             # заглушки: api.py (FastAPI), queue.py, ingest.py (M2)
│
├── tests/                    # TDD: ~100 файлов, ~2470 тестов; LLM мокается реальными ответами
│   │                         #   гварды: запись в репо, голые конструкторы Segment/Word,
│   │                         #   список стадий ручного пути, суффиксы sidecar, пути от _project_root
│   │                         #   не запускать во время рендера (гвард следит за reels-out/)
│   ├── conftest.py
│   ├── fixtures/             # реальные ответы LLM (в т.ч. сценарист Sonnet), короткие транскрипты
│   └── test_*.py
│
├── handoff/                  # задачи ассистента из ветки `handoff` (в .gitignore main)
├── inputs/                   # исходные видео (gitignored)
├── inputs-archive/           # обработанные видео
├── manifests/                # JSON-манифесты (в git — контракт между машинами)
├── calibrations/             # профили кропа + PNG кадров (в git)
├── reels-out/<stem>/         # mp4, .cover.jpg, .post.txt, .txt, index.md, _review.html, _map.html (gitignored)
│   └── _gate/<имя>/          # проверочные рендеры, отдельно от настоящих клипов
├── export/                   # crosspost / export / article — для импорта, не публикация (gitignored)
├── reviews/                  # разметка (НЕ в git — порча невосстановима):
│                             #   *_answer.txt — владельца; <stem>_auto_*.txt — черновики автомонтажа;
│                             #   *.review.json — копии манифестов (не применять)
├── transcripts/              # транскрипты, <stem>.speechmap.json, <stem>.map.json (gitignored)
└── data/                     # рантайм (gitignored, кроме blocks_dataset/)
    ├── cache/                # транскрипты; autocut_judge.json (ответы судей); scenario/ (ответы сценариста)
    ├── models/               # face_detection_yunet_2023mar.onnx (качается один раз, см. render.yaml)
    ├── blocks_dataset/       # эталонные оценки человека (в git)
    ├── history.jsonl         # история прогонов (`arl history`)
    └── token_scale.json      # EMA-калибровка оценки токенов
```

## Принципы раскладки

- **`cloud/` ⟂ `local/`** — несущая граница. Код в `cloud/` никогда не открывает видеоряд (только аудио/текст); код в `local/` никогда не ходит в API. `extract_audio.py` сидит на границе и потому в `cloud/` (готовит вход облаку), хотя физически гоняет локальный ffmpeg. Лица и обложки — `local/`: им нужны кадры.
- **`prompts/` ≠ документация.** `prompts/` — рантайм-инструкции LLM. `CLAUDE.md`/`*_SPEC.md` — инварианты для агента/человека.
- **`config/` + `profiles/`** — всё настраиваемое. В коде — ноль магических чисел; в документации значения не повторяются, только ссылка на файл.
- **`core/models.py`** — единственное место схемы манифеста.
- **Черновик автомонтажа — та же разметка, что у человека.** `autocut`/`scenario` пишут строки в `reviews/`; дальше их ведёт ручной путь (`plan.py`), и правила клипа живут в одном месте.
- **`cloud/edit.py` — фабрика окон.** Сегменты и слова создаются в фабриках (`cloud/edit.py`, `cloud/transcribe.py`, `core/models.py`); в остальном коде — только `model_copy`. Гвард-тест это проверяет.
- **Проверочные рендеры** — только в `reels-out/<stem>/_gate/`: запись демо поверх настоящих клипов запрещена кодом.
