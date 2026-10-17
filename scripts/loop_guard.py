#!/usr/bin/env python3
"""Страж PR: существующие проверки нельзя менять или удалять без одобрения владельца.

- Файлы из `.loop/protected.txt`: добавлять строки и новые файлы можно; удалять, переименовывать или менять
  существующие строки — только с меткой PR `loop:tests-approved` (её ставит владелец).
- Файлы из `.loop/append_only.txt` (например `DECISIONS.md`): только дописывать.
- `PLAN.md` — не длиннее 150 строк.

Списки берутся из целевой ветки, а не из PR: изменить список, чтобы обойти стража, не получится.

В CI: python3 scripts/loop_guard.py            (берёт GITHUB_BASE_REF и событие PR)
Локально: python3 scripts/loop_guard.py --base dev --local
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.parse

DEFAULT_PROTECTED = [
    "tests/**", "test/**", "**/tests/**", "**/test_*.py", "**/*_test.py", "**/*_test.go",
    "**/*.test.js", "**/*.test.ts", "**/*.spec.js", "**/*.spec.ts",
    ".github/workflows/**", ".loop/**", "Makefile", "scripts/loop_guard.py",
]
DEFAULT_APPEND_ONLY = ["DECISIONS.md"]
PLAN_MAX_LINES = 150
CHANGED = "loop:tests-changed"
APPROVED = "loop:tests-approved"


def git(args, check=True):
    p = subprocess.run(["git"] + args, capture_output=True, text=True)
    if check and p.returncode != 0:
        sys.exit(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def glob_re(pattern: str) -> re.Pattern:
    i, out = 0, ""
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"; i += 3
        elif pattern.startswith("**", i):
            out += ".*"; i += 2
        elif pattern[i] == "*":
            out += "[^/]*"; i += 1
        elif pattern[i] == "?":
            out += "[^/]"; i += 1
        else:
            out += re.escape(pattern[i]); i += 1
    return re.compile("^" + out + "$")


def matches(path: str, patterns) -> bool:
    return any(glob_re(p).match(path) or fnmatch.fnmatch(path, p) for p in patterns)


def read_list(base_ref: str, name: str, default):
    p = subprocess.run(["git", "show", f"{base_ref}:.loop/{name}"], capture_output=True, text=True)
    if p.returncode != 0:
        return list(default)
    items = [l.strip() for l in p.stdout.splitlines() if l.strip() and not l.strip().startswith("#")]
    return items or list(default)


def removed_lines(base_ref: str, path: str) -> int:
    diff = git(["diff", "-U0", f"{base_ref}...HEAD", "--", path])
    return sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))


def analyse(base_ref: str):
    protected = read_list(base_ref, "protected.txt", DEFAULT_PROTECTED)
    append_only = read_list(base_ref, "append_only.txt", DEFAULT_APPEND_ONLY)
    violations, hard = [], []
    for line in git(["diff", "--name-status", "-M", f"{base_ref}...HEAD"]).splitlines():
        parts = line.split("\t")
        status, path = parts[0], parts[-1]
        old = parts[1] if len(parts) > 2 else path
        guarded = matches(old, protected) or matches(old, append_only)
        if not guarded:
            continue
        kind = "только дописывать" if matches(old, append_only) else "защищённая проверка"
        if status.startswith("D"):
            violations.append(f"`{old}` удалён ({kind})")
        elif status.startswith("R"):
            violations.append(f"`{old}` переименован в `{path}` ({kind})")
        elif status.startswith("M"):
            n = removed_lines(base_ref, path)
            if n:
                violations.append(f"`{path}`: изменено или удалено строк — {n} ({kind})")
    if os.path.exists("PLAN.md"):
        with open("PLAN.md", encoding="utf-8") as f:
            n = sum(1 for _ in f)
        base_plan = subprocess.run(["git", "show", f"{base_ref}:PLAN.md"], capture_output=True, text=True)
        base_n = len(base_plan.stdout.splitlines()) if base_plan.returncode == 0 else 0
        # Лимит действует, только пока план в него укладывается: у подключённых проектов со своим
        # длинным планом страж следит лишь, чтобы план не рос.
        limit = PLAN_MAX_LINES if base_n <= PLAN_MAX_LINES else base_n
        if n > limit:
            hard.append(f"`PLAN.md` — {n} строк, лимит {limit}: сверните сделанное")
    return violations, hard


def pr_context():
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return None, set()
    with open(path, encoding="utf-8") as f:
        ev = json.load(f)
    pr = ev.get("pull_request") or {}
    return pr.get("number"), {l["name"] for l in pr.get("labels", [])}


def gh_label(number, add: bool):
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not (repo and number and os.environ.get("GH_TOKEN")):
        return
    if add:
        args = ["gh", "api", "-X", "POST", f"repos/{repo}/issues/{number}/labels", "-f", f"labels[]={CHANGED}"]
    else:
        args = ["gh", "api", "-X", "DELETE",
                f"repos/{repo}/issues/{number}/labels/{urllib.parse.quote(CHANGED, safe='')}"]
    subprocess.run(args, capture_output=True, text=True)


def summary(text: str):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("GITHUB_BASE_REF"))
    ap.add_argument("--local", action="store_true", help="без меток GitHub, только отчёт")
    a = ap.parse_args(argv)
    if not a.base:
        print("Нет целевой ветки (GITHUB_BASE_REF или --base) — проверять нечего.")
        return 0
    if not a.local:
        git(["fetch", "--no-tags", "origin", a.base], check=False)
    base_ref = a.base
    if "/" not in a.base:
        has_remote = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"origin/{a.base}"],
                                    capture_output=True).returncode == 0
        base_ref = f"origin/{a.base}" if has_remote else a.base
    violations, hard = analyse(base_ref)
    number, labels = (None, set()) if a.local else pr_context()
    approved = APPROVED in labels

    lines = ["## Страж петли"]
    code = 0
    if violations:
        lines.append("Изменены существующие проверки или неизменяемые файлы:")
        lines += [f"- {v}" for v in violations]
        if approved:
            lines.append("\nЕсть одобрение владельца (`loop:tests-approved`) — пропускаю.")
        else:
            lines.append("\nНужно одобрение владельца: метка `loop:tests-approved`. Мозг её не ставит.")
            if not a.local:
                gh_label(number, add=True)
            code = 1
    else:
        lines.append("Существующие проверки не тронуты.")
        if CHANGED in labels and not a.local:
            gh_label(number, add=False)
    if hard:
        lines += [f"- {h}" for h in hard]
        code = 1
    summary("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
