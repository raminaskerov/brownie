import json
from copy import deepcopy

import pytest

from brownie_agent.actions import StaleObservation, execute_prediction
from brownie_agent.cli import print_prediction, print_step
from brownie_agent.steering import SteeringRoute, steer_action, validate_steering_choice


def observation():
    return {
        "url": "https://example.test/",
        "title": "Example",
        "text": "Search products",
        "viewport": {"width": 1000, "height": 700, "scroll_y": 0, "document_height": 700},
        "elements": [
            {
                "index": 1,
                "node_id": 91,
                "role": "searchbox",
                "name": "Products",
                "value": "",
                "checked": None,
                "operations": ["CLICK", "TYPE_TEXT", "SUBMIT"],
            },
            {
                "index": 2,
                "node_id": 92,
                "role": "button",
                "name": "Search",
                "value": "",
                "checked": None,
                "operations": ["CLICK"],
            },
        ],
        "can_scroll_up": False,
        "can_scroll_down": False,
        "fingerprint": "snapshot-a",
    }


def test_any_provider_uses_the_same_validated_action_contract():
    def fake_llm(_observation, _goal, _recent_steps):
        return {
            "operation": "CLICK",
            "target": 2,
            "target_name": "provider cannot forge this",
            "reason": "The filled form is ready.",
        }

    choice = steer_action(
        observation(),
        "Search for a laptop",
        provider="llm",
        providers={"llm": fake_llm},
    )

    assert choice["operation"] == "CLICK"
    assert choice["target"] == 2
    assert choice["target_name"] == "Search"
    assert choice["source"] == "llm"
    assert choice["reason"] == "The filled form is ready."
    assert choice["executed"] is False


def test_provider_cannot_select_an_unobserved_target():
    with pytest.raises(ValueError, match="unavailable target"):
        validate_steering_choice(
            observation(),
            {"operation": "CLICK", "target": 99},
            source="llm",
        )


def test_type_text_requires_a_bounded_text_mode_from_every_provider():
    with pytest.raises(ValueError, match="valid text mode"):
        validate_steering_choice(
            observation(),
            {"operation": "TYPE_TEXT", "target": 1},
            source="llm",
        )


def test_non_target_operation_rejects_a_provider_target():
    with pytest.raises(ValueError, match="supplied a target"):
        validate_steering_choice(
            observation(),
            {"operation": "DONE", "target": 1},
            source="llm",
        )


def test_router_can_switch_providers_per_decision_without_changing_execution():
    called = []

    def jev(_observation, _goal, _history):
        called.append("jev")
        return {"operation": "CLICK", "target": 2}

    def llm(_observation, _goal, _history):
        called.append("llm")
        return {"operation": "TYPE_TEXT", "target": 1, "text_mode": "SEARCH_SEED"}

    def choose(context):
        assert context["action_space"]["TYPE_TEXT"] == [1]
        assert "node_id" not in json.dumps(context)
        assert "snapshot-a" not in json.dumps(context)
        # A test-only switch, not a production workload heuristic.
        return SteeringRoute(context["state"]["goal"], "Fixture routing decision")

    for provider, expected in (("llm", "TYPE_TEXT"), ("jev", "CLICK")):
        choice = steer_action(observation(), provider, providers={"jev": jev, "llm": llm}, router=choose)
        assert choice["operation"] == expected
        assert choice["source"] == provider
        assert choice["routing"] == {"provider": provider, "reason": "Fixture routing decision"}
    assert called == ["llm", "jev"]


def test_provider_inputs_are_public_detached_and_cannot_expand_executable_targets():
    original = observation()
    before = deepcopy(original)
    history = [{"operation": "CLICK", "node_id": 123, "text": str(i)} for i in range(10)]

    def provider(public, _goal, recent):
        serialized = json.dumps([public, recent])
        assert "node_id" not in serialized
        assert "fingerprint" not in serialized
        assert len(recent) == 8
        assert recent[0]["text"] == "2"
        public["elements"][0]["operations"].append("INVENTED")
        public["elements"][0]["index"] = 99
        public["viewport"]["width"] = 1
        recent[0]["text"] = "changed"
        return {"operation": "CLICK", "target": 99}

    with pytest.raises(ValueError, match="unavailable target"):
        steer_action(original, "Search", history, provider="llm", providers={"llm": provider})
    assert original == before
    assert history[2]["text"] == "2"


