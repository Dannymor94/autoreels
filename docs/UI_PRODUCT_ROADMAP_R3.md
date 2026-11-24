# Autoreels — UI/UX, продуктовая архитектура и план реализации R3

Дата: 2026-11-24. Базовый срез main: `3e91e6bec5488fd132f9776550c618b962442f22`.
Статус: проектный план после повторной сверки; требует принятия владельцем через merge документа. Не является CODE GO, MEDIA GO, разрешением на установку пакетов, сетевые/платные вызовы или обработку реальных материалов.

## 1. Назначение и источники истины

Autoreels — инструмент производства коротких видео и, в перспективе, очистки целого видео. Один редактор, мобильный приоритет, автоматический и ручной режимы, детерминированное исполнение. LLM не управляет программой: она предлагает смысловые решения, код проверяет и применяет их.

Этот документ объединяет продуктовый план, технические контракты, UX, перечень функций, кандидатов OSS и этапы реализации. После принятия он задаёт последовательность развития UI вместо прежней последовательности R2. [PLAN-UI.md](PLAN-UI.md) и [UI-HANDOFF.md](UI-HANDOFF.md) остаются историей и источником совместимых контрактов. При противоречиях с [CLAUDE.md](../CLAUDE.md), [PLAN.md](../PLAN.md), [REEL_SPEC.md](REEL_SPEC.md) и [M232/M233 handoff](M232_M233_CLOSURE_AND_HANDOFF.md) действуют их инварианты и отдельные решения владельца; изменения контрактов оформляются явно, а не молчаливой заменой.

Не переоткрывать M232 A6/A7, отвергнутые гипотезы скоринга, трекинг лица, active-speaker tracking, облачный рендер, публикацию, RAG, многопользовательность, PostgreSQL. Не строить аналог CapCut целиком до появления потребности. Не делать полный рефакторинг CLI, второй движок рендера или платформенную миграцию ради UI.

## 2. Исходное состояние и узкие места

Проверено статически на указанном main; ветка ui на момент аудита — 5f5455cb9e5a1801a11e8597c711b877cac9b9f0. Каркас U1–U2d в main, не рабочий полноценный редактор. Не заявляется runtime PASS, свежий CI, результат мобильных тестов или реальный пилот.

| Что | Фактическое состояние / узкое место | Действие |
|---|---|---|
| Конвейер | Подготовка, транскрипция, speech map, разметка, autocut, планы, рендер, субтитры, посты, экспорт, ручное ревью существуют | Переиспользовать, не дублировать |
| M232/M233 | M232 закрыт; G0 pure evaluation влит; G1–G3 не начаты | Отдельный пилот только по MEDIA GO; не блокирует UI |
| UI | React 18 / TypeScript / Vite, TanStack Query, FastAPI, OpenAPI-типы, список, карточки, плеер, варианты, позиция, переименование | Сохранить пригодные компоненты; мобильную компоновку создать заново |
| API | Реальные routes в orchestrator/app.py; api.py, queue.py, ingest.py — заглушки; gateway возвращает fallback verdict_tags | Типизированный адаптер, затем по одному рабочему сценарию |
| Источники | _list_sources строится по reels-out и только с найденными MP4 | Список по данным источника, манифестам, заданиям и артефактам; показать ошибки и черновики |
| Вердикты | CLI review-apply, reviews/verdicts.jsonl, старый UI-контракт отдельного журнала reviews/verdicts/<stem>.jsonl | Не создавать два независимых журнала решений: согласовать адаптер и миграцию в UI-103; технические замечания и экспортные решения имеют разные семантики |
| Идентичность | rNN, stem, вариант и render fingerprint недостаточны для устойчивой идентичности | Стабильные ID, revision, привязка к точному артефакту, миграция с отказом при неоднозначности |
| Время | Reel.playback_windows, segments, cold_open, reordered, скорость, паузы и искусственные хвосты; Word без устойчивого ID | Единая карта сыгранного времени и источника, typed operations |
| Настройки | Pydantic config + YAML + CLI overrides; часть параметров зависит от машины | Allowlist пользовательских настроек и capability registry, фиксировать эффективный профиль |
| CLI | __main__.py >14 тыс. строк; печатные progress/stage строки | Извлекать узкие публичные интерфейсы по необходимости; не разбирать локализованный stdout как контракт |
| Безопасность | Uvicorn привязан к 127.0.0.1; media path/symlink guards и Range-тесты есть | Не открывать порт наружу; private authenticated access; сохранить guards |
| Просмотр | Только отрендеренные видео; длительность/thumbnail по запросу, кэш по файловым атрибутам | Кэш метаданных и лёгкие локальные прокси; нагрузку измерить |
| Потенциальный дефект | cmd_auto 11346–11377: n=0 может пройти к results ok; требуется воспроизведение, а не утверждение о подтверждённом баге | Адресный тест empty harvest/nonempty transcript, отсутствие архивации |
| M217 | Старая сводка о 26 локальных манифестах и двух тестах; текущий статус локальных файлов не установлен | Не удалять и не перезаписывать; сверить только по необходимости с владельцем |

