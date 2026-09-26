import json
from copy import deepcopy
from pathlib import Path

import pytest

from brownie_agent import cli, llm_model
from brownie_agent.actions import StaleObservation
from brownie_agent.basic import parse_basic_task
from brownie_agent.chat_model import ModelHTTPError
from brownie_agent.text_model import generate_field_text


@pytest.fixture
def browser(monkeypatch):
    class Browser:
        def __init__(self):
            self.mutations = []
            self.changed = False
            self.page = {
                "url": "https://example.test/", "title": "Catalog", "text": "Search",
                "viewport": {"scroll_y": 0, "document_height": 800},
                "elements": [{"index": 1, "node_id": 99, "role": "searchbox", "name": "Search",
                              "operations": ["CLICK", "TYPE_TEXT", "SUBMIT"], "value": ""}],
                "can_scroll_up": False, "can_scroll_down": False, "omitted_elements": 0,
                "fingerprint": "initial",
            }

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def open(self, *_args, **_kwargs):
            pass

        def observe(self):
            result = deepcopy(self.page)
            if self.changed:
                result["elements"][0]["name"] = "Changed search field"
            return {**result, "fingerprint": "changed" if self.changed else "initial"}

        def type_node(self, node, value):
            self.mutations.append(("TYPE_TEXT", node, value))

    browser = Browser()
    monkeypatch.setattr(cli, "BrowserSession", lambda **_: browser)
    monkeypatch.setattr(cli, "load_env", lambda _: None)
    monkeypatch.setenv("GEMINI_API_KEY", "shared-key")
    monkeypatch.setenv("STEERING_MODEL", "steering-primary")
    monkeypatch.setenv("STEERING_MODEL_FALLBACKS", "steering-backup")
    monkeypatch.setenv("TEXT_MODEL", "text-primary")
    monkeypatch.setenv("TEXT_MODEL_FALLBACKS", "text-backup")
    monkeypatch.setattr("brownie_agent.model.predict_action", lambda *_: pytest.fail("Jev should not be called"))
    return browser


def limited(model):
    return ModelHTTPError(429, {"error": {"details": [{
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [{"quotaDimensions": {"model": model}}],
    }]}})


def set_args(monkeypatch, mode="--step"):
    monkeypatch.setattr("sys.argv", [
        "brownie", mode, "--steerer", "llm", "--goal", "Find laptops", "--json", "https://example.test/",
    ])


@pytest.mark.parametrize("stale", [False, True])
def test_llm_and_text_fallbacks_finish_before_one_validated_browser_mutation(monkeypatch, browser, capsys, stale):
    set_args(monkeypatch)
    calls = []

    def post(_url, _key, body):
        model = body["model"]
        calls.append(model)
        if model.endswith("primary"):
            raise limited(model)
        if model == "steering-backup":
            value = {"operation": "TYPE_TEXT", "target": 1, "text_mode": "SEARCH_SEED"}
        else:
            browser.changed = stale
            value = {"text": "laptops"}
        return {"choices": [{"message": {"content": json.dumps(value)}}]}

    adapter = llm_model.predict_llm_action
    monkeypatch.setattr(llm_model, "predict_llm_action", lambda *args: adapter(*args, post=post))
    monkeypatch.setattr(cli, "generate_field_text", lambda context: generate_field_text(context, post=post))
    if stale:
        with pytest.raises(StaleObservation):
            cli.main()
        assert browser.mutations == []
    else:
        cli.main()
        result = json.loads(capsys.readouterr().out)
        assert result["prediction"]["source"] == "llm"
        assert result["prediction"]["model"] == "steering-backup"
        assert result["execution"]["text_model"]["model"] == "text-backup"
        assert browser.mutations == [("TYPE_TEXT", 99, "laptops")]
    assert calls == ["steering-primary", "steering-backup", "text-primary", "text-backup"]


def test_predict_does_not_generate_text_or_execute(monkeypatch, browser, capsys):
    set_args(monkeypatch, "--predict")
    monkeypatch.setattr(llm_model, "predict_llm_action", lambda *_: {
        "operation": "TYPE_TEXT", "target": 1, "text_mode": "SEARCH_SEED",
    })
    monkeypatch.setattr(cli, "generate_field_text", lambda _: pytest.fail("Prediction must not generate text"))
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["prediction"]["source"] == "llm"
    assert browser.mutations == []


