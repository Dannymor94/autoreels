# UI-103 — оценка конкретного видео

Owner decision A (issue #38): Keep is a technical review, not export approval. UI-103 never invokes review-apply, changes a draft, writes the legacy export/learning journal or authorizes publication. No migration of old records. Separate export approval remains UI-204.

## Contract
One adapter returns current technical review, history and unbound legacy observations for the selected locator (stem, clip, variant). New technical review events have one local authoritative store: reviews/ui/technical_reviews.sqlite3 (gitignored). The legacy reviews/verdicts.jsonl is read only; gate/date/note displayed as historical, not mapped into current review. No duplicate event write to CLI journal. The new journal is for a different decision, not a second export approval source.

GET /api/reviews/{stem}/{clip}?variant= returns full SHA-256 of selected rendered bytes, current event for that SHA, newest-first history and legacy rows. GET before first write does not create database. PUT uses request_id and base_revision plus artifact_sha256, keep/fix/drop, comment and played position. SQLite transaction serializes writes; same ID + same payload is retry; same ID + changed payload or stale revision is conflict. A replaced artifact is unreviewed; historical assessment remains. Identical bytes under a different variant are separate review locators. No automatic decision transfer by rNN or render.json fingerprint.

Versioned player URL includes artifact SHA. Server verifies opened bytes and streams the same open handle, checks mutation during streaming, supports single byte range. Legacy unversioned playback remains unchanged. Selected-file full hash is calculated on open/seek/save, not on catalog listing; cost on long clips not measured. No media snapshots/copies, no remote access. Assume trusted local files and no malicious filesystem race; UI-105 is separate HIGH security scope. No claimed iOS/real-media acceptance.

UI: buttons save the decision and comment at current player time only after loaded metadata; saved status after server receipt; explicit refresh for conflicts; prior versions and old CLI records visible in history. Does not export. Editing/multi-clip status summaries and side-by-side comparison are separate subsequent slices.

## Minimal QA
Two synthetic API tests (save/reload, retry/conflict, exact bytes/range, replacement, variant isolation, old journal/draft unchanged), API/OpenAPI and generated TS parity, one targeted browser save/reload using synthetic video in existing responsive smoke. No new product dependencies. CI only; no owner media or live provider calls. No broad independent audit: local isolated technical assessment, no manifest/export writes; dedicated HIGH gate before remote access or export integration.
