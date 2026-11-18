# Offline QA evidence bundle — optional manifest

The companion Python 3.13 stdlib tool is \`handoff/bin/evidence_consistency.py\`. It checks only **published bytes, return-code receipts, numbered assertions, and claim labels**. It is **not** a substitute for code review, real CLI execution or independent Sol 6.1 PASS.

Store \`evidence.json\` and its referenced files in the same task's \`handoff/mNN/\` directory; use relative paths only. The file names in this example are illustrative, not evidence from M224.

\`\`\`json
{
  "schema": 1,
  "task": "M224-R2",
  "base_sha": "3c011e94263e16e5780936b4769d3490cd03b682",
  "artifacts": [
    {"path": "positive.stdout", "sha256": "<actual 64-digit hex>"},
    {"path": "positive.stderr", "sha256": "<actual 64-digit hex>"},
    {"path": "positive.exit",   "sha256": "<actual 64-digit hex>"},
    {"path": "negative.stdout", "sha256": "<actual 64-digit hex>"},
    {"path": "negative.stderr", "sha256": "<actual 64-digit hex>"},
    {"path": "negative.exit",   "sha256": "<actual 64-digit hex>"}
  ],
  "runs": [
    {
      "name": "positive",
      "expected_exit": 0,
      "stdout": "positive.stdout",
      "stderr": "positive.stderr",
      "exit_file": "positive.exit",
      "checks": 44
    },
    {
      "name": "negative",
      "expected_exit": 1,
      "stdout": "negative.stdout",
      "stderr": "negative.stderr",
      "exit_file": "negative.exit"
    }
  ],
  "claims": [
    {
      "id": "finding5",
      "level": "CLI",
      "status": "CONFIRMED",
      "evidence": ["positive.stdout"]
    },
    {
      "id": "finding6-end",
      "level": "NOT_REPRODUCED",
      "status": "NOT_REPRODUCED",
      "evidence": ["positive.stdout"]
    }
  ]
}
\`\`\`

The tool accepts \`level\` values \`CLI|HELPER|STATIC|NOT_REPRODUCED\` and \`status\` values \`CONFIRMED|NOT_REPRODUCED|INTENTIONAL|BLOCKED\`. Never report \`CLI\` merely because production YAML was loaded. The reviewer must verify that a real \`cmd_autocut()\` path was invoked.

Generate hashes from **actual published files** and capture return codes immediately:

\`\`\`bash
python handoff/m224/CLI_REPRO.py > handoff/m224/positive.stdout 2> handoff/m224/positive.stderr
rc=$?
printf '%s\n' "$rc" > handoff/m224/positive.exit
sha256sum handoff/m224/positive.stdout handoff/m224/positive.stderr handoff/m224/positive.exit
python handoff/bin/evidence_consistency.py handoff/m224/evidence.json
\`\`\`

Do **not** pipe the command into \`tee\` and then use the pipeline's \`$?\`, or fake expected exit codes. This tool does **not execute** the provided runs; it validates saved receipts and hashes only. Reviewers still rerun the command in a clean worktree on the pinned SHA. The \`checks\` field is optional for commands without numbered \`PASS [NN]\` assertions; when present, numbers must be consecutive from 1. Do not retroactively force historical M223 reports into this new format; no new QA cycle should be caused by the optional manifest.
