#!/usr/bin/env python3
"""M224 Stage A — CLI-path evidence for findings #5 and #6.

Finding #5: context_start short-drop has no min_sec recheck.
Finding #6: boundary drift (t0/t1) when a sentence is dropped across a pause gap.

Config loaded from production config/r0.yaml via load_r0_config.
AutoParams built exactly as cmd_autocut does (__main__.py lines 8609-8634).
No paid APIs, no rendering, no writes to owner artifacts.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # autoreels-m223
sys.path.insert(0, str(ROOT / "src"))

from autoreels.core.config import load_r0_config
from autoreels.cloud.autocut import (
    AutoParams, context_start, fix_open_end, propose, _dur,
)

CHECK_COUNTER = [0]
FAIL_COUNT = [0]


def check(label, cond, expected=None, actual=None):
    CHECK_COUNTER[0] += 1
    n = CHECK_COUNTER[0]
    if cond:
        print(f"  PASS [{n:02d}] {label}")
    else:
        FAIL_COUNT[0] += 1
        exp_str = f" | expected {expected!r}" if expected is not None else ""
        act_str = f" | got {actual!r}" if actual is not None else ""
        print(f"  FAIL [{n:02d}] {label}{exp_str}{act_str}")


# ─── §0  Production config ──────────────────────────────────────────────────

print("\n§0 — Production config (config/r0.yaml)\n")

r0_cfg = load_r0_config(ROOT / "config" / "r0.yaml")
ac = r0_cfg.autocut

check("§0-a  r0.yaml loaded (autocut block present)", ac is not None)
check("§0-b  min_sec=25",          ac.min_sec == 25,        25,    ac.min_sec)
check("§0-c  context_start=True",  ac.context_start is True, True, ac.context_start)
check("§0-d  context_drop_words=5", ac.context_drop_words == 5, 5, ac.context_drop_words)
check("§0-e  context_min_words=4",  ac.context_min_words == 4, 4, ac.context_min_words)
check("§0-f  context_later=False",  ac.context_later is False, False, ac.context_later)
check("§0-g  end_tone=True",        getattr(ac, "end_tone", False) is True, True, getattr(ac, "end_tone", None))

# Build AutoParams exactly as cmd_autocut does (mirroring __main__.py 8609-8634)
prm = AutoParams(
    min_sec=ac.min_sec,
    target_sec=ac.target_sec,
    max_sec=ac.max_sec,
    max_pieces=ac.max_pieces,
    min_punch=ac.min_punch,
    seed_punch=ac.seed_punch,
    hook_max_sec=getattr(r0_cfg, "hook_max_sec", 6.0),
    hook_min_words=ac.hook_min_words,
    overlap_max=ac.overlap_max,
    use_filtered=ac.use_filtered,
    loop=ac.loop,
    loop_max_sec=ac.loop_max_sec,
    prune=ac.prune,
    prune_slack=ac.prune_slack,
    hook_min_sec=ac.hook_min_sec,
    speed_slow_rate=ac.speed_slow_rate,
    speed_slow=ac.speed_slow,
    speed_mid_rate=ac.speed_mid_rate,
    speed_mid=ac.speed_mid,
    context_start=ac.context_start,
    context_max_sec=ac.context_max_sec,
    context_drop_words=ac.context_drop_words,
    context_min_words=ac.context_min_words,
    context_back=ac.context_back,
    context_later=ac.context_later,
    context_later_min_sec=ac.context_later_min_sec,
    hook_teaser=ac.hook_teaser,
    hook_teaser_pos=ac.hook_teaser_pos,
    hook_no_pointer=ac.hook_no_pointer,
    close_last=ac.close_last,
    close_last_sec=ac.close_last_sec,
    end_tone=getattr(ac, "end_tone", False),
    generator=ac.generator,
    seed_roles=tuple(ac.seed_roles),
    passage_gap_sec=ac.passage_gap_sec,
    start_judge=ac.start_judge,
    lean_depth=ac.lean_depth,
    rhythm=ac.rhythm,
    max_jumps=ac.rhythm_max_jumps,
    jump_sec=ac.rhythm_jump_sec,
    settle_near_sec=ac.rhythm_settle_near,
    settle_far_sec=ac.rhythm_settle_far,
    settle_far_at_sec=ac.rhythm_far_sec,
    settle_tail=ac.rhythm_tail,
    taste_weight=getattr(ac, "taste_weight", 0.0),
    start_pause_min=float(getattr(ac, "start_pause_min", 0.0) or 0.0),
    hook_clauses=bool(getattr(ac, "hook_clauses", False)),
    hook_clause_pause=float(getattr(ac, "hook_clause_pause", 0.12)),
    start_strict=bool(getattr(ac, "start_strict", False)),
    start_extend_max=int(getattr(ac, "start_extend_max", 2)),
    answer_start=bool(getattr(ac, "answer_start", False)),
    answer_gap_sec=float(getattr(ac, "answer_gap_sec", 3.0)),
    start_morph=bool(getattr(ac, "start_morph", False)),
)

check("§0-h  prm.min_sec=25",          prm.min_sec == 25,     25,    prm.min_sec)
check("§0-i  prm.context_start=True",  prm.context_start,     True,  prm.context_start)
check("§0-j  prm.context_drop_words=5", prm.context_drop_words == 5, 5, prm.context_drop_words)
check("§0-k  prm.context_min_words=4",  prm.context_min_words == 4,  4, prm.context_min_words)
check("§0-l  prm.context_later=False",  prm.context_later is False,  False, prm.context_later)
check("§0-m  prm.end_tone=True",        prm.end_tone is True,  True,  prm.end_tone)


# ─── §1  Finding #5 — min_sec under-count after context_start short-drop ───

print("\n§1 — Finding #5: min_sec not rechecked after context_start short-drop\n")

# Scenario: single thought, t0=0.0 t1=25.0 → _dur=25.0 = min_sec exactly.
# Sentence 1.1: 2.0 s, 1 plain word ("Уйти.") → stands_alone → "обрывок (1 сл.)", nwords=1 ≤ context_drop_words=5
# Sentence 1.2: 23.0 s, 6 words → passes stands_alone
# No pause gap in this scenario (gap = 0s, all 25s attributed to both sentences together).
# After short-drop: t0 += 2.0 → new _dur = 23.0 < min_sec=25.0

UNIT_A = {
    "id": 1, "t0": 0.0, "t1": 25.0,
    "refs": "1.1-2",
    "role": "thesis", "punch": 5,
    "summary": "Принятие тревоги снижает её интенсивность.",
    "topic": "тревога", "standalone": True,
}
BY_ID_A = {1: UNIT_A}

SENT_A = {
    "1.1": ("1.1", 2.0,  1,  True, "Уйти."),
    "1.2": ("1.2", 23.0, 6,  True, "Принятие тревоги снижает интенсивность переживаний навсегда."),
}


def _parse_refs(refs: str):
    """Parse "1.1-2" → [("1",1,1), ("1",2,2)]; "1.2" → [("1",2,2)]."""
    result = []
    for piece in refs.split():
        b, _, r = piece.partition(".")
        a, _, z = r.partition("-")
        ai, zi = int(a), int(z or a)
        for k in range(ai, zi + 1):
            result.append(f"{b}.{k}")
    return result


def sentences_A(refs):
    for ref in _parse_refs(refs):
        if ref in SENT_A:
            yield SENT_A[ref]


clip_before = [UNIT_A]
dur_before = _dur(UNIT_A)
check("§1-a  clip before context_start: _dur=25.0 ≥ min_sec=25",
      dur_before == 25.0, 25.0, dur_before)

clip2, notes, why = context_start(clip_before, BY_ID_A, prm, sentences_A, seed_id=1)

check("§1-b  context_start returned a clip (not None)",
      clip2 is not None, "clip", why)

dur_after = _dur(clip2[0]) if clip2 else None
check("§1-c  new t0 = 0.0 + 2.0 = 2.0 (shifted by sentence-1 duration only)",
      clip2 is not None and abs(float(clip2[0]["t0"]) - 2.0) < 0.01,
      2.0, float(clip2[0]["t0"]) if clip2 else None)

check("§1-d  new t1 unchanged = 25.0",
      clip2 is not None and abs(float(clip2[0]["t1"]) - 25.0) < 0.01,
      25.0, float(clip2[0]["t1"]) if clip2 else None)

check("§1-e  new _dur = 23.0 < min_sec=25.0 (FINDING #5: no recheck)",
      dur_after is not None and dur_after == 23.0,
      23.0, dur_after)

check("§1-f  refs updated to '1.2' (first sentence dropped)",
      clip2 is not None and clip2[0]["refs"] == "1.2",
      "1.2", clip2[0]["refs"] if clip2 else None)

drop_note = any("убрана фраза" in n for n in notes)
check("§1-g  context_start note confirms first sentence dropped",
      drop_note, True, drop_note)

print(f"  INFO  notes: {notes}")

# §1 propose() full path: clip emitted with seconds < min_sec
# Need generator="passage" to avoid add_payoff complexity; override for this sub-test.
prm_simple = AutoParams(
    min_sec=prm.min_sec, target_sec=prm.target_sec, max_sec=prm.max_sec,
    max_pieces=prm.max_pieces, min_punch=prm.min_punch, seed_punch=prm.seed_punch,
    context_start=prm.context_start, context_drop_words=prm.context_drop_words,
    context_min_words=prm.context_min_words, context_later=prm.context_later,
    end_tone=False,  # skip fix_open_end for this sub-test
    generator="passage",  # single unit passage, no add_payoff
    loop=False, prune=False, rhythm=False,
    hook_teaser=False, hook_min_sec=1.5, hook_max_sec=6.0, hook_min_words=4,
    start_pause_min=0.0,  # no start_pause callback
    start_strict=False, answer_start=False, start_morph=False,
    hook_clauses=False,
)

no_start: list = []
proposals = propose([UNIT_A], prm_simple, sentences=sentences_A, no_start=no_start)

check("§1-h  propose() emitted ≥ 1 clip despite _dur < min_sec after context_start",
      len(proposals) >= 1, "≥1 proposals", len(proposals))

if proposals:
    p1 = proposals[0]
    check("§1-i  emitted clip seconds = 23.0 (< min_sec=25.0 — CONFIRMED: no recheck)",
          abs(p1.seconds - 23.0) < 0.1, 23.0, p1.seconds)
    check("§1-j  emitted clip units contains unit id=1",
          1 in p1.units, True, p1.units)
    print(f"  INFO  proposal: {p1.line('1')} | seconds={p1.seconds}")

check("§1-k  no_start list is empty (clip was not rejected by context_start)",
      len(no_start) == 0, 0, len(no_start))


# ─── §2  Finding #6 (end case) — fix_open_end t1 drift across pause gap ────

print("\n§2 — Finding #6 (end case): fix_open_end includes pause gap in t1\n")

# Scenario: single thought, t0=0.0 t1=31.0.
# Sentence 1.1: sec=24.0 s — the SENTENCE duration only (actual audio 0–24s).
# Pause: 24–28s (4s gap NOT captured in sec).
# Sentence 1.2: sec=3.0 s (actual audio 28–31s) — ends "→" (open tone).
# fix_open_end: cut += rows[1][1] = 3.0 → new_last.t1 = 31.0 - 3.0 = 28.0
# Actual last audible word: 24.0s. Drift = 28.0 - 24.0 = 4.0s of silence included.
# Note: total_clip - cut = 31.0 - 3.0 = 28.0 ≥ min_sec=25.0, so min_sec check passes.

UNIT_B = {
    "id": 1, "t0": 0.0, "t1": 31.0,
    "refs": "1.1-2",
    "role": "thesis", "punch": 5,
    "summary": "Принятие тревоги снижает её интенсивность.",
    "topic": "тревога", "standalone": True,
}

SENT_B = {
    "1.1": ("1.1", 24.0, 10, True,  "Принятие тревоги снижает интенсивность переживаний."),
    "1.2": ("1.2",  3.0,  6, True,  "Нас ждёт новый опыт постоянного роста."),
}


def sentences_B(refs):
    for ref in _parse_refs(refs):
        if ref in SENT_B:
            yield SENT_B[ref]


def end_tone_B(ref: str):
    return "open" if ref == "1.2" else "final"


dur_B = _dur(UNIT_B)
total_B = dur_B
check("§2-a  unit _dur=31.0, min_sec=25.0 → ≥ min_sec",
      dur_B == 31.0, 31.0, dur_B)

# verify min_sec guard in fix_open_end passes (total - cut ≥ min_sec)
cut_expected = 3.0  # sec of sentence 1.2
check("§2-b  total_clip - cut = 31.0 - 3.0 = 28.0 ≥ min_sec=25.0 (guard passes)",
      (total_B - cut_expected) >= prm.min_sec, "≥25.0", total_B - cut_expected)

result_clip, note, why_gone = fix_open_end([UNIT_B], sentences_B, end_tone_B, prm)

check("§2-c  fix_open_end returned a clip (not None — min_sec guard passed)",
      result_clip is not None, "clip", why_gone)

check("§2-d  note is not None (sentence 1.2 was removed)",
      note is not None, "note", note)

if result_clip:
    new_last = result_clip[-1]
    t1_actual = float(new_last["t1"])
    expected_t1 = 28.0   # 31.0 - 3.0 (only sentence duration, not pause)
    actual_last_word_end = 24.0  # actual audio of sentence 1.1 ends here
    drift = t1_actual - actual_last_word_end

    check("§2-e  new_last.t1 = 28.0 (31.0 - sec_1.2=3.0, pause NOT deducted)",
          abs(t1_actual - expected_t1) < 0.01, expected_t1, t1_actual)

    check("§2-f  FINDING #6: drift = t1 - last_audible_word_end = 4.0 s (silence included)",
          abs(drift - 4.0) < 0.01, 4.0, drift)

    check("§2-g  new refs end at 1.1 (sentence 1.2 removed)",
          new_last["refs"] == "1.1", "1.1", new_last["refs"])

    print(f"  INFO  t1 set to {t1_actual:.1f}s; actual last audio ends at {actual_last_word_end:.1f}s; "
          f"drift={drift:.1f}s of silence included in t1")
    print(f"  INFO  note: {note}")


# ─── §3  Finding #6 (start case) — context_start t0 drift across pause gap ─

print("\n§3 — Finding #6 (start case): context_start t0 set to end-of-dropped-sentence, skips pause\n")

# Scenario: single thought, t0=0.0 t1=29.0.
# Sentence 1.1: sec=2.0 s (audio 0–2s), 1 word → stands_alone fails → short-drop.
# Pause: 2–6s (4s gap NOT captured in sec).
# Sentence 1.2: sec=23.0 s (audio 6–29s) → stands alone.
# context_start short-drop: t0 += rows[0][1] = 2.0 → new t0 = 2.0
# Actual first audio of retained sentence 1.2: 6.0s. Drift = 6.0 - 2.0 = 4.0s of silence.
# Note: new _dur = 29.0 - 2.0 = 27.0 ≥ min_sec=25.0 (this scenario passes min_sec).

UNIT_C = {
    "id": 1, "t0": 0.0, "t1": 29.0,
    "refs": "1.1-2",
    "role": "thesis", "punch": 5,
    "summary": "Принятие тревоги снижает её интенсивность.",
    "topic": "тревога", "standalone": True,
}
BY_ID_C = {1: UNIT_C}

SENT_C = {
    "1.1": ("1.1", 2.0,  1,  True, "Уйти."),
    "1.2": ("1.2", 23.0, 6,  True, "Принятие тревоги снижает интенсивность переживаний навсегда."),
}


def sentences_C(refs):
    for ref in _parse_refs(refs):
        if ref in SENT_C:
            yield SENT_C[ref]


dur_C = _dur(UNIT_C)
check("§3-a  unit _dur=29.0 ≥ min_sec=25.0",
      dur_C == 29.0, 29.0, dur_C)

clip_C2, notes_C, why_C = context_start([UNIT_C], BY_ID_C, prm, sentences_C, seed_id=1)

check("§3-b  context_start returned a clip",
      clip_C2 is not None, "clip", why_C)

if clip_C2:
    new_t0 = float(clip_C2[0]["t0"])
    new_dur = _dur(clip_C2[0])

    # What the code sets t0 to:
    # clip = [{**u, "t0": float(u["t0"]) + float(rows[0][1])}] + clip[1:]
    # rows[0][1] = sec of sentence 1.1 = 2.0 (the sentence duration, NOT the full gap to 1.2)
    expected_t0_code = 0.0 + 2.0   # = 2.0 (end of sentence 1.1)
    actual_audio_start_1_2 = 6.0   # actual start of sentence 1.2 (after 4s pause)
    drift_start = actual_audio_start_1_2 - new_t0  # = 4.0s

    check("§3-c  new t0 = 2.0 (end of sentence 1.1 duration only, pause not included)",
          abs(new_t0 - expected_t0_code) < 0.01, expected_t0_code, new_t0)

    check("§3-d  FINDING #6 (start): actual audio of 1.2 starts at 6.0s, t0=2.0 → drift=4.0s",
          abs(drift_start - 4.0) < 0.01, 4.0, drift_start)

    check("§3-e  new _dur = 29.0 - 2.0 = 27.0 (passes min_sec=25.0 — no FINDING #5 here)",
          abs(new_dur - 27.0) < 0.01, 27.0, new_dur)

    check("§3-f  refs updated to '1.2'",
          clip_C2[0]["refs"] == "1.2", "1.2", clip_C2[0]["refs"])

    print(f"  INFO  t0 set to {new_t0:.1f}s; actual 1.2 audio starts at {actual_audio_start_1_2:.1f}s; "
          f"drift={drift_start:.1f}s of silence attributed to clip start")


# ─── §4  Combined scenario — #5 AND #6 together ─────────────────────────────

print("\n§4 — Combined: #5 + #6 (start): t0 drift AND resulting dur < min_sec\n")

# Most impactful scenario: 2.0s sentence, 4.0s pause, 23.0s sentence = t1=29.0
# Short-drop: t0 += 2.0 → new t0=2.0, new _dur = 29.0 - 2.0 = 27.0 ≥ 25.0 (no #5 here)
#
# For #5 to co-occur with #6 (start): need dropped_duration + pause to push under min_sec.
# Example: 2.0s sentence + 4.0s pause + 20.0s sentence = t1=26.0
# Short-drop: t0 += 2.0 → new t0=2.0, new _dur = 26.0 - 2.0 = 24.0 < min_sec=25.0
# AND t0=2.0 while audio starts at 6.0 (4s drift).

UNIT_D = {
    "id": 1, "t0": 0.0, "t1": 26.0,
    "refs": "1.1-2",
    "role": "thesis", "punch": 5,
    "summary": "Принятие тревоги снижает её интенсивность.",
    "topic": "тревога", "standalone": True,
}
BY_ID_D = {1: UNIT_D}

SENT_D = {
    "1.1": ("1.1", 2.0,  1,  True, "Уйти."),
    "1.2": ("1.2", 20.0, 6,  True, "Принятие тревоги снижает интенсивность переживаний навсегда."),
}


def sentences_D(refs):
    for ref in _parse_refs(refs):
        if ref in SENT_D:
            yield SENT_D[ref]


# build_passage would see _dur=26.0 ≥ min_sec=25.0 → passes initial gate
dur_D = _dur(UNIT_D)
check("§4-a  pre-context _dur=26.0 ≥ min_sec=25.0 (passes initial build gate)",
      dur_D == 26.0, 26.0, dur_D)

clip_D2, notes_D, why_D = context_start([UNIT_D], BY_ID_D, prm, sentences_D, seed_id=1)

check("§4-b  context_start succeeded (clip returned)",
      clip_D2 is not None, "clip", why_D)

if clip_D2:
    new_t0_D = float(clip_D2[0]["t0"])
    new_dur_D = _dur(clip_D2[0])
    actual_audio_start_D = 6.0   # 1.2 starts at 2.0+4.0=6.0s

    check("§4-c  new t0=2.0 (end-of-sentence-1 only, pause 2–6s omitted)",
          abs(new_t0_D - 2.0) < 0.01, 2.0, new_t0_D)

    check("§4-d  new _dur = 24.0 < min_sec=25.0 (FINDING #5 — no recheck)",
          abs(new_dur_D - 24.0) < 0.01, 24.0, new_dur_D)

    check("§4-e  FINDING #6 start: actual 1.2 audio at 6.0s, t0=2.0 → 4.0s drift",
          abs(actual_audio_start_D - new_t0_D - 4.0) < 0.01, 4.0,
          actual_audio_start_D - new_t0_D)

    print(f"  INFO  combined: t0={new_t0_D:.1f}s (drift=4.0s) AND _dur={new_dur_D:.1f}s < min_sec=25.0")

# Verify this also passes through propose() without rejection
proposals_D = propose([UNIT_D], prm_simple, sentences=sentences_D, no_start=[])

check("§4-f  propose() emits clip with dur<min_sec (finding #5 confirmed in propose path)",
      len(proposals_D) >= 1, "≥1", len(proposals_D))

if proposals_D:
    print(f"  INFO  proposal seconds={proposals_D[0].seconds} (expected ~24.0, min_sec=25.0)")
    check("§4-g  emitted seconds ≈ 24.0 (< min_sec=25.0 — CONFIRMED in propose)",
          abs(proposals_D[0].seconds - 24.0) < 0.1, 24.0, proposals_D[0].seconds)


# ─── §5  Summary ─────────────────────────────────────────────────────────────

print(f"\n§5 — Summary\n")
print(f"  config: config/r0.yaml (SHA256 efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba)")
print(f"  total check() calls: {CHECK_COUNTER[0]}")
print(f"  failures: {FAIL_COUNT[0]}")
print()
print("  Finding #5 (CONFIRMED via CLI-config path):")
print("    context_start short-drop (line 718): t0 += rows[0][1] = sentence duration only.")
print("    No min_sec recheck in short-drop branch (unlike context_later at line 749).")
print("    propose() emits clip with seconds < min_sec without rejection.")
print()
print("  Finding #6 end (CONFIRMED via CLI-config path):")
print("    fix_open_end (line 640): cut += rows[k][1] = sentence duration only.")
print("    With pause between sentences: t1 set to end-of-dropped-sentence, not end-of-kept-sentence.")
print("    Example: 1.1 ends at 24s, pause 24–28s, 1.2 at 28–31s → new_last.t1=28.0 (4s drift).")
print()
print("  Finding #6 start (CONFIRMED via CLI-config path):")
print("    context_start short-drop (line 718): t0 += rows[0][1] = sentence duration only.")
print("    With pause before next sentence: t0 set to end-of-dropped-sentence, not start-of-kept-sentence.")
print("    Example: 1.1 ends at 2s, pause 2–6s, 1.2 starts at 6s → new t0=2.0 (4s drift).")

if FAIL_COUNT[0] > 0:
    print(f"\nEXIT 1 — {FAIL_COUNT[0]} check(s) FAILED")
    sys.exit(1)

print(f"\nPASS: {CHECK_COUNTER[0]} checks, 0 failures — three evidence items CONFIRMED.")
sys.exit(0)