def test_login_guard_prevents_llm_calls(monkeypatch, browser, capsys):
    set_args(monkeypatch)
    browser.page["access"] = {"visible_password_field": True}
    monkeypatch.setattr(llm_model, "predict_llm_action", lambda *_: pytest.fail("Login page must not reach LLM"))
    cli.main()
    assert json.loads(capsys.readouterr().out)["execution"]["status"] == "access_blocked"
    assert browser.mutations == []


def test_exhausted_model_chain_never_executes_a_browser_action(monkeypatch, browser):
    set_args(monkeypatch)
    calls = []

    def post(_url, _key, body):
        calls.append(body["model"])
        raise limited(body["model"])

    adapter = llm_model.predict_llm_action
    monkeypatch.setattr(llm_model, "predict_llm_action", lambda *args: adapter(*args, post=post))
    with pytest.raises(RuntimeError, match="All configured models"):
        cli.main()
    assert calls == ["steering-primary", "steering-backup"]
    assert browser.mutations == []


def test_steerer_flag_requires_a_model_mode(monkeypatch):
    monkeypatch.setattr("sys.argv", ["brownie", "--steerer", "llm", "https://example.test/"])
    monkeypatch.setattr(cli, "BrowserSession", lambda **_: pytest.fail("Invalid flags must stop before browser launch"))
    with pytest.raises(SystemExit):
        cli.main()


def test_search_needs_no_url_and_launches_headed_isolated_browser(monkeypatch, capsys):
    captured = {}

    class Context:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            assert captured["waited"] is True
            captured["exited"] = True

    def session(**options):
        captured["browser_options"] = options
        return Context()

    def search(_browser, goal, **options):
        captured["goal"] = goal
        captured["search_options"] = options
        return {
            "goal": goal,
            "status": "source_read",
            "stop_reason": "one_source_read",
            "search_engine": "https://duckduckgo.com/",
            "search_query": "fixture query",
            "steps": [],
            "last_page": {"url": "https://example.test/report", "title": "Report"},
            "source": {
                "url": "https://example.test/report", "title": "Report", "material": "Evidence",
                "seen_elements": [], "scrolls": 0, "stop_reason": "bottom",
            },
        }

    monkeypatch.setattr("sys.argv", [
        "brownie", "--search", "--keep-open", "--steerer", "llm", "--goal", "Find the report", "--json",
    ])
    monkeypatch.setattr(cli, "BrowserSession", session)
    monkeypatch.setattr(cli, "run_search", search)
    monkeypatch.setattr(cli, "load_env", lambda _: None)
    monkeypatch.setattr("builtins.input", lambda: captured.setdefault("waited", True) and "")

    cli.main()

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "source_read"
    assert captured["goal"] == "Find the report"
    assert captured["browser_options"]["headed"] is True
    assert captured["browser_options"]["cdp_url"] is None
    assert captured["search_options"]["provider"] == "llm"
    assert captured["waited"] is True
    assert captured["exited"] is True


def test_research_needs_no_url_and_passes_source_budget(monkeypatch, capsys):
    captured = {}

    class Context:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr("sys.argv", [
        "brownie", "--research", "--steerer", "llm", "--goal", "Compare reports",
        "--max-sources", "4", "--json",
    ])
    monkeypatch.setattr(cli, "BrowserSession", lambda **options: captured.setdefault("browser", options) and Context())
    monkeypatch.setattr(cli, "load_env", lambda _: None)
    monkeypatch.setattr(cli, "load_decisions", lambda: [])

    def research(_browser, goal, **options):
        captured["goal"], captured["options"] = goal, options
        return {
            "mode": "research", "goal": goal, "status": "needs_user",
            "stop_reason": "user_input_required", "question": "Which year?",
            "answer": None, "cited_sources": [], "sources": [],
        }

    monkeypatch.setattr(cli, "run_research", research)
    cli.main()

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "needs_user"
    assert captured["goal"] == "Compare reports"
    assert captured["options"] == {"provider": "llm", "max_sources": 4, "accepted_decisions": []}
    assert captured["browser"]["headed"] is True


def test_research_dialogue_reads_one_answer_for_the_controller(monkeypatch, capsys):
    captured = {}

    class Context:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr("sys.argv", [
        "brownie", "--research", "--research-dialogue", "--goal", "Compare reports", "--json",
    ])
    monkeypatch.setattr(cli, "BrowserSession", lambda **_options: Context())
    monkeypatch.setattr(cli, "load_env", lambda _: None)
    monkeypatch.setattr("builtins.input", lambda: "Use 2025")

    def research(_browser, goal, **options):
        captured["answer"] = options["ask_user"]("Which year?")
        return {
            "mode": "research", "goal": goal, "status": "stopped",
            "stop_reason": "fixture", "question": None, "answer": None,
            "cited_sources": [], "sources": [],
        }

    monkeypatch.setattr(cli, "run_research", research)
    cli.main()

    assert json.loads(capsys.readouterr().out)["stop_reason"] == "fixture"
    assert captured["answer"] == "Use 2025"


