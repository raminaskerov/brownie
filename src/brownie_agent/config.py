"""Small working-directory .env loader; existing process variables win."""

import os
from pathlib import Path


def runtime_root() -> Path:
    """Return Brownie's explicit or current working directory for private runtime files."""
    configured = os.environ.get("BROWNIE_RUNTIME_DIR", "").strip()
    return Path(configured or Path.cwd()).expanduser().resolve()


def load_env(path: str | Path | None = None) -> Path:
    env_path = Path(path).expanduser().resolve() if path else runtime_root() / ".env"
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
