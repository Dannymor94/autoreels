# M133 — ревью кода и состояния папки (ТОЛЬКО ЧТЕНИЕ)

Выполнено без изменений в репозитории. Рабочая копия на `a86a1a2` (main, ahead 1).
Параллельно шёл MAIN — ничего не трогал. Номера строк скана — от `c9bd55a` (могли сдвинуться, имена актуальны).

Полный инвентарь — `handoff/m133/folder_audit.md`.

---

## 1. Папка

### Незакоммиченное / неотслеживаемое в git
| что | откуда | предложение |
|---|---|---|
| `data/token_scale.json` (M, 1 строка) | калибровка токенов, файл отслеживается | **оставить** — похоже результат калибровки; коммитить (MAIN), либо откатить, если локальный дрейф |
| `data/models/` (227 КБ, YuNet onnx) | модель лица (`face_model`), не ignored | **решить**: в `.gitignore` (бинарник) или коммитить — сейчас в лимбе |
| `manifests/_archive/` (+ `IMG_6848.2026-10-08.json.bak`) | ручной архив старых манифестов, не ignored | **в архив/удалить** — манифесты в git, backup-копия лишняя |
| `manifests/PXL_20260729_copy.discarded.json` | sidecar, не попал в обнаружение | оставить (sidecar) |
| `transcripts/*.json` (~70 untracked) | транскрипты локальные, **но не gitignored** → засоряют `git status` | **в архив**: много экспериментов `IMG_6848.local-m111-*`, `*.txcompare-*`, `Pxl…m114-novad-*` — одноразовые пробы транскрипции |
| `transcripts/_archive/` | уже перенесённые | оставить/чистить локально |

Чистых «источников манифестов вне inputs*/» нет — все 8 манифестов нашли свой файл в `inputs*/` по имени.

### Место
- `inputs-archive/` — **25 ГБ**, 7 исходников (крупнейший `Pxl 20260621 112938952.mp4` 9.8 ГБ). Это рабочие исходники — **оставить**.
- `reels-out/` — **24.2 ГБ**, почти всё в `_gate/` (гейт-рендеры): IMG_6848 35 гейтов/5.4 ГБ, Pxl 112938952 28 гейтов/4.6 ГБ, 11h42 21 гейт/7.1 ГБ. Старые гейты 15–21 д. **В архив/удалить** гейты старше 14 д (кроме нужных для открытых шагов) — освобождает ~15–20 ГБ. Реальных клипов (вне `_gate`) мало.
- `data/cache/` — 588 МБ: `chunks/` 184 МБ, `*.motion.npz` ~140 МБ, mp3 ~250 МБ. Кэш, восстановимо — **оставить**, чистить при нехватке места.
- `export/crosspost/` — 395 МБ готовых клипов на импорт — оставить до публикации.

### Мусор
- **113** temp/lock-файлов (раздел 4 аудита): почти все — **stale `.render.lock` (0 Б, 5–15 д)** по всем источникам/гейтам. Рендер не идёт → замки протухли. **Удалить** пустые `.render.lock` старше суток (безопасно; MAIN держит свой — его не трогать).
- `.bak`: `reviews/PXL_20260729_copy_auto.txt.bak`, `reviews/_montage2/lec0933_answer_montage.txt.bak`, `manifests/_archive/IMG_6848.2026-10-08.json.bak`, `handoff/m52/09h33_copy.txt.bak` — **удалить** (оригиналы на месте).
- `.DS_Store` в `reels-out/` и `reviews/` — **удалить**, добавить в `.gitignore`.
- Нечитаемых/пустых манифестов нет; сироты в `transcripts/` — 1 (`PXL_20260729_085910095`, норма).
- Замечание по аудиту: `reviews/` — **отдельный git-репозиторий** (`reviews/.git`, ветка main, ignored в основном). «574 other» в разделе 7 — это его `.git/*`, не мусор; `folder_audit.py` зашёл в `.git` при rglob (косметика скрипта).

