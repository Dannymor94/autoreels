"""`arl prepare`: a source from transcript to a checked labelling draft, one command (M36).

Before: six commands per source (speech map → alignment → intonation → motion → draft → plan),
each a separate task. Now one command runs them in order; every stage is idempotent (a finished
stage is skipped), a failed stage stops THIS source with the reason and the command to rerun, and
the label stage resumes: a draft with unanswered windows is retried, a finished draft is re-checked
with the current rules. Several sources run one after another; the run ends with a table.

Nothing is installed or rendered: the result is a draft for the owner and its dry-run plan.
"""
from __future__ import annotations

import io
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

STAGES = ("speech-map", "align", "prosody", "motion", "label", "plan")


@dataclass
class SourceResult:
    stem: str
    done: list[str] = field(default_factory=list)
    failed_stage: str | None = None
    reason: str = ""
    draft: Path | None = None
    clips: int = 0
    flagged: int = 0
    unanswered: int = 0
    plan_errors: list[str] = field(default_factory=list)
    plan_rc: int | None = None

    @property
    def ok(self) -> bool:
        return self.failed_stage is None and self.plan_rc == 0 and not self.plan_errors


class _Tee(io.TextIOBase):
    """Write to the real stream and keep a copy (the plan's ERROR lines go into the summary)."""

    def __init__(self, real):
        self.real, self.buf = real, io.StringIO()

    def write(self, s):
        self.real.write(s)
        self.buf.write(s)
        return len(s)

    def flush(self):
        self.real.flush()


def draft_stats(text: str) -> tuple[int, int, int]:
    """(review lines, '#!' lines, unanswered windows) of a draft."""
    from autoreels.cloud.label import unanswered_windows
    clips = sum(1 for l in text.splitlines() if l[:1].isdigit())
    flagged = sum(1 for l in text.splitlines() if l.startswith("#!"))
    return clips, flagged, len(unanswered_windows(text))


_ERR_RE = re.compile(r"\[ERROR\]|^error:|Traceback", re.MULTILINE)


def run_source(stem: str, *, stages: dict[str, Callable[[], int]], draft_path: Path,
               label: Callable[[str], int], plan: Callable[[], int],
               log: Callable[[str], None] = print) -> SourceResult:
    """Run the stages of one source. `stages`: speech-map/align/prosody/motion → rc. `label(mode)`
    with mode 'new' | 'retry' | 'check'. `plan()` = the dry-run --apply of the draft."""
    res = SourceResult(stem, draft=draft_path)
    for name in ("speech-map", "align", "prosody", "motion"):
        log(f"── {stem}: {name}")
        try:
            rc = stages[name]()
        except Exception as exc:  # noqa: BLE001 — a stage crash stops this source, not the batch
            rc, res.reason = 1, f"{type(exc).__name__}: {exc}"
        if rc != 0:
            res.failed_stage = name
            res.reason = res.reason or f"код {rc}"
            return res
        res.done.append(name)
    log(f"── {stem}: label")
    if not draft_path.exists():
        mode = "new"
    elif draft_stats(draft_path.read_text(encoding="utf-8"))[2]:
        mode = "retry"
    else:
        mode = "check"
    try:
        rc = label(mode)
    except Exception as exc:  # noqa: BLE001
        rc, res.reason = 1, f"{type(exc).__name__}: {exc}"
    if rc != 0 or not draft_path.exists():
        res.failed_stage = "label"
        res.reason = res.reason or f"код {rc} ({mode})"
        return res
    res.done.append(f"label:{mode}")
    res.clips, res.flagged, res.unanswered = draft_stats(draft_path.read_text(encoding="utf-8"))
    log(f"── {stem}: plan (пробный --apply черновика)")
    tee_out, tee_err = _Tee(sys.stdout), _Tee(sys.stderr)
    old = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = tee_out, tee_err
    try:
        res.plan_rc = plan()
    except Exception as exc:  # noqa: BLE001
        res.plan_rc = 1
        tee_err.write(f"Traceback: {type(exc).__name__}: {exc}\n")
    finally:
        sys.stdout, sys.stderr = old
    text = tee_out.buf.getvalue() + tee_err.buf.getvalue()
    res.plan_errors = [l.strip() for l in text.splitlines() if _ERR_RE.search(l)]
    res.done.append("plan")
    return res


def summary(results: list[SourceResult]) -> str:
    rows = ["", "итог arl prepare:"]
    for r in results:
        if r.failed_stage:
            rows.append(f"  ✗ {r.stem}: остановлен на «{r.failed_stage}» — {r.reason}. "
                        f"После исправления: arl prepare \"{r.stem}\" (готовые этапы пропустятся)")
            continue
        mark = "✓" if r.ok and not r.unanswered else "!"
        line = (f"  {mark} {r.stem}: клипов в черновике {r.clips}, с замечаниями #! {r.flagged}, "
                f"окон без ответа {r.unanswered}; план: "
                + ("без ошибок" if r.plan_rc == 0 and not r.plan_errors else f"ошибок {len(r.plan_errors) or 1}"))
        rows.append(line)
        for e in r.plan_errors[:5]:
            rows.append(f"      {e}")
        if r.unanswered:
            rows.append(f"      окна без ответа доберёт повторный запуск: arl prepare \"{r.stem}\"")
        rows.append(f"      черновик: {r.draft}")
    ok = [r for r in results if not r.failed_stage]
    if ok:
        rows += ["", "дальше: откройте черновик, поправьте или удалите строки, затем",
                 "  arl blocks --apply \"reviews/<stem>_auto.txt\" --labeler auto --install",
                 "  arl render --manifest \"<stem>\""]
    return "\n".join(rows)
