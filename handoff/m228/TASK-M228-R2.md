# TASK M228-R2 — Targeted correction after independent Sol review

**Executor:** Claude Code Sonnet 4.6. **Reviewer:** independent Sol 6.1. **Coordinator:** ChatGPT. **STATUS=READY_FOR_EXECUTION (docs only).**

Read `handoff/m228/SOL-REVIEW-R1.md` first. Correct the exact P1 contradictions in the four M228 Markdown deliverables. This is a **bounded first correction**, not a new M223–M227 diagnostics campaign.

## Pinned inputs

- Production baseline: `main@3c011e94263e16e5780936b4769d3490cd03b682`.
- Failed M228 delivery: `handoff@44086710a04af83ccbef41b8c491096349003e5a`.
- Independent QA decision: `handoff/m228/SOL-REVIEW-R1.md` (recorded at handoff commit `717556c15ac8f56ec5057d56b8a062de0d30e367`).
- Authoritative original task: `handoff/m228/TASK-M228-R1.md`. Keep its other guardrails.
- Frozen accepted Sol evidence: M223–M227 as pinned in `REPORT.md`. Do **not** rerun or relabel it.

## Allowed edits

Only:
1. `handoff/m228/FINDINGS.md`
2. `handoff/m228/ARCHITECTURE.md`
3. `handoff/m228/GATES.md`
4. `handoff/m228/REPORT.md`

Optionally one new `handoff/m228/R2-CHANGELOG.md` if needed for an auditable summary. **No edits** to `src/`, `tests/`, `config/`, `CLAUDE.md`, production `main`, or owner data. No render, LLM API, media upload, CI-triggering production PR or merges. The handoff orphan branch must be handled as evidence-only; do not infer source deletion from whole-tree diff.

## P1 correction set — all required

**P1-A: Correct evidence classification.**
- Replace `GATES.md` claim that seven FIX_NOW parent findings are CLI/boundary proven: #1/#2/#3/#5 are bounded CLI/boundary; #7/#8/#9 are HELPER-only; do not imply final Proposal/render.
- Preserve #4 selector helper with late rejection NOT_REPRODUCED; #6 CLI-helper timing and playback unproven; #11 manual CLI-output accounting + helper teaser + static weak-seed; #12 same-input determinism only.
- Maintain both counts with units labelled: 12 parent findings, 14 subcases; 7 FIX_NOW parents/9 subcases, 3 instrument parents, 2 no-current-fix parents.

**P1-B: Make M229/M230 code gates noncontradictory.**
- Accepted source baseline places suppression #1 inside `propose` (see `autocut.py:1175,1262–1264`) and other M229 cases may also modify its body. The restriction is **not only signature**.
- Explicitly require **M230 architecture review before ANY `propose` body/signature mutation**, no matter which milestone number contains the eventual code. Choose and document a single coherent order: e.g. M229 pre-arch docs/tests-only, then M230 arch approval, then appropriately gated implementation; or move `propose`-dependent implementation to post-arch milestones.
- If any M229 *code* is proposed before M230, enumerate exact non-`propose` symbols, prove no behavioral/callgraph dependency on `propose`, and respect feature-off parity; otherwise keep `M229_CODE_GO=NO`.
- Independent Sol review of M228 **plus an explicit recorded coordinator GO decision** are both required to authorize implementation. QA PASS alone is not authority. Each later code stage needs its own independent QA before merge.

**P1-C: Specify a bounded #1 recovery mechanism.**
- Current `used_seeds/taken -> continue` reproduces the observed suppression. Do not leave it unchanged while calling #1 fixed.
- Distinguish candidate enumeration from final selection and lawful overlap policy. Specify stable identity, bounded alternate attempts, deterministic dedup/overlap enforcement, and a stopping condition. Preserve the intentionally disallowed overlapping final clips.
- Do NOT assert late downstream rejection in real media; that was NOT_REPRODUCED. The test contract must prove only the bounded suppressed-alternative mechanism and a legal recovery strategy under explicit conditions. Make behavior design subject to the architectural gate.

**P1-D: Keep M231 observational.**
- M231: additive counters, per-stage reasons and t0/t1 delta diagnostic on synthetic/no-side-effect fixtures; no selection fallback, weak-seed callback wiring, acceptance/rejection or timing validator behavior changes.
- Move `no_start/open_end` wiring, reusing `rhythm_out`, `teaser_misses` signature/behavior changes, post-select fallback and other algorithm mutations to separately approved follow-on work with explicit flags/tests.
- No new owner data input, paid API or render requirements for instrumentation; real owner logs/media require separate written owner authorization and privacy plan.

**P1-E: Protect supported semantics and APIs.**
- Remove unconditional ban on question-first clips: supported question-led loop path must remain legal; #8 addresses question as **last** unit only.
- Treat unconditional answer extension after question and `build_passage -> (clip,reason)` API change as alternatives/hypotheses awaiting architecture review, callable compatibility and bounded neighbor legality. No implicit auto-repair with an unproven neighbor.
- For #8b, no promise of recovery: if there is no proven legal repair, fail closed with reason; record NOT_VERIFIED.

**P1-F: Gate real media.**
- Replace mandatory run on owner video/real logs with synthetic, consent-free no-side-effect validation in M231. Any real owner media/logs playback, M237 A/B render or paid model calls requires **separate explicit owner authorization**. Do not present a hypothetical owner-data run as accepted or required before GO.

## Contract/editorial corrections

- `FINDINGS.md` primary table: exactly **12 numbered main rows #1..#12**. Nest #8a/b and #9a/b in their main rows or use a **separate** subcase table; retain their distinct proof levels/actions and correct 14 subcase arithmetic.
- #12 disposition should be `DEFER` or `NOT_REPRODUCED` (no runtime identity-permutation proof), **not** `NO_FIX_INTENTIONAL` implying a confirmed intentional order-sensitive mechanism. #10 six-hook call budget is confirmed intentional.
- Define existing test suite pass on pristine baseline, but new defect-focused regression should **fail-before/pass-after** the future fix. Expected fail-closed negative tests should pass by asserting correct rejection.
- In FINDINGS rename #4 to describe the selector comparison, not nonexistent reproduced late drop. #8b cannot guarantee a legal neighbor.
- If action counts change when #12 becomes DEFER, update each summary and table consistently; never hide parent/subcase unit distinctions.

## Delivery and acceptance

- Publish only the four corrected documents (and optional changelog) to `origin/handoff`; record exact resulting SHA and changed paths.
- Include a compact mapping `P1-A...F / corrected path+section / CLOSED or STILL_OPEN` in the final report. Do not silently omit a Sol finding.
- Check that parent row IDs parse exactly #1..#12, every scope claim matches accepted review levels, and every code gate has one unambiguous sequencing rule. No new reproductions are required.
- End with:
  `TASK=M228-R2`, `BASE_SHA`, `EVIDENCE_BASE_SHA=44086710...`, `FINAL_HANDOFF_SHA`, `PRODUCTION_DIFF=NONE`, `P1_A...P1_F`, `READY_FOR_SOL_QA=YES/NO`.
- Stop for independent Sol 6.1 re-review on the new pinned SHA. Do not start M229 code and do not merge main.

**STOP RULE:** This is a bounded R2 documentation correction. No endless R3. If a semantic choice remains undecidable, mark it explicitly as requiring owner/architect decision while allowing nonconflicting planning. Do not invent authorization.