Кодовые ссылки: [app.py](../src/autoreels/orchestr/app.py), [pipeline_gateway.py](../src/autoreels/orchestr/pipeline_gateway.py), [models.py](../src/autoreels/core/models.py), [config.py](../src/autoreels/core/config.py), [CLI](../src/autoreels/__main__.py), [UI](../ui/src), [API tests](../tests/ui).

## 3. Продукт и UX

Три сценария при создании проекта:
1. Нарезать длинный исходник на самостоятельные рилсы (существующий основной путь).
2. Обработать целое видео (новый режим, отдельный контракт длительности/отбора, без искусственного деления на рилсы; только после проверки ограничений). Gling-подобное удаление пауз/дублей, оформление.
3. Смонтировать вручную (поэтапно: сначала один источник и текст, затем слои).

Один рабочий проект, три уровня сложности, без копирования проекта при переключении:
- Авто: исходник → пресет → обработать → ревью → экспорт.
- Настраиваемый: независимые модули, понятные параметры, ручная корректировка текста и изображения.
- Расширенный: таймлайн, точные интервалы, слои, микшер, анимация и keyframes по мере готовности.

Основная навигация: Проекты, Редактор, Задания, Экспорт. На телефоне — нижняя навигация с safe areas; настройки контекстно. Редактор: вертикальное превью, вкладки Авто / Текст / Монтаж, действия в нижней панели, инспектор выбранного объекта. На компьютере те же компоненты, боковые панели, горячие клавиши, больше пространства. Скрытие инструментов не сбрасывает выбор и настройки. Понятные русские названия, доступные hit targets (ориентир ≥44 CSS px), управление клавиатурой, отсутствие горизонтального скролла страницы, явные загрузка/ошибка/пустое состояние. Таймлайн может прокручиваться отдельно. Не делать свайп единственным способом выполнения действия.

Сценарии:
- Проекты: список всех стадий, поиск, имя, дата, превью, статус, продолжить работу; добавить разрешённый локальный источник или ссылку Я.Диска (импорт только после GO).
- Авто: пресет + переключатели основных механик; разворачиваемые расширенные параметры; итоговый профиль перед запуском; видимые причины недоступности.
- Ревью: один тап оставить/исправить/убрать, замечание на позиции, причина, комментарий, переход к следующему; различать производственный вердикт и техническую заметку. Сравнение версий последовательно на телефоне, рядом на desktop, синхронизация по общему источнику при наличии карты; одинаковая секунда ролика не всегда означает одинаковый фрагмент.
- Текст: сыгранные и удалённые слова, текущая позиция, выбор диапазона, восстановление, начало/конец, разрез, перестановка, пометка ключевого слова. Исправление написания субтитров отдельно от удаления речи; действия имеют preview/undo. Не переносить произвольные изменения распознанного текста в звук.
- Кадр: tap по субтитрам/слою, перетаскивание, масштаб, допустимые границы, crop guides, safe zones; инспектор свойств. Ручной статичный кроп; смена существующих планов; не вводить трекинг.
- Таймлайн: zoom/pan, playhead, waveform, snap к слову/паузе/кадру, ручки trim/split/move, клипы/речь/субтитры/вставки/музыка по мере поддержки; жесты только изменяют черновик, commit один раз при завершении, cancel не пишет. Визуальные изменения не создают новый шов речи.
- Экспорт: явно выбранная проверенная ревизия, только одобренные клипы, готовые MP4/тексты/план; stale render требует проверки. Публикации нет.

