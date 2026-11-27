# UI-504A — saved synthetic revision to actual MP4 staging

MEDIUM, trusted offline synthetic-only slice. No HTTP launch, public job queue,
owner files, network or deployment. Snapshot the exact current editor revision
and reconstruct its server-generated candidate under one read transaction.
The shipped preview has no audio and the editor historically used a placeholder
source hash. Keep the editor bytes intact. Verify the pinned bundled MP4 SHA-256,
copy its video stream and add a silent AAC stream to a separate fresh workspace.
Verify optional generated WAV against the existing typed asset ref. Change
only the source digest in the staged Manifest; record both revision and staged
hashes plus media/config binding. Existing staged executor consumes that
Manifest with normal checks and no fallback. No silent source replacement,
no overwrite or export publication. Old revisions aren't exported via a stale
head request. A later edit doesn't change the captured snapshot. Actual FFmpeg
acceptance reads the saved editor DB, not a separately hand-constructed plan.
This does not remove existing frame-grid/unsupported-effect renderer checks;
not all demo rate/trim combinations are renderable yet. The preview has no
speech: this test is not a test of real speech quality. New HTTP execution
or owner media requires separate HIGH/MEDIA authorization and independent QA.
