# TASK M115 (окно MAIN, Mac, облачная модель): автоматический клип не кончается на «→» — интонация, этап C плана M1.9

Файлы — в ветке `handoff`, папка `handoff/m115/`: `TASK-M115.md`, `m115-end-tone.patch`.

**Ставится поверх M113** (c35feef). Одна сессия, без фоновых задач. gamebox не нужен (`--llm cloud`). Около 10 минут.

## Зачем
Владелец: «давай» — этап C плана M1.9. Замер M99 на клипах владельца: 62 из 65 его концовок сказаны «↘» (голос опустился), «→» — только одна. Внутри тех же клипов «→» стоит на 45 из 484 концов фраз. «→» значит, что говорящий продолжает: такая концовка звучит как «не договорил», даже если в тексте точка.

Что меняется (`autocut.end_tone`, при `false` — прежний выход):
- если последняя фраза автоматической сборки сказана «→», последняя мысль теряет хвостовые фразы до ближайшей законченной, сказанной не «→», пока клип не станет короче `min_sec`;
- если так укоротить нельзя, сборка не предлагается (её место занимает следующая) и попадает в черновик отдельным списком;
- «неясный» тон и конец без тона остаются предупреждением плана, как раньше;
- ручной путь не меняется: явный `e:` владельца код не двигает, там по-прежнему только предупреждение (инвариант 5);
- нужна карта интонации `transcripts/<stem>.prosody.json`; без неё — предупреждение и прежний выход.

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера. pytest — только в шаге 1.
3. Не трогать: `reviews/*_answer.txt`, `reviews/*_auto_m56.txt`, `reviews/*_auto_all.txt`, `reviews/*_auto_m112.txt`, `reviews/*.review.json`, `reviews/verdicts.jsonl`, манифест `PXL_20260729_085910095_34f06abf.json`. Черновики этой задачи — новые файлы `reviews/<stem>_auto_m115.txt`. `arl auto`, `arl render`, `arl export` не запускать.
4. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.
5. В `git status` допустимы прежние строки (` M data/blocks_dataset/IMG_6848.jsonl`, ` M data/token_scale.json`, `?? manifests/_archive/`, `??` из `transcripts/` и `*.discarded.json`).
6. Итог — «IMPLEMENTED, GATE PENDING».

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
git apply --check handoff/m115/m115-end-tone.patch && git apply handoff/m115/m115-end-tone.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/r0.yaml docs/REEL_SPEC.md src/autoreels/__main__.py src/autoreels/cloud/autocut.py src/autoreels/core/config.py tests/test_autocut.py
git commit -m "Montage (M115, M1.9 stage C): an automatic clip does not end on a sentence spoken with the voice up — the last thought loses trailing sentences back to one that is not «→» (clip stays ≥ min_sec), else the clip is not proposed and is listed; manual path unchanged (warning only)"
git push; git log --oneline -1
```
Ожидается:
- последний коммит до патча — M113 (c35feef); `arl не запущен`; `applied`;
- pytest: все прошли (если что-то упало — **СТОП**, не коммитить); коммит запушен.

## Шаг 2. Черновики трёх источников с новым правилом
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m115
for S in "IMG_6848" "2026-08-08 11h 42m 49s" "Pxl 20260621 112938952"; do ls -l "transcripts/$S.prosody.json"; done
{
for S in "IMG_6848" "2026-08-08 11h 42m 49s" "Pxl 20260621 112938952"; do
  echo "=== $S"; arl autocut "$S" --llm cloud --out "reviews/${S}_auto_m115.txt"
done
} 2>&1 | tee handoff/m115/run.txt
.venv/bin/python - <<'EOF' | tee handoff/m115/endings.txt
import re
for S in ("IMG_6848", "2026-08-08 11h 42m 49s", "Pxl 20260621 112938952"):
    print(f"=== {S}")
    txt = open(f"reviews/{S}_auto_m115.txt", encoding="utf-8").read().splitlines()
    notes, shortened = [], 0
    for ln in txt:
        if ln.startswith("# --- M") or ln.startswith("# --- "):
            notes = []
        if ln.startswith("#   "):
            notes.append(ln[4:])
        elif re.match(r"M\d+ ", ln):
            end = [n for n in notes if n.startswith("конец: ")]
            shortened += bool(end)
            print(f"{ln.split()[0]:4} {ln.split(' | ')[1]}\n      {end[0] if end else 'конец не менялся'}")
    sec = [i for i, ln in enumerate(txt) if ln.startswith("# --- конец звучит с продолжением")]
    dropped = []
    if sec:
        for ln in txt[sec[0] + 1:]:
            if not ln.startswith("#   "):
                break
            dropped.append(ln[4:])
    print(f"укорочено: {shortened}; не предложено (конец «→», не укоротить): {len(dropped)}")
    for d in dropped:
        print(f"   ✗ {d}")
EOF
git status --short
```
Ожидается:
- `ls` показывает `prosody.json` у источников. Если у какого-то нет — не СТОП: в `run.txt` будет строка `warning: нет интонации …`, так и написать в отчёте;
- у каждого источника строка `autocut …: предложено сборок N …`, может быть с `(конец «→», не укоротить: K)`;
- в `endings.txt` у каждой сборки — «конец не менялся» или строка `конец: «…» звучит с продолжением («→») — клип кончается на B.N «…» (убрано фраз: K)`, в конце — итоги по источнику;
- в `git status` новых строк нет.

## Шаг 3. Отчёт в ветку
Записать `handoff/m115/REPORT.md`:
1. Хэш коммита шага 1 и строка pytest.
2. `endings.txt` целиком.
3. Сколько сборок предложено по каждому источнику сейчас и в m112 (строки `предложено сборок` из `handoff/m112/run.txt`, если файл есть, иначе из ветки: `git show origin/handoff:handoff/m112/run.txt`).

```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/report.sh m115 run.txt endings.txt
```
Ожидается `отчёт m115 отправлен в ветку handoff`. Владельцу в чат — одна строка: сколько концовок укорочено и сколько сборок снято из-за «→», «отчёт в ветке».

Статус: IMPLEMENTED, GATE PENDING.
