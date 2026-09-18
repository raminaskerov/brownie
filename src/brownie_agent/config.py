"""Small project-local .env loader; existing process variables win."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env(path: str | Path | None = None) -> Path:
    env_path = Path(path).expanduser().resolve() if path else PROJECT_ROOT / ".env"
    if not env_path.exists():
        return env_path
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        if key:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))
    return env_path
