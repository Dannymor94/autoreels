import argparse
import threading
import webbrowser
from pathlib import Path

import uvicorn


def main():
    parser = argparse.ArgumentParser(prog="python -m autoreels.orchestr")
    parser.add_argument("--root")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--synthetic-jobs", action="store_true", help="Enable isolated synthetic queue only")
    parser.add_argument("--synthetic-editor", action="store_true", help="Enable fixed synthetic subtitle editor only")
    parser.add_argument("--synthetic-export-workspace", type=Path, help="One-shot local synthetic whole-video export workspace, opt-in")
    parser.add_argument("--private-origin", help="Exact private HTTPS origin, opt-in")
    parser.add_argument("--owner-digest-file", help="Local 0600 file containing SHA-256 of random owner password")
    args = parser.parse_args()
    if (args.synthetic_jobs or args.synthetic_editor) and (not args.root or not Path(args.root).expanduser().is_dir()):
        parser.error("synthetic modes require an explicit existing test root")

    from .settings import Settings
    import autoreels.orchestr.settings as _s
    try:
        _s.settings = Settings.from_env(root_override=args.root, port=args.port, no_browser=args.no_browser,
                                       private_origin=args.private_origin, owner_digest_file=args.owner_digest_file,
                                       synthetic_jobs=args.synthetic_jobs, synthetic_editor=args.synthetic_editor,
                                       synthetic_export_workspace=args.synthetic_export_workspace)
    except (ValueError, OSError):
        parser.error("invalid private access configuration")

    from .app import app

    # repo root: orchestr -> autoreels -> src -> autoreels-ui
    repo_root = Path(__file__).parent.parent.parent.parent
    dist = repo_root / "ui" / "dist"
    if dist.exists():
        from starlette.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="static")
    else:
        from fastapi.responses import PlainTextResponse

        @app.get("/")
        def root_fallback():
            return PlainTextResponse("UI not built: cd ui && npm run build")

    if not args.no_browser and not _s.settings.private_origin:
        def _open():
            import time
            time.sleep(1)
            webbrowser.open(f"http://127.0.0.1:{_s.settings.port}")
        threading.Thread(target=_open, daemon=True).start()

    stop = threading.Event()
    worker = None
    if _s.settings.synthetic_jobs:
        from .queue import run_worker
        worker = threading.Thread(target=run_worker, args=(_s.settings.root, stop), daemon=True)
        worker.start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=_s.settings.port,
                    proxy_headers=False, access_log=not bool(_s.settings.private_origin),
                    limit_concurrency=32 if _s.settings.private_origin else None)
    finally:
        stop.set()
        if worker is not None:
            worker.join(timeout=6)


if __name__ == "__main__":
    main()
