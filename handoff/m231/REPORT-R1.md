# M231-OBSERVABILITY-R1 — отчёт исполнителя (код)

TASK=M231-OBSERVABILITY-R1
BASE_SHA=1f3c7a43273b34ac997c4690f327f8f769355d97 (reviewed M231, не переписан)
BASE_PRODUCTION_SHA=3c011e94263e16e5780936b4769d3490cd03b682
BRANCH=task/m231-observability
MODE=CODE_ONLY_SCOPED_REWORK · MERGE_GO=NO · M232_CODE_GO=NO

Исправления по Issue #15. Остался строго в разрешённом списке M231: `autocut.py::propose`,
`__main__.py::cmd_autocut`, `tests/test_m231_trace.py`, `tests/fixtures/m231/**`,
`handoff/m231/**`. Ни конфиг, ни схема манифеста, ни другие символы не тронуты. Рендера,
платных моделей, сети, правок данных владельца нет. Это НЕ вердикт Sol — жду независимого QA.

## Что сделано по пунктам Issue #15

### P1.1 — реальный `speed_secs`/`speed_status` (M231.3)
Было: `"speed_secs": None, "speed_status": None` захардкожены.
Стало: `speed_secs` = `@speed`, который дали бы длительности по словам (`w1−w0`), через **замороженную**
формулу `_speed()` (`autocut.py:1131`) — без собственной аппроксимации. Синтетический клип
`{"t0": w0, "t1": w1, "voice": {"rate": …}}` подаётся в `_speed(…, prm)`, пороги берутся из `prm`
(те же `speed_slow_rate/speed_mid_rate/speed_slow/speed_mid`). Считается **только** когда у каждого
юнита есть `err` (обе границы известны) И `voice.rate > 0`; иначе `speed_secs=None` с явной причиной
`speed_status ∈ {no_err_coverage, no_rate, no_units}`. `ok` сохраняется, даже если формула вернула
`None` (быстрая речь → нет тега) — статус различает «неизвестно» и «тега нет». Неизвестное в ноль не
превращается. Отдельные `d0`/`d1`, точные счётчики покрытия и `err` оставлены как были.
Доказательство: `test_p9_full_timing_and_speed` (реальный CLI: `rate 2.4 → speed_secs 1.05`,
`speed_status ok`, `d0=d1=0.4`, `err=0`, `secs_delta=0.0`), `test_p9_speed_status_no_rate_when_rate_missing`
(`rate 0 → None + no_rate`), `test_p10_sparse_mixed_coverage` (`no_err_coverage`).

### P1.2 — учёт select/fate по фактическому пулу монтажа
Было: `select` печатался сразу после основного `propose()` — **до** `fill_pool` слабых семян,
до фильтра ведущего и до сортировки сомнений; слабосеменные кандидаты в учёт не попадали.
Стало: `select` эмитится один раз **перед циклом отбора** (`__main__.py`, у `not_reached`), по
финальному `pool` — после `fill_pool`, фильтра `interviewer: off` и пересортировок. Трассировка
самого слабосеменного `propose()` не ведётся (ему `trace` не передаётся — запрет соблюдён): его
кандидаты наблюдаются как члены пула (select/fate), без внутренних seed-решений.
`fate` переразложен так, что **Σ fate = размер пула**: короткие версии (`variant_of is not None`)
больше не попадают в `accepted`/`rejected` молча — для них отдельное событие `variant`
(`fate: accepted|rejected`), а разбиение пула = `accepted(не-variant) + rejected(не-variant) + close +
hookless + not_reached` (совпадает с инвариантом учёта M202 `_counted`). Добавлено событие
`pool_accounting {pool, fates, select, variants}` — явная сверка. Легаси-отбор не менялся.
Доказательство: `test_p6_…_with_schema` (`fates == select == pool`), `test_p3_*`.

