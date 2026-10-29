# TASK M184 (окно MAIN, Mac): замер — куда теряются крючки (5 минут, без правок и рендера)

Файлы — ветка `handoff`, папка `handoff/m184/`: `TASK-M184.md`, `why_hooks.py`. Отчёт — только на русском.

## Зачем
Цифры m183 расходятся:
- в пробе шага 2 у prew_isaev_anna 7 строк из 8 с `h:`;
- в готовых клипах m183 крючок у 2 из 9;
- 98 строк «крючок …» у клипов разметки, а у клипов разметки крючков почти нет.

Значит, крючок где-то между черновиком и клипом снимается. Нужен список: где и с каким предупреждением.

## Шаги
```bash
cd /Users/danny/Documents/autoreels; git pull -q; bash handoff/bin/take.sh m184; mkdir -p handoff/m184
.venv/bin/python handoff/m184/why_hooks.py > handoff/m184/why.txt; tail -1 handoff/m184/why.txt
grep -B1 -A3 "ПОТЕРЯН" handoff/m184/why.txt | head -60
grep -cE "^M[0-9]+ .*h:" reviews/prew_isaev_anna_auto_m183.txt reviews/prew_isaev_anna_auto_all_m183.txt 2>/dev/null
grep -hE "cold open skipped|крючок .* без своего звука|has no sound|refused" handoff/m183/auto.txt | sort | uniq -c | sort -rn | head -15 | tee handoff/m184/skips.txt
```

## Отчёт
`handoff/m184/REPORT.md`: строка ВСЕГО, потерянные крючки с предупреждениями (первые 20), `skips.txt`, счёт `h:` в черновиках.
`bash handoff/bin/report.sh m184 why.txt skips.txt`. Владельцу — одна строка: «замер у ассистента».
