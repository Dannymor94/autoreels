"""Offline M231 parity probe, executable with PYTHONPATH=<pinned source root>/src.

Runs frozen propose() with synthetic in-memory units. Prints only hashes and
callback logs; never calls a provider or writes user data.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json

from autoreels.cloud.autocut import AutoParams, propose


def _unit(i: int, t0: float, role: str, punch: int, refs: str) -> dict:
    return {
        "id": i, "t0": t0, "t1": t0 + 20.0, "role": role, "punch": punch,
        "refs": refs, "standalone": True, "refers": None, "topic": 1,
        "summary": f"мысль {i}", "similar": [],
        "missing": False, "filtered": "",
        "voice": {"energy": 50.0, "rate": 2.4},
    }


def main() -> None:
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
    proposals = propose(units, p, sentences, judge=judge, end_tone=end_tone, taste=taste)
    encoded = json.dumps([dataclasses.asdict(pr) for pr in proposals],
                         ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    cb = json.dumps(calls, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    print(json.dumps({"proposals_sha256": hashlib.sha256(encoded).hexdigest(),
                      "callbacks_sha256": hashlib.sha256(cb).hexdigest(),
                      "callback_counts": {name: len(log) for name, log in calls.items()},
                      "proposals": len(proposals)}, sort_keys=True))


if __name__ == "__main__":
    main()