### P1.3 — `dep_broken`: реальный ярлык стадии + детерминированный порядок
Было: один и тот же проблемный блок 7× скопирован в `propose`, с `set`-включением (порядок зависит
от `PYTHONHASHSEED`) и поиском стадии по **соседним** снимкам — при пропущенной (None) опциональной
стадии возвращался `None` вместо ярлыка.
Стало: 7 дублей удалены из `propose` (−119 строк); `dep_broken` считается **один раз** в обогащении
CLI из `snap` для **каждого** seed-события. Корень: сравниваются только **достигнутые** (не-None)
снимки по порядку S0→S6, поэтому пропущенные опциональные стадии (напр. S3 в passage) не ломают
поиск; стадия = первый достигнутый снимок, где опора была в предыдущем достигнутом и исчезла. Пары
сортируются (`sorted(_pairs)`) → порядок не зависит от хеш-сида.
Доказательство: `test_p8_dep_broken_when_support_dropped_at_s5` (FX-7L: опора #10 снята на S5 →
`dep_broken == [[11,10,"S5"]]`, при пропущенном S3 в passage), `test_p8_no_dep_broken_when_support_preserved`
(чистый прогон → `[]`), `test_p4_dep_broken_stable_across_hash_seeds` (SHA256 трейса совпадает под
`PYTHONHASHSEED` 0/42/1337).

### P1.4 — безопасная запись трейса (fail-closed)
Было: `open(ARL_AUTOCUT_TRACE, "w")` писал по любому пути и шёл по симлинку.
Стало: перед записью путь отклоняется, если он резолвится внутрь корня репозитория (защищённые/
трекаемые пути) или финальный компонент — симлинк. `os.open(..., O_NOFOLLOW)` делает отказ от
симлинка атомарным; любой `OSError` — тихий пропуск, прогон не падает. Отказ **молчит** (ни stdout, ни
stderr), чтобы сохранить паритет env set/unset (P2).
Доказательство: `test_p6_refuses_repo_path_fail_closed` (путь в репо → файла нет, rc 0),
`test_p6_does_not_follow_symlink` (цель симлинка не перезаписана), `test_p6_…_tmp_path` (запись в
`tmp_path`, не в репо — autouse-гвард репозитория зелёный).

### P1.5 — P9/P10 проверяют настоящую реализацию
Было: тесты копировали цикл обогащения inline (`# Apply enrichment logic (copy from __main__.py)`).
Стало: удалены все inline-копии; P9/P10/P6/P2/P8 гоняют **настоящий** `cmd_autocut` в процессе на
синтетическом монтажном проекте (`_montage_project`: источник из `tests.test_montage._source`, конфиг
без модели, `min_sec` снижен, карта из реального `sent_by_ref`). Полный тайминг (включая speed),
разрежённое покрытие (`no_sentence`, смешанное), `d0=d1=0.4`+`err=0`, детерминизм JSONL — всё через
реальный CLI. Тесты полностью синтетические, без сети/модели/медиа/рендера.

### P1.6 — P6 не проходит вхолостую
`test_p6_trace_written_to_tmp_path_with_schema` утверждает: rc==0, файл существует и лежит в
`tmp_path` (а не в репо), `schema==1` на каждой строке, присутствие событий
`{seed, truncate, select, fate, pool_accounting}`, ровно один `truncate`, и `fates==select==pool`.
Плюс негативные проверки небезопасного пути и симлинка (P1.4).

### P1.7 — P11 все девять выходов, каждый по своему исходу
Каждый из девяти выходов (`skip_used`/`skip_taken` делят один выход) форсируется монкипатчем
**реального** решающего помощника (`build_clip`/`fit_rhythm`/`context_start`/`fix_open_end`/
`rhythm_why`/`build_passage`) и проверяется **конкретным** исходом — без `len(outcomes)>0` и без
широких OR: `test_p11_pooled`, `_build_none`, `_skip_used` (+`sup==0`), `_skip_taken`
(в `taken`, но не в `used_seeds`), `_rhythm_fail`, `_start_fail`, `_open_end_fail` (+`spans_final`),
`_final_rhythm_fail`, `_taken_after_context`, `_overlap_or_payoff`. `truncate` — последнее событие,
проверяется в P3.

### P1.8 — P2/P7/P8 доказательства
- P2: `test_p2_env_parity_stdout_and_review` — env unset vs set: одинаковые stdout и SHA256 чернового
  листа; единственное отличие ON — сам файл трейса.
- P7: полный прогон и оффлайн-CI ниже; сверка с `baseline-failures.txt`.
- P8: FX-7L и сохранённый вопрос-петля выше.
- Паритет колбэков: `test_p5_no_extra_callback_calls` — счётчики и аргументы `taste` идентичны ON/OFF.

