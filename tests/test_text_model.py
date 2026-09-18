import json

import pytest

from brownie_agent.state import decision_state, text_field_state
from brownie_agent.text_model import generate_field_text


def observation():
    return {
        "url": "https://example.test/search?session=private#results",
        "title": "Search",
        "text": "Private visible page material",
        "viewport": {"width": 1120, "height": 780, "scroll_y": 0, "document_height": 1200},
        "elements": [
            {
                "index": 1,
                "node_id": 41,
                "role": "textbox",
                "name": "From",
                "value": "Zurich",
                "checked": None,
                "operations": ["CLICK", "TYPE_TEXT"],
            },
            {
                "index": 2,
                "node_id": 42,
                "role": "textbox",
                "name": "To",
                "value": "",
                "checked": None,
                "operations": ["CLICK", "TYPE_TEXT"],
            },
        ],
        "can_scroll_up": False,
        "can_scroll_down": True,
        "fingerprint": "private-fingerprint",
    }


def test_decision_state_keeps_factual_progress_without_private_node_ids():
    recent = [{"operation": "TYPE_TEXT", "target_name": "From", "text": "Zurich", "status": "executed"}]

    state = decision_state(observation(), "Travel from Zurich to London", recent)

    assert state["goal"] == "Travel from Zurich to London"
    assert state["recent_steps"] == recent
    assert state["current_elements"][0]["value"] == "Zurich"
    assert "node_id" not in json.dumps(state)
    assert "fingerprint" not in json.dumps(state)


def test_text_state_omits_page_text_field_values_queries_and_typed_history():
    recent = [{"operation": "TYPE_TEXT", "target_name": "From", "text": "Zurich", "status": "executed"}]

    state = text_field_state(
        observation(),
        "Travel from Zurich to London",
        {"operation": "TYPE_TEXT", "target": 2},
        recent,
    )
    serialized = json.dumps(state)

    assert state["selected_field"] == {"role": "textbox", "name": "To"}
    assert state["other_visible_fields"] == [{"role": "textbox", "name": "From", "filled": True}]
    assert state["current_page"]["url_without_query"] == "https://example.test/search"
    assert "Private visible page material" not in serialized
    assert "Zurich" in state["goal"]
    assert '"text": "Zurich"' not in serialized
    assert "session=private" not in serialized
    assert "node_id" not in serialized


def test_generate_field_text_uses_gemini_compatible_strict_json(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("TEXT_MODEL", "gemini-test")
    captured = {}

    def fake_post(url, key, body):
        captured.update(url=url, key=key, body=body)
        return {
            "choices": [{"message": {"content": '{"text":"London"}'}}],
            "usage": {"prompt_tokens": 10},
        }

    value, metadata = generate_field_text({"goal": "Travel to London"}, post=fake_post)

    assert value == "London"
    assert metadata["model"] == "gemini-test"
    assert captured["url"] == "https://model.example/v1/chat/completions"
    assert captured["key"] == "test-key"
    assert captured["body"]["response_format"]["type"] == "json_schema"
    assert json.loads(captured["body"]["messages"][1]["content"])["goal"] == "Travel to London"


@pytest.mark.parametrize("content", ['{"text":null}', '{"text":"","explanation":"missing"}', "not json"])
def test_generate_field_text_rejects_missing_or_non_exact_output(monkeypatch, content):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test-key")

    def fake_post(_url, _key, _body):
        return {"choices": [{"message": {"content": content}}]}

    with pytest.raises(ValueError, match="nothing typed"):
        generate_field_text({"goal": "Missing value"}, post=fake_post)
