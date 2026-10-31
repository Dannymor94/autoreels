"""M201, часть 2: почему платная модель не отвечает с m197. Один короткий запрос к sonnet и к haiku через код проекта
(_make_pool, как arl auto) — печатает ответ или текст ошибки и строку расхода. Ключ не печатается.
Цена: два запроса по ~30 токенов, меньше $0.001. Запуск из корня проекта: .venv/bin/python handoff/m201/ping_claude.py"""
from __future__ import annotations

import os
import sys
from pathlib import Path

root = Path.cwd()
assert (root / "config" / "r0.yaml").is_file(), "запускать из корня проекта"
sys.path.insert(0, str(root / "src"))

from autoreels import __main__ as M  # noqa: E402
from autoreels.cloud.providers import brief_error  # noqa: E402
from autoreels.core.config import load_r0_config  # noqa: E402

M._load_env()
key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
print(f"ключ ANTHROPIC_API_KEY: {'есть' if key else 'НЕТ'}"
      + (f", длина {len(key)}, начинается с sk-ant-: {'да' if key.startswith('sk-ant-') else 'нет'}" if key else ""))
cfg = load_r0_config(root / "config" / "r0.yaml")
print(f"модели в config/r0.yaml: {dict(cfg.anthropic.models)}")
for mode in ("sonnet", "haiku"):
    pool = M._make_pool(cfg, mode)
    try:
        text = pool.complete([{"role": "user", "content": "Ответь одним словом: да"}])
        print(f"{mode}: ОТВЕТИЛ «{text.strip()[:40]}»")
    except Exception as exc:  # noqa: BLE001 — the point is to see it
        print(f"{mode}: НЕ ОТВЕТИЛ — {brief_error(exc, limit=400)}")
    for ln in pool.usage_lines():
        print(f"  {ln}")
