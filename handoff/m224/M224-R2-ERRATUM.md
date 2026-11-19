# M224 R2 — evidence erratum (documentation only)

**Evidence snapshot:** `d18627fb0fff56c4735b3c0462b1796337989715` (immutable).  
**Main under test:** `3c011e94263e16e5780936b4769d3490cd03b682`.  
**Sol first review:** `handoff/m224/SOL-REVIEW-R2.md` — `CHANGES_REQUIRED`.  
**Reproduction status:** original R2 script reproduced by coordinator on isolated main+handoff archive, `40/40 PASS`, `exit 0`.

## Evidence classifications (replace over-broad wording in REPORT.md)

| Item | Proven observation | Unproven claim |
| --- | --- | --- |
| #5 short-drop/min_sec | `CLI_HELPER_BOUNDARY_CONFIRMED`: transparent spy of real `context_start`, `refs 1.1-2→1.2`, span `25.0→23.0` with production `min_sec=25` | Final `Proposal.seconds=23.0` was not asserted; `NOT_VERIFIED` |
| #6-start | `CLI_HELPER_BOUNDARY_CONFIRMED`: output `t0=102.0` vs first retained synthetic word at `102.4`, difference `0.4s` | Actual playback silence `NOT_REPRODUCED` |
| #6-end | `CLI_HELPER_BOUNDARY_CONFIRMED`: `t1=229.0` vs last retained synthetic word at `228.0`, difference `1.0s` with synthetic prosody | Actual playback silence `NOT_REPRODUCED` |
| §3 negative | `CONFIG_DIFFERENCE_ONLY`: synthetic `select=greedy` loaded and differs from production `global` | No subprocess/nonzero exit; `FAIL_CLOSED_NOT_VERIFIED` |

The `40/40` count is the count of passing assertions in the R2 script, **not** 40 assertions of independent CLI behavior. The test's `H9` condition is literal `True` and not evidence of final output. `spy_propose` recorded results but no assertion of their final `seconds/pieces` was made.

## Log provenance correction

`handoff/m224/repro_stdout.txt` is the **old R1 44-check log**. **It is hereby withdrawn as supporting evidence for R2**; do not cite it for R2 checks, results, or SHA256. The independently observed R2 result was `40/40 PASS, exit 0` when the coordinator executed `handoff/m224/REPRO.py` from an isolated archive of production main plus handoff evidence, using local test Python, without paid API or owner media. A complete stdout log was not persisted as a new handoff artifact; its SHA256 is `NOT_AVAILABLE`. The script itself is reproducible at immutable SHA.

## M228 ledger pending cases

- `M224-5-FINAL_PROPOSAL=NOT_VERIFIED`
- `M224-6-START_RENDERED_AUDIO=NOT_REPRODUCED`
- `M224-6-END_RENDERED_AUDIO=NOT_REPRODUCED`
- `M224-NEGATIVE_SUBPROCESS=NOT_VERIFIED`

Do **not** convert these to CLI-confirmed without new targeted proof; they are bounded questions for M228 architecture and production acceptance, not a reason to initiate R3.

## Gate and instruction

`M224=AWAITING_SOL_REASSESSMENT_OF_ERRATUM`. If independent Sol accepts **only** the verified helper-boundary observations and explicitly excludes all unverified final/render claims, it may issue a **scoped PASS** allowing M225 Stage A diagnostics. Otherwise keep M225 blocked and escalate the residuals to M228 without a third reproduction.
