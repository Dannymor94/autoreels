# TASK: M229-PREP-R2 — Correct bounded regression blueprints

ROLE: Claude Code Sonnet 4.6 (docs executor)  
REPO: Dannymor94/autoreels  
PRODUCTION_BASE_SHA: 3c011e94263e16e5780936b4769d3490cd03b682  
HANDOFF_BASE: origin/handoff at or after d0108cbdfc80054651ca40e796209be3ccf48b25  
REVIEW_PIN: 9fcb8159a217f517c1e141b96ea4c9ebbdc5712d  
REQUIRED_REVIEW: handoff/m229/SOL-REVIEW-R1.md  
MODE: DOCS_ONLY; M229_CODE_GO=NO; M230_GO=NO; M231_GO=NO; M232_CODE_GO=NO

## Objective

Perform exactly one bounded correction pass on the M229 test/specification blueprints. Repair the six P1 contradictions identified by independent Sol 6.1 QA; recover the already accepted M223–M227 causal witnesses. Do not create new, unproven production defect claims or run expensive novel exploratory probes. Keep all tests marked SPECIFIED and NOT_EXECUTED, including all prospective fail-before and pass-after claims.

## Authorized edit set — exactly these four existing files

1. handoff/m229/REGRESSION_CONTRACTS.md
2. handoff/m229/FIXTURE_CATALOG.md
3. handoff/m229/CALLGRAPH_AND_ARCH_QUESTIONS.md
4. handoff/m229/REPORT.md

Read-only reference documents: handoff/m229/SOL-REVIEW-R1.md, accepted Sol reviews for M223, M224, M225, M226, M227, and M228 and the pinned production source. Do not modify any read-only reference. No source, tests, prompt, config, CI, owner assets or other repo paths.

## Mandatory fixes

A. TC-1 / FX-1: make suppression genuinely follow accepted-clip used_seeds semantics at autocut.py:1262–1264. The competing eligible seed must be inside the accepted first candidate if subsequent used_seeds suppression is asserted. Overlapping candidate enumeration is legitimate; final accepted clip dedup must remain nonoverlapping. Restore the M223 bounded fixture and repair the invalid length-vs-set negative assertion. Separate observations, inferences and hypotheses.

B. TC-3 / FX-3: ensure that a clause-bearing candidate reaches the actual _hook_cands clauses branch (not excluded by hook_teaser_pos before branch execution). Use M223 accepted multi-sentence witness or precise reachable config. Preserve the M223 omission evidence levels: helper-level clause versus CLI caller-level lack of forwarding, when supported.

C. TC-7 / FX-7: restore accepted M225 Case A, first [50,76], required short middle [90,95], third [160,193], integer refers=2 and production params. Evidence is propose helper losing middle and returning [1,3]. Distinguish result from eventual end-to-end CLI.

D. TC-8a / FX-8a: align with M225 Case B: first [50,76], conclusion [90,93], question [94,119]; fit_rhythm appends a late question after build_passage. Question-first as first segment remains lawful. Remove claims that build_passage itself is the demonstrated final question append.

E. TC-8b / FX-8b: align with M225 Case C: fix_open_end trims the final piece to 2.5s; final rhythm_why rejects under approximately 4.09s and records rhythm_out. It is not a silent drop. Do not assume legal neighbor repair success; route repair decisions to the M230 architecture gate.

F. Source/callgraph/plan coherence: inspect exact symbol definition and call line numbers at pinned production SHA. fix_open_end is around 625; stands_alone around 657; do not retain inaccurate ~1080/~800 pointers. Include final validator and distinguish STATIC source edges from OBSERVED executed proof. Treat any suggested break→continue for TC-9a as unsafe without bounded fallback/termination specification. M231 is OBSERVABILITY ONLY; behavior/propose changes are separately gated M232.

G. Secondary: TC-2 preserves legitimate question-first and strict config and labels fail-before/pass-after correctly. TC-5 reconciles 15s/23s timing against accepted M224 evidence. TC-9b answer-extension remains an M230 hypothesis. Each TC must have coherent setup, action, baseline oracle, prospective post-fix oracle, negative control and feature-off parity. Use valid Python assertion types for blueprints.

## Validation and stopping conditions

- Check precisely the accepted evidence; do not assert observed new behavior when evidence was only static, helper or limited CLI.
- Keep mapping of fourteen M228 subfindings to nine test IDs accurate; a 14-to-9 matrix does not itself prove all fixture adequacy.
- Ensure docs have consistent line pointers, metrics and phase gates. Prefer UNKNOWN/ARCH_QUESTION over fabricated assurance.
- Read-only check the diff against origin/handoff's parent: only four authorized existing docs changed. Check no production diff versus the unchanged SHA using path-scoped evidence (or git diff --name-only on the handoff doc edit); the orphan handoff branch is not comparable whole-tree to main.
- One bounded R2 pass only. If a fixture cannot be made proven from accepted evidence, record the explicit blocker and stop; do not silently start R3.
- Do not run render, API, external LLM, live source/owner media, ffmpeg, project-wide pipeline, merge, deploy, branch rewrite or main writes. New tests must not be implemented.
- Publish changes in a dedicated evidence commit on handoff as already authorized by the M229 docs workflow. Do not create merge requests or grant code GO.

## Required handoff response

TASK=M229-PREP-R2
BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682
EVIDENCE_BASE_SHA=9fcb8159a217f517c1e141b96ea4c9ebbdc5712d
FINAL_HANDOFF_SHA=<40-char SHA>
CHANGED_PATHS=<the four documents only>
PRODUCTION_DIFF=NONE
TEST_STATUS=SPECIFIED_NOT_EXECUTED
M229_CODE_GO=NO
P1_A=RESOLVED/BLOCKED (+ exact doc location and accepted evidence)
P1_B=...
P1_C=...
P1_D=...
P1_E=...
P1_F=...
READY_FOR_SOL_QA=YES/NO

Include a concise before/after correction matrix and cite exact M223–M227 accepted evidence sources. Stop for independent Sol review; no M230 implementation or architecture signoff before explicit coordinator release.
