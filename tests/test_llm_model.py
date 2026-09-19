import json

import pytest

from brownie_agent.llm_model import predict_llm_action


def observation():
    return {
        "url": "https://example.test/", "title": "Search", "text": "Search catalog",
        "viewport": {"scroll_y": 0, "document_height": 800},
        "elements": [{"index": 1, "node_id": 987, "role": "searchbox", "name": "Search",
                      "value": "", "operations": ["CLICK", "TYPE_TEXT", "SUBMIT"]}],
        "can_scroll_up": False, "can_scroll_down": False, "fingerprint": "private-fingerprint",
    }


def answer(choice):
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(choice)}}]}


def test_llm_receives_public_state_and_returns_same_action_contract(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "shared-key")

    def post(url, key, body):
        assert url.endswith("/openai/chat/completions")
        assert key == "shared-key"
        assert body["response_format"]["json_schema"]["strict"] is True
        schema = body["response_format"]["json_schema"]["schema"]
        assert "SCROLL_UP" not in schema["properties"]["operation"]["enum"]
        state = json.loads(body["messages"][1]["content"])
        assert state["action_space"]["TYPE_TEXT"] == [1]
        assert state["state"]["goal"] == "Search laptops"
        assert "node_id" not in json.dumps(body)
        assert "private-fingerprint" not in json.dumps(body)
        return answer({"operation": "TYPE_TEXT", "target": 1, "text_mode": "SEARCH_SEED"})

    result = predict_llm_action(observation(), "Search laptops", post=post)
    assert result["target_name"] == "Search"
    assert result["source"] == "llm"
    assert result["executed"] is False
    assert "confidence" not in result


@pytest.mark.parametrize("choice", [
    {"operation": "CLICK", "target": 999, "text_mode": None},
    {"operation": "CLICK", "target": True, "text_mode": None},
    {"operation": "SCROLL_UP", "target": None, "text_mode": None},
    {"operation": "TYPE_TEXT", "target": 1, "text_mode": "invented"},
    {"operation": "TYPE_TEXT", "target": 1, "text_mode": "FIELD_VALUE", "text": "invented"},
    {"operation": "CLICK", "target": 1, "text_mode": None, "selector": "#search"},
])
def test_invalid_choices_stop_without_model_fallback(monkeypatch, choice):
    monkeypatch.setenv("GEMINI_API_KEY", "shared-key")
    monkeypatch.setenv("STEERING_MODEL_FALLBACKS", "unused-model")
    calls = []

    def post(_url, _key, body):
        calls.append(body["model"])
        return answer(choice)

    with pytest.raises(ValueError):
        predict_llm_action(observation(), "Search laptops", post=post)
    assert len(calls) == 1
