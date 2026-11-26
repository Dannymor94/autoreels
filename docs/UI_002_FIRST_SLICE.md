# UI-002 — минимальный контракт первого среза

2026-11-26. Base main `74677b9c40a489ea09b98a1c5c676306bf0f945a`. Owner approved R3 and dev_4 execution plan; scoped UI-002/101–102 only, no MEDIA GO.

## Observed base
Existing React/Vite shell, hash routes, list, overview, player, variant selection, browser-local resume, and FastAPI/OpenAPI v1 exist. GET /api/sources is render-directory-only, not a complete project catalog; no review write route, job execution, or export route. GET /api/health exposes root on localhost; UI shell no longer displays it, but this is not remote security. Existing PUT source meta is preserved, not exercised on real data.

## First slice: scope and contracts
- UI-101 keeps hash routes #/, #/s/<stem>, #/s/<stem>/<clip>?v=<variant>, browser Back, saved position, list/grid, and variant selection. Bottom navigation on narrow screens, visible disabled jobs/export until implemented, editor only for an opened clip. No fake actions or second editor.
- Current UI-101 continues using generated OpenAPI types and existing endpoints unchanged. `stem` and `(stem,clip,variant)` are legacy locators, not stable identities or approval keys. No inference that render fingerprint identifies exact artifact.
- UI-102 next: source catalog projection from validated source/manifests/job/output metadata; never infer empty or failed from absence of MP4. Explicit unknown when no evidence. States unprocessed/draft/empty/failed/ready and unknown; source collision or ambiguity must not silently merge. Existing media resolver still controls playback. No source scanning outside allowed roots, no mutation or archive from listing. Before schema change inspect manifest resolution and actual history statuses; preserve legacy API clients and regenerate snapshot/types together.
- UI-103/104 later: choose existing verdict adapter after examining CLI; exact rendered artifact identity and review vs export decision semantics; stale verdicts never accepted by clip number. No new journal or writes in this slice.
- UI-105 HIGH and MEDIA GO remain separate. No new libraries, provider requests, real render or source changes.

## Acceptance
Static: existing typecheck/build; CI with lockfile. Responsive browser fixture: 360/390/430px + desktop, long source names, grid/list, variant tabs, keyboard, back navigation, loading/error/empty states, no page overflow (table may scroll inside its own region). Exercise only synthetic data. Report actual build and browser evidence separately; do not claim mobile acceptance before measured. UI-102 acceptance deferred to its own PR.

## Risk and scope
UI-101 changes frontend presentation and route entry points; MEDIUM due to existing review UI behavior. No API/server/schema/pipeline change. Independent audit per CLAUDE.md after CI; focused correction only. Existing review gate and local-owner-data gate preserved. 