Состояния модуля отдельно: available (поддержка), visible (видимость UI), automation_enabled (генерация предложений), output_enabled (участие в результате, если допустимо), сохранённые ручные и автоматические операции, их принятие. Выключение автоматизации не удаляет ранее принятые операции; выключение вклада в результат — отдельная обратимая операция с показом diff и защитой ручной работы. Зависимости явные, без скрытого включения платных или новых функций. Глобальный пресет → проект → ролик; effective config материализуется и хэшируется для задания. Смена дефолта не меняет сохранённый проект. Не выводить весь YAML: типизированные диапазоны, единицы, значение по умолчанию, help, reset, scope, invalidates, зависимости; отсутствие возможности означает недоступность, а не молчаливый no-op. Числа из UX-макетов не являются реальными дефолтами.

## 4. Карта функций и политика автоматизации

E = существующий механизм, не обязательно production-ready; X = расширить; N = новое. P0 — ближайшее полезное ядро; P1 — расширение редактора; P2 — backlog. Авто-флаги и ручные возможности независимы. Не обещать доступность неподключённой функции.

| Функция | Статус | Приоритет / подход |
|---|---|---|
| Импорт локального файла/Я.Диск, список и статусы | E/X | P0; существующий CLI + безопасный каталог |
| Отбор клипов, число/длительность, хук, сценарист, исключение ведущего | E | P0; существующая политика, LLM смысл/ранжирование |
| Ручной выбор и монтаж по транскрипту, подрезка, перестановка | X | P0; команды, карта речи, grammar/apply |
| Удаление пауз и слов-паразитов | E | P0; speech map и текущие правила, approved exceptions |
| Нормализация звука | E | P0; DSP/FFmpeg |
| Кроп, общий/крупный план | E | P0; статичный кроп, существующие правила |
| Субтитры, ключевые слова, заголовок и посты | E | P0; layout и rule-based выделение, LLM для смысловых текстов |
| Вердикты, причины, сравнение до/после | E/X | P0; точная версия артефакта |
| Стили субтитров и исправление текста | X | P0; структурированные параметры и source anchors |
| Черновой preview, undo/redo, manual protection | N/X | P0 для текстового редактора; не нужен весь timeline |
| Рендер/экспорт одобренных | E | P0; локально, без публикации |
| Шумоподавление, музыка/ducking | E | P1; FFmpeg, фиксированный выбор трека, без незаписанной случайности |
| Ручные планы, zoom, color, переходы, karaoke | E/X | P1; существующие механики через capability, без нарушения швов |
| 9:16 / 16:9 / 1:1 | X | P1; проверка профилей, safe areas, кодеки |
| Субтитры на кадре, бренд-стили, логотипы | X/N | P1; нормализованные координаты, шрифты и assets |
| Таймлайн, waveform, snapping, точные кадры | N | P1; детерминированная геометрия, ограничения Python |
| Пользовательские пресеты, пакетное изменение | N | P1; diff и per-clip locks; batch atomicity по явно заданному scope |
| Обработка целиком | X | P1; отдельный режим, проверки long-form |
| Поиск плохих дублей | N | P1; сначала предложения, не автоудаление |
| Ручные фото, видео, B-roll, заставки/концовки | X/N | P1; локальные content-addressed assets, typed layers; учесть старые выключенные концовки |
| Звуковой микшер, звуки, overlay, keyframes | X/N | P2; после стабильного ручного монтажа |
| Автоматический B-roll, мемы | N | P2; локальная библиотека, модель предлагает ID/якоря, код проверяет права/длительность/частоту/неперекрытие; никаких произвольных загрузок |
| M233 | X | Отдельный G1–G3 scope; не судья в production до реального пилота |

Gling: one-click cleanup, плохие дубли, transcript; Descript: текстовые правки; OpusClip: серия клипов и индивидуальное ревью; Submagic: субтитры, визуальные стили и вставки; CapCut: контекстные инструменты, touch timeline. Это продуктовые референсы, не обязательство клонировать сервисы, не повторное runtime-исследование и не разрешение копировать их UI/code.

Повторы/дубли: нормализация токенов, похожесть соседних фраз, локальное временное окно, признаки сбоя, полноты и речи; кандидаты детерминированно ранжируются. Повтор в лекции может быть сознательным: по умолчанию только предложение с обоими диапазонами, защита слов автора и ручной выбор; LLM только для неоднозначного смысла. Автоудаление после измеренного качества и отдельного флага/GO.

