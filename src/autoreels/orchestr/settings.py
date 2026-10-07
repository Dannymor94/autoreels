import os
from pathlib import Path
from pydantic import BaseModel


class Settings(BaseModel):
    root: Path
    port: int = 8765
    no_browser: bool = False

    @classmethod
    def from_env(
        cls,
        root_override: str | None = None,
        port: int = 8765,
        no_browser: bool = False,
    ) -> "Settings":
        root = root_override or os.environ.get("AUTOREELS_ROOT", "~/Documents/autoreels")
        return cls(root=Path(root).expanduser().resolve(), port=port, no_browser=no_browser)


settings = Settings.from_env()
