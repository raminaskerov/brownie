"""Provider-neutral boundary for choosing one observed browser action."""

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass

from .access import READY, classify_access, local_blocked_prediction
from .actions import TARGETED_OPERATIONS, action_space, element_description
from .state import decision_state, public_element
from .trace import trace_event

TEXT_MODES = frozenset({"SEARCH_SEED", "FIELD_VALUE", "IDENTIFIER", "FREEFORM", "VALUE_MISSING"})
Steerer = Callable[[dict, str, Iterable[dict]], dict]


@dataclass(frozen=True)
class SteeringRoute:
    """A code-owned provider selection with an inspectable reason."""

    provider: str
    reason: str


Router = Callable[[dict], SteeringRoute]


def validate_steering_choice(observation: dict, choice: dict, *, source: str) -> dict:
    """Validate any steering provider against the current executable action space."""
    if not isinstance(choice, dict):
        raise ValueError(f"{source} returned no valid steering choice; no browser action executed.")

    space = action_space(observation)
    operation = choice.get("operation")
    if not isinstance(operation, str) or operation not in space:
        raise ValueError(f"{source} chose an unavailable operation; no browser action executed.")

    target = choice.get("target")
    element = None
    if operation in TARGETED_OPERATIONS:
        if type(target) is not int or target not in space[operation]:
            raise ValueError(f"{source} chose an unavailable target; no browser action executed.")
        element = next(item for item in observation["elements"] if item["index"] == target)
    elif target is not None:
        raise ValueError(f"{source} supplied a target for {operation}; no browser action executed.")

    text_mode = choice.get("text_mode")
    if operation == "TYPE_TEXT":
        if not isinstance(text_mode, str) or text_mode not in TEXT_MODES:
            raise ValueError(f"{source} supplied no valid text mode; no browser action executed.")
    elif text_mode is not None:
        raise ValueError(f"{source} supplied a text mode for {operation}; no browser action executed.")

    validated = dict(choice)
    validated.update(
        operation=operation,
        target=target,
        target_name=element_description(element) if element else None,
        source=source,
        executed=False,
    )
    return validated


def steer_action(
    observation: dict,
    goal: str,
    recent_steps=(),
    *,
    provider: str | None = None,
    providers: Mapping[str, Steerer] | None = None,
    router: Router | None = None,
) -> dict:
    """Select one provider explicitly or through a router; never switch providers on failure.

    Providers receive a detached public observation and bounded factual history.
    Routers receive public decision state plus the offered action space. Neither
    receives browser handles, node IDs, or the execution fingerprint.
    """
    if provider is not None and router is not None:
        raise ValueError("Choose either an explicit steering provider or a router.")
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("Steering requires a non-empty goal.")
    goal = goal.strip()
    snapshot = deepcopy(observation)
    access = classify_access(snapshot)
    if access["status"] != READY:
        return local_blocked_prediction(access)

    public_observation = deepcopy({
        **{key: snapshot[key] for key in (
            "url", "title", "text", "viewport", "can_scroll_up", "can_scroll_down"
        )},
        "elements": [public_element(element) for element in snapshot["elements"]],
    })
    state = decision_state(public_observation, goal, recent_steps)
    route = SteeringRoute(
        provider if provider is not None else "jev",
        "Explicit provider" if provider is not None else "Default provider",
    )
    if router is not None:
        route = router(deepcopy({"state": state, "action_space": action_space(snapshot)}))
    if (
        not isinstance(route, SteeringRoute)
        or not isinstance(route.provider, str)
        or not route.provider.strip()
        or not isinstance(route.reason, str)
        or not route.reason.strip()
    ):
        raise ValueError("Router must select one named provider and give a non-empty reason.")

    if providers is None:
        from .llm_model import predict_llm_action
        from .model import predict_action

        providers = {"jev": predict_action, "llm": predict_llm_action}
    trace_event("steering_context", {
        "route": {"provider": route.provider, "reason": route.reason},
        "observer_output": snapshot,
        "provider_input": state,
        "action_space": action_space(snapshot),
    })
    try:
        steerer = providers[route.provider]
    except KeyError:
        available = ", ".join(sorted(providers)) or "none"
        raise ValueError(f"Unknown steering provider {route.provider!r}; available: {available}.") from None
    choice = steerer(public_observation, goal, deepcopy(state["recent_steps"]))
    validated = validate_steering_choice(snapshot, choice, source=route.provider)
    validated["routing"] = {"provider": route.provider, "reason": route.reason}
    trace_event("steering_result", {"choice": validated})
    return validated