LLM: карта мыслей, оценка смысловой завершённости, подходящие хуки, пересказ плашки/посты, контекст B-roll. Не использовать для точных таймингов, пауз, кадрирования, эффектов, UI, рендера, принятия необратимых решений. Все ответы привязаны к transcript IDs и provenance; пропущенные IDs повторить и затем missing, не ноль. Записанные ответы record/replay; кэш-промах не является успешным replay. Без LLM доступен ручной и технический монтаж; смысловые функции показывают ограничение, а не имитируют эквивалентное качество.

## 5. Архитектура и контракт

React/TS/Vite + TanStack Query → FastAPI/OpenAPI → pipeline_gateway → публичный контракт Python/существующий CLI → валидированный Manifest → локальный FFmpeg. UI не импортирует внутренности cloud/local/core (кроме общих моделей на сервере) и не строит собственный авторитетный монтажный план. Новые команды версионируются. Старые CLI, разметка и флаги совместимы.

### 5.1 Состояние, команды и идентичность
Manifest — единственный межтирный монтажный контракт; журнал локальных операций — история/транзакционная основа материализации, не второй независимо редактируемый план. На этапе простого ревью не нужен новый движок. Перед первым монтажным write: выбрать единый durable commit point (например, revision envelope с Manifest и операцией, атомарный указатель); нельзя заявлять атомарность пары независимых файлов. Черновики и accepted revisions различать. Восстановление после прерванной записи проверяется; CLI и UI используют одну границу записи и lock либо конфликтуют fail-closed. Нельзя обходить запрет install для gate/review копий.

Предлагаемый typed command (финальная схема в UI-301): schema_version, op_id/request_id, project/source_id, clip_uid, base_revision/hash, type, typed payload, author/origin, provenance. Сервер присваивает audit timestamp вне reducer. Stable IDs из неизменной идентичности или записанные при создании, без случайности в replay. Повтор op_id с тем же payload возвращает прежний результат; другой payload — конфликт; stale base — отказ без silent rebase. Batch либо полностью валиден, либо не меняет состояние. Undo/redo — новая обратимая операция к известной ревизии, ручные правки не стираются; redo branch явно инвалидируется после новой несовместимой операции. Сохранять model_copy guard для Segment/Word. 
Авторитетный источник слов: source hash + transcript revision + word anchor (индекс только внутри frozen revision, source times, text/context); отдельный occurrence_id для каждого проигрывания (hook/body, повтор, reorder). rNN/stem — display aliases. Миграция только при однозначном соответствии; иначе review, не fuzzy auto-apply.
Минимальная операция UI-303: select/remove/restore или trim одного диапазона → validated plan → история → preview; не проектировать десятки операций до рабочего вертикального среза.
Human precedence: ручной выбор не пересматривается решающими стадиями, форматирующие стадии допустимы по текущему контракту. AI proposals dry-run, diff и привязка к base; принимать только актуальную версию. Защищённые поля/интервалы не изменяются автоматически.

### 5.2 Время и preview
Использовать существующие playback_windows и фактическую семантику render planner, не сумму сырых сегментов вслепую. Source time, played time, display/frame time различны; скорость, reordered, cold_open, повтор окна, вырезанные паузы, искусственные intro/outro, fade и швы имеют явные соответствия. Synthetic spans без source anchor. Source→played может быть 0/1/N; played→source может отсутствовать. Единые half-open интервалы, квантование/округление документировать; внешнюю схему float не менять без миграции и parity, внутри рациональное время/целые ticks. Граница реза подтверждается звуком и правилами проекта, UI snap только подсказка. Golden fixtures с повторным хуком, скоростью, gap, reordered, empty, boundary, synthetic tail. Проверить соответствие существующему argv/filtergraph, а не выдумать независимую карту.

Preview HTML Video + H.264 proxy на gamebox, при необходимости precomputed waveform/thumbnail; переиспользовать существующие Range/path guards. Черновой preview отмечен как приблизительный; финальный FFmpeg — истина. Не обещать точный browser seek/frame sync на всех устройствах. Fragment render с корректными preroll/контекстом эффектов либо fallback на рендер клипа, если изолированный результат неэквивалентен. Не делать новый рендер на каждое движение пальца. Проверять JASSUB отдельно на Safari/Android, шрифты, shaping, COOP/COEP, CPU/RAM; fallback на простое представление или готовый локальный рендер.

