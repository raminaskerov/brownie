import json
from copy import deepcopy
from pathlib import Path

import pytest

from brownie_agent import BrowserSession
from brownie_agent.basic import load_basic_task, parse_basic_inputs, parse_basic_task, run_basic_task

FIXTURE = Path(__file__).with_name("fixture.html")


def observation(url, fingerprint, *, elements=None, text="", title="Page", perception=None):
    return {
        "url": url,
        "title": title,
        "text": text,
        "viewport": {"width": 1000, "height": 700, "scroll_y": 0, "document_height": 700},
        "elements": elements or [],
        "access": {},
        "perception": perception or {
            "surface": "top_document_viewport_dom",
            "frame_count": 0,
            "visible_frame_count": 0,
            "open_shadow_root_count": 0,
            "text_limit_reached": False,
            "element_limit_reached": False,
        },
        "can_scroll_up": False,
        "can_scroll_down": False,
        "omitted_elements": 0,
        "fingerprint": fingerprint,
    }


def contract(*steps, inputs=None, allowed_origins=None):
    return {
        "version": 1,
        "name": "Find report",
        "start_url": "https://example.test/",
        "allowed_origins": allowed_origins or ["https://example.test"],
        "inputs": inputs or [],
        "steps": list(steps),
    }


class BasicBrowser:
    def __init__(self):
        self.opened = None
        self.state = "home"

    def open(self, url):
        self.opened = url

    def observe(self):
        if self.state == "home":
            return observation("https://example.test/", "home", elements=[{
                "index": 1,
                "node_id": 10,
                "role": "searchbox",
                "name": "Search",
                "value": "",
                "checked": None,
                "operations": ["CLICK", "TYPE_TEXT", "SUBMIT"],
                "context": "",
                "destination": "",
            }])
        if self.state == "typed":
            result = self.observe_for("home")
            result["fingerprint"] = "typed"
            result["elements"][0]["value"] = "solar report"
            return result
        if self.state == "results":
            return observation(
                "https://example.test/results?q=solar",
                "results",
                text="Official Solar Report",
                elements=[{
                    "index": 1,
                    "node_id": 20,
                    "role": "link",
                    "name": "Official Solar Report",
                    "value": "",
                    "checked": None,
                    "operations": ["CLICK"],
                    "context": "Example Institute",
                    "destination": "/report",
                }],
            )
        return observation(
            "https://example.test/report",
            "report",
            title="Official Solar Report",
            text="Solar capacity reached 100 GW.",
        )

    def observe_for(self, state):
        current = self.state
        self.state = state
        result = deepcopy(self.observe())
        self.state = current
        return result

    def type_node(self, node_id, value):
        assert (node_id, value) == (10, "solar report")
        self.state = "typed"

    def submit_node(self, node_id):
        assert node_id == 10
        self.state = "results"

    def click_node(self, node_id):
        assert node_id == 20
        self.state = "report"

    def wait_for_page_ready(self, _previous_url, _previous_fingerprint):
        return True

    def scroll_down(self):
        return False

    def scroll_up(self):
        return False


def test_basic_task_runs_deterministic_search_navigation_and_assertion_without_models():
    task = parse_basic_task(contract(
        {
            "operation": "TYPE_TEXT",
            "target": {"role": "searchbox", "name": "Search"},
            "input": "query",
        },
        {"operation": "SUBMIT", "target": {"role": "searchbox", "name": "Search"}},
        {
            "operation": "CLICK",
            "target": {
                "role": "link",
                "name": "Official Solar Report",
                "context_contains": "Institute",
                "destination_contains": "/report",
            },
        },
        {"operation": "ASSERT", "check": {"text_contains": "100 GW", "title_contains": "Solar Report"}},
        {"operation": "DONE"},
        inputs=["query"],
    ))

    result = run_basic_task(BasicBrowser(), task, {"query": "solar report"})

    assert result["status"] == "completed"
    assert result["stop_reason"] == "task_complete"
    assert [step["operation"] for step in result["steps"]] == [
        "TYPE_TEXT", "SUBMIT", "CLICK", "ASSERT", "DONE",
    ]
    assert result["last_page"]["url"] == "https://example.test/report"
    assert "solar report" not in repr(result["steps"])


