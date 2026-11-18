# M223 — CLI preflight by lead developer

Date: 2026-11-18 (Europe/Moscow).
Scope: **read-only parser inspection**, not P1 reproduction.

Environment: separate local worktree of autoreels with Python 3.13.5 and project editable install. Source parser behavior belongs to the unchanged production CLI `autoreels.__main__`.

Command:
```bash
./.venv/bin/python -m autoreels autocut --help
```

Measured exit code: **0**.

Verified actual parser usage:
```
usage: autoreels autocut [-h] [--clips CLIPS] [--out OUT]
                         [--llm {auto,local,cloud,haiku,sonnet,local-think,none}]
                         [--judge-log JUDGE_LOG] [--no-voice-keys]
                         [--no-check] [--scenario] [--ac ключ=значение]
                         [--root ROOT] [--cache-dir CACHE_DIR]
                         манифест
```

Relevant supported options:
- Positional manifest path or name in `manifests/`.
- `--root ROOT`: use an isolated temporary project root.
- `--cache-dir CACHE_DIR`, `--out OUT`: redirect derived artifacts to isolated temporary paths.
- `--llm none`: explicit no-model operation (still inspect downstream code before invoking).
- Omit `--scenario` to exercise the autocut/montage proposal route; production `config/r0.yaml` has `auto_mode: scenario` for higher-level `arl auto`.
- `--ac key=value` exists, but M223 baseline proof must not silently override expected config. Any test override must be explicitly reported.

**Not yet done:** running autocut on synthetic CLI fixtures, proving actual `__main__` branches, or validating absence of unsafe side effects from that run. Sol's CHANGES_REQUIRED remains in force until Sonnet submits M223-R1 and passes independent review.

No external provider calls, renders or user artifact writes occurred in this preflight.
