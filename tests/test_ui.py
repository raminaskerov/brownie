import io
import json
import sys

import pytest

from brownie_agent.ui import HTML, RunManager, _result_reply, _visible_research_state, build_command


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


def test_research_command_has_separate_source_budget(tmp_path):
    command = build_command({
        "mode": "research",
        "browser": "managed",
        "steerer": "llm",
        "goal": "Compare the official positions",
        "max_sources": 4,
        "keep_open": False,
    }, trace_path=tmp_path / "last-run.jsonl")

    assert "--research" in command
    assert "--research-dialogue" in command
    assert command[command.index("--max-sources") + 1] == "4"
    assert "--search" not in command
    assert "--max-steps" not in command


def test_attached_research_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="cannot take ownership"):
        build_command({
            "mode": "research", "browser": "attach", "steerer": "llm", "goal": "Compare",
        }, trace_path=tmp_path / "last-run.jsonl")


def test_basic_command_uses_typed_task_path_and_inputs_without_models(tmp_path):
    command = build_command({
        "mode": "basic",
        "browser": "playwright",
        "task_path": "tasks/report.json",
        "inputs": ["query=solar report", "region=Azerbaijan"],
        "keep_open": False,
    }, trace_path=tmp_path / "last-run.jsonl")

    assert "--headed" in command
    assert command[command.index("--basic-task") + 1] == "tasks/report.json"
    assert command.count("--input") == 2
    assert "query=solar report" in command
    assert "--steerer" not in command
    assert "--goal" not in command