def test_basic_task_stops_before_clicking_generic_button():
    class ButtonBrowser(BasicBrowser):
        def observe(self):
            return observation("https://example.test/", "button", elements=[{
                "index": 1,
                "node_id": 30,
                "role": "button",
                "name": "Buy now",
                "operations": ["CLICK"],
                "context": "",
                "destination": "",
            }])

        def click_node(self, _node_id):
            raise AssertionError("Unsupported generic button must not be clicked")

    task = parse_basic_task(contract({
        "operation": "CLICK",
        "target": {"role": "button", "name": "Buy now"},
    }))

    result = run_basic_task(ButtonBrowser(), task)

    assert result["status"] == "stopped"
    assert result["stop_reason"] == "unsupported_click"
    assert result["steps"] == []


def test_basic_task_stops_before_cross_origin_link():
    class ExternalBrowser(BasicBrowser):
        def observe(self):
            return observation("https://example.test/", "external", elements=[{
                "index": 1,
                "node_id": 40,
                "role": "link",
                "name": "External",
                "operations": ["CLICK"],
                "context": "",
                "destination": "https://outside.test/path",
            }])

        def click_node(self, _node_id):
            raise AssertionError("Disallowed external link must not be clicked")

    task = parse_basic_task(contract({
        "operation": "CLICK",
        "target": {"role": "link", "name": "External"},
    }))

    result = run_basic_task(ExternalBrowser(), task)

    assert result["stop_reason"] == "origin_not_allowed"
    assert result["steps"] == []


def test_missing_target_reports_incomplete_perception_instead_of_absence():
    class FrameBrowser(BasicBrowser):
        def observe(self):
            return observation(
                "https://example.test/",
                "frame",
                perception={
                    "surface": "top_document_viewport_dom",
                    "frame_count": 1,
                    "visible_frame_count": 1,
                    "open_shadow_root_count": 0,
                    "text_limit_reached": False,
                    "element_limit_reached": False,
                },
            )

    task = parse_basic_task(contract({
        "operation": "CLICK",
        "target": {"role": "link", "name": "Inside frame"},
    }))

    result = run_basic_task(FrameBrowser(), task)

    assert result["stop_reason"] == "perception_incomplete"


def test_contract_validation_and_input_parsing_are_strict(tmp_path):
    raw = contract({"operation": "DONE"}, inputs=["query"])
    path = tmp_path / "task.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    task = load_basic_task(path)

    assert task.name == "Find report"
    assert parse_basic_inputs(["query=solar=report"]) == {"query": "solar=report"}
    with pytest.raises(ValueError, match="Duplicate"):
        parse_basic_inputs(["query=one", "query=two"])
    with pytest.raises(ValueError, match="unsupported fields"):
        parse_basic_task({**raw, "selector": "#unsafe"})
    with pytest.raises(ValueError, match="undeclared"):
        parse_basic_task(contract({
            "operation": "TYPE_TEXT",
            "target": {"role": "searchbox", "name": "Search"},
            "input": "missing",
        }))


def test_basic_task_runs_through_real_browser_boundary(tmp_path):
    task = parse_basic_task({
        "version": 1,
        "name": "Search fixture",
        "start_url": FIXTURE.as_uri(),
        "allowed_origins": ["file://"],
        "inputs": ["destination"],
        "steps": [
            {
                "operation": "TYPE_TEXT",
                "target": {"role": "searchbox", "name": "Destination"},
                "input": "destination",
            },
            {"operation": "SUBMIT", "target": {"role": "searchbox", "name": "Destination"}},
            {"operation": "ASSERT", "check": {"text_contains": "searched"}},
            {"operation": "DONE"},
        ],
    })

    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        result = run_basic_task(browser, task, {"destination": "Istanbul"})

    assert result["status"] == "completed"
    assert [step["operation"] for step in result["steps"]] == ["TYPE_TEXT", "SUBMIT", "ASSERT", "DONE"]
    assert result["steps"][0]["observation_changed"] is True