### Чего не хватает
Ничего критичного: `config/render.local.yaml` **есть** (`role: both`), YuNet-модель **есть**, `.env` есть. 

---

## 2. Скан (vulture) — проверка

### A. Мёртвый код (кандидаты на удаление)
| файл:строка | имя | класс | почему |
|---|---|---|---|
| __main__.py:2685 | `_Seg` | dead | импорт `Segment as _Seg` не используется |
| __main__.py:5725 | `_Segment` | dead | импорт в общей строке не используется (остальные алиасы живые) |
| __main__.py:5866 | `dropped_blks` | dead | распаковка кортежа, не читается (→ `_`) |
| __main__.py:5949 | `_wis` | dead | `words_in_span as _wis` не используется |
| cloud/autocut.py:550 | `Judge` | **dynamic** | тип-алиас, живёт в строковых аннотациях (FP vulture) |
| cloud/blocks.py:477 | `falloff_end` | dead | посчитан, но `return` считает знаменатель заново |
| cloud/blocks.py:487 | `_BSC` | dead | локальный импорт «против цикла», ни разу не использован |
| cloud/label.py:379 | `kept_nums` | dead | присвоено, не читается |
| cloud/label.py:625 | `err2` | dead | распаковка, не читается |
| cloud/plan.py:313 | `_ends_with_stop` | dead | функция без вызовов |
| cloud/providers.py:340,372 | `last_status` | dead | присвоен `status_code`, не читается (потерян в сообщении об ошибке) |
| cloud/snap.py:123 | `_pause_word_ends` | dead | функция без вызовов |
| cloud/snap.py:225 | `_prefer_longer_end` | dead | функция без вызовов (тест упоминает лишь «старое поведение» в комменте) |
| core/calibration.py:56 | `Calibrator` | dead | Protocol без наследников/использований (`ManualCalibrator` структурно не связан) |
| core/env.py:20 | `API_KEY_NAMES` | dead | кортеж не используется |
| core/models.py:169 | `self_contained_start` | **dead** | поле модели никто не пишет и не читает (grounding-поле не заведено) |
| core/models.py:170 | `start_justification` | **dead** | поле модели никто не пишет и не читает |
| core/models.py:203 | `subtitle_emph_words` | **dead⚠** | поле эмфазы (M1.7-2) никто не пишет и не читает — фича `k:`/эмфаза в рендер не заведена |
| local/render.py:132 | `wall` | dead | `time.time()` «approx», не используется |
| prepare.py:20 | `STAGES` | dead | кортеж стадий нигде не читается (prepare гоняет стадии иначе) |

### B. Поля конфига, которые код не читает (YAML-ручка ничего не делает)
| файл:строка | имя | класс | почему |
|---|---|---|---|
| core/config.py:489 | `chunk_overlap_sec` | **config-noop** | `r0.yaml:46 = 60` нигде не читается |
| core/config.py:553 | `prompt_language` | **config-noop** | `r0.yaml:141 = en` не читается (язык промпта захардкожен) |
| core/config.py:767 | `intrusion_guard_sec` | **config-noop** | `render.yaml:85 = 0.12` не читается (fade-гард вторжения не применяется) |
| core/config.py:844 | `margin_v` | **config-noop** | `render.yaml:238 = 300` не читается; реальная ручка позиции субтитров — `position_v` (config.py:1104) |
| core/config.py:846 | `font_dir` | **config-noop** | `render.yaml:241 = null` не читается (нет `fontsdir` в argv), хотя доки обещают «под машину рендера» |
| core/config.py:996 | `shot_tolerance_frames` | test-only (НЕ noop) | Pydantic-поле читают только тесты, **но** YAML-ручка работает — `scripts/verify_gate.py:31` читает сырой yaml |
| core/config.py:644,1062,1069 | `_sync_block_min_sec`, `_validate_transition`, `_validate_role` | **dynamic** | Pydantic `@model_validator`/`@field_validator` — вызываются при создании |