def test_attached_basic_task_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="cannot take ownership"):
        build_command({
            "mode": "basic", "browser": "attach", "task_path": "task.json",
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


def test_result_reply_reports_basic_task_stop_without_an_extra_model_call():
    reply = _result_reply({
        "mode": "basic",
        "task": "Daily report",
        "status": "stopped",
        "stop_reason": "target_not_found",
        "last_page": {"title": "Portal", "url": "https://example.test/"},
        "output": None,
    })

    assert "Basic task stopped: Daily report" in reply
    assert "Reason: target_not_found" in reply


def test_result_reply_renders_research_answer_and_cited_sources():
    reply = _result_reply({
        "mode": "research",
        "status": "answered",
        "answer": "The evidence differs [S1].",
        "cited_sources": [{"id": "S1", "title": "Official report", "url": "https://example.test/"}],
    })

    assert "The evidence differs [S1]." in reply
    assert "[S1] Official report" in reply


def test_polling_does_not_replace_unchanged_copyable_text():
    assert "if(eventKey!==lastEvents)" in HTML
    assert "if(logText!==lastLogs)" in HTML
    assert "function setText(id,value)" in HTML


def test_product_ui_exposes_keys_and_quit_without_returning_secrets():
    assert 'id="typesafe-key" type="password"' in HTML
    assert 'id="gemini-key" type="password"' in HTML
    assert 'id="quit"' in HTML
    assert "/api/settings" in HTML
    assert "Brownie has stopped." in HTML
    assert 'option value="basic"' in HTML
    assert 'option value="research"' in HTML
    assert 'id="max-sources"' in HTML
    assert 'id="reply-input"' in HTML
    assert 'id="send-reply"' in HTML
    assert 'id="research-state"' in HTML
    assert 'id="research-needs"' in HTML
    assert 'id="research-sources"' in HTML
    assert "/api/reply" in HTML
    assert 'id="task-path"' in HTML
    assert 'id="basic-inputs"' in HTML


def test_run_manager_sends_reply_only_for_a_pending_research_question(tmp_path):
    class Process:
        def __init__(self):
            self.stdin = io.StringIO()

        def poll(self):
            return None

    manager = RunManager(tmp_path)
    manager.trace_path.parent.mkdir(parents=True)
    manager.trace_path.write_text(json.dumps({
        "event": "research_question",
        "data": {"turn": 1, "question": "Which year?"},
    }) + "\n", encoding="utf-8")
    process = Process()
    manager._process = process
    manager._status = "running"

    state = manager.snapshot()
    assert state["status"] == "awaiting_user"
    assert state["can_reply"] is True
    assert state["question"] == "Which year?"

    manager.reply("Use 2025")

    assert process.stdin.getvalue() == "Use 2025\n"
    assert manager.snapshot()["can_reply"] is False
    with pytest.raises(RuntimeError, match="not waiting"):
        manager.reply("Duplicate answer")

    with manager.trace_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": "research_answer", "data": {"turn": 1, "answer": "Use 2025"}}) + "\n")
        handle.write(json.dumps({
            "event": "research_question",
            "data": {"turn": 2, "question": "Which region?"},
        }) + "\n")
    next_state = manager.snapshot()
    assert next_state["can_reply"] is True
    assert next_state["question"] == "Which region?"


def test_run_manager_rejects_reply_without_a_pending_question(tmp_path):
    manager = RunManager(tmp_path)

    with pytest.raises(RuntimeError, match="no active research run"):
        manager.reply("Unsolicited instruction")


def test_ui_projects_only_bounded_research_plan_facts():
    state = _visible_research_state([{
        "event": "research_plan",
        "data": {
            "plan": {"decision": "SEARCH_WEB", "reason": "Need an official source"},
            "state": {
                "source_budget_remaining": 2,
                "evidence_needs": ["Official policy"],
                "sources": [{
                    "id": "S1", "title": "Agency report", "url": "https://agency.test/",
                    "excerpts": ["private trace detail"],
                }],
                "dialogue": [{"question": "Private?", "answer": "Private answer"}],
            },
        },
    }])

    assert state == {
        "decision": "SEARCH_WEB",
        "reason": "Need an official source",
        "evidence_needs": ["Official policy"],
        "sources": [{"id": "S1", "title": "Agency report", "url": "https://agency.test/"}],
        "remaining": 2,
    }
    assert "Private" not in repr(state)


def test_local_api_token_is_private_and_snapshot_exposes_structured_result(tmp_path):
    import os

    from brownie_agent.ui import _write_api_token

    token_path = tmp_path / "artifacts" / "api-token"
    _write_api_token(token_path, "example-token")
    assert token_path.read_text(encoding="utf-8") == "example-token\n"
    if os.name != "nt":
        assert token_path.stat().st_mode & 0o077 == 0

    manager = RunManager(tmp_path)
    manager.trace_path.write_text(json.dumps({
        "event": "run_result",
        "data": {"result": {"mode": "basic", "status": "completed", "captures": {
            "reference": {"value": "ABC", "url": "https://example.test/"},
        }}},
    }) + "\n", encoding="utf-8")
    assert manager.snapshot()["result"]["captures"]["reference"]["value"] == "ABC"


def test_control_room_can_launch_firefox_basic_task(tmp_path):
    command = build_command({
        "mode": "basic", "browser": "firefox", "task_path": "tasks/report.json", "keep_open": False,
    }, trace_path=tmp_path / "last-run.jsonl")
    assert command[command.index("--browser") + 1] == "firefox"
    assert "--headed" in command
    assert "--managed-cdp" not in command
    assert 'option value="firefox"' in HTML
    assert 'option value="webkit"' in HTML


def test_basic_reply_includes_named_captures():
    reply = _result_reply({
        "mode": "basic", "task": "Daily report", "status": "completed", "stop_reason": "task_complete",
        "last_page": {"title": "Portal", "url": "https://example.test/"}, "output": None,
        "captures": {"reference": {"value": "ABC", "url": "https://example.test/"}},
    })
    assert "reference: ABC (https://example.test/)" in reply


def test_finished_run_archives_full_trace_and_compact_proposal_index(tmp_path):
    import os

    manager = RunManager(tmp_path)
    manager._run_id = "20260926T120000Z-test0001"
    manager._status = "completed"
    manager.trace_path.parent.mkdir(parents=True)
    events = [
        {"event": "run", "data": {"mode": "research", "goal": "Compare policies"}},
        {"event": "research_plan", "data": {"plan": {
            "decision": "SEARCH_WEB", "reason": "Need official policy", "search_query": "policy",
        }}},
        {"event": "research_question", "data": {"turn": 1, "question": "Which year?"}},
        {"event": "research_answer", "data": {"turn": 1, "answer": "2025"}},
        {"event": "run_result", "data": {"result": {
            "status": "answered", "stop_reason": "answer", "last_page": {"url": "https://example.test/"},
            "sources": [{"id": "S1", "title": "Policy", "url": "https://example.test/policy", "excerpts": ["text"]}],
        }}},
    ]
    original = "".join(json.dumps(event) + "\n" for event in events)
    manager.trace_path.write_text(original, encoding="utf-8")

    assert manager._archive_run() == manager._run_id
    archive_dir = tmp_path / "artifacts" / "runs"
    assert (archive_dir / f"{manager._run_id}.jsonl").read_text(encoding="utf-8") == original
    summary = json.loads((archive_dir / f"{manager._run_id}.json").read_text(encoding="utf-8"))
    assert summary["mode"] == "research"
    assert summary["goal"] == "Compare policies"
    assert summary["planner_proposals"] == [{"decision": "SEARCH_WEB", "reason": "Need official policy"}]
    assert summary["user_clarifications"] == [{"turn": 1, "question": "Which year?", "answer": "2025"}]
    assert summary["source_links"] == [{"id": "S1", "title": "Policy", "url": "https://example.test/policy"}]
    assert "search_query" not in repr(summary)
    assert "excerpts" not in repr(summary)
    if os.name != "nt":
        assert (archive_dir / f"{manager._run_id}.jsonl").stat().st_mode & 0o077 == 0
