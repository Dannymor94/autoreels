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
    args = parser.parse_args()

    from .settings import Settings
    import autoreels.orchestr.settings as _s
    _s.settings = Settings.from_env(root_override=args.root, port=args.port, no_browser=args.no_browser)

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

    if not args.no_browser:
        def _open():
            import time
            time.sleep(1)
            webbrowser.open(f"http://127.0.0.1:{_s.settings.port}")
        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host="127.0.0.1", port=_s.settings.port)


if __name__ == "__main__":
    main()