def test_basic_task_captures_unique_visible_line_and_pastes_through_executor():
    class CopyBrowser(BasicBrowser):
        def observe(self):
            result = super().observe()
            result["text"] = "Reference: solar report"
            return result

    task = parse_basic_task(contract(
        {
            "operation": "CAPTURE_TEXT",
            "line_contains": "Reference:",
            "extract_after": "Reference:",
            "save_as": "reference",
        },
        {
            "operation": "TYPE_TEXT",
            "target": {"role": "searchbox", "name": "Search"},
            "capture": "reference",
        },
        {"operation": "DONE"},
    ))

    result = run_basic_task(CopyBrowser(), task)

    assert result["status"] == "completed"
    assert result["captures"] == {
        "reference": {"value": "solar report", "url": "https://example.test/"},
    }
    assert [step["operation"] for step in result["steps"]] == ["CAPTURE_TEXT", "TYPE_TEXT", "DONE"]
    assert "solar report" not in repr(result["steps"])


def test_basic_capture_stops_on_ambiguous_or_incomplete_visible_text():
    class ReadOnlyBrowser(BasicBrowser):
        def __init__(self, text, perception=None):
            super().__init__()
            self.text = text
            self.perception = perception

        def observe(self):
            return observation(
                "https://example.test/", "copy", text=self.text, perception=self.perception,
            )

    task = parse_basic_task(contract({
        "operation": "CAPTURE_TEXT", "line_contains": "Reference:",
        "extract_after": "Reference:", "save_as": "reference",
    }, {"operation": "DONE"}))

    ambiguous = run_basic_task(ReadOnlyBrowser("Reference: A\nReference: B"), task)
    assert ambiguous["stop_reason"] == "capture_ambiguous"
    assert ambiguous["captures"] == {}
    incomplete = run_basic_task(ReadOnlyBrowser(
        "Reference: A", perception={"text_limit_reached": True},
    ), task)
    assert incomplete["stop_reason"] == "perception_incomplete"


def test_basic_capture_reference_must_be_prior_and_unique():
    target = {"role": "searchbox", "name": "Search"}
    with pytest.raises(ValueError, match="earlier CAPTURE_TEXT"):
        parse_basic_task(contract({"operation": "TYPE_TEXT", "target": target, "capture": "reference"}))
    with pytest.raises(ValueError, match="unique"):
        parse_basic_task(contract(
            {"operation": "CAPTURE_TEXT", "line_contains": "Reference:", "save_as": "reference"},
            {"operation": "CAPTURE_TEXT", "line_contains": "Reference:", "save_as": "reference"},
        ))


def test_basic_capture_and_paste_run_through_real_browser_boundary(tmp_path):
    fixture = Path(__file__).with_name("capture_fixture.html")
    task = parse_basic_task({
        "version": 1,
        "name": "Copy report reference",
        "start_url": fixture.as_uri(),
        "allowed_origins": ["file://"],
        "inputs": [],
        "steps": [
            {
                "operation": "CAPTURE_TEXT", "line_contains": "Reference: solar report",
                "extract_after": "Reference:", "save_as": "reference",
            },
            {
                "operation": "TYPE_TEXT", "target": {"role": "textbox", "name": "Reference"},
                "capture": "reference",
            },
            {"operation": "DONE"},
        ],
    })

    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        result = run_basic_task(browser, task)
        assert browser.observe()["elements"][0]["value"] == "solar report"

    assert result["status"] == "completed"
    assert result["captures"]["reference"]["value"] == "solar report"