### C. Используется только тестами
Подтверждённо test-only (прод-путь другой) — вопрос «оставить как API или удалить с тестом»:
| файл:строка | имя | класс | почему |
|---|---|---|---|
| cloud/providers.py:1327 | `FallbackLLM` | **dead-legacy** | «устаревшая, оставлена для совместимости», нигде не создаётся |
| local/archive.py:36,47,67 + __main__.py:75 | `is_archived`,`archive_input`,`borrow_from_archive` | **dead⚠** | импорт в `__main__` не вызван; авто-архивация источника не заведена |
| core/state.py:34 | `file_sha256_cached` | test-only | прод везде зовёт `file_sha256_cached_fast` (partial) |
| local/render.py:339,3908 | `estimate_size_mb`,`render_cut` | test-only | прод-рендер идёт другим путём |
| __main__.py:1676,1889 | `_shot_spans_merged`,`assign_shots` | test-only | прод-путь — `_stage_two_shot_auto` (batch) |
| cloud/blocks.py:1150 | `_make_merged_block` | test-only | вызывают только тесты |
| cloud/montage.py:101 | `is_montage_line` | test-only | вызывают только тесты |
| cloud/select.py:227 | `filter_min_clip_duration` | test-only | вызывают только тесты |
| cloud/speechmap.py:40 | `CUT_PAUSE_MIN_SEC` | test-only | константа не читается в проде |

Поля-модели/диагностика (пишутся в проде, читаются тестами → контракт манифеста, **не удалять**): `ends_on_host_turn`, `rejected_alignment`, `start_repair_sec`, `start_drift_sec`, `end_drift_sec`, `prompt_leak_removed`, `topic`, `last_marks` → **dynamic**.

### D. `except …: pass/continue`
| файл:строка | класс | почему |
|---|---|---|
| __main__.py:1807 | swallow-ok | промах кэша speechmap → пересборка ниже |
| __main__.py:4476 | **swallow-bad** | битый `r0.yaml` молча обнуляет `credit_word_patterns` (фича тихо выключается, без предупреждения) |
| __main__.py:4648 | swallow-ok | нет источника → speechmap опускается (деградация) |
| __main__.py:5247 | **swallow-bad⚠** | нечитаемый манифест → `continue` в учёте для удаления сирот; его stem не посчитан → риск удалить как сироту |
| __main__.py:6006 | swallow-ok | промах кэша block-speechmap → пересборка |
| __main__.py:6962 | swallow-ok | битая строка JSONL пропускается |
| __main__.py:10352 | swallow-ok | устойчивый перебор файлов транскриптов |
| local/render.py:687 | **swallow-bad** | сбой проверки tail-seam SSIM молча `return None` — проверка качества шва бесшумно «проходит» (CLAUDE.md: проверка не пропускает проблемный случай) |

---

## 3. Ручной просмотр

Прочитаны целиком: `cloud/scenario.py`, `local/autocrop.py`, функции `_source_face`/`_reel_framing` (`render.py`). Скан по `cloud/autocut.py`, `cloud/plan.py`.

Инвариантных нарушений не найдено. Проверено: голых конструкторов `Segment(`/`Word(` в целевых файлах нет; путей не от `_project_root()` нет; `scenario.py` строго следует инв.1 (модель предлагает, код проверяет каждую строку).

