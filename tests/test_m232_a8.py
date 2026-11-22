"""M232-A8: synthetic complementary seeds, with the legacy lifecycle frozen."""

from __future__ import annotations

from dataclasses import asdict, replace

import pytest

from autoreels.cloud.autocut import AutoParams, propose
from autoreels.core.config import AutocutConfig
from tests.test_m231_trace import U, _montage_project


def _fx1():
    return [U(1, 0, 22, "thesis", 5, "1.1"),
            U(2, 24, 22, "conclusion", 4, "2.1")]


def _params(**kw):
    return replace(AutoParams(clips=2, generator="passage", loop=False, prune=False,
                              min_sec=10, target_sec=40, max_sec=60), **kw)


def test_a8_flags_default_off_and_are_typed():
    assert AutoParams().seed_alt is False
    assert AutoParams().seed_alt_max is None
    assert AutocutConfig().seed_alt is False
    assert AutocutConfig().seed_alt_max is None
    assert AutocutConfig.model_validate({"seed_alt": True, "seed_alt_max": 2}).seed_alt_max == 2
    with pytest.raises(ValueError):
        AutocutConfig.model_validate({"seed_alt_max": -1})


def test_a8_fx1_descriptor_is_pure_and_g2_excludes_suppressor():
    units = _fx1()
    original = propose(units, _params())
    assert [v.units for v in original] == [[1, 2]]
    descriptions = []
    sent_calls, judge_calls = [], []

    def sentences(refs):
        sent_calls.append(refs)
        return []

    def judge(*args):
        judge_calls.append(args)
        return None

    p = _params(seed_alt=True, seed_alt_max=1)
    legacy = propose(units, p, sentences=sentences, judge=judge, variant_descs_out=descriptions)
    on_calls = (list(sent_calls), list(judge_calls))
    sent_calls.clear()
    judge_calls.clear()
    propose(units, _params(), sentences=sentences, judge=judge)
    assert [asdict(v) for v in legacy] == [asdict(v) for v in original]
    assert descriptions == [(2, 0, (1,))]
    assert on_calls == (sent_calls, judge_calls)  # G1 adds no callbacks to legacy

    variants = propose(units, p, variant_descs=descriptions)
    assert [v.units for v in variants] == [[2]]
    assert variants[0].alt_of == 0
    assert "alt_of" not in asdict(variants[0])
    assert not set(variants[0].units) & set(descriptions[0][2])
    assert variants[0].notes is not legacy[0].notes
    assert variants[0].hooks is not legacy[0].hooks
    assert variants[0].keys is not legacy[0].keys
    assert variants[0].unit_refs is not legacy[0].unit_refs


def test_a8_disabled_keyword_keeps_exact_proposals_and_trace():
    units = _fx1()
    descriptors = []
    trace_old, trace_off = [], []
    frozen = propose(units, _params(), trace=trace_old)
    disabled = propose(units, _params(seed_alt=False), variant_descs_out=descriptors, trace=trace_off)
    assert descriptors == []
    assert trace_old == trace_off
    assert [asdict(v) for v in frozen] == [asdict(v) for v in disabled]


def test_a8_g1_respects_cap_and_never_collects_in_disabled_mode():
    units = [U(1, 0, 22, "thesis", 5, "1.1"),
             U(2, 23, 22, "conclusion", 4, "2.1"),
             U(3, 46, 22, "conclusion", 4, "3.1")]
    p = _params(target_sec=69, max_sec=80, seed_alt=True, seed_alt_max=1)
    descriptors = []
    propose(units, p, variant_descs_out=descriptors)
    assert len(descriptors) == 1 and descriptors[0][0] == 2
    none = []
    propose(units, replace(p, seed_alt=False), variant_descs_out=none)
    assert not none


def _cli_fx1(tmp_path):
    probe = _montage_project(tmp_path)
    refs = probe["refs"]
    assert len(refs) >= 2
    units = _fx1()
    units[0]["refs"] = refs[0]
    units[1]["refs"] = refs[1]
    import json
    (tmp_path / "transcripts" / "v.map.json").write_text(json.dumps(
        {"version": 1, "stem": "v", "source_sha256": "f" * 64, "units": units}), encoding="utf-8")
    return probe


