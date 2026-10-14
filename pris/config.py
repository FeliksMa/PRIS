from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(slots=True)
class Settings:
    root: Path
    raw: dict[str, Any]

    @property
    def database(self) -> Path:
        return self.root / self.raw["system"]["database"]

    @property
    def vault(self) -> Path:
        return self.root / self.raw["system"]["vault"]

    @property
    def runner_id(self) -> str:
        return os.getenv("PRIS_RUNNER_ID", "primary")

    @property
    def is_active_runner(self) -> bool:
        return self.runner_id == self.raw["system"].get("active_runner_id", "primary")

    def secret(self, name: str) -> str:
        return os.getenv(name, "").strip()


def load_settings(root: Path | None = None) -> Settings:
    root = (root or Path.cwd()).resolve()
    load_dotenv(root / ".env")
    config_path = root / "config.toml"
    if not config_path.exists():
        example = root / "config.example.toml"
        if not example.exists():
            raise FileNotFoundError("缺少 config.toml 和 config.example.toml")
        shutil.copyfile(example, config_path)
    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)
    from .preferences import load_overrides
    load_overrides(root, raw)
    settings = Settings(root=root, raw=raw)
    settings.database.parent.mkdir(parents=True, exist_ok=True)
    settings.vault.mkdir(parents=True, exist_ok=True)
    return settings

