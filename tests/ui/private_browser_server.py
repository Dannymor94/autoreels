"""Synthetic HTTPS server for browser acceptance only. Never uses the owner root."""
import hashlib
import os
from pathlib import Path

import uvicorn
from pydantic import SecretStr
from starlette.staticfiles import StaticFiles
from autoreels.orchestr import settings
from autoreels.orchestr.app import app

root = Path(os.environ["ARL_PRIVATE_TEST_ROOT"]).resolve()
source = root / "reels-out" / "DEMO"
(source / "_gate" / "b").mkdir(parents=True)
(source / "r01.mp4").write_bytes(b"0123456789")
(source / "_gate" / "b" / "r01.mp4").write_bytes(b"variant")
settings.settings = settings.Settings(
    root=root, private_origin="https://127.0.0.1:8766",
    owner_digest=SecretStr(hashlib.sha256(b"synthetic-only-not-a-real-password").hexdigest()),
)
dist = Path(__file__).resolve().parents[2] / "ui" / "dist"
app.mount("/", StaticFiles(directory=dist, html=True), name="static")
uvicorn.run(app, host="127.0.0.1", port=8766, proxy_headers=False, access_log=False,
            ssl_certfile=os.environ["ARL_PRIVATE_TEST_CERT"], ssl_keyfile=os.environ["ARL_PRIVATE_TEST_KEY"])