Находки:
1. **core/models.py:203 `subtitle_emph_words` — средняя.** Поле эмфазы M1.7-2 определено, но ни рендер, ни парсинг его не пишут/читают → фича эмфазы (`k:`) не заведена в рендер. (Память `[[m1_7_step2_emphasis]]`: «гейт-рендер в процессе» — похоже, не завершено.) Проверить, работает ли вообще эмфаза.
2. **local/archive.py — средняя.** Весь модуль архивации (`archive_input`/`is_archived`/`borrow_from_archive`) не вызывается из прода, импорт в `__main__:75` мёртв. Инв.3 говорит «источник архивируется/не архивируется» — механизма в рантайме нет. Либо фича не дописана, либо мёртвая.
3. **render.py:687 tail-seam SSIM — средняя.** Проверка шва глушит исключение и возвращает «ок» (None). Нарушает дисциплину «проверка не пропускает проблемный случай».
4. **cloud/plan.py:56–59 filler/pause — низкая (проверить).** Пороги `filler_min_sec`/`pause_max_sec` работают по зазорам между словами. Инв.9: паузы не выводятся из зазоров Whisper, только карта речи/alignment. Судя по контексту (`load_alignment`, «untranscribed speech»), читается alignment — вероятно ок, но стоит подтвердить, что не сырой Whisper.
5. **config-noop (раздел B) — средняя.** 5 YAML-ручек ничего не делают (`chunk_overlap_sec`, `prompt_language`, `intrusion_guard_sec`, `margin_v`, `font_dir`) — нарушение «конфиг вынесен, а не хардкод»: правка значения в yaml не меняет поведение.
6. **manifests/PXL_20260729_copy.json — средняя.** Единственный манифест с `selection_source = None` (и top-level, и во всех рилах), остальные `human`. Инв.5 (ручной путь vs авто) опирается на это поле — None неоднозначен на `--apply`/рендере. Проверить дефолт.
7. **scenario.py:200 `score=max(40, 95-rank)` — низкая.** Магические 95/40 для сортировки (скор — только подсказка, инв.1 допускает). Можно вынести, не срочно.
8. Дублирования логики autocut/scenario/plan не обнаружено: `scenario.py` переиспользует `rhythm_pieces`/`rhythm_why`/`_hook_cands` из `autocut.py`; `plan.py` — отдельная забота (тайминг реза).
9. Флагов «всегда включён, флаг можно убрать» в беглом скане не видно (`reel_framing`, `two_shot_xfade`, `use_filtered`, `rhythm` переключаемы и имеют выключенную ветку).

Высокая срочность: **0.** Средняя: находки 1–3, 5–6 + swallow-bad __main__:5247.

---

## 4. Предлагаемые действия (каждое — отдельной будущей задачей)

1. **Чистка `.render.lock` и `.DS_Store`**: удалить stale `.render.lock` (0 Б, >1 д) и `.DS_Store` во всём дереве, добавить `.DS_Store` в `.gitignore`. MAIN-замок не трогать.
2. **Чистка старых гейтов**: удалить `reels-out/<src>/_gate/*` старше 14 д, кроме нужных для открытых шагов (спросить владельца, какие держать). ~15–20 ГБ.
3. **Разобрать untracked**: решить судьбу `data/models/` (gitignore vs commit), `manifests/_archive/` (удалить), `transcripts/` экспериментов (архив), `.bak`-файлов (удалить). Добавить `transcripts/` в `.gitignore`, если он не должен быть в статусе.
4. **config-noop (дефект)**: либо завести чтение 5 ручек (`chunk_overlap_sec`, `prompt_language`, `intrusion_guard_sec`, `margin_v`→unify с `position_v`, `font_dir`→`fontsdir` в argv), либо удалить поля+yaml. `font_dir` и `intrusion_guard_sec` — приоритетнее (обещаны в доках/коде).
5. **swallow-bad**: __main__:5247 (нечитаемый манифест в учёте сирот → риск удаления) и render.py:687 (tail-seam SSIM молча ок) — предупреждать/падать, не глотать. __main__:4476 (битый r0.yaml) — логировать.
6. **subtitle_emph_words / эмфаза (M1.7-2)**: проверить, заведена ли фича `k:` в рендер; либо дозавести, либо удалить поле.
7. **archive.py**: решить — дописать авто-архивацию (инв.3) или удалить модуль + мёртвый импорт в `__main__:75`.
8. **PXL_20260729_copy.json selection_source=None**: проверить обработку None на `--apply`/рендере; проставить корректный источник.
9. **FallbackLLM + мёртвый код (раздел A)**: удалить `FallbackLLM` (legacy) и dead-импорты/переменные одним проходом.
10. **косметика folder_audit.py**: исключить вложенные `.git` из rglob (сейчас `reviews/.git` даёт «574 other»).
