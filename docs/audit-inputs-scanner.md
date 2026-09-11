# Audit — inputs/ scanner (read-only diagnosis)

Symptom: `inputs/` holds one readable file `lecture1.mp4` (4,152,482,356 B ≈ 4.15 GB),
yet menu option 1 ("process videos from inputs/") prints `inputs/ пуст — нечего обрабатывать`.
No behaviour changed by this audit.

Menu path: menu item 1 → action `go` (`__main__.py:2615`) → bash `go)` → `_ar_cli run "$@"`
(`aliases.sh:186-192`) → with no video argument → `cmd_run_batch` (`__main__.py:3753-3756`).

---

## 1. The enumeration code

`src/autoreels/__main__.py:1301-1311` (inside `cmd_run_batch`):

```python
    root = Path(root)
    ...
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"
    videos = sorted(inputs_dir.glob("*.mp4"))
    if not videos:
        print("inputs/ пуст — нечего обрабатывать", flush=True)
        return [], [], []
```

`root` defaults to `"."` (`cmd_run_batch` signature, `__main__.py:1284`), and the `run`
dispatch calls `cmd_run_batch(ffmpeg=ffmpeg, push=not args.no_push)` with **no `root`**
(`__main__.py:3754`) — so `root` stays `"."`.

## 2. How the candidate list is built

- **Pattern / walk:** a single non-recursive glob, `inputs_dir.glob("*.mp4")` (`:1308`).
  No directory walk, no other patterns, no `**`.
- **Extension match / case:** only literal `*.mp4`. On this repo's Python (`pathlib.glob`,
  3.12+) the match follows the filesystem's case sensitivity; macOS is case-insensitive, so
  `.mp4`/`.MP4` both match here — **but no other container extension is accepted at all**
  (`.mov`, `.mkv`, `.m4v`, `.webm`, `.avi` are never enumerated by the batch scanner).
- **Hidden/dotfiles:** not explicitly excluded by code; `glob("*.mp4")` simply won't match a
  name that isn't `*.mp4`. A dotfile like `.lecture.mp4` would match the pattern; it is not
  specially filtered here.
- **Absolute vs relative:** **relative.** `inputs_dir = root / "inputs"` with `root = "."`
  (`:1307`, `:1284`) → `Path("inputs")`, resolved against the **current working directory** at
  invocation, not the project root.

**Empirically verified from the repo root** (`/Users/danny/Documents/autoreels`):
`sorted(Path("inputs").glob("*.mp4"))` returns `['lecture1.mp4']`, and
`Path("inputs/lecture1.mp4")` reports `suffix='.mp4'`, `st_size=4152482356`. So the file **is**
seen when cwd is the project root. The pattern and the file are not the problem.

## 3. Filters applied AFTER enumeration and BEFORE the "empty" message

**None.** The `if not videos:` check (`:1309`) fires on the raw glob result, immediately after
`glob` and before the per-file loop (`:1316`). Specifically:

- **File-size limit (min/max):** NOT FOUND in this path. The only `stat().st_size` read is
  `size_gb = Path(video).stat().st_size / (1 << 30)` at `__main__.py:1117`, inside `cmd_run`
  (per file, after enumeration) and used only for a log line — no threshold, no rejection.
  Nothing rejects a 4.15 GB file.
- **Duration limit:** NOT FOUND anywhere in the scan/run-batch path.
- **Deduplication against processed files:** No hash/name ledger is consulted before the empty
  message. Idempotency is instead by **archiving**: after a successful run, `_archive_video`
  moves the file to `inputs-archive/` (`__main__.py:509-517`, called at `:1188`), so a
  processed file simply no longer appears in `inputs/` next time. There is **no separate
  state/ledger file** listing processed inputs; the archive directory *is* the mechanism.
  `lecture1.mp4` is still physically in `inputs/` (not archived), so dedup/archive is not
  removing it from the glob.
- **Skip list of known-bad inputs:** NOT FOUND. "Bad" files are discovered only during
  processing — `InputInvalid` raised inside `cmd_run` and caught per-file at `:1324-1326`
  ("битые/пустые файлы … остаются в inputs/") — this happens *after* enumeration and cannot
  affect the pre-loop empty check.

## 4. Is failure silent?

For this specific symptom, **yes — silent by construction.** The empty branch prints one fixed
line, `inputs/ пуст — нечего обрабатывать` (`:1310`), and returns. It does **not** print the
resolved absolute path it scanned, the cwd, or how many entries `inputs_dir` contained. If the
scanned `inputs/` is the wrong (empty) directory, nothing reveals which directory was inspected
— the mismatch vanishes before the message.

(Per-file rejections later in the batch are *not* silent — they are logged at `:1325`, `:1328`,
`:1337-1342` — but those never run when the glob is empty.)

## 5. Single most likely reason this file is rejected

**It is not rejected by a filter — the scanner is looking in a different directory.** The file
matches the glob and passes every filter when cwd is the project root (verified in §2), and
there are no size/duration/dedup/skip filters before the empty message (§3). The one variable
that changes the result is the working directory:

- **Responsible check:** `inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"`
  with `root="."` — `src/autoreels/__main__.py:1307` (default from `:1284`), feeding the glob
  at `:1308`.
- **Why it triggers:** `aliases.sh` computes `_AR_ROOT` (`aliases.sh:8`) but **never `cd`s to
  it** — neither `arl()` nor `_ar_cli()` changes directory (the only `cd` in the file is inside
  the command-substitution that defines `_AR_ROOT`, which does not affect the caller's cwd), and
  the `run` dispatch passes no `root` (`:3754`). So when the menu is launched from any directory
  other than the project root, `Path("inputs")` resolves to a nonexistent/empty `inputs/`
  relative to that cwd, `glob("*.mp4")` returns `[]`, and `:1310` prints the empty message even
  though `/Users/danny/Documents/autoreels/inputs/lecture1.mp4` exists.

Most likely trigger in practice: the menu was invoked with a current working directory that is
not `/Users/danny/Documents/autoreels`. (A less likely alternative — `inputs/` being a symlink
or the file living under a different real path — is ruled out for this file by the §2
verification, which found `lecture1.mp4` from the repo root.)
