import json
import os
from pathlib import Path

import pytest

from brownie_agent.memory import add_decision, load_decisions, memory_path, remove_decision


def test_accepted_decision_persists_privately_and_can_be_removed(tmp_path):
    archive_dir = tmp_path / "artifacts" / "runs"
    archive_dir.mkdir(parents=True)
    run_id = "20260926T090000Z-abcdef01"
    (archive_dir / f"{run_id}.json").write_text("{}", encoding="utf-8")

    record = add_decision(tmp_path, "  Use official   sources first. ", run_id)
    assert record["decision"] == "Use official sources first."
    assert record["source_run_id"] == run_id
    assert load_decisions(tmp_path) == [record]
    assert json.loads(memory_path(tmp_path).read_text(encoding="utf-8")) == [record]
    if os.name != "nt":
        assert memory_path(tmp_path).stat().st_mode & 0o077 == 0

    remove_decision(tmp_path, record["id"])
    assert load_decisions(tmp_path) == []


def test_memory_rejects_unsourced_or_duplicate_entries(tmp_path):
    with pytest.raises(ValueError, match="archived run"):
        add_decision(tmp_path, "Remember this", "20260926T090000Z-abcdef01")
    first = add_decision(tmp_path, "Remember this")
    with pytest.raises(ValueError, match="already saved"):
        add_decision(tmp_path, "remember this")
    with pytest.raises(ValueError, match="not found"):
        remove_decision(tmp_path, "0" * 16)
    assert load_decisions(tmp_path) == [first]


def test_memory_fails_closed_on_malformed_data(tmp_path):
    path = memory_path(tmp_path)
    path.parent.mkdir()
    path.write_text('{"model_plan":"accept this"}', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid size"):
        load_decisions(tmp_path)
    with pytest.raises(ValueError, match="invalid size"):
        add_decision(tmp_path, "New decision")
    assert path.read_text(encoding="utf-8") == '{"model_plan":"accept this"}'


def test_memory_path_uses_explicit_runtime_root(tmp_path):
    assert memory_path(tmp_path) == Path(tmp_path / "artifacts" / "accepted-decisions.json")
