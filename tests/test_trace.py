import json

from brownie_agent.chat_model import complete_chat
from brownie_agent.trace import TraceRecorder, trace_event


def test_trace_writes_exact_jsonl_and_text_only_html(tmp_path):
    path = tmp_path / "run.jsonl"
    with TraceRecorder(path) as recorder:
        trace_event("controller_memory", {
            "sent_to_provider": [{"operation": "CLICK"}],
            "stored_not_sent": {"visited_pages": ["https://example.test/"]},
        })
        trace_event("model_request", {
            "provider": "jev",
            "role": "steering",
            "model": "jev-test",
            "body": {"state": {"goal": "Find report"}, "questions": {"operation": {"type": "choice"}}},
        })
        trace_event("model_response", {
            "provider": "jev",
            "role": "steering",
            "model": "jev-test",
            "response": {"answers": {"operation": {
                "choice": "CLICK", "confidence": 0.61, "probabilities": {"CLICK": 0.61, "BLOCKED": 0.39},
            }}},
        })

    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert [event["event"] for event in events] == ["controller_memory", "model_request", "model_response"]
    assert events[1]["data"]["body"]["state"]["goal"] == "Find report"
    output = recorder.html_path.read_text()
    assert "Memory sent to provider" in output
    assert "Stored controller memory not sent" in output
    assert "Exact request body, without credentials" in output
    assert "0.61" in output
    assert "screenshot" not in output.lower()


def test_trace_requires_jsonl_suffix(tmp_path):
    try:
        TraceRecorder(tmp_path / "run.txt")
    except ValueError as error:
        assert ".jsonl" in str(error)
    else:
        raise AssertionError("A non-JSONL trace path must be rejected")


def test_chat_transport_traces_each_exact_model_request_and_response(monkeypatch, tmp_path):
    class Cooldowns:
        def access(self, _identity, _now, _until=None):
            return 0

    monkeypatch.setenv("GEMINI_API_KEY", "private-key-not-traced")
    monkeypatch.setenv("STEERING_MODEL", "fixture-model")
    monkeypatch.delenv("STEERING_MODEL_FALLBACKS", raising=False)
    captured = {}

    def post(url, key, body):
        captured.update(url=url, key=key, body=body)
        return {"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 12}}

    path = tmp_path / "llm.jsonl"
    with TraceRecorder(path):
        complete_chat(
            "STEERING",
            {"messages": [{"role": "user", "content": "context"}]},
            post=post,
            cooldowns=Cooldowns(),
            clock=lambda: 0,
        )

    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert [event["event"] for event in events] == ["model_request", "model_response"]
    assert events[0]["data"]["body"] == captured["body"]
    assert events[1]["data"]["response"]["usage"]["prompt_tokens"] == 12
    serialized = path.read_text()
    assert captured["key"] == "private-key-not-traced"
    assert "private-key-not-traced" not in serialized