### P1.9 — два предсуществующих падения `test_snap.py`
Nodeid: `tests/test_snap.py::test_corpus_max_drift_within_cap`,
`tests/test_snap.py::test_task5_corpus_still_passes_after_fix`.
Сигнатура (идентична на BASE и HEAD):
`pydantic_core.ValidationError: Input should be an object [type=model_type, input_value=[{'chunk_idx': 2, …}], input_type=list]`.
Причина: корпусные тесты сканируют `manifests/*.json`; их glob исключает `.discarded`/`.blocks`, но
**не** `.failed_chunks.json` — а это неотслеживаемые локальные сайдкары владельца (JSON-массив, не
Manifest). Воспроизведено на замороженном BASE_SHA (`git stash` → `1f3c7a4`): те же два nodeid, та же
ошибка (`2 failed, 94 deselected`). `tests/test_snap.py` байт-идентичен между BASE и HEAD
(`git diff 3c011e9 -- tests/test_snap.py` пуст). Это не регрессия R1, файл вне разрешённого списка, в
чистом checkout/оффлайн-CI тесты пропускаются (нет `manifests/`). Правку не вносил.

## Инварианты

- **OFF-паритет (байт/запрос/колбэк).** Структурно доказано: в `propose` единственное незащищённое
  изменение — дефолтный параметр `trace=None`; в `cmd_autocut` — две строки чтения env
  (`_trace_path = os.environ.get(...)`, `_trace = [] if _trace_path else None`), инертные при снятой
  переменной. Всё прочее — под `if (_)trace is not None`. При снятой `ARL_AUTOCUT_TRACE` путь кода
  идентичен production-базе. P1 (`trace=None` ≡ `trace=[]` по Proposal), P2 (stdout+лист), P5
  (колбэки) — зелёные.
- Ровно `|seeds|+1` seed-записей (девять выходов + `truncate`) — P3.
- Детерминизм под хеш-сидами 0/42/1337 — P4 (SHA256 совпадают).
- Новых моделей/сети/флагов нет (только существующий opt-in `ARL_AUTOCUT_TRACE`).

## Тесты и CI

- `tests/test_m231_trace.py`: **26 passed** (`.venv/bin/python -m pytest tests/test_m231_trace.py -q`).
- Оффлайн-CI подмножество (`.github/workflows/offline-smoke.yml`, env без ключей):
  `test_autocut test_select_validate test_config test_models test_models_m116` → **163 passed**.
- Полный прогон (`pytest -q -rf`): **2 failed, 2754 passed, 20 skipped, 9 deselected** (307 s).
  Единственные падения — два `test_snap.py` из P1.9 (локальные данные, не R1).
- Сверка с базлайном (`compare_failures.py compare baseline-failures.txt <log>`):
  `Baseline=29; current=2; new=2; disappeared=29`. `new` = те же два `test_snap`
  (объяснены в P1.9); 29 базлайновых падений f92b отсутствуют на 3c011e9.

## Диффстат

- R1-дельта vs reviewed BASE_SHA `1f3c7a4`:
  `__main__.py +111/−10`, `autocut.py −119` (удалены 7 дублей `dep_broken`), `test_m231_trace.py`
  переписан (`+736/−458` строк по git). Нетто `propose` стал короче.
- Полный M231 vs production base `3c011e9`:
  `__main__.py +169/−1`, `autocut.py +79/−1`, `test_m231_trace.py +485`; новые
  `tests/fixtures/m231/{README.md, fx7l_units.json}`.

## Нерешённое / замечания для Sol

1. **Перенос `dep_broken` из `propose` в обогащение CLI** — сознательное решение корня (один
   детерминированный источник вместо 7 копий). Оба файла в списке; поле `dep_broken` seed-события
   сохранено (в `propose` инициализируется `[]`, заполняется в CLI из `snap`+карты юнитов). Прошу
   подтвердить, что это в духе разрешённого списка (не расширение области).
2. **`no_refs`** — защитная ветвь обогащения: `eligible` отбрасывает юнит с пустыми `refs` до того,
   как он станет семенем, поэтому реальный span до неё не доходит (в P10 отмечено комментарием).
3. Два `test_snap.py` — вне области; не трогал (owner-данные + не в списке).

FINAL_SHA=6a07e3fe3ce1e0d244cb0aadcfebc6c940ba45db
STOP_FOR_INDEPENDENT_SOL_CODE_QA
