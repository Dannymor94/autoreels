"""arl prepare (M36): every analysis stage of a source in order, resumable, with a summary."""
from pathlib import Path

from autoreels import __main__ as cli
from autoreels.prepare import run_source, summary

DRAFT = ("# head\n# fingerprint: abc\n"
         "3 85+ | s:2 | e:9 | t: T | d: D\n"
         "#! 7 80 | s:1 | e:2  ← end 7.2 is unfinished\n"
         "12 80 | s:1 | e:4 | t: T | d: D\n")


def _stages(calls, fail=None):
    def mk(name):
        def f():
            calls.append(name)
            return 1 if name == fail else 0
        return f
    return {n: mk(n) for n in ("speech-map", "align", "prosody", "motion")}


def test_all_stages_in_order_new_draft_and_plan_errors_collected(tmp_path, capsys):
    calls, draft = [], tmp_path / "s_auto.txt"

    def label(mode):
        calls.append(f"label:{mode}")
        draft.write_text(DRAFT, encoding="utf-8")
        return 0

    def plan():
        calls.append("plan")
        print("  plan 3+4:")
        print("  [ERROR] r02: seam inside word")
        return 1

    r = run_source("s", stages=_stages(calls), draft_path=draft, label=label, plan=plan, log=lambda m: None)
    assert calls == ["speech-map", "align", "prosody", "motion", "label:new", "plan"]
    assert (r.clips, r.flagged, r.unanswered) == (2, 1, 0)
    assert r.plan_rc == 1 and r.plan_errors == ["[ERROR] r02: seam inside word"] and not r.ok
    assert "  plan 3+4:" in capsys.readouterr().out          # the plan is still shown live
    text = summary([r])
    assert "клипов в черновике 2" in text and "#! 1" in text and "[ERROR] r02" in text


def test_failed_stage_stops_the_source(tmp_path):
    calls = []
    r = run_source("s", stages=_stages(calls, fail="align"), draft_path=tmp_path / "d.txt",
                   label=lambda m: calls.append("label") or 0, plan=lambda: calls.append("plan") or 0,
                   log=lambda m: None)
    assert calls == ["speech-map", "align"] and r.failed_stage == "align" and r.done == ["speech-map"]
    assert 'arl prepare "s"' in summary([r])


def test_existing_draft_is_retried_or_rechecked(tmp_path):
    draft = tmp_path / "d.txt"
    modes = []
    draft.write_text(DRAFT + "# blocks 20–23: no answer (ProviderError: budget)\n", encoding="utf-8")
    r = run_source("s", stages=_stages([]), draft_path=draft, label=lambda m: modes.append(m) or 0,
                   plan=lambda: 0, log=lambda m: None)
    assert modes == ["retry"] and r.unanswered == 1 and "доберёт повторный запуск" in summary([r])
    draft.write_text(DRAFT, encoding="utf-8")
    r2 = run_source("s", stages=_stages([]), draft_path=draft, label=lambda m: modes.append(m) or 0,
                    plan=lambda: 0, log=lambda m: None)
    assert modes[-1] == "check" and r2.ok


def test_label_failure_without_draft_stops(tmp_path):
    r = run_source("s", stages=_stages([]), draft_path=tmp_path / "none.txt", label=lambda m: 1,
                   plan=lambda: 0, log=lambda m: None)
    assert r.failed_stage == "label" and r.plan_rc is None


def test_cmd_prepare_reports_missing_manifest(tmp_path, capsys):
    root = Path(__file__).resolve().parents[1]
    rc = cli.cmd_prepare([str(tmp_path / "nope.json")], root=root)
    assert rc == 1 and "манифест не найден" in capsys.readouterr().out


def test_parser_accepts_several_sources():
    a = cli._build_parser().parse_args(["prepare", "A", "2026-08-08 10h 59m 38s"])
    assert a.cmd == "prepare" and a.manifests == ["A", "2026-08-08 10h 59m 38s"] and a.root is None
