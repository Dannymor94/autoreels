import json
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")


def test_openapi_snapshot():
    from autoreels.orchestr.app import app
    live = json.dumps(app.openapi(), sort_keys=True, indent=2) + "\n"
    saved = (Path(__file__).parent.parent.parent / "ui" / "openapi.json").read_text()
    assert live == saved, (
        "run: python -m autoreels.orchestr.export_openapi > ui/openapi.json && cd ui && npm run gen:api"
    )
