# TASK M206B (окно MAIN, Mac): документация M201–M206, не вошедшая в M206

Файлы — ветка `handoff`, папка `handoff/m206b/`: `TASK-M206B.md`, `m206b-docs.patch` (ложится на `main` после M206, `c77f582`).
Около 3 минут. Только документация, кода и конфига нет. Отчёт — только на русском.

## Зачем
Задача m206 была дополнена через 11 минут после выкладки, но агент уже взял первую версию. В коммит `c77f582` не вошли 4 документа:
- `docs/REEL_SPEC.md` — `k:` по правилу; похожесть по звуку, глобальный отбор, учёт ушедших кандидатов; «начало без опоры» включено; модель прогона для роликов сценариста;
- `R0_SPEC.md` — сценарист: модели при `scenario_polish`, «Сценарист через чат» (план, M207);
- `PROJECT_STRUCTURE.md` — `cloud/llmcache.py`, `tools/kw_rule_check.py`, число тестов;
- `PROJECT_GUIDE.md` — `data/cache/llm/`.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: команда и последние 40 строк. Ничего не чинить.
2. Ничего, кроме этих 4 файлов. `data/token_scale.json` (авто-калибровка, M206) не коммитить и не откатывать.
3. Итог — «DOCUMENTED».

## Часть 1
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1
bash handoff/bin/take.sh m206b
git apply --check handoff/m206b/m206b-docs.patch && git apply handoff/m206b/m206b-docs.patch && echo applied
git diff --stat
git add docs/REEL_SPEC.md R0_SPEC.md PROJECT_STRUCTURE.md PROJECT_GUIDE.md
git commit -m "Docs (M206b): M201–M206 in REEL_SPEC (k: rule, closeness by sound, global selection, candidate accounting, start_morph on, polish model), R0_SPEC (scenario models, the planned chat scenarist), PROJECT_STRUCTURE (llmcache, kw_rule_check), PROJECT_GUIDE (data/cache/llm)"
git push; git log --oneline -1
git status -s | grep -v "handoff/\|data/token_scale.json" || echo "всё закоммичено"
```
Ожидается:
- последний коммит — M206 (`c77f582`);
- `applied`; в `git diff --stat` — 4 файла (+ `data/token_scale.json`, его не трогать);
- коммит запушен; «всё закоммичено».

## Отчёт
`handoff/m206b/REPORT.md`: `M206B — DOCUMENTED. Коммит <хэш>.`
```bash
bash handoff/bin/report.sh m206b
```
Владельцу в чат — 1 строка: «M206B — DOCUMENTED, коммит <хэш>: документация M201–M206 полная».
