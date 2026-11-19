# M227 · Independent Sol 6.1 Stage A review

**VERDICT: PASS_SCOPED** — 2026-11-19. `STOP_REPEATING=yes`. This is acceptance of bounded diagnostics, **not authorization for production changes**.

- `BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682`
- `EVIDENCE_SHA=929646319dc55b5d6dc62f6321582bf20622cc09` (pinned; handoff branch is an evidence-only orphan branch)
- `CONFIG_SHA256=efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba`
- `REPRO.py` Git blob `3ee7281e3b4dde98114037dfb466df2e70d803c5`, SHA256 `e4da7f546b5b21deef4dfef8c4ab837d168b76ce747963cc257f551b04d4440e`
- `REPORT.md` Git blob `b11dc765eb3c5cc800a29ab61f941a9564bf78d9`, SHA256 `5cd4bd4f578f8691ea34fbfe4a7f735f8d1b6a0e95650467d62075754e4e91e5`
- Published stdout SHA256 `e9a7bdf64d4984f87a7267a585e41429160c5394cd4bc8217ecdb9e57e6faf08`
- Published stderr SHA256 `dc36f1c8d97fd0680af6d12348507badf832426514e43fc79ac5a52bb4bf64c6`

## Independent replay

Sol 6.1 assembled the exact main production archive and the pinned handoff repro in an isolated directory `/tmp/sol-m227-9296463`. Executed with **Python 3.12.14**: **exit 0; 27 PASS; 0 FAIL**. No paid API, models, full rendering, owner media, or production changes. This independent result verifies observed exit zero; it is not a historical receipt for the original author's Python 3.11 run.

## What is accepted

1. **CLI_CONFIRMED (bounded):** original `cmd_autocut(..., llm="none")` completes and writes synthetic review proposals. Map A yields one M-line; Map B yields one M-line.
2. **MANUAL_ACCOUNTING + CLI_OUTPUT:** evaluator reconstructs eligible seeds A=1 and B=2, while each CLI review has one proposal line. This proves an output/accounting gap in the synthetic scenario; it does **not** instrument every seed attempt, pool insert, validator, or final rendered video.
3. **HELPER_CONFIRMED:** original `build_passage` directly returns None for the isolated too-short Map B seed.
4. **HELPER_CONFIRMED with synthetic callback:** `teaser_misses` reports `{'прошла': 1}` for `2.1`, whereas original `_hook_cands` rejects with `start_pause=0.05` under `start_pause_min=0.15`; without callback it accepts. Independently verified `teaser_pointer("Главная мысль теста здесь.") is None`.
5. **STATIC_CONFIRMED:** weak-seed `propose` call omits `no_start` and `open_end`, discards `rhythm_out=[]`; diagnostic `teaser_misses` lacks `start_pause` / `clauses` parameters.

## Hard limits and corrections

- The 12 prepool gates form a **static grouped inventory**, not 12 triggered scenarios (table has 11 grouped rows). No evidence that each `None` is a defect.
- No transparent CLI spies identify the exact rejected seed, failure boundary, fill attempts, final selected IDs, or validation outcome. Review M-lines are proposals, **not measured pool or validated video entries**.
- The teaser discrepancy is **HELPER_ONLY**. The actual CLI fixture lacks alignment/prosody; no live CLI mismatch or clauses-rescue was demonstrated.
- Synthetic sentence text has four words though callback metadata says `nwords=6`. With `hook_min_words=4` this does not change the demonstrated outcome, but remains a fixture limitation.
- `evidence.json` references `repro.exit`, which **is missing from the published tree**. Published stdout/stderr hash checks pass. Independent exit0 does not make that manifest complete.
- No negative subprocess tests, end-to-end render, real media playback, or production impact were measured. The partially copied `AutoParams` helper is not proof of all CLI settings.

**M228 disposition:** Treat finding #11 as **observability-first**: CLI proposal count gap and a scoped teaser diagnostic mismatch exist; precise rejection accounting, user impact and final pipeline behavior remain unverified. Do not rerun M227 solely to enlarge claims. M228 is a distinct consolidation stage and requires its own independent Sol gate before any algorithm code change.
