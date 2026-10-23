# M135 — Отчёт: фиксы и уборка по ревью m133

## Шаг 1 — Патч и тесты

- `render.local.yaml`: удаляемых ключей нет — ок.
- Патч применён без конфликтов: `git apply --check` + `git apply` — applied.
- pytest (worktree `/Users/danny/Documents/autoreels-m135`):
  `2456 passed, 12 skipped, 9 deselected; 5 failed` — все 5 падают на чистом `origin/main` без патча (pre-existing: `test_cli.py::test_run_dispatch_*` × 4, `test_providers.py::test_r0_output_parsing_survives_lower_max_tokens`). Патч новых падений не вносит.

## Шаг 2 — Коммит и push

- Коммит: `3233acb  Cleanup (M135): dead config knobs removed (render.yaml subtitles copy, intrusion_guard_sec, chunk_overlap_sec, prompt_language), silent excepts speak, FallbackLLM gone, .gitignore transcripts rule fixed (m133 review)`
- Влит в **main** (`git push origin HEAD:main`): `8749be4..3233acb`.
- `origin/main` уже содержал M134 до push, rebase не менял ни одного файла.

## Шаг 3 — Уборка папки

| секция | что | итог |
|---|---|---|
| 1. Пустые `.render.lock` старше суток | удалены насовсем | **107 файлов** |
| 2. `.DS_Store` | удалены насовсем | **25 файлов** |
| 3. `.bak` / `.orig` | в Корзину `~/.Trash/autoreels-m135` | **4 файла** |
| 4. Гейты > 14 д (без keep-списка) | в Корзину | **22 гейта, 7 ГБ** |

Сохранены (KEEP_RE): `m18_final`, `m88`, `m94`, `m101`, `m102`, `m105`, `m112`, `m115`, `m126`, `m131`, `m134`.

Гейты в Корзине: `m18_synth`, `manual`, `montage`, `montage2`, `codec_test` — старые тестовые прогоны.

`git status` основной копии: без изменений от уборки — только `data/token_scale.json M` и неотслеживаемые, что были до.

## df до и после

```
до:   /dev/disk3s5   228Gi   188Gi    16Gi    93%
после: /dev/disk3s5   228Gi   188Gi    16Gi    93%
```

Диск показывает одинаково: 7 ГБ находятся в Корзине (`~/.Trash/autoreels-m135`) и освободятся после очистки.