### 5.3 Задания, кэш, хранение
Первоначально один исполнитель, один владелец; atomic files/append journal под lock либо SQLite только если доказаны требования к транзакциям, конкуренции и восстановлению. Не вводить Redis/PostgreSQL. Durable job_id, frozen effective profile, source/manifest revision, stage, state, logs (redacted), result refs, retry policy, cancel_requested. queued/running/waiting_for_owner/waiting_for_lock/succeeded/empty/failed/cancelled/interrupted; invalid transitions rejected; empty != success. Duplicate requests idempotent, concurrent same-output jobs serialized, existing heavy flock shared with audiobook respected; не убивать чужой процесс. Отмена только на безопасных точках, не перезаписывать готовый файл незавершённым. Recovery проверяет артефакты и владельца lock, не повторяет необратимые шаги. Structured events вместо парсинга stdout; начать polling, SSE если измеримо улучшает UX. Не показывать выдуманный процент у этапов без метрики.
Cache dependency plan: source/audio hash → tx params/revision → speech map/analysis → recorded LLM inputs+rubric/model response → montage plan → visual/audio styles/assets → render plan/artifact. Поменяли цвет субтитра — не вызываем транскрипцию, LLM, отбор; изменили речь — инвалидируем зависимые derived results. Существующий run_key не расширять молча; новый fingerprint отдельно от старого и migration/OFF proof. Рендер fingerprint включает эффективный план, все влияющие параметры, assets/fonts, версии алгоритма и FFmpeg/кодека в provenance; строгая привязка к фактическому файлу. Сохранить temp/atomic rename, full decode, freeze checks, VAAPI fallback и _errors. Сравнивать byte parity где возможно, иначе argv/filtergraph по контракту, при разных кодеках не обещать bit-identical MP4.
Сохранить прежний бесплатный путь и explicit chat exchange; UI не разрешает платный fallback, `--delete-source keep`, no shell/raw argv from browser. Реальный запуск только scoped owner GO; синтетический smoke до него. Данные/транскрипты/reviews/медиа и secrets не в Git. Git для кода/документов, из production данных только разрешённые manifests/calibrations.

### 5.4 Доступ и защита
Gamebox — локальный дом видео. Телефон владельца получает разрешённый локальный proxy/плеер через защищённую частную сеть или согласованный authenticated HTTPS transport, не облачный текстовый тир и не публичный storage. Оставить loopback по умолчанию. Remote access HIGH: explicit approval, authentication/authorization single-owner, origin/CSRF protection for writes, no arbitrary paths/URLs, deny traversal/symlink outside root, limits, redacted logs, no secrets in browser/cache, no public video endpoints, media route permission incl. Range. SSRF-safe allowlist для импорта Я.Диска. Сервис не отдаёт полный локальный путь в удалённый health. Не создавать multiuser/RBAC без решения владельца. PWA shell может кэшироваться; private media/transcript и mutation responses не кэшировать в service worker по умолчанию. Offline editing не обещается.

## 6. OSS: точечное переиспользование

Предпочтение: существующая функция autoreels → маленькая проверенная библиотека → собственная реализация доменного контракта. Не переносить чужие stores, canonical state, renderer, AI proxies или entire editor. Приведённые статусы лицензий — по предыдущему статическому аудиту закреплённых upstream SHA, не юридическое заключение и не разрешение на импорт.

| Кандидат | Что изучить/использовать | Решение |
|---|---|---|
| Cutline (Aepzie/cutline, ab715202) | typed ops, inverse patches, atomic batches, agent proposals | MIT на проверенном срезе; референс. Их reapply stale proposal не подходит без строгого base check |
| OpenScene (Theorvane/OpenScene, 4bd3d3c4) | чистая геометрия, snapping, touch handles, timeline logic | MIT на срезе; отдельные функции после проверки submodule/license |
| OpenReel (Augani/openreel-video, 367d7e90) | inspector, action validation, responsive controls | MIT root; не переносить renderer/FFmpeg/Blender bundle |
| Kite (iang0h/kite-video, 68a531c7) | mobile tabs/PWA, responsive state | MIT root, производный OpenReel; не брать дублирующий core/AI proxy |
| Omniclip (omni-media/omniclip, cbe581a4) | isolated UI/geometry | MIT root; компоненты связаны с context/controller, не drop-in |
| Rescript (wassgha/rescript, db15871c) | transcript range editing, keep/cut visual UX | PolyForm Noncommercial на срезе; только идеи, independent implementation, без копирования кода |
| WaveSurfer.js | waveform/regions, предварительные peaks | Кандидат; проверить touch, seek, память, лицензию pinned version |
| dnd-kit | reorder фраз/карточек, доступность | Кандидат; не тащить drag library в trim, если простые Pointer Events лучше |
| TanStack Virtual | длинные transcripts/lists | Только при измеренной необходимости |
| JASSUB | preview ASS/libass | Spike: Safari/Android, fonts, workers, parity, license |
| PySceneDetect | будущий детерминированный поиск смен сцен | Только отдельная гипотеза, не трекинг и не замена speech map |
| FFmpeg | authoritative render/DSP | Уже используется; не менять стек |

