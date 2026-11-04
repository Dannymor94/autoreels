M217 — IMPLEMENTED; СТОП на финальной проверке части 1.
Коммит: 98dbfa9, отправлен в main.
Проверки: OK база; OK патч; OK выключено по умолчанию; OK тесты планировщика; OK набор (2728 прошли, ждали ≥ 2721); OK запушено; FAIL: осталось 26.
Целевые тесты: 60 passed, 16 skipped.
Полный набор: 2 failed, 2728 passed, 20 skipped, 9 deselected in 323.52s.
Падения:
- tests/test_snap.py::test_corpus_max_drift_within_cap
- tests/test_snap.py::test_task5_corpus_still_passes_after_fix
Оба: ValidationError при чтении sidecar со списком ошибок как Manifest. Флейка меню нет. Число падений отличается от ожидавшихся 7–8, порог прошедших выполнен.
Логи: /tmp/m217a.txt, /tmp/m217b.txt.

Часть 1: остановка на команде:
left=$(git status -s | grep -v "handoff/\|data/token_scale.json" | wc -l | tr -d " ")
test "$left" = 0 && echo "OK всё закоммичено" || { echo "FAIL: осталось $left"; git status -s | grep -v "handoff/\|data/token_scale.json"; }
Последний вывод:
OK запушено
98dbfa9 Cut gaps (M217, Codex review of plan.py)
FAIL: осталось 26
?? manifests/2026-08-08_12h_37m_01s_4722e065.json
?? manifests/2026-08-08_12h_39m_36s_3b459f7a.discarded.json
?? manifests/2026-08-08_12h_39m_36s_3b459f7a.json
?? manifests/2026-08-09_11h_05m_31s_819cf6c9.failed_chunks.json
?? manifests/2026-08-09_11h_05m_31s_819cf6c9.json
?? manifests/2026-08-09_11h_57m_39s_a0c1f911.failed_chunks.json
?? manifests/2026-08-09_11h_57m_39s_a0c1f911.json
?? manifests/PXL_20260404_082116245_0b29506c.failed_chunks.json
?? manifests/PXL_20260404_082116245_0b29506c.json
?? manifests/PXL_20260405_081143598_1a10c74f.failed_chunks.json
?? manifests/PXL_20260405_081143598_1a10c74f.json
?? manifests/PXL_20260822_123850053_1ad6fd27.failed_chunks.json
?? manifests/PXL_20260822_123850053_1ad6fd27.json
?? manifests/PXL_20260822_124807330_80d38d57.failed_chunks.json
?? manifests/PXL_20260822_124807330_80d38d57.json
?? manifests/PXL_20260823_090959061_fb17c55e.failed_chunks.json
?? manifests/PXL_20260823_090959061_fb17c55e.json
?? manifests/VID_20251227_144620_fc5169f2.failed_chunks.json
?? manifests/VID_20251227_144620_fc5169f2.json
?? manifests/VID_20251227_161218_3e04cf48.failed_chunks.json
?? manifests/VID_20251227_161218_3e04cf48.json
?? manifests/dadaApr26full_5a495201.discarded.json
?? manifests/dadaApr26full_5a495201.failed_chunks.json
?? manifests/dadaApr26full_5a495201.json
?? "manifests/\320\224\320\260\320\264\320\260-\320\230\321\202\320\276\320\263\320\227\320\260\320\277\320\270\321\201\321\214_6220e657.failed_chunks.json"
?? "manifests/\320\224\320\260\320\264\320\260-\320\230\321\202\320\276\320\263\320\227\320\260\320\277\320\270\321\201\321\214_6220e657.json"

Все 26 неотслеживаемых файлов существовали до задачи; они и data/token_scale.json не коммитились и не исправлялись.
Часть 2: не выполнялась по правилу СТОП; compare.txt не создан.
Без рендера и arl auto. gaps_after_cuts выключено.