@pytest.mark.parametrize("mode", ["greedy", "global"])
@pytest.mark.parametrize("max_shared", [0, 1])
def test_a8_cli_legacy_draft_prefix_and_variant_close(tmp_path, capsys, mode, max_shared):
    from autoreels import __main__ as cli

    _cli_fx1(tmp_path)
    extra = ["generator=passage", "loop=false", "prune=false", "short_variant=false",
             "target_sec=40", "min_sec=10", "max_sec=60", f"select={mode}",
             f"max_shared={max_shared}"]
    off_path = tmp_path / "reviews" / "off.txt"
    on_path = tmp_path / "reviews" / "on.txt"
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False,
                           clips=2, llm="none", out=str(off_path), ac_over=extra) == 0
    off_console = capsys.readouterr().out
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False,
                           clips=2, llm="none", out=str(on_path),
                           ac_over=extra + ["seed_alt=true", "seed_alt_max=2"]) == 0
    on_console = capsys.readouterr().out
    off = off_path.read_text(encoding="utf-8").splitlines()
    on = on_path.read_text(encoding="utf-8").splitlines()
    # Only the first map source/header path differs; every legacy M line stays exact.
    def m_lines(rows):
        return [line for line in rows if line.startswith("M1 ") or line.startswith("# --- M1:")]

    assert m_lines(off) == m_lines(on)
    assert "variant_close" in "\n".join(on)
    assert "вариант" not in "\n".join(off)
    assert any(line.startswith("  M1 ") for line in off_console.splitlines())
    assert any(line.startswith("  M1 ") for line in on_console.splitlines())


def test_a8_cli_rejected_legacy_allows_spare_slot(tmp_path, monkeypatch):
    from autoreels import __main__ as cli

    _cli_fx1(tmp_path)
    calls = []

    def fake_check(_head, line, _root, _cache):
        calls.append(line)
        return ("legacy rejected", "") if "1.1" in line else (None, "")

    monkeypatch.setattr(cli, "_autocut_check", fake_check)
    res = tmp_path / "reviews" / "a8.txt"
    opts = ["generator=passage", "loop=false", "prune=false", "short_variant=false",
            "target_sec=40", "min_sec=10", "max_sec=60", "seed_alt=true"]
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=True,
                           clips=2, llm="none", out=str(res), ac_over=opts) == 0
    assert "variant_accepted" in res.read_text(encoding="utf-8")
    assert len(calls) >= 2


@pytest.mark.parametrize("mode", ["greedy", "global"])
def test_a8_provider_enabled_off_seam_check_keeps_legacy_request_prefix(tmp_path, monkeypatch, mode):
    """Seam functions must remain callable in the outer legacy scope (QA R1)."""
    from autoreels import __main__ as cli
    from autoreels.cloud import autocut as mod

    _cli_fx1(tmp_path)

    class Fake:
        name = "fake"

        def __init__(self):
            self.calls = []

        def complete(self, messages, temperature=0.0):
            self.calls.append(messages[0])
            return "{}"

    def check_seams(pr, pairs, provider, **_kw):
        provider.complete([{"action": "seams", "pieces": pr.pieces}])

    def rank_hooks(pr, provider, **_kw):
        provider.complete([{"action": "rank", "pieces": pr.pieces}])
        return False

    monkeypatch.setattr(mod, "check_seams", check_seams)
    monkeypatch.setattr(mod, "seam_pairs", lambda *_a: [])
    monkeypatch.setattr(mod, "rank_hooks", rank_hooks)

    opts = ["generator=passage", "loop=false", "prune=false", "short_variant=false",
            "target_sec=40", "min_sec=10", "max_sec=60", "seam_check=true",
            "hook_title=false", "hook_judge=false", f"select={mode}"]

    def run(flag):
        provider = Fake()
        out = tmp_path / "reviews" / f"seams_{flag}.txt"
        args = opts + (["seed_alt=true"] if flag else [])
        assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"),
                               check=False, clips=2, llm="local", provider=provider,
                               out=str(out), ac_over=args) == 0
        return provider.calls, out.read_text(encoding="utf-8")

    off_calls, off_draft = run(False)
    on_calls, on_draft = run(True)
    assert off_calls and off_calls[0]["action"] == "seams"
    assert len([c for c in off_calls if c["action"] == "seams"]) == 1
    assert on_calls[:len(off_calls)] == off_calls
    assert [line for line in off_draft.splitlines() if line.startswith("M1 ")] == [
        line for line in on_draft.splitlines() if line.startswith("M1 ")]


