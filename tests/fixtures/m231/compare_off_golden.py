"""Offline M231 parity probe, executable with PYTHONPATH=<pinned source root>/src.

Runs frozen propose() with synthetic in-memory units. Prints only hashes and
callback logs; never calls a provider or writes user data.
"""
from __future__ import annotations

import dataclasses
import argparse
import contextlib
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import autoreels
import autoreels.cloud.autocut as ac
from autoreels.cloud.autocut import AutoParams, propose


def _unit(i: int, t0: float, role: str, punch: int, refs: str) -> dict:
    return {
        "id": i, "t0": t0, "t1": t0 + 20.0, "role": role, "punch": punch,
        "refs": refs, "standalone": True, "refers": None, "topic": 1,
        "summary": f"мысль {i}", "similar": [],
        "missing": False, "filtered": "",
        "voice": {"energy": 50.0, "rate": 2.4},
    }


def _sha(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _frozen_preflight() -> None:
    """Fail closed before generating a supposedly immutable production golden."""
    repo = Path.cwd().resolve()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=repo, text=True)
    source = Path(autoreels.__file__).resolve()
    expected = "3c011e94263e16e5780936b4769d3490cd03b682"
    print(f"FROZEN_PREFLIGHT HEAD={head} SOURCE={source} CLEAN={not status}", file=sys.stderr)
    if head != expected or status or not source.is_relative_to(repo / "src"):
        raise RuntimeError("frozen golden requires clean production HEAD and imports")


def _coverage_case(name: str):
    one = {**_unit(1, 0.0, "thesis", 5, "1.1"), "t1": 30.0}
    two = {**_unit(2, 35.0, "thesis", 4, "2.1"), "t1": 65.0}
    cases = {
        "pooled": ([one], AutoParams(clips=1, generator="montage", rhythm=False,
                 prune=False, context_start=False), {}, {"pooled"}),
        "build_none": ([one], AutoParams(clips=1, generator="montage"),
                       {"build_clip": lambda *a, **kw: None}, {"build_none"}),
        "skip_used": ([one, two], AutoParams(clips=2, generator="montage", rhythm=False,
                      prune=False, context_start=False, overlap_max=1.0),
                      {"build_clip": lambda *a, **kw: [one, two]}, {"pooled", "skip_used"}),
        "skip_taken": ([one, {**two, "role": "explanation"}],
                       AutoParams(clips=3, generator="passage", rhythm=False,
                                  context_start=False, overlap_max=1.0,
                                  seed_roles=("thesis", "explanation")),
                       {"build_passage": lambda *a, **kw: [one, {**two, "role": "explanation"}]},
                       {"pooled", "skip_taken"}),
        "rhythm_fail": ([one], AutoParams(clips=1, generator="montage", rhythm=True,
                         prune=False, context_start=False),
                        {"fit_rhythm": lambda *a, **kw: (None, ["rhythm"])},
                        {"rhythm_fail"}),
        "start_fail": ([one], AutoParams(clips=1, generator="montage", rhythm=False,
                        prune=False, context_start=True),
                       {"context_start": lambda *a, **kw: (None, [], "no context")},
                       {"start_fail"}),
        "open_end_fail": ([one], AutoParams(clips=1, generator="montage", rhythm=False,
                           prune=False, context_start=False, end_tone=True),
                          {"fix_open_end": lambda *a, **kw: (None, "", "→")},
                          {"open_end_fail"}),
        "final_rhythm_fail": ([one], AutoParams(clips=1, generator="montage", rhythm=True,
                              prune=False, context_start=False),
                             {"fit_rhythm": lambda clip, *a, **kw: (clip, []),
                              "rhythm_why": lambda *a, **kw: ("rhythm", None)},
                             {"final_rhythm_fail"}),
        "taken_after_context": ([one, two], AutoParams(clips=3, generator="passage",
                                rhythm=False, context_start=True, overlap_max=1.0),
                               {"build_passage": lambda seed, *a, **kw: [one] if seed["id"] == 1 else [two],
                                "context_start": lambda clip, *a, **kw: ([one, two], [], "")
                                if clip[0]["id"] == 2 else (clip, [], "")},
                               {"pooled", "taken_after_context"}),
        "overlap_or_payoff": ([one, two], AutoParams(clips=3, generator="montage",
                              rhythm=False, prune=False, context_start=False, overlap_max=0.0),
                             {"build_clip": lambda *a, **kw: [one]},
                             {"pooled", "overlap_or_payoff"}),
        "passage_rhythm": ([one, {**two, "role": "example"},
                            _unit(3, 55.0, "conclusion", 3, "3.1")],
                           AutoParams(clips=3, generator="passage", rhythm=True,
                                      target_sec=55, max_sec=90, min_sec=25,
                                      context_start=False), {}, None),
        # build_clip yields a non-question opener [1] so propose's loop guard
        # fires; _loop_question returns the question (id 2, punch 3 < seed_punch
        # so it is not itself a seed) → it is prepended: S0=[1], S1=[2,1], pooled.
        "loop_question": ([one, {**two, "role": "question", "punch": 3}],
                          AutoParams(clips=2, generator="montage", loop=True,
                                     rhythm=False, prune=False, context_start=False),
                          {"build_clip": lambda *a, **kw: [one],
                           "_loop_question": lambda *a, **kw: {**two, "role": "question", "punch": 3}},
                          {"pooled"}),
    }
    if name == "fx7l":
        fixture = Path(__file__).with_name("fx7l_units.json")
        units = json.loads(fixture.read_text(encoding="utf-8"))["units"]
        return (units, AutoParams(clips=2, generator="montage", rhythm=False,
                                  prune=False, context_start=True, min_sec=1,
                                  target_sec=30),
                {"context_start": lambda clip, *a, **kw: ([u for u in clip if u["id"] != 10]
                                                       or clip, [], "")}, None)
    return cases[name]