def test_router_cannot_change_the_state_given_to_the_selected_provider():
    def router(context):
        context["state"]["current_elements"][0]["operations"].clear()
        context["action_space"]["CLICK"].clear()
        return SteeringRoute("llm", "Test")

    def provider(public, _goal, _recent):
        assert public["elements"][0]["operations"] == ["CLICK", "TYPE_TEXT", "SUBMIT"]
        return {"operation": "CLICK", "target": 2, "source": "forged", "routing": {"reason": "forged"}}

    choice = steer_action(observation(), "Search", router=router, providers={"llm": provider})
    assert choice["source"] == "llm"
    assert choice["routing"]["reason"] == "Test"


@pytest.mark.parametrize("route", [None, "llm", SteeringRoute("llm", ""), SteeringRoute("missing", "Test")])
def test_invalid_routes_stop_before_any_provider_call(route):
    def forbidden(*_args):
        pytest.fail("Invalid routing must not call a provider")

    with pytest.raises(ValueError):
        steer_action(observation(), "Search", router=lambda _: route, providers={"jev": forbidden})


def test_explicit_provider_and_router_are_mutually_exclusive():
    with pytest.raises(ValueError, match="either"):
        steer_action(observation(), "Search", provider="jev", router=lambda _: pytest.fail("Router was called"))


def test_provider_failure_does_not_retry_or_fall_back():
    calls = []

    def fail(*_args):
        calls.append("llm")
        raise RuntimeError("Provider failed")

    with pytest.raises(RuntimeError, match="Provider failed"):
        steer_action(
            observation(), "Search", provider="llm",
            providers={"llm": fail, "jev": lambda *_: pytest.fail("Fallback was called")},
        )
    assert calls == ["llm"]


def test_access_guard_stops_before_routing_or_provider_calls():
    page = observation()
    page["access"] = {"visible_password_field": True}
    choice = steer_action(page, "Search", router=lambda _: pytest.fail("Router was called"))
    assert choice["source"] == "local_access_guard"
    assert choice["operation"] == "BLOCKED"


@pytest.mark.parametrize("choice", [
    None,
    {"operation": ["CLICK"]},
    {"operation": "CLICK", "target": True},
    {"operation": "CLICK", "target": "2"},
    {"operation": "TYPE_TEXT", "target": 1, "text_mode": {}},
])
def test_malformed_provider_values_raise_validation_errors(choice):
    with pytest.raises(ValueError):
        validate_steering_choice(observation(), choice, source="llm")


@pytest.mark.parametrize("provider", ["jev", "llm"])
def test_all_providers_use_the_same_freshness_check_before_execution(provider):
    page = observation()
    choice = steer_action(
        page, "Search", provider=provider,
        providers={provider: lambda *_: {"operation": "CLICK", "target": 2}},
    )

    class ChangedBrowser:
        def observe(self):
            changed = deepcopy(page)
            changed["elements"][1]["name"] = "Replaced target"
            changed["fingerprint"] = "changed"
            return changed

        def click_node(self, _node):
            pytest.fail("Stale choice must not execute")

    with pytest.raises(StaleObservation):
        execute_prediction(ChangedBrowser(), page, choice)


@pytest.mark.parametrize("printer", [print_prediction, print_step])
def test_cli_accepts_provider_without_jev_confidence_fields(printer, capsys):
    choice = validate_steering_choice(
        observation(), {"operation": "TYPE_TEXT", "target": 1, "text_mode": "SEARCH_SEED"}, source="llm",
    )
    printer({
        "prediction": choice,
        "observation": {**observation(), "omitted_elements": 0},
        "decision_fingerprint": "snapshot-a",
        "execution": {"status": "executed"},
    })
    output = capsys.readouterr().out
    assert "Text mode: SEARCH_SEED" in output
    assert "Steering source: llm" in output
    assert "Confidence:" not in output
