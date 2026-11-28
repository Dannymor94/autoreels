import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, SecretStr, model_validator


class Settings(BaseModel):
    root: Path
    port: int = 8765
    no_browser: bool = False
    synthetic_jobs: bool = False
    synthetic_editor: bool = False
    synthetic_export_workspace: Path | None = None
    private_origin: str | None = None
    owner_digest: SecretStr | None = None

    @model_validator(mode="after")
    def validate_private(self):
        if self.synthetic_export_workspace is not None:
            stage=self.synthetic_export_workspace
            if (not self.synthetic_editor or self.private_origin is not None
                    or not stage.is_absolute() or not stage.is_dir() or stage.resolve()!=stage
                    or stage==self.root or stage.is_relative_to(self.root) or self.root.is_relative_to(stage)):
                raise ValueError("synthetic export requires a separate canonical local test workspace")
        if (self.private_origin is None) != (self.owner_digest is None):
            raise ValueError("private origin and owner digest must be configured together")
        if self.private_origin is not None:
            u = urlsplit(self.private_origin)
            if (u.scheme != "https" or not u.hostname or u.username or u.password
                    or u.path or u.query or u.fragment
                    or self.private_origin != "https://" + u.netloc
                    or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*(?::[0-9]{1,5})?", u.netloc)
                    or (u.port is not None and not 1 <= u.port <= 65535)):
                raise ValueError("private origin must be a canonical HTTPS origin")
            if not re.fullmatch(r"[0-9a-f]{64}", self.owner_digest.get_secret_value()):
                raise ValueError("invalid owner password digest")
        return self

    @classmethod
    def from_env(
        cls,
        root_override: str | None = None,
        port: int = 8765,
        no_browser: bool = False,
        private_origin: str | None = None,
        owner_digest_file: str | None = None,
        synthetic_jobs: bool = False,
        synthetic_editor: bool = False,
        synthetic_export_workspace: Path | None = None,
    ) -> "Settings":
        root = root_override or os.environ.get("AUTOREELS_ROOT", "~/Documents/autoreels")
        digest = None
        if owner_digest_file is not None:
            path = Path(owner_digest_file).expanduser()
            if path.is_symlink() or not path.is_file():
                raise ValueError("owner digest must be a regular file")
            mode = path.stat().st_mode
            if os.name == "posix" and mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise ValueError("owner digest file must not be accessible to group or others")
            digest = SecretStr(path.read_text(encoding="ascii").strip())
        return cls(root=Path(root).expanduser().resolve(), port=port, no_browser=no_browser,
                   private_origin=private_origin, owner_digest=digest, synthetic_jobs=synthetic_jobs, synthetic_editor=synthetic_editor,
                   synthetic_export_workspace=synthetic_export_workspace)


settings = Settings.from_env()
