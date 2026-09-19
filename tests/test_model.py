import json

import pytest

from brownie_agent.config import load_env
from brownie_agent.model import predict_action


def observation():
    return {
        "url": "https://example.test/",
        "title": "Example",
        "text": "Search places",
        "viewport": {"width": 1120, "height": 780, "scroll_y": 0, "document_height": 780},
        "elements": [
            {
                "index": 1,
                "node_id": 41,
                "role": "searchbox",
                "name": "Destination",
                "value": "",
                "checked": False,
                "operations": ["CLICK", "TYPE_TEXT"],
            },
            {
                "index": 2,
                "node_id": 42,
                "role": "button",
                "name": "Search",
                "value": "",
                "checked": None,
                "operations": ["CLICK"],
            },
        ],
        "can_scroll_up": False,
        "can_scroll_down": False,
        "fingerprint": "not-sent",
    }


def test_predict_action_validates_operation_and_selected_target(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    captured = {}

    def fake_post(url, key, body):
        captured.update(url=url, key=key, body=body)
        return {
            "model": "jev-test",
            "answers": {
                "operation": {
                    "choice": "CLICK",
                    "probabilities": {"CLICK": 0.7, "TYPE_TEXT": 0.1, "DONE": 0.1, "BLOCKED": 0.1},
                    "confidence": 0.8,
                },
                "click_target": {
                    "choice": "2",
                    "probabilities": {"1": 0.2, "2": 0.8},
                    "confidence": 0.9,
                },
                "type_text_target": {
                    "choice": "1",
                    "probabilities": {"1": 1.0},
                    "confidence": 1.0,
                },
            },
        }

    prediction = predict_action(observation(), "Run the search", post=fake_post)

    assert prediction["operation"] == "CLICK"
    assert prediction["target"] == 2
    assert prediction["target_name"] == "Search"
    assert prediction["executed"] is False
    assert captured["key"] == "test-key"
    assert captured["body"]["questions"]["click_target"]["criteria"].keys() == {"1", "2"}
    assert captured["body"]["state"]["goal"] == "Run the search"
    assert captured["body"]["state"]["current_page"]["visible_text"] == "Search places"
    serialized_request = json.dumps(captured["body"])
    assert "node_id" not in serialized_request
    assert "not-sent" not in serialized_request


def test_predict_action_rejects_invalid_selected_target(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")

    def fake_post(_url, _key, _body):
        return {
            "answers": {
                "operation": {
                    "choice": "CLICK",
                    "probabilities": {"CLICK": 0.7, "TYPE_TEXT": 0.1, "DONE": 0.1, "BLOCKED": 0.1},
                    "confidence": 0.8,
                },
                "click_target": {
                    "choice": "99",
                    "probabilities": {"99": 1.0},
                    "confidence": 1.0,
                },
            }
        }

    with pytest.raises(ValueError, match="Invalid TypeSafe choice response"):
        predict_action(observation(), "Run the search", post=fake_post)


def test_predict_action_returns_mode_for_selected_text_field(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    captured = {}
    modes = {"SEARCH_SEED": 0.8, "FIELD_VALUE": 0.1, "IDENTIFIER": 0.04, "FREEFORM": 0.04, "VALUE_MISSING": 0.02}

    def fake_post(_url, _key, body):
        captured.update(body)
        return {
            "model": "jev-test",
            "answers": {
                "operation": {
                    "choice": "TYPE_TEXT",
                    "probabilities": {"CLICK": 0.1, "TYPE_TEXT": 0.8, "DONE": 0.05, "BLOCKED": 0.05},
                    "confidence": 0.8,
                },
                "click_target": {
                    "choice": "1",
                    "probabilities": {"1": 0.4, "2": 0.6},
                    "confidence": 0.2,
                },
                "type_text_target": {
                    "choice": "1",
                    "probabilities": {"1": 1.0},
                    "confidence": 1.0,
                },
                "text_mode_1": {"choice": "SEARCH_SEED", "probabilities": modes, "confidence": 0.7},
            },
        }

    prediction = predict_action(observation(), "Find a quiet hotel with free cancellation", post=fake_post)

    assert prediction["operation"] == "TYPE_TEXT"
    assert prediction["target"] == 1
    assert prediction["text_mode"] == "SEARCH_SEED"
    assert prediction["text_mode_probabilities"] == modes
    assert captured["questions"]["text_mode_1"]["instructions"]["field"]["name"] == "Destination"
    assert "text_mode_2" not in captured["questions"]


def test_predict_action_can_select_submit_for_a_form_field(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    state = observation()
    state["elements"][0]["operations"].append("SUBMIT")

    def fake_post(_url, _key, _body):
        return {
            "model": "jev-test",
            "answers": {
                "operation": {
                    "choice": "SUBMIT",
                    "probabilities": {
                        "CLICK": 0.05,
                        "TYPE_TEXT": 0.05,
                        "SUBMIT": 0.8,
                        "DONE": 0.05,
                        "BLOCKED": 0.05,
                    },
                    "confidence": 0.8,
                },
                "submit_target": {
                    "choice": "1",
                    "probabilities": {"1": 1.0},
                    "confidence": 1.0,
                },
            },
        }

    prediction = predict_action(observation=state, goal="Submit the completed search", post=fake_post)

    assert prediction["operation"] == "SUBMIT"
    assert prediction["target"] == 1
    assert prediction["target_name"] == "Destination"


def test_load_env_does_not_replace_existing_process_value(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TYPESAFE_API_KEY=file-key\nTYPESAFE_MODEL=jev-test\n")
    monkeypatch.setenv("TYPESAFE_API_KEY", "process-key")
    monkeypatch.delenv("TYPESAFE_MODEL", raising=False)

    loaded = load_env(env_file)

    assert loaded == env_file
    assert __import__("os").environ["TYPESAFE_API_KEY"] == "process-key"
    assert __import__("os").environ["TYPESAFE_MODEL"] == "jev-test"


def test_load_env_defaults_to_runtime_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BROWNIE_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    (tmp_path / ".env").write_text("TYPESAFE_API_KEY=working-key\n")

    loaded = load_env()

    assert loaded == tmp_path / ".env"
    assert __import__("os").environ["TYPESAFE_API_KEY"] == "working-key"


def test_runtime_directory_override_controls_default_env_location(tmp_path, monkeypatch):
    runtime = tmp_path / "private-runtime"
    runtime.mkdir()
    (runtime / ".env").write_text("TYPESAFE_MODEL=runtime-model\n")
    monkeypatch.setenv("BROWNIE_RUNTIME_DIR", str(runtime))
    monkeypatch.delenv("TYPESAFE_MODEL", raising=False)

    loaded = load_env()

    assert loaded == runtime / ".env"
    assert __import__("os").environ["TYPESAFE_MODEL"] == "runtime-model"
