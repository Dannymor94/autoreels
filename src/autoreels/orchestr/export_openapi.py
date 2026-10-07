"""Run: python -m autoreels.orchestr.export_openapi > ui/openapi.json"""
import json

from .app import app


def main():
    print(json.dumps(app.openapi(), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
