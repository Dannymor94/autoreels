"""M231-R1: passive observability trace for propose() and cmd_autocut.

Two layers, both exercising the REAL implementation (no inline copies of the
enrichment or of propose's exit routing):

* propose() directly — OFF parity, determinism, the callback spy, and every one
  of the nine seed exits (P1/P3/P4/P5/P11). Each exit is forced by monkeypatching
  the real decision helper (build_clip / fit_rhythm / context_start / fix_open_end
  / rhythm_why) so the asserted outcome is the specific one, never `len(...) > 0`.
* cmd_autocut() in-process on a synthetic montage project — the real CLI
  enrichment: timing deltas, speed_secs, dep_broken, select/fate accounting and
  the fail-closed trace-path boundary (P2/P6/P8/P9/P10). The repo-write guard in
  conftest proves nothing is written under the repository.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

import pytest

import autoreels.cloud.autocut as ac
from autoreels.cloud.autocut import AutoParams, propose


def U(i, t0, dur, role, punch, refs, standalone=True, refers=None, rate=2.4):
    return {
        "id": i, "t0": float(t0), "t1": float(t0 + dur),
        "role": role, "punch": punch, "refs": refs,
        "standalone": standalone, "refers": refers,
        "voice": {"energy": 50.0, "rate": rate}, "summary": f"мысль {i}",
        "topic": 1, "similar": [], "missing": False, "filtered": "",
    }


def _base_units():
    return [
        U(1, 0, 15, "thesis", 4, "1.1-2"),
        U(2, 20, 15, "example", 3, "2.1-3", standalone=False, refers=1),
        U(3, 40, 20, "conclusion", 5, "3.1-2"),
        U(4, 65, 12, "thesis", 2, "4.1"),
    ]


# ===========================================================================
# P1 — OFF parity: trace=None vs trace=[] give equal Proposals and side-outputs
# ===========================================================================

def test_p1_trace_none_vs_empty_equal_proposals():
    units = _base_units()
    p = AutoParams(clips=5, target_sec=30)
    r_none = propose(units, p)
    tr: list = []
    r_traced = propose(units, p, trace=tr)
    assert [pr.pieces for pr in r_none] == [pr.pieces for pr in r_traced]
    assert [pr.score for pr in r_none] == [pr.score for pr in r_traced]
    assert len(tr) > 0


def test_p1_side_outputs_unchanged():
    units = _base_units()
    p = AutoParams(clips=5, target_sec=30)
    ns1: list = []
    ns2: list = []
    r1 = propose(units, p, no_start=ns1)
    r2 = propose(units, p, no_start=ns2, trace=[])
    assert ns1 == ns2
    assert [pr.pieces for pr in r1] == [pr.pieces for pr in r2]


# ===========================================================================
# P3 — accounting identities at the propose level
# ===========================================================================

def test_p3_seed_count_and_truncate_identities():
    units = _base_units()
    p = AutoParams(clips=1, target_sec=30)
    tr: list = []
    out = propose(units, p, trace=tr)
    seeds = [e for e in tr if e["event"] == "seed"]
    truncs = [e for e in tr if e["event"] == "truncate"]
    assert len(truncs) == 1 and tr[-1]["event"] == "truncate"
    t = truncs[0]
    assert t["kept"] + t["dropped"] == t["pooled"]
    assert t["kept"] == len(out)
    assert t["pooled"] == sum(1 for e in seeds if e["outcome"] == "pooled")
    # exactly one seed event per eligible seed
    roles = tuple(p.seed_roles) or ac.STORY
    elig = [u for u in units if ac.eligible(u, p) and u["role"] in roles and u["punch"] >= p.seed_punch]
    assert len(seeds) == len(elig)
    assert {e["seed"] for e in seeds} == {u["id"] for u in elig}


def test_p3_every_seed_event_well_formed():
    tr: list = []
    propose(_base_units(), AutoParams(clips=5, target_sec=30), trace=tr)
    for ev in [e for e in tr if e["event"] == "seed"]:
        assert ev["schema"] == 1 and ev["outcome"] is not None
        assert set(ev["snap"]) == {"S0", "S1", "S2", "S3", "S4", "S5", "S6"}
        assert isinstance(ev["dep_broken"], list)


# ===========================================================================
# P4 — determinism (identical traces; stable under PYTHONHASHSEED)
# ===========================================================================

def test_p4_two_runs_byte_identical():
    units = _base_units()
    p = AutoParams(clips=5, target_sec=30)
    t1: list = []
    t2: list = []
    propose(units, p, trace=t1)
    propose(units, p, trace=t2)
    assert t1 == t2


def test_p4_dep_broken_stable_across_hash_seeds(tmp_path):
    """The dep_broken order is sorted, so the CLI trace is byte-identical under
    PYTHONHASHSEED 0/42/1337 (the former set-comprehension was hash-ordered)."""
    proj = _montage_project(tmp_path)
    digests = set()
    for seed in ("0", "42", "1337"):
        out = tmp_path / f"trace_{seed}.jsonl"
        env = {**os.environ, "ARL_AUTOCUT_TRACE": str(out), "PYTHONHASHSEED": seed}
        r = subprocess.run([sys.executable, "-m", "autoreels", "autocut", "v",
                            f"--root={tmp_path}", f"--cache-dir={tmp_path / 'cache'}",
                            "--no-check", "--clips=2"],
                           capture_output=True, text=True, env=env, cwd=str(tmp_path))
        assert r.returncode == 0, r.stderr
        digests.add(hashlib.sha256(out.read_bytes()).hexdigest())
    assert len(digests) == 1


# ===========================================================================
# P5 — callback spy: trace ON adds no callback calls or new arguments
# ===========================================================================

def test_p5_no_extra_callback_calls():
    off: list = []
    on: list = []
    units = _base_units()
    p = AutoParams(clips=5, target_sec=30, taste_weight=1.0)
    propose(units, p, taste=lambda clip: (off.append(tuple(u["id"] for u in clip)) or 0.0))
    propose(units, p, taste=lambda clip: (on.append(tuple(u["id"] for u in clip)) or 0.0), trace=[])
    assert off == on and len(off) > 0


def test_p5_all_callback_kinds_have_identical_arguments():
    units = [U(1, 0, 30, "thesis", 5, "1.1")]
    p = AutoParams(clips=1, generator="montage", rhythm=False, prune=False,
                   context_start=True, context_min_words=1, min_sec=1,
                   end_tone=True, taste_weight=1.0)

    def run(trace):
        calls = {"sentences": [], "judge": [], "end_tone": [], "taste": []}

        def sentences(refs):
            calls["sentences"].append(refs)
            return [("1.1", 30.0, 4, True, "Практика помогает каждому человеку")]

        def judge(text, following, core):
            calls["judge"].append((text, following, core))
            return (True, "")

        def end_tone(ref):
            calls["end_tone"].append(ref)
            return "final"

        def taste(clip):
            calls["taste"].append(tuple(u["id"] for u in clip))
            return 0.0

        result = propose(units, p, sentences, judge=judge, end_tone=end_tone,
                         taste=taste, trace=trace)
        return result, calls

    off, off_calls = run(None)
    trace: list = []
    on, on_calls = run(trace)
    assert off == on
    assert all(off_calls[k] for k in off_calls), off_calls
    assert off_calls == on_calls
    assert [e["outcome"] for e in trace if e["event"] == "seed"] == ["pooled"]


def test_p7_frozen_production_golden_for_off_proposals_and_callback_logs():
    """Golden generated on 3c011e9, with a real proposal and all four callbacks."""
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    spec = json.loads((repo / "tests" / "fixtures" / "m231" /
                       "frozen_production_off_golden.json").read_text(encoding="utf-8"))
    result = subprocess.run([sys.executable, str(repo / "tests" / "fixtures" / "m231" /
                                                 "compare_off_golden.py")],
                            env={**os.environ, "PYTHONPATH": os.pathsep.join((str(repo / "src"), str(repo)))},
                            cwd=str(repo), capture_output=True, text=True, check=True)
    assert spec["provenance"]["source_sha"] == "3c011e94263e16e5780936b4769d3490cd03b682"
    assert json.loads(result.stdout) == spec["expected"]


def test_p7_frozen_production_golden_for_cli_review_and_console():
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    spec = json.loads((repo / "tests" / "fixtures" / "m231" /
                       "frozen_production_off_golden.json").read_text(encoding="utf-8"))
    result = subprocess.run([sys.executable, str(repo / "tests" / "fixtures" / "m231" /
                                                 "compare_cli_off_golden.py")],
                            env={**os.environ, "PYTHONPATH": os.pathsep.join((str(repo / "src"), str(repo)))},
                            cwd=str(repo), capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == spec["cli_expected"]


# ===========================================================================
# P11 — the nine seed exits, each forced and asserted by its specific outcome
# ===========================================================================

def _one_outcome(tr):
    seeds = [e for e in tr if e["event"] == "seed"]
    return seeds


def test_p11_pooled():
    tr: list = []
    propose([U(1, 0, 30, "thesis", 5, "1.1")], AutoParams(clips=1, target_sec=30,
            generator="montage", rhythm=False, prune=False, context_start=False), trace=tr)
    assert [e["outcome"] for e in _one_outcome(tr)] == ["pooled"]


def test_p11_build_none(monkeypatch):
    monkeypatch.setattr(ac, "build_clip", lambda *a, **k: None)
    tr: list = []
    propose([U(1, 0, 30, "thesis", 5, "1.1")],
            AutoParams(clips=1, generator="montage"), trace=tr)
    assert [e["outcome"] for e in _one_outcome(tr)] == ["build_none"]
    assert tr[0]["snap"]["S0"] is None


def test_p11_skip_used(monkeypatch):
    # seed 1 pools a clip that consumes seed 2's STORY unit → seed 2 is skip_used
    units = [U(1, 0, 20, "thesis", 5, "1.1"), U(2, 25, 20, "thesis", 5, "2.1")]
    monkeypatch.setattr(ac, "build_clip", lambda seed, *a, **k: [units[0], units[1]])
    tr: list = []
    propose(units, AutoParams(clips=2, generator="montage", rhythm=False,
            prune=False, context_start=False, overlap_max=1.0), trace=tr)
    seeds = _one_outcome(tr)
    assert seeds[0]["outcome"] == "pooled"
    sk = next(e for e in seeds if e["outcome"] == "skip_used")
    assert sk["sup"] == 0  # the earlier pooled candidate that contains it


def test_p11_skip_taken(monkeypatch):
    # passage: seed 1 pools [1(thesis), 2(explanation)] → taken={1,2}, used_seeds={1}.
    # seed 2 (a non-STORY seed_role) is in taken but not used_seeds → skip_taken, not skip_used.
    units = [U(1, 0, 20, "thesis", 5, "1.1"), U(2, 25, 20, "explanation", 5, "2.1")]
    monkeypatch.setattr(ac, "build_passage", lambda seed, *a, **k: [units[0], units[1]])
    tr: list = []
    propose(units, AutoParams(clips=3, generator="passage", rhythm=False,
            context_start=False, overlap_max=1.0, seed_roles=("thesis", "explanation")), trace=tr)
    outs = [e["outcome"] for e in _one_outcome(tr)]
    assert outs[0] == "pooled" and "skip_taken" in outs and "skip_used" not in outs


def test_p11_rhythm_fail(monkeypatch):
    monkeypatch.setattr(ac, "fit_rhythm", lambda *a, **k: (None, ["ритм"]))
    tr: list = []
    propose([U(1, 0, 30, "thesis", 5, "1.1")],
            AutoParams(clips=1, generator="montage", rhythm=True,
                       prune=False, context_start=False), trace=tr)
    assert [e["outcome"] for e in _one_outcome(tr)] == ["rhythm_fail"]


def test_p11_start_fail(monkeypatch):
    monkeypatch.setattr(ac, "context_start", lambda *a, **k: (None, [], "нет контекста"))
    tr: list = []
    propose([U(1, 0, 30, "thesis", 5, "1.1")],
            AutoParams(clips=1, generator="montage", rhythm=False, prune=False,
                       context_start=True),
            sentences=lambda refs: [("1.1", 5.0, 3, True)], trace=tr)
    assert [e["outcome"] for e in _one_outcome(tr)] == ["start_fail"]


def test_p11_open_end_fail(monkeypatch):
    monkeypatch.setattr(ac, "fix_open_end", lambda *a, **k: (None, "", "→"))
    tr: list = []
    propose([U(1, 0, 30, "thesis", 5, "1.1")],
            AutoParams(clips=1, generator="montage", rhythm=False, prune=False,
                       context_start=False, end_tone=True),
            sentences=lambda refs: [("1.1", 5.0, 3, True)],
            end_tone=lambda ref: "open", trace=tr)
    seeds = _one_outcome(tr)
    assert [e["outcome"] for e in seeds] == ["open_end_fail"]
    assert seeds[0]["spans_final"] is not None  # spans captured for exits after S5


def test_p11_final_rhythm_fail(monkeypatch):
    monkeypatch.setattr(ac, "fit_rhythm", lambda clip, *a, **k: (clip, []))
    monkeypatch.setattr(ac, "rhythm_why", lambda *a, **k: ("скачок", None))
    tr: list = []
    propose([U(1, 0, 30, "thesis", 5, "1.1")],
            AutoParams(clips=1, generator="montage", rhythm=True, prune=False,
                       context_start=False), trace=tr)
    assert [e["outcome"] for e in _one_outcome(tr)] == ["final_rhythm_fail"]


def test_p11_taken_after_context(monkeypatch):
    units = [U(1, 0, 20, "thesis", 5, "1.1"), U(2, 25, 20, "thesis", 5, "2.1")]
    calls = {"n": 0}

    def fake_passage(seed, *a, **k):
        return [units[0]] if seed["id"] == 1 else [units[1]]

    def fake_context(clip, *a, **k):
        # the second seed's context reaches unit 1, already taken by the first clip
        return ([units[0], units[1]], [], "") if clip and clip[0]["id"] == 2 else (clip, [], "")

    monkeypatch.setattr(ac, "build_passage", fake_passage)
    monkeypatch.setattr(ac, "context_start", fake_context)
    tr: list = []
    propose(units, AutoParams(clips=3, generator="passage", rhythm=False,
            context_start=True, overlap_max=1.0),
            sentences=lambda refs: [("x", 5.0, 3, True)], trace=tr)
    outs = [e["outcome"] for e in _one_outcome(tr)]
    assert outs[0] == "pooled" and "taken_after_context" in outs


def test_p11_overlap_or_payoff(monkeypatch):
    units = [U(1, 0, 20, "thesis", 5, "1.1"), U(2, 25, 20, "thesis", 5, "2.1")]
    monkeypatch.setattr(ac, "build_clip", lambda seed, *a, **k: [units[0]])  # identical clips
    tr: list = []
    propose(units, AutoParams(clips=3, generator="montage", rhythm=False,
            prune=False, context_start=False, overlap_max=0.0), trace=tr)
    outs = [e["outcome"] for e in _one_outcome(tr)]
    assert outs[0] == "pooled" and "overlap_or_payoff" in outs


# ===========================================================================
# CLI integration harness
# ===========================================================================

def _montage_project(tmp_path, units=None, *, rate=2.4):
    """A real offline montage project: source, config (no model, min_sec low),
    and a map.json whose units sit at word-span + 0.4 s unless `units` is given.
    Returns the computed sent_by_ref so a test can reason about word times."""
    from autoreels import __main__ as cli
    from autoreels.core.models import Manifest
    from autoreels.cloud.montage import montage_blocks
    from autoreels.cloud.edit import merge_group_sentences
    from tests.test_montage import _source

    mpath = _source(tmp_path)
    cfg = tmp_path / "config" / "r0.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("  min_sec: 25 ", "  min_sec: 1 ")
                   .replace("  hook_llm: auto ", "  hook_llm: none "), encoding="utf-8")
    r0 = cli.load_r0_config(cfg)
    manifest = Manifest.model_validate_json(mpath.read_text())
    tx = cli._resolve_cached_transcript(manifest, tmp_path / "cache")
    all_blocks, kept, _ = cli._review_block_set(tx, r0, "lecture")
    sbr: dict = {}
    for key, b in montage_blocks(all_blocks, kept).items():
        for k, st in enumerate(merge_group_sentences([b], tx.words), 1):
            sbr[f"{key}.{k}"] = st
    refs = sorted(sbr, key=lambda r: (r.split(".")[0], int(r.split(".")[1])))
    if units is None:
        units = []
        for i, ref in enumerate(refs[:4], 1):
            st = sbr[ref]
            units.append({"id": i, "t0": round(float(st[0].t0) + 0.4, 3),
                          "t1": round(float(st[-1].t1) + 0.4, 3), "role": "thesis",
                          "punch": 4, "refs": ref, "topic": 1, "standalone": True,
                          "summary": f"мысль {i}", "voice": {"energy": 50.0, "rate": rate}})
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    (tmp_path / "transcripts" / "v.map.json").write_text(json.dumps(
        {"version": 1, "stem": "v", "source_sha256": "f" * 64, "units": units}), encoding="utf-8")
    return {"cli": cli, "tmp": tmp_path, "sbr": sbr, "refs": refs, "units": units}


def _run(proj, monkeypatch, *, trace=True, **kw):
    out = proj["tmp"] / "trace.jsonl"
    if trace:
        monkeypatch.setenv("ARL_AUTOCUT_TRACE", str(out))
    else:
        monkeypatch.delenv("ARL_AUTOCUT_TRACE", raising=False)
    rc = proj["cli"].cmd_autocut("v", root=proj["tmp"], cache_dir=str(proj["tmp"] / "cache"),
                                 check=False, **kw)
    events = None
    if trace and out.exists():
        events = [json.loads(ln) for ln in out.read_text(encoding="utf-8").splitlines()]
    review = (proj["tmp"] / "reviews" / "v_auto_m56.txt")
    return rc, events, (review.read_text(encoding="utf-8") if review.exists() else None), out


# ===========================================================================
# P6 — real CLI, non-vacuous: file in tmp_path, schema, counts, NOT in repo
# ===========================================================================

def test_p6_trace_written_to_tmp_path_with_schema(tmp_path, monkeypatch, capsys):
    proj = _montage_project(tmp_path)
    rc, events, review, out = _run(proj, monkeypatch, clips=2)
    assert rc == 0
    assert out.exists() and out.parent == tmp_path          # in tmp_path, not the repo
    assert events and all(e.get("schema") == 1 for e in events)
    kinds = {e["event"] for e in events}
    assert {"seed", "truncate", "select", "fate", "pool_accounting"} <= kinds
    assert sum(1 for e in events if e["event"] == "truncate") == 1
    # Σ fate == Σ select == pool (P3 over the effective montage pool)
    acct = next(e for e in events if e["event"] == "pool_accounting")
    assert acct["fates"] == acct["select"] == acct["pool"]


def test_p6_refuses_repo_path_fail_closed(tmp_path, monkeypatch):
    """A trace path inside the repository is refused: nothing is written and the
    run still succeeds (the repo-write guard would otherwise fail this test)."""
    import autoreels.__main__ as cli
    proj = _montage_project(tmp_path)
    inside = cli._project_root() / "reviews" / "m231_should_not_exist.jsonl"
    monkeypatch.setenv("ARL_AUTOCUT_TRACE", str(inside))
    rc = cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False, clips=2)
    assert rc == 0
    assert not inside.exists()


def test_p6_does_not_follow_symlink(tmp_path, monkeypatch):
    proj = _montage_project(tmp_path)
    real = tmp_path / "real_target.jsonl"
    real.write_text("PRESERVE\n", encoding="utf-8")
    link = tmp_path / "trace_link.jsonl"
    link.symlink_to(real)
    monkeypatch.setenv("ARL_AUTOCUT_TRACE", str(link))
    rc = proj["cli"].cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"),
                                 check=False, clips=2)
    assert rc == 0
    assert real.read_text(encoding="utf-8") == "PRESERVE\n"  # the symlink target is untouched


def test_p6_refuses_preexisting_regular_file(tmp_path, monkeypatch):
    proj = _montage_project(tmp_path)
    existing = tmp_path / "existing.jsonl"
    existing.write_text("DO NOT OVERWRITE\n", encoding="utf-8")
    monkeypatch.setenv("ARL_AUTOCUT_TRACE", str(existing))
    rc = proj["cli"].cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"),
                                 check=False, clips=2)
    assert rc == 0
    assert existing.read_text(encoding="utf-8") == "DO NOT OVERWRITE\n"


def test_p6_parent_symlink_swap_cannot_redirect_write(tmp_path, monkeypatch):
    """A parent replacement immediately before final open cannot redirect writes.

    All destinations are synthetic tmp directories; no real repository path is a target.
    """
    proj = _montage_project(tmp_path)
    original = tmp_path / "stage"
    relocated = tmp_path / "stage_renamed"
    fake_repo = tmp_path / "fake_repository"
    original.mkdir()
    fake_repo.mkdir()
    sentinel = fake_repo / "trace.jsonl"
    sentinel.write_text("PROTECTED\n", encoding="utf-8")
    monkeypatch.setenv("ARL_AUTOCUT_TRACE", str(original / "trace.jsonl"))
    original_open = os.open
    switched = []

    def swap_on_final_open(path, flags, *args, **kwargs):
        if not switched and (
            (path == "trace.jsonl" and kwargs.get("dir_fd") is not None)
            or os.fspath(path) == str(original / "trace.jsonl")
        ):
            original.rename(relocated)
            original.symlink_to(fake_repo, target_is_directory=True)
            switched.append(True)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_on_final_open)
    rc = proj["cli"].cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"),
                                 check=False, clips=2)
    assert rc == 0 and switched
    assert sentinel.read_text(encoding="utf-8") == "PROTECTED\n"
    assert (relocated / "trace.jsonl").exists()


def test_p6_parent_symlink_loop_fails_closed(tmp_path, monkeypatch, capsys):
    proj = _montage_project(tmp_path)
    loop = tmp_path / "loop"
    loop.symlink_to(loop, target_is_directory=True)
    monkeypatch.setenv("ARL_AUTOCUT_TRACE", str(loop / "trace.jsonl"))
    rc = proj["cli"].cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"),
                                 check=False, clips=2)
    assert rc == 0
    assert not (tmp_path / "trace.jsonl").exists()
    assert "Traceback" not in capsys.readouterr().err


# ===========================================================================
# P2 — env unset vs set: identical stdout and review draft (byte-for-byte)
# ===========================================================================

def test_p2_env_parity_stdout_and_review(tmp_path, monkeypatch, capsys):
    proj = _montage_project(tmp_path)
    rc_off, _, review_off, _ = _run(proj, monkeypatch, trace=False, clips=2)
    out_off = capsys.readouterr().out
    rc_on, events, review_on, _ = _run(proj, monkeypatch, trace=True, clips=2)
    out_on = capsys.readouterr().out
    assert rc_off == rc_on == 0
    assert out_off == out_on
    assert hashlib.sha256((review_off or "").encode()).hexdigest() == \
           hashlib.sha256((review_on or "").encode()).hexdigest()
    assert events  # the only difference ON is the trace file itself


# ===========================================================================
# P9 — real CLI timing: t0=w0+0.4, t1=w1+0.4 → d0=d1=0.4, err=0, speed computed
# ===========================================================================

def test_p9_full_timing_and_speed(tmp_path, monkeypatch):
    proj = _montage_project(tmp_path, rate=2.4)      # 2.4 < speed_mid_rate 2.6 → @speed 1.05
    rc, events, _, _ = _run(proj, monkeypatch, clips=2)
    assert rc == 0
    pooled = [e for e in events if e["event"] == "seed" and e.get("timing")
              and e["timing"]["units_total"] > 0]
    assert pooled, "expected a pooled seed with timing"
    tmg = pooled[0]["timing"]
    for s in tmg["spans"]:
        assert s[4]["status_d0"] == "ok" and s[4]["status_d1"] == "ok"
        assert s[4]["d0"] == 0.4 and s[4]["d1"] == 0.4 and s[4]["err"] == 0.0
    assert tmg["n_err"] == tmg["units_total"]
    assert tmg["secs_delta"] == 0.0 and tmg["secs_delta_known"] == 0.0
    assert tmg["speed_status"] == "ok" and tmg["speed_secs"] == 1.05


def test_p9_speed_status_no_rate_when_rate_missing(tmp_path, monkeypatch):
    proj = _montage_project(tmp_path, rate=0.0)       # no voice.rate → speed null + reason
    rc, events, _, _ = _run(proj, monkeypatch, clips=2)
    tmg = next(e["timing"] for e in events if e["event"] == "seed" and e.get("timing")
               and e["timing"]["units_total"] > 0)
    assert tmg["speed_secs"] is None and tmg["speed_status"] == "no_rate"
    assert tmg["secs_delta"] == 0.0           # timing itself is still fully covered


# ===========================================================================
# P10 — sparse timing: unknown is null (never 0); mixed coverage; OFF-identical
# ===========================================================================

def test_p10_sparse_mixed_coverage(tmp_path, monkeypatch):
    proj0 = _montage_project(tmp_path)
    refs = proj0["refs"]
    st = proj0["sbr"][refs[0]]
    w0, w1 = float(st[0].t0), float(st[-1].t1)
    # one real-timed unit + one whose ref is absent from sent_by_ref, same topic so build_clip
    # merges them into a single clip (mixed coverage). (The `no_refs` status is a defensive branch:
    # `eligible` rejects an empty-refs unit before it can seed a clip, so no real span reaches it.)
    units = [
        {"id": 1, "t0": round(w0 + 0.4, 3), "t1": round(w1 + 0.4, 3), "role": "thesis",
         "punch": 4, "refs": refs[0], "topic": 1, "standalone": True, "summary": "ok",
         "voice": {"energy": 50.0, "rate": 2.4}},
        {"id": 2, "t0": round(w1 + 1.0, 3), "t1": round(w1 + 6.0, 3), "role": "example",
         "punch": 3, "refs": "99.9", "topic": 1, "standalone": True, "summary": "missing",
         "voice": {"energy": 50.0, "rate": 2.4}},
    ]
    proj = _montage_project(tmp_path, units=units)
    rc_off, _, review_off, _ = _run(proj, monkeypatch, trace=False, clips=2)
    rc, events, review_on, _ = _run(proj, monkeypatch, trace=True, clips=2)
    assert rc == rc_off == 0
    assert review_off == review_on                        # trace never alters the draft
    tmg = next(e["timing"] for e in events if e["event"] == "seed" and e.get("timing")
               and e["timing"]["units_total"] >= 2)
    by_id = {s[0]: s[4] for s in tmg["spans"]}
    assert by_id[1]["status_d0"] == "ok" and by_id[1]["err"] == 0.0
    assert by_id[2]["status_d0"] == "no_sentence" and by_id[2]["d0"] is None and by_id[2]["err"] is None
    assert tmg["n_err"] < tmg["units_total"]
    assert tmg["secs_delta"] is None                      # not full coverage → null, not 0
    assert tmg["secs_delta_known"] == 0.0                 # the one known unit
    assert tmg["speed_secs"] is None and tmg["speed_status"] == "no_err_coverage"


# ===========================================================================
# P8 — dep_broken: established support dropped at S5 → [[11,10,"S5"]]; clean → []
# ===========================================================================

def _fx7l_units():
    # committed fixture: unit 11 leans on unit 10 (non-standalone, refers=10); adjacent, one topic
    import pathlib
    p = pathlib.Path(__file__).parent / "fixtures" / "m231" / "fx7l_units.json"
    return json.loads(p.read_text(encoding="utf-8"))["units"]


def test_p8_dep_broken_when_support_dropped_at_s5(tmp_path, monkeypatch):
    proj = _montage_project(tmp_path, units=_fx7l_units())

    def drop_ten(clip, *a, **k):
        kept = [u for u in clip if u["id"] != 10]
        return (kept or clip), [], ""

    monkeypatch.setattr(ac, "context_start", drop_ten)   # context_start drops the support at S5
    rc, events, _, _ = _run(proj, monkeypatch, clips=2)
    assert rc == 0
    seed11 = [e for e in events if e["event"] == "seed" and e["dep_broken"]]
    assert seed11, "expected a dep_broken observation"
    assert seed11[0]["dep_broken"] == [[11, 10, "S5"]]


def test_p8_direct_propose_reports_dep_broken_before_cli_enrichment(monkeypatch):
    units = _fx7l_units()

    def drop_ten(clip, *args, **kwargs):
        kept = [u for u in clip if u["id"] != 10]
        return (kept or clip), [], ""

    monkeypatch.setattr(ac, "context_start", drop_ten)
    tr: list = []
    propose(units, AutoParams(clips=2, generator="montage", rhythm=False,
            prune=False, context_start=True, min_sec=1.0, target_sec=30.0),
            sentences=lambda refs: [("1.1", 5.0, 3, True)], trace=tr)
    seed_events = [e for e in tr if e["event"] == "seed"]
    assert seed_events
    assert any(e["dep_broken"] == [[11, 10, "S5"]] for e in seed_events)


@pytest.mark.parametrize("stage", ("S3", "S4"))
def test_p8_direct_propose_uses_reached_drop_stage(monkeypatch, stage):
    units = _fx7l_units()
    if stage == "S3":
        monkeypatch.setattr(ac, "_prune", lambda clip, *args: (
            [u for u in clip if u["id"] != 10], [10]))
    else:
        monkeypatch.setattr(ac, "fit_rhythm", lambda clip, *args: (
            [u for u in clip if u["id"] != 10], []))
        monkeypatch.setattr(ac, "rhythm_why", lambda *args: (None, None))
    tr: list = []
    propose(units, AutoParams(clips=2, generator="montage", rhythm=stage == "S4",
            prune=stage == "S3", context_start=False, min_sec=1.0, target_sec=30.0),
            trace=tr)
    seed_events = [e for e in tr if e["event"] == "seed"]
    assert any(e["dep_broken"] == [[11, 10, stage]] for e in seed_events)


def test_p8_no_dep_broken_when_support_preserved(tmp_path, monkeypatch):
    proj = _montage_project(tmp_path, units=_fx7l_units())
    rc, events, _, _ = _run(proj, monkeypatch, clips=2)
    assert rc == 0
    assert all(e["dep_broken"] == [] for e in events if e["event"] == "seed")