@pytest.mark.parametrize("check", [False, True])
def test_a8_fx1i_interviewer_full_refs_before_variant_provider(tmp_path, monkeypatch, check):
    """The variant with interviewer audio is rejected even after the legacy pool is filtered."""
    from autoreels import __main__ as cli
    from autoreels.cloud import speakers

    project = _montage_project(tmp_path)
    r1, r2, r3 = project["refs"][:3]
    units = [U(1, 0, 22, "thesis", 5, r1),
             U(2, 23, 22, "conclusion", 4, r2),
             U(3, 46, 22, "conclusion", 4, r3)]
    import json
    (tmp_path / "transcripts" / "v.map.json").write_text(json.dumps(
        {"version": 1, "stem": "v", "source_sha256": "f" * 64, "units": units}), encoding="utf-8")
    monkeypatch.setattr(speakers, "load", lambda *_: object())
    monkeypatch.setattr(speakers, "other_refs", lambda *_: {r2})
    calls = []
    if check:
        monkeypatch.setattr(cli, "_autocut_check", lambda *args: (calls.append(args[1]) or (None, "")))
    dest = tmp_path / "reviews" / "a8_interviewer.txt"
    opts = ["generator=passage", "loop=false", "prune=false", "short_variant=false",
            "target_sec=69", "min_sec=10", "max_sec=75", "interviewer=off",
            "seed_alt=true", "seed_alt_max=2", "hook_title=false", "seam_check=false"]
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=check,
                           clips=2, llm="none", out=str(dest), ac_over=opts) == 0
    draft = dest.read_text(encoding="utf-8")
    assert "variant_interviewer" in draft
    assert "variant_accepted" in draft  # the clean third thought may fill the slot
    chosen = [line for line in draft.splitlines() if line.startswith("M")]
    assert chosen and all(r2 not in line for line in chosen)
    assert all(r2 not in line for line in calls)


@pytest.mark.parametrize("mode", ["greedy", "global"])
def test_a8_fx1h_hookless_legacy_preempts_hooked_alt(tmp_path, monkeypatch, mode):
    """An existing hookless clip keeps its slot despite a conflicting hooked variant."""
    from autoreels import __main__ as cli
    from autoreels.cloud import autocut as mod
    from autoreels.cloud.autocut import Proposal

    project = _montage_project(tmp_path)
    r1, r2 = project["refs"][:2]
    calls = []

    def synthetic_propose(_units, params, *_args, variant_descs_out=None, variant_descs=None, **_kw):
        calls.append((params.seed_punch, variant_descs is not None))
        if variant_descs is not None:
            variant = Proposal([2], r2, r2, "alt", "alt", 95, 20, opener=2)
            variant.alt_of, variant._alt_seed = 0, 2
            return [variant]
        if variant_descs_out is not None:
            variant_descs_out.append((2, 0, (1,)))
        if params.seed_punch < 4:
            return []
        return [Proposal([1, 2], f"{r1} {r2}", None, "legacy", "legacy", 60, 40, opener=1)]

    monkeypatch.setattr(mod, "propose", synthetic_propose)
    out = tmp_path / "reviews" / "a8_hookless.txt"
    opts = ["seed_alt=true", "fill_seed_punch=3", "hook_teaser=true", "hookless_last=true",
            "short_variant=false", "hook_title=false", "seam_check=false", f"select={mode}"]
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False,
                           clips=1, llm="none", out=str(out), ac_over=opts) == 0
    draft = out.read_text(encoding="utf-8")
    assert "M1 60" in draft and "legacy" in draft
    assert "variant_not_reached" in draft
    assert not any(is_variant for _, is_variant in calls)  # no G2 when no spare slots


