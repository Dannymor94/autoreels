# REPORT M153

## Шаг 1

```
git apply --check handoff/m153/m153-auto-mode.patch && git apply ... → applied
```

pytest: **2503 passed**, 9 deselected (232.97s)  
tests/test_m153_auto_mode.py: **6/6 passed**

Коммит: `514d9fb Auto (M153): arl auto writes reels with the scenarist by default …`  
Запушен: `main` → `origin/main`

## Шаг 2

```
--mode {autocut,scenario}
    M153: кто пишет ролики — scenario (сценарист, платно) | autocut (автомонтаж, бесплатно); по умолчанию …
--scenario-llm {haiku,sonnet}
    M153: модель сценариста (по умолчанию r0.yaml autocut.scenario_llm)
```

Ключ Claude: **в .env есть**

## Итог

`arl auto` теперь пишет ролики сценаристом (sonnet); бесплатно — `--mode autocut`; переключатели — таблица в README.
