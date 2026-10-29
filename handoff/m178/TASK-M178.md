# TASK M178 (окно MAIN, Mac): документация M171–M177

Файлы — ветка `handoff`, папка `handoff/m178/`: `TASK-M178.md`, `m178-docs.patch`. Около 5 минут, без рендера.

## Зачем
Владелец 2026-10-29: «всё задокументировано?» В документах нет вех M171–M177:
- имена источников;
- правило коротких планов;
- общий черновик и повторы;
- посты от «я»;
- сетка публикаций;
- набор m176.

Патч дописывает:
- PLAN.md — строки блока «Автомонтаж» и сводку;
- README — переключатели `short_shot_sec`, `autocut.combined_overlap_max`, `post.voice`;
- docs/REEL_SPEC.md — §3 п. 6 «Короткий план».

## Шаги
```bash
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; bash handoff/bin/take.sh m178
git apply --check handoff/m178/m178-docs.patch && git apply handoff/m178/m178-docs.patch && echo applied
.venv/bin/python -m pytest -q tests/test_docs*.py tests/test_plan*.py 2>&1 | tail -2 || true
git add PLAN.md README.md docs/REEL_SPEC.md CLAUDE.md && git commit -m "Docs (M178): M171–M177, Russian-only reports — source names, short shots, combined draft and repeats, first-person posts, publishing grid, m176 set" && git push && git log --oneline -1
```
Ожидается: `applied`; тесты документации (если есть) прошли; коммит запушен. Патч не применяется (main ушёл вперёд) — СТОП с выводом `git apply --check`.

## Отчёт
`handoff/m178/REPORT.md`: коммит. `bash handoff/bin/report.sh m178`. Владельцу — одна строка: «документация M171–M177 в main (коммит …)».

Статус: IMPLEMENTED.
