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
        moves = body["questions"]["move"]["criteria"]
        return {
            "model": "jev-test",
            "answers": {
                "move": {
                    "choice": "CLICK:2",
                    "probabilities": {
                        move: (0.7 if move == "CLICK:2" else 0.3 / (len(moves) - 1))
                        for move in moves
                    },
                    "confidence": 0.8,
                },
            },
        }

    prediction = predict_action(observation(), "Run the search", post=fake_post)

    assert prediction["operation"] == "CLICK"
    assert prediction["target"] == 2
    assert prediction["target_name"] == "Search"
    assert prediction["executed"] is False
    assert captured["key"] == "test-key"
    assert captured["body"]["questions"]["move"]["criteria"].keys() == {
        "CLICK:1", "CLICK:2", "TYPE_TEXT:1", "DONE", "BLOCKED",
    }
    assert captured["body"]["state"]["goal"] == "Run the search"
    assert captured["body"]["state"]["current_page"]["visible_text"] == "Search places"
    assert "current_elements" not in captured["body"]["state"]
    serialized_request = json.dumps(captured["body"])
    assert "node_id" not in serialized_request
    assert "not-sent" not in serialized_request


def test_predict_action_rejects_invalid_selected_target(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")

    def fake_post(_url, _key, body):
        moves = body["questions"]["move"]["criteria"]
        return {
            "answers": {
                "move": {
                    "choice": "CLICK:99",
                    "probabilities": {move: 1 / len(moves) for move in moves},
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
        moves = body["questions"]["move"]["criteria"]
        return {
            "model": "jev-test",
            "answers": {
                "move": {
                    "choice": "TYPE_TEXT:1",
                    "probabilities": {
                        move: (0.8 if move == "TYPE_TEXT:1" else 0.2 / (len(moves) - 1))
                        for move in moves
                    },
                    "confidence": 0.8,
                },
                "text_mode_1": {"choice": "SEARCH_SEED", "probabilities": modes, "confidence": 0.7},
            },
        }

    prediction = predict_action(observation(), "Find a quiet hotel with free cancellation", post=fake_post)

    assert prediction["operation"] == "TYPE_TEXT"
    assert prediction["target"] == 1
    assert prediction["text_mode"] == "SEARCH_SEED"
    assert prediction["text_mode_probabilities"] == modes
    assert captured["questions"]["text_mode_1"]["instructions"]["field"] == {
        "index": 1, "role": "searchbox", "name": "Destination",
    }
    assert "text_mode_2" not in captured["questions"]


def test_predict_action_can_select_submit_for_a_form_field(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    state = observation()
    state["elements"][0]["operations"].append("SUBMIT")
    state["elements"][0]["value"] = "completed query"

    def fake_post(_url, _key, body):
        moves = body["questions"]["move"]["criteria"]
        return {
            "model": "jev-test",
            "answers": {
                "move": {
                    "choice": "SUBMIT:1",
                    "probabilities": {
                        move: (0.8 if move == "SUBMIT:1" else 0.2 / (len(moves) - 1))
                        for move in moves
                    },
                    "confidence": 0.8,
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
