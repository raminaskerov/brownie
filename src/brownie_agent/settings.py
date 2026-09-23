"""Minimal local provider-key settings for the product-test UI."""

import os
from pathlib import Path

KEY_FIELDS = {
    "typesafe_api_key": "TYPESAFE_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
}


def _env_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        if key:
            values[key] = value.strip().strip('"').strip("'")
    return values


def provider_status(runtime_dir: Path) -> dict[str, bool]:
    values = _env_values(runtime_dir / ".env")

    def configured(*names: str) -> bool:
        return any(os.environ.get(name, "").strip() or values.get(name, "").strip() for name in names)

    return {
        "jev_configured": configured("TYPESAFE_API_KEY"),
        "llm_configured": configured("STEERING_MODEL_API_KEY", "GEMINI_API_KEY"),
        "text_configured": configured("TEXT_MODEL_API_KEY", "GEMINI_API_KEY"),
    }


def save_provider_keys(runtime_dir: Path, payload: dict) -> dict[str, bool]:
    updates: dict[str, str] = {}
    for field, env_name in KEY_FIELDS.items():
        raw_value = payload.get(field, "")
        if not isinstance(raw_value, str):
            raise ValueError("API keys must be text")
        value = raw_value.strip()
        if not value:
            continue
        if len(value) > 4096 or "\n" in value or "\r" in value:
            raise ValueError("Invalid API key")
        updates[env_name] = value
    if not updates:
        raise ValueError("Enter at least one API key")

    env_path = runtime_dir / ".env"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    try:
        lines = env_path.read_text(encoding="utf-8-sig").splitlines() if env_path.exists() else []
    except OSError as exc:
        raise RuntimeError("Brownie could not read its settings file") from exc

    remaining = dict(updates)
    output: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        candidate = stripped.removeprefix("export ").strip()
        key = candidate.split("=", 1)[0].strip() if "=" in candidate else ""
        if key in remaining:
            output.append(f"{key}={remaining.pop(key)}")
        else:
            output.append(raw_line)
    if output and output[-1]:
        output.append("")
    output.extend(f"{key}={value}" for key, value in remaining.items())

    temporary = env_path.with_name(".env.tmp")
    try:
        temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(env_path)
    except OSError as exc:
        raise RuntimeError("Brownie could not save its settings") from exc
    return provider_status(runtime_dir)


def validate_provider_settings(runtime_dir: Path, config: dict) -> None:
    mode = str(config.get("mode", "search"))
    if mode not in {"search", "predict", "step"}:
        return
    status = provider_status(runtime_dir)
    steerer = str(config.get("steerer", "jev"))
    if steerer == "jev" and not status["jev_configured"]:
        raise ValueError("Add a TypeSafe API key under Model keys before using Jev")
    if steerer == "llm" and not status["llm_configured"]:
        raise ValueError("Add a Gemini API key under Model keys before using LLM steering")
    if mode == "search" and not status["text_configured"]:
        raise ValueError("Add a Gemini API key under Model keys before searching")