def test_research_dialogue_flag_requires_research(monkeypatch):
    monkeypatch.setattr("sys.argv", ["brownie", "--research-dialogue", "https://example.test/"])
    monkeypatch.setattr(cli, "BrowserSession", lambda **_: pytest.fail("Invalid flags must stop before launch"))

    with pytest.raises(SystemExit):
        cli.main()


def test_managed_cdp_search_starts_chrome_then_attaches(monkeypatch, capsys):
    captured = {"events": []}

    class ChromeContext:
        def __init__(self, **options):
            captured["managed_options"] = options

        def __enter__(self):
            captured["events"].append("chrome_started")
            return self

        def __exit__(self, *_args):
            captured["events"].append("chrome_stopped")

    class BrowserContext:
        def __init__(self, **options):
            captured["browser_options"] = options

        def __enter__(self):
            captured["events"].append("browser_attached")
            return object()

        def __exit__(self, *_args):
            captured["events"].append("browser_detached")

    monkeypatch.setattr("sys.argv", [
        "brownie", "--managed-cdp", "--search", "--goal", "Find the report", "--json",
    ])
    monkeypatch.setattr(cli, "ManagedChrome", ChromeContext)
    monkeypatch.setattr(cli, "BrowserSession", BrowserContext)
    monkeypatch.setattr(cli, "load_env", lambda _: None)
    monkeypatch.setattr(cli, "run_search", lambda *_args, **_options: {
        "status": "source_read",
        "stop_reason": "one_source_read",
        "search_query": "fixture query",
        "last_page": {"url": "https://example.test/report", "title": "Report"},
        "source": {"url": "https://example.test/report", "title": "Report", "material": "Evidence",
                   "scrolls": 0, "stop_reason": "bottom"},
    })

    cli.main()

    assert json.loads(capsys.readouterr().out)["status"] == "source_read"
    assert captured["managed_options"]["profile_dir"] == Path(".browser-profile-cdp")
    assert captured["managed_options"]["endpoint"] == "http://127.0.0.1:9222"
    assert captured["browser_options"]["cdp_url"] == "http://127.0.0.1:9222"
    assert captured["events"] == ["chrome_started", "browser_attached", "browser_detached", "chrome_stopped"]


def test_basic_task_needs_no_url_and_uses_no_model_configuration(monkeypatch, capsys):
    captured = {}
    task = parse_basic_task({
        "version": 1,
        "name": "Fixture task",
        "start_url": "https://example.test/",
        "allowed_origins": ["https://example.test"],
        "inputs": ["query"],
        "steps": [{"operation": "DONE"}],
    })

    class Context:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr("sys.argv", [
        "brownie",
        "--basic-task", "fixture.json",
        "--input", "query=solar report",
        "--json",
    ])
    monkeypatch.setattr(cli, "load_basic_task", lambda path: captured.setdefault("path", path) and task)
    monkeypatch.setattr(
        cli,
        "parse_basic_inputs",
        lambda values: captured.setdefault("raw_inputs", values) and {"query": "solar report"},
    )
    monkeypatch.setattr(cli, "BrowserSession", lambda **options: captured.setdefault("browser", options) and Context())
    monkeypatch.setattr(cli, "load_env", lambda *_: pytest.fail("Basic mode must not load model configuration"))
    monkeypatch.setattr(
        cli,
        "run_basic_task",
        lambda _browser, received_task, inputs: {
            "mode": "basic",
            "task": received_task.name,
            "status": "completed",
            "stop_reason": "task_complete",
            "steps": [],
            "last_page": {"url": received_task.start_url, "title": "Fixture"},
            "output": None,
            "inputs_seen": inputs,
        },
    )

    cli.main()

    result = json.loads(capsys.readouterr().out)
    assert captured["path"] == Path("fixture.json")
    assert captured["raw_inputs"] == ["query=solar report"]
    assert result["status"] == "completed"
    assert result["inputs_seen"] == {"query": "solar report"}


def test_input_without_basic_task_stops_before_browser_launch(monkeypatch):
    monkeypatch.setattr("sys.argv", ["brownie", "--input", "query=value", "https://example.test/"])
    monkeypatch.setattr(cli, "BrowserSession", lambda **_: pytest.fail("Invalid flags must stop before browser launch"))

    with pytest.raises(SystemExit):
        cli.main()
