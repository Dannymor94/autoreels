# TASK M166 (любое окно, Mac): три клипа m163, отброшенные рендером — где ошибается план

Рендер m163 отбросил три клипа, его проверки сработали правильно:
- 10h59 r13 и r15 — «last word cut»: конец клипа раньше конца последнего слова по карте речи (на 0,56 и 0,41 с);
- 11h42 r02 — «first word cut»: начало на 0,15 с позже начала первого слова.

Это не ошибка разметки: ролики автоматические, границы ставит план клипа. Значит, план и проверка рендера видят время слова по-разному. Найти, где расходятся. Замер, кода нет, около 5 минут.

## Шаг 1
```bash
cd /Users/danny/Documents/autoreels; bash handoff/bin/take.sh m166
.venv/bin/python handoff/m166/edges.py "2026-08-08 10h 59m 38s" m163 r13 r15 2>&1 | tee handoff/m166/edges.txt
.venv/bin/python handoff/m166/edges.py "2026-08-08 11h 42m 49s" m163 r02 2>&1 | tee -a handoff/m166/edges.txt
grep -nE "r13|r15" handoff/m163/auto.txt | grep -iE "конец|хвост|end|tail|ERROR" | head -12 | tee -a handoff/m166/edges.txt
grep -nE " r02" handoff/m163/auto.txt | grep -iE "начал|start|preroll|ERROR" | head -8 | tee -a handoff/m166/edges.txt
```
Ожидается: по блоку «== …» на клип.

## Шаг 2. Отчёт
`handoff/m166/REPORT.md` = `edges.txt` целиком.
`bash handoff/bin/report.sh m166 edges.txt`
Владельцу — одна строка: «замер трёх клипов готов, ассистент разберёт причину».