Перед import: exact commit/version, LICENSE + transitive dependencies/fonts/assets, SPDX/notices, provenance, размеры бандла, browser support, тесты, отсутствие cloud media transfer, оценка maintenance vs небольшой pure local implementation. Утверждать только выигрышные зависимости. Никаких package installs на gamebox в рамках этого документа.

## 7. Единый backlog и порядок реализации

Идентификаторы ниже проектные, не созданные GitHub issues. UI-0 — документальный gate, не большой рефакторинг. Первый полезный slice — UI-1, параллельно подготовка маленьких контрактов UI-2/3. Каждый пакет: acceptance tests, risk class, exact HEAD evidence, owner gate по CLAUDE.md. Не ждать завершения всех этапов A–G.

| ID | Результат / scope | Acceptance / зависимость |
|---|---|---|
| UI-001 | Инвентаризация main, U/MU, план R3 (этот документ) | Документация принята; локальные данные не изменены |
| UI-002 | Контракт UX, feature registry, безопасные границы и fixtures | Уточнены scoped commands и критерии; не строить generic engine |
| UI-101 | Mobile shell, проекты/редактор/задания/экспорт | Синтетические 360–430px + desktop; основные сценарии без горизонтального overflow |
| UI-102 | Каталог всех источников, статус, метаданные | Необработанный/ошибка/empty/готовый видны; нет ошибочной архивации |
| UI-103 | U3 + MU1: ревью и актуальность | Единый adapter решений, exact render_ref, stale/duplicate/invalid tests; старые решения сохранены |
| UI-104 | U4: сравнение и история вердиктов | Выбор варианта, актуальность обоих refs; не синхронизировать ложные совпадения |
| UI-105 | Защищённый mobile access (HIGH, отдельный GO) | Auth, CSRF/origin, traversal/Range, private network; реальный просмотр только с разрешением |
| UI-201 | Public gateway, capabilities (MU5), effective config | Schema version, allowlist, типы OpenAPI, no shell injection, legacy CLI parity |
| UI-202 | U5/MU2: jobs, stage events, cancel/recovery | Synthetic worker, duplicate/lock/restart tests; empty outcome; no real execution |
| UI-203 | Пресеты, переключатели, dependency/invalidation | 4 независимых состояния, scope precedence, diff, OFF parity, no silent manual loss |
| UI-204 | Экспорт и утверждённый путь auto --no-render / render | Одобренный exact artifact; keep source, no paid fallback, no publish; mock provider и render |
| UI-301 | Stable IDs, revision, migration | Old manifests read; ambiguous mappings rejected; deterministic replay |
| UI-302 | MU3: time map, dry-plan contract | Cold open/body/reorder/speed/gaps/synthetic fixtures; no writes to owner data |
| UI-303 | MU4: typed manual edit, undo/redo | One vertical slice, stale revision, atomicity, manual precedence, crash recovery, OFF parity |
| UI-304 | U6/U7: text editor | Word seek, select/remove/restore/trim, subtitle correction separate; no sound/text mismatch |
| UI-401 | U8/MU2: proxy preview/fragment render | Approximate clearly labelled, no re-render per gesture, bounded cache, no media outside local tier |
| UI-402 | Timeline/waveform | Pointer capture, cancel, snapping, zoom, keyboard; only accepted operation persists |
| UI-403 | U9/MU6 + U11/MU8: visual edit | Crop, plans, styles, subtitle layout, existing effects; show unsupported options as unavailable |
| UI-404 | Проверочный render + compare | Plan provenance, decode checks and stale detection; synthetic tests prior to GO |
| UI-501 | Asset library + typed layers | Hash, rights metadata, local storage, no traversal, no unapproved downloads |
| UI-502 | Manual photo/video/music/B-roll, mix | Typed positions/durations, preserved speech, preview/undo |
| UI-503 | U10/MU7 + extended effects | Intro/outro composition contract, keyframes/animation as separate slices; OFF parity |
| UI-504 | Long-form mode, repeat/take candidates | Distinct duration/selection contract; no silent removal of deliberate repeats; separate quality GO |
| UI-601 | M233 adapter / blind review | Only scoped G1–G3 after MEDIA GO; trusted frozen experiment hash, no production scorer assumption |
| UI-602 | Contextual B-roll/memes | Local assets and deterministic placement rules, optional grounded LLM proposal, manual override |
| UI-603 | Batch edits, custom styles, optimization | Per-clip preview and conflicts, no stale export, measured benefit |

