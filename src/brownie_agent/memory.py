"""Private, user-accepted research decisions kept separate from run traces."""

import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .config import runtime_root

MAX_DECISIONS = 30
MAX_DECISION_CHARS = 500
RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
DECISION_ID = re.compile(r"^[0-9a-f]{16}$")


def memory_path(root: Path | None = None) -> Path:
    return (root or runtime_root()) / "artifacts" / "accepted-decisions.json"


def _validate_record(raw: object) -> dict:
    if not isinstance(raw, dict) or set(raw) != {"id", "created_at", "decision", "source_run_id"}:
        raise ValueError("Accepted decision memory contains an invalid record")
    identifier = raw["id"]
    created = raw["created_at"]
    decision = raw["decision"]
    source_run_id = raw["source_run_id"]
    if not isinstance(identifier, str) or not DECISION_ID.fullmatch(identifier):
        raise ValueError("Accepted decision memory contains an invalid ID")
    if not isinstance(created, str) or len(created) > 40:
        raise ValueError("Accepted decision memory contains an invalid timestamp")
    if not isinstance(decision, str) or not decision.strip() or len(decision) > MAX_DECISION_CHARS:
        raise ValueError("Accepted decision memory contains invalid text")
    if source_run_id is not None and (
        not isinstance(source_run_id, str) or not RUN_ID.fullmatch(source_run_id)
    ):
        raise ValueError("Accepted decision memory contains an invalid source run")
    return dict(raw)


def validate_decisions(raw: object) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > MAX_DECISIONS:
        raise ValueError("Accepted decision memory has an invalid size")
    records = [_validate_record(item) for item in raw]
    if len({item["id"] for item in records}) != len(records):
        raise ValueError("Accepted decision memory contains duplicate IDs")
    return records


def load_decisions(root: Path | None = None) -> list[dict]:
    path = memory_path(root)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Could not read accepted decision memory") from exc
    return validate_decisions(raw)


def _save_decisions(root: Path, records: list[dict]) -> None:
    path = memory_path(root)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".brownie-memory-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def add_decision(root: Path, text: object, source_run_id: object = None) -> dict:
    """Save one explicitly accepted decision; never infer one from model output."""
    if not isinstance(text, str):
        raise ValueError("Decision must be text")
    decision = " ".join(text.split())
    if not decision or len(decision) > MAX_DECISION_CHARS:
        raise ValueError(f"Decision must contain 1 to {MAX_DECISION_CHARS} characters")
    if source_run_id == "":
        source_run_id = None
    if source_run_id is not None:
        if not isinstance(source_run_id, str) or not RUN_ID.fullmatch(source_run_id):
            raise ValueError("source_run_id is invalid")
        if not (root / "artifacts" / "runs" / f"{source_run_id}.json").is_file():
            raise ValueError("source_run_id does not name an archived run")
    records = load_decisions(root)
    if len(records) >= MAX_DECISIONS:
        raise ValueError(f"Accepted decision memory is limited to {MAX_DECISIONS} records")
    if decision.casefold() in {item["decision"].casefold() for item in records}:
        raise ValueError("This decision is already saved")
    record = {
        "id": secrets.token_hex(8),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": decision,
        "source_run_id": source_run_id,
    }
    records.append(record)
    _save_decisions(root, records)
    return record


def remove_decision(root: Path, identifier: object) -> None:
    if not isinstance(identifier, str) or not DECISION_ID.fullmatch(identifier):
        raise ValueError("Decision ID is invalid")
    records = load_decisions(root)
    remaining = [record for record in records if record["id"] != identifier]
    if len(remaining) == len(records):
        raise ValueError("Decision ID was not found")
    _save_decisions(root, remaining)
