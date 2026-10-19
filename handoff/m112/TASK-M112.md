# TASK M112 (окно MAIN, Mac, облачная модель): плашка-крючок у клипов без тизера; посты в `arl auto`; `arl export` — только одобренное

Файлы — в ветке `handoff`, папка `handoff/m112/`: `TASK-M112.md`, `m112-plate-export.patch`.

**Ставится поверх M111** (коммит шага 1 задачи m111). Если M111 ещё не в `main` — **СТОП**: сначала «Выполни m111». Одна сессия, без фоновых задач. gamebox не нужен (`--llm cloud`).

## Зачем
1. **Плашка у клипа без тизера.** У трети клипов тизера (холодного старта) нет. Плашка `t:` у них идёт первой, в самом начале. Сейчас она только называет тему (`plate: context`), хотя должна цеплять сама. Теперь у такого клипа плашка — заголовок-крючок M71/M73: вопрос зрителю, утверждение на «вы» или контраст, словами ролика. У клипов с тизером плашка прежняя. Флаг — `plate_hookless` в `config/r0.yaml`; пустое значение — прежний выход.
2. **От видео до crosspost — две команды, ревью посередине** (инвариант 6: выдача только после одобрения).
   - `arl auto` перед листом ревью сам пишет посты (`arl describe`), и они видны на карточках. Флаг — `post.auto`; при `false` последовательность прежняя.
   - После оценок на листе: `arl export <источник> --decisions <файл решений>`. Команда записывает решения (как `arl review-apply`) и выгружает в план crosspost только клипы с оценкой «оставить». Нет одобренных — нет выгрузки. Ничего не публикуется.
   - Изменён существующий тест `tests/test_auto.py::test_auto_runs_every_stage_in_order_and_merges_the_drafts`: в ожидаемой последовательности появилась стадия `describe`. Прежняя последовательность при выключенном флаге доказывается новым тестом `test_auto_without_posts_is_as_before`.

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера. pytest — только в шаге 1.
3. Не трогать: `reviews/*_answer.txt`, `reviews/*_auto_m56.txt`, `reviews/*_auto_all.txt`, `reviews/*.review.json`, `reviews/verdicts.jsonl`, манифест `PXL_20260729_085910095_34f06abf.json`. Черновики шага 2 пишутся в новые файлы `reviews/<stem>_auto_m112.txt`: листы прежних гейтов (m105 и др.) ссылаются на старые черновики, их перезапись испортила бы оценки владельца.
4. `arl auto` и `arl export` в этой задаче не запускать: у прежних гейтов ещё нет оценок владельца. Первое настоящее применение `arl export` — после его просмотра.
5. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.
6. В `git status` допустимы прежние строки (` M data/blocks_dataset/IMG_6848.jsonl`, ` M data/token_scale.json`, `?? manifests/_archive/`, `??` из `transcripts/` и `*.discarded.json`).
7. Итог — «IMPLEMENTED, GATE PENDING».

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -2; pgrep -fl "arl " || echo "arl не запущен"
git apply --check handoff/m112/m112-plate-export.patch && git apply handoff/m112/m112-plate-export.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/r0.yaml docs/REEL_SPEC.md src/autoreels/__main__.py src/autoreels/cloud/autocut.py src/autoreels/core/config.py tests/test_auto.py tests/test_autocut.py tests/test_crosspost_export.py
git commit -m "Montage (M112): a clip with no cold open gets a curiosity plate (plate_hookless); arl auto writes the posts before the review sheet (post.auto); arl export sends only the clips the owner kept to the crosspost plan (invariant 6)"
git push; git log --oneline -1
```
Ожидается:
- последний коммит до патча — M111; `arl не запущен`; `applied`;
- pytest: все прошли (если что-то упало — **СТОП**, не коммитить);
- новый коммит запушен.

## Шаг 2. Плашки на трёх источниках (только черновики, без рендера)
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m112
{
for S in "IMG_6848" "2026-08-08 11h 42m 49s" "Pxl 20260621 112938952"; do
  echo "=== $S"; arl autocut "$S" --llm cloud --out "reviews/${S}_auto_m112.txt"
done
} 2>&1 | tee handoff/m112/run.txt
.venv/bin/python - <<'EOF' | tee handoff/m112/plates.txt
import re
for S in ("IMG_6848", "2026-08-08 11h 42m 49s", "Pxl 20260621 112938952"):
    print(f"=== {S}")
    notes = []
    for ln in open(f"reviews/{S}_auto_m112.txt", encoding="utf-8"):
        ln = ln.rstrip("\n")
        if ln.startswith("# --- "):
            notes = []
        elif ln.startswith("#   "):
            notes.append(ln[4:])
        elif re.match(r"M\d+ ", ln):
            t = ln.split("| t: ")[1].split(" | ")[0] if "| t: " in ln else "—"
            hook = "с тизером" if " h:" in ln else "БЕЗ тизера"
            how = next((n for n in notes if n.startswith(("заголовок-крючок", "плашка-контекст", "плашка осталась",
                                                          "заголовок остался", "крючок снят"))), "")
            print(f"{ln.split()[0]:4} {hook:10} t: {t}\n      {how[:300]}")
EOF
git status --short
```
Ожидается:
- в `run.txt` у каждого источника строка `autocut …: предложено сборок N`;
- в `plates.txt` у клипов «БЕЗ тизера» строка «заголовок-крючок: …» или «заголовок остался …», у клипов «с тизером» — «плашка-контекст: …» или «плашка осталась …»;
- в `git status` новых строк нет (`reviews/` не в git).

Если ни у одного клипа нет пометки «БЕЗ тизера» — это не СТОП, а замер. Так и написать в отчёте.

## Шаг 3. Отчёт в ветку
Записать `handoff/m112/REPORT.md`:
1. Шаг 1 — хэш коммита и строка pytest.
2. Шаг 2 — `plates.txt` целиком и сколько клипов без тизера на каждом источнике.
3. Как владельцу выгрузить одобренное после просмотра листа (одна строка, для каждого гейта с листом):
   `arl export "<источник>" --decisions ~/Downloads/<stem>_decisions.txt`.

```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/report.sh m112 run.txt plates.txt
```
Ожидается `отчёт m112 отправлен в ветку handoff`. Владельцу в чат — одна строка: сколько клипов без тизера получили плашку-крючок, «отчёт в ветке».

Статус: IMPLEMENTED, GATE PENDING.