@pytest.mark.parametrize("mode", ["greedy", "global"])
def test_a8_fx1p_fake_provider_request_prefix_after_complete_legacy(tmp_path, monkeypatch, mode):
    """A8 may add provider requests only after all legacy title/rank requests."""
    from autoreels import __main__ as cli
    from autoreels.cloud import autocut as mod

    _cli_fx1(tmp_path)
    monkeypatch.setattr(cli, "_autocut_check", lambda _h, line, _r, _c:
                        (("legacy rejected", "") if "1.1" in line else (None, "")))

    class Fake:
        name = "fake"

        def __init__(self):
            self.calls = []

        def complete(self, messages, temperature=0.0):
            self.calls.append(messages)
            return "{}"

    def rank(pr, provider, **_kw):
        provider.complete([{"action": "rank", "piece": pr.pieces}])
        return False

    def plate(pr, provider, _text, **_kw):
        provider.complete([{"action": "title", "piece": pr.pieces}])
        pr.title = "plate " + pr.pieces
        return True

    monkeypatch.setattr(mod, "rank_hooks", rank)
    monkeypatch.setattr(mod, "headline", plate)
    monkeypatch.setattr(mod, "check_seams", lambda *args, **kw: None)
    opts = ["generator=passage", "loop=false", "prune=false", "short_variant=false",
            "target_sec=40", "min_sec=10", "max_sec=60", "hook_judge=false",
            "seam_check=false", "hook_title=true", "judge_cache=false", f"select={mode}"]

    def run(flag):
        fake = Fake()
        dest = tmp_path / "reviews" / f"fake_{flag}.txt"
        args = opts + (["seed_alt=true"] if flag else [])
        assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=True,
                               clips=2, llm="local", provider=fake, out=str(dest), ac_over=args) == 0
        return dest.read_text(encoding="utf-8"), fake.calls

    off, requests_off = run(False)
    on, requests_on = run(True)
    assert requests_off and requests_on[:len(requests_off)] == requests_off
    assert len(requests_on) > len(requests_off)
    def legacy_lines(s):
        return [x for x in s.splitlines() if x.startswith("# --- не прошли") or x.startswith("#! M")]
    assert legacy_lines(on) == legacy_lines(off)
    assert "variant_accepted" in on


@pytest.mark.parametrize("check", [False, True])
def test_a8_r4_dirty_repaired_variant_never_calls_context_judge(tmp_path, monkeypatch, check):
    """V1 sees the *finished* G2 refs: a backward-repaired host ref is fatal."""
    from autoreels import __main__ as cli
    from autoreels.cloud import autocut as mod, speakers
    from autoreels.cloud.autocut import Proposal

    project = _montage_project(tmp_path)
    host, answer = project["refs"][:2]
    monkeypatch.setattr(speakers, "load", lambda *_: object())
    monkeypatch.setattr(speakers, "other_refs", lambda *_: {host})
    judge_calls, provider_calls = [], []

    def context_judge(*args):
        judge_calls.append(args)
        return False, "непонятно"

    monkeypatch.setattr(mod, "make_judge", lambda *_a, **_kw: context_judge)

    class Fake:
        name = "fake"

        def complete(self, messages, temperature=0.0):
            provider_calls.append(messages)
            return "{}"

    def fake_propose(_units, _params, *_args, variant_descs_out=None, variant_descs=None, **kw):
        if variant_descs is None:
            if variant_descs_out is None:
                return []  # frozen weak-seed fill does not collect G1 descriptors
            assert kw.get("judge") is context_judge
            variant_descs_out.append((2, 0, (1,)))
            return [Proposal([1, 2], f"{host} {answer}", None, "legacy", "", 70, 44, opener=1)]
        assert kw.get("judge") is None  # R4: no live model inside G2
        variant = Proposal([1, 2], f"{host} {answer}", None, "dirty", "", 80, 44, opener=2)
        variant.alt_of, variant._alt_seed = 0, 2
        return [variant]

    monkeypatch.setattr(mod, "propose", fake_propose)
    if check:
        monkeypatch.setattr(cli, "_autocut_check", lambda *_: (None, ""))
    dest = tmp_path / "reviews" / "dirty.txt"
    opts = ["seed_alt=true", "interviewer=off", "context_start=true", "context_judge=true",
            "short_variant=false", "hook_judge=false", "seam_check=false", "hook_title=false"]
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=check,
                           clips=1, llm="local", provider=Fake(), out=str(dest), ac_over=opts) == 0
    assert "variant_interviewer" in dest.read_text(encoding="utf-8")
    assert not provider_calls and not judge_calls


@pytest.mark.parametrize("start_judge,expected", [("veto", "variant_rejected"),
                                                   ("rank", "variant_accepted")])