Этапы: A = UI-0 и минимальные контракты; B = UI-1/2 полезный production control; C = UI-3 плюс минимальный preview UI-401; D = UI-4; E = UI-501–503; F = UI-504/602; G = UI-601/603. Этапы зависимости, не обещание сроков. UI-105 необходим до фактического удалённого доступа, но не блокирует localhost demo. MU1–MU8 сохранены в соответствующих пакетах, не ведём параллельный конфликтующий backlog. Новые функции допускаются только после доказательства предыдущего полезного среза; long-form/keyframes/B-roll не блокируют core.

## 8. Измерения и QA

Цели (не измеренные результаты): ≤3 действия после выбора источника до типового запуска; один тап для keep/drop и undo; ручные изменения без терминала; сохранность ручных правок и deterministic plan replay — 100% на контрактных fixtures; потеря исходников/передача видео в облачный тир — 0. Не считать отсутствующие функции успехом. Продуктовые метрики: время review одного ролика, доля правок без агента, время до preview, число повторных LLM calls, лишние рендеры, latency/scroll FPS на тестовом устройстве, память, доля принятых клипов на реальном пилоте M233. До оптимизации снять baseline; не обещать latency без измерения.
CI: Python existing offline suite + адресные тесты; OpenAPI snapshot + TS typecheck/build; добавить небольшой browser smoke на synthetic fixtures, responsive tests 360/390/430/desktop, keyboard/touch, reduced motion, errors; реальные Safari iPhone и Android Chrome — отдельный user acceptance до заявления mobile-ready. Golden input → validated Manifest/plan/hash; old fixtures сохраняют OFF output, compare argv/filtergraph; LLM replay only for A/B. Не фиксировать arbitrary UI screenshots как semantic contract.
QA по CLAUDE.md: LOW/MEDIUM/HIGH до разработки; один независимый аудит значимого scope, затем адресная перепроверка исправлений; полное повторение только по documented trigger. HIGH security/manifest migration/real media — отдельный протокол. P3 backlog, не бесконечный цикл. Merge по owner gate; отчёт не доказательство без CI/тестов. Не приписывать M233-G0 независимый R3 PASS.
Готовность первого релиза: реальный пользователь может открыть разрешённый существующий проект, просмотреть клипы, сравнить, сохранить корректный вердикт и продолжить позже, без терминала; при этом запись не трогает исходники/канонический Manifest. До MEDIA GO это доказывается только синтетикой. Следующий релиз: управление текущим конвейером и экспорт; затем ручной редактор. Полный timeline не является первым релизом.

## 9. Зафиксированные уточнения и оставшиеся решения

- Не создавать редактор с нуля целиком: reuse UI scaffold и existing pipeline. Собственное ядро означает минимальные domain operations над текущим контрактом, а не замену существующего движка.
- Не смешивать UI visibility, automation, output and accepted edits.
- Не считать review-apply и UI verdict journal взаимозаменяемыми без mapping семантики.
- Не считать rNN или float source time стабильной identity сами по себе.
- Не заменять старые документы/контракты удалением; эта спецификация добавляется отдельно, указатели в старом плане только после принятия.
- Не вводить SQLite/SSE/JASSUB/другие библиотеки как обязательные до проверки; private transport и durable commit point выбираются в соответствующих пакетах.
- Не менять production configs, defaults, рубрику, закрытые решения владельца и QA policy этим PR.
- Статический аудит не подтверждает состояние локальных файлов, runtime, качество роликов, лицензии всех транзитивных зависимостей или мобильную производительность. Нужны соответствующие узкие проверки.
- Ближайшее действие после принятия: UI-002 + UI-101–103 как небольшие scoped задачи, синтетические fixtures, без нового рендера. Реальный доступ, запись вердиктов по owner media, обработка/рендер и M233 pilot — только по отдельному разрешению.