def _coverage(*, trace_on: bool) -> dict:
    names = ("pooled", "build_none", "skip_used", "skip_taken", "rhythm_fail",
             "start_fail", "open_end_fail", "final_rhythm_fail", "taken_after_context",
             "overlap_or_payoff", "passage_rhythm", "loop_question", "fx7l")
    results = {}
    for name in names:
        units, params, patches, expected = _coverage_case(name)
        calls: list = []

        def sentences(refs):
            calls.append(["sentences", copy.deepcopy(refs)])
            return [(str(refs).split()[0], 8.0, 7, True,
                     "Практика помогает каждому человеку каждый день")]

        def judge(text, following, core):
            calls.append(["judge", copy.deepcopy([text, following, core])])
            return True, ""

        def end_tone(ref):
            calls.append(["end_tone", copy.deepcopy(ref)])
            return "open" if name == "open_end_fail" else "final"

        def taste(clip):
            calls.append(["taste", copy.deepcopy(clip)])
            return 0.0

        trace = [] if trace_on else None
        with contextlib.ExitStack() as stack:
            for symbol, substitute in patches.items():
                stack.enter_context(patch.object(ac, symbol, substitute))
            kwargs = {"trace": trace} if trace_on else {}
            proposed = propose(units, params, sentences, judge=judge, end_tone=end_tone,
                               taste=taste, **kwargs)
        if trace_on and expected is not None:
            observed = {ev["outcome"] for ev in trace if ev["event"] == "seed"}
            if observed != expected:
                raise AssertionError(f"{name}: expected {expected}, observed {observed}")
        if trace_on and any(ev["proxy_overlong_side"] is not None
                            for ev in trace if ev["event"] == "seed"):
            raise AssertionError(f"{name}: proxy_overlong_side not null")
        if trace_on and name == "fx7l" and not any(
                ev["event"] == "seed" and ev["dep_broken"] == [[11, 10, "S5"]]
                for ev in trace):
            raise AssertionError("fx7l: expected S5 dependency loss")
        results[name] = {"proposals_sha256": _sha([dataclasses.asdict(pr) for pr in proposed]),
                         "callbacks_sha256": _sha(calls),
                         "callback_count": len(calls), "proposals": len(proposed)}
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-on", action="store_true")
    parser.add_argument("--frozen-only", action="store_true")
    args = parser.parse_args()
    if args.frozen_only:
        _frozen_preflight()
    units = [
        _unit(1, 0.0, "thesis", 5, "1.1"),
        _unit(2, 25.0, "example", 4, "1.2"),
        _unit(3, 50.0, "conclusion", 5, "1.3"),
    ]
    calls: dict[str, list] = {"sentences": [], "end_tone": [], "judge": [], "taste": []}

    def sentences(refs: str):
        calls["sentences"].append(refs)
        return [(refs.split()[0], 8.0, 7, True, "Практика помогает каждому человеку каждый день")]

    def end_tone(ref: str):
        calls["end_tone"].append(ref)
        return "final"

    def judge(text: str, following: str, core: str):
        calls["judge"].append([text, following, core])
        return True, ""

    def taste(clip: list[dict]):
        calls["taste"].append([u["id"] for u in clip])
        return 0.0

    p = AutoParams(clips=3, generator="montage", context_start=True, rhythm=False,
                   prune=False, min_sec=1.0, end_tone=True, taste_weight=1.0,
                   context_min_words=1)
    proposals = propose(units, p, sentences, judge=judge, end_tone=end_tone, taste=taste,
                        **({"trace": []} if args.trace_on else {}))
    encoded = json.dumps([dataclasses.asdict(pr) for pr in proposals],
                         ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    cb = json.dumps(calls, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    print(json.dumps({"proposals_sha256": hashlib.sha256(encoded).hexdigest(),
                      "callbacks_sha256": hashlib.sha256(cb).hexdigest(),
                      "callback_counts": {name: len(log) for name, log in calls.items()},
                      "proposals": len(proposals),
                      "coverage": _coverage(trace_on=args.trace_on)}, sort_keys=True))


if __name__ == "__main__":
    main()
