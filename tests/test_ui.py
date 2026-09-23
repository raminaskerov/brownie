import sys

import pytest

from brownie_agent.ui import HTML, _result_reply, build_command


def test_search_command_is_typed_and_keeps_managed_browser_open(tmp_path):
    command = build_command({
        "mode": "search",
        "browser": "managed",
        "steerer": "jev",
        "goal": "Find the official report",
        "max_steps": 6,
        "max_pages": 2,
        "max_scrolls": 0,
        "keep_open": True,
    }, trace_path=tmp_path / "last-run.jsonl")

    assert command[:3] == [sys.executable, "-m", "brownie_agent.cli"]
    assert "--managed-cdp" in command
    assert "--search" in command
    assert "--keep-open" in command
    assert command[command.index("--goal") + 1] == "Find the official report"
    assert "--max-scrolls" not in command


def test_attached_search_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="cannot take ownership"):
        build_command({
            "mode": "search", "browser": "attach", "steerer": "jev", "goal": "Find it",
        }, trace_path=tmp_path / "last-run.jsonl")


def test_one_step_command_can_attach_without_keep_open(tmp_path):
    command = build_command({
        "mode": "step",
        "browser": "attach",
        "steerer": "llm",
        "goal": "Open pricing",
        "url": "https://example.test/",
        "keep_open": True,
    }, trace_path=tmp_path / "last-run.jsonl")

    assert "--attach" in command
    assert "--use-open-tab" in command
    assert "--step" in command
    assert "--keep-open" not in command


def test_command_rejects_unbounded_or_non_url_input(tmp_path):
    with pytest.raises(ValueError, match="Start URL"):
        build_command({
            "mode": "observe", "browser": "playwright", "url": "example.test",
        }, trace_path=tmp_path / "last-run.jsonl")


def test_result_reply_reports_source_without_an_extra_model_call():
    reply = _result_reply({
        "source": {"title": "Report", "url": "https://example.test/report", "material": "Grounded text"},
    })

    assert reply == "I found and read: Report\nhttps://example.test/report\n\nGrounded text"


def test_polling_does_not_replace_unchanged_copyable_text():
    assert "if(eventKey!==lastEvents)" in HTML
    assert "if(logText!==lastLogs)" in HTML
    assert "function setText(id,value)" in HTML
