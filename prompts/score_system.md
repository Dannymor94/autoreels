# Score system prompt — M1.6 stage 4

Runtime prompt for the block-scoring LLM call. English system, Russian blocks in.
Unlike R0, this call returns scores only — no titles, timestamps, or reasons.
The `_extract_prompt_body` helper in select.py loads the text between the fences.

```
Score Russian-language transcript blocks for standalone Reels/Shorts quality.

Each block is prefixed with its ID in brackets: [block_id] text...

Rubric (0–100):
- 80–100: complete thought, self-contained opening (no dangling pronoun requiring prior context), quotable line, question→answer arc, or counterintuitive claim
- 60–79: complete and coherent thought, decent but unremarkable
- below 60: broken thought, dangling reference, organisational talk (break, subscribe), or list without payoff

Return ONLY valid JSON, no commentary, no markdown fences:
{"scores":[{"id":"<block_id>","score":<integer>},...]}
Include ONLY blocks you would score ≥65. Omit weaker blocks entirely.
```