def test_a8_r4_clean_context_judge_does_not_rebuild_pieces(tmp_path, monkeypatch, start_judge, expected):
    from autoreels import __main__ as cli
    from autoreels.cloud import autocut as mod
    from autoreels.cloud.autocut import Proposal

    project = _montage_project(tmp_path)
    clean = project["refs"][0]
    observed, built = [], []

    def negative(text, following, core):
        observed.append((text, following, core))
        return False, "not on topic"

    monkeypatch.setattr(mod, "make_judge", lambda *_a, **_kw: negative)
    monkeypatch.setattr(mod, "rank_hooks", lambda *_a, **_kw: False)

    def fake_propose(_units, _params, *_args, variant_descs_out=None, variant_descs=None, **kw):
        if variant_descs is None:
            if variant_descs_out is None:
                return []
            variant_descs_out.append((1, 0, (2,)))
            return []
        built.append(kw.get("judge"))
        v = Proposal([1], clean, None, "clean", "clean", 60, 20, opener=1)
        v.alt_of, v._alt_seed = 0, 1
        return [v]

    monkeypatch.setattr(mod, "propose", fake_propose)

    class Fake:
        name = "fake"

        def complete(self, messages, temperature=0.0):
            raise AssertionError("no model completion needed for unhooked variant")

    dest = tmp_path / "reviews" / "clean.txt"
    opts = ["seed_alt=true", "context_start=true", "context_judge=true", f"start_judge={start_judge}",
            "short_variant=false", "hook_judge=false", "seam_check=false", "hook_title=false"]
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False,
                           clips=1, llm="local", provider=Fake(), out=str(dest), ac_over=opts) == 0
    content = dest.read_text(encoding="utf-8")
    assert expected in content
    assert built == [None] and len(observed) == 1
    if start_judge == "rank":
        assert any(line.startswith("M1 ") and clean in line for line in content.splitlines())


@pytest.mark.parametrize("check,with_provider", [(False, False), (True, False),
                                                 (False, True), (True, True)])
def test_a8_r4_empty_pool_clean_variant_polished_once(tmp_path, monkeypatch, check, with_provider):
    """Legacy may be empty; V1-clean alternatives still initialize one polish closure."""
    from autoreels import __main__ as cli
    from autoreels.cloud import autocut as mod
    from autoreels.cloud.autocut import Proposal

    project = _montage_project(tmp_path)
    clean = project["refs"][0]
    init_calls, complete_calls = [], []

    def fake_propose(_units, _params, *_args, variant_descs_out=None, variant_descs=None, **kw):
        if variant_descs is None:
            if variant_descs_out is None:
                return []
            variant_descs_out.append((1, 0, (2,)))
            return []
        v = Proposal([1], clean, None, "clean", "clean", 60, 20, opener=1)
        v.alt_of, v._alt_seed = 0, 1
        return [v]

    monkeypatch.setattr(mod, "propose", fake_propose)

    class Fake:
        name = "fake"

        def complete(self, messages, temperature=0.0):
            complete_calls.append(messages)
            return "{}"

    def rank(pr, provider, **kw):
        init_calls.append(pr.pieces)
        provider.complete([{"action": "rank", "pieces": pr.pieces}])
        return False

    monkeypatch.setattr(mod, "rank_hooks", rank)
    if check:
        monkeypatch.setattr(cli, "_autocut_check", lambda *_a: (None, ""))
    dest = tmp_path / "reviews" / "empty.txt"
    opts = ["seed_alt=true", "short_variant=false", "hook_judge=false",
            "hook_title=false", "seam_check=false"]
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=check,
                           clips=1, llm="local" if with_provider else "none",
                           provider=Fake() if with_provider else None, out=str(dest), ac_over=opts) == 0
    assert "variant_accepted" in dest.read_text(encoding="utf-8")
    assert init_calls == ([clean] if with_provider else [])
    assert len(complete_calls) == (1 if with_provider else 0)


def test_a8_v0_duplicate_descriptors_get_distinct_explicit_fates(tmp_path, monkeypatch):
    from autoreels import __main__ as cli
    from autoreels.cloud import autocut as mod
    from autoreels.cloud.autocut import Proposal

    proj = _montage_project(tmp_path)
    clean = proj["refs"][0]

    def fake_propose(_units, _params, *_args, variant_descs_out=None, variant_descs=None, **kw):
        if variant_descs is None:
            if variant_descs_out is not None:
                variant_descs_out.extend([(1, 0, (2,)), (2, 0, (1,))])
            return []
        generated = []
        for sid in (1, 2):
            v = Proposal([1], clean, None, "same", "same", 60, 20, opener=1)
            v.alt_of, v._alt_seed = 0, sid
            generated.append(v)
        return generated

    monkeypatch.setattr(mod, "propose", fake_propose)
    dest = tmp_path / "reviews" / "dups.txt"
    opts = ["seed_alt=true", "seed_alt_max=2", "hook_title=false", "seam_check=false",
            "short_variant=false"]
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False,
                           clips=1, llm="none", out=str(dest), ac_over=opts) == 0
    draft = dest.read_text(encoding="utf-8")
    assert draft.count("variant_accepted") == 1
    assert draft.count("duplicate") == 1
    assert len([line for line in draft.splitlines() if line.startswith("M")]) == 1
