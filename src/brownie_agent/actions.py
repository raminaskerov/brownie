"""Validated one-operation execution against a fresh viewport observation."""

OPERATIONS = ("SCROLL_DOWN", "SCROLL_UP", "CLICK", "TYPE_TEXT", "SUBMIT", "DONE", "BLOCKED")
TARGETED_OPERATIONS = {"CLICK", "TYPE_TEXT", "SUBMIT"}


def element_description(element: dict) -> str:
    """Describe one observed target without relying on its temporary index."""
    parts = [element["name"]]
    if element.get("context") and element["context"].casefold() != element["name"].casefold():
        parts.append(element["context"])
    if element.get("destination"):
        parts.append(element["destination"])
    return " · ".join(parts)


class StaleObservation(ValueError):
    """The current page no longer matches the observation used for an action."""


def action_space(observation: dict) -> dict[str, list[int] | None]:
    """Return only operations and current element indexes that can execute."""
    space: dict[str, list[int] | None] = {"DONE": None, "BLOCKED": None}
    if observation["can_scroll_down"]:
        space["SCROLL_DOWN"] = None
    if observation["can_scroll_up"]:
        space["SCROLL_UP"] = None
    for element in observation["elements"]:
        for operation in element["operations"]:
            space.setdefault(operation, []).append(element["index"])
    return {operation: space[operation] for operation in OPERATIONS if operation in space}


def _validate(operation: str, target: int | None, text: str | None, observation: dict) -> dict | None:
    if operation not in OPERATIONS:
        raise ValueError(f"Unsupported operation: {operation}")
    space = action_space(observation)
    if operation not in space:
        raise ValueError(f"{operation} is not available in the current viewport")

    if operation in TARGETED_OPERATIONS:
        if type(target) is not int or target not in space[operation]:
            raise ValueError(f"{operation} requires one of the offered target indexes: {space[operation]}")
        element = next(element for element in observation["elements"] if element["index"] == target)
    else:
        if target is not None:
            raise ValueError(f"{operation} does not accept a target")
        element = None

    if operation == "TYPE_TEXT":
        if not isinstance(text, str):
            raise ValueError("TYPE_TEXT requires --text")
        if len(text) > 2000:
            raise ValueError("TYPE_TEXT is limited to 2000 characters")
    elif text is not None:
        raise ValueError(f"{operation} does not accept text")
    return element


def execute_action(
    browser,
    observation: dict,
    *,
    operation: str,
    target: int | None = None,
    text: str | None = None,
) -> dict:
    """Validate and execute exactly one operation without mutation retries."""
    operation = operation.upper()
    element = _validate(operation, target, text, observation)
    current = browser.observe()
    if current["fingerprint"] != observation["fingerprint"]:
        raise StaleObservation("The page changed after observation; observe again before acting.")

    if operation == "SCROLL_DOWN":
        executed = browser.scroll_down()
    elif operation == "SCROLL_UP":
        executed = browser.scroll_up()
    elif operation == "CLICK":
        browser.click_node(element["node_id"])
        executed = True
    elif operation == "TYPE_TEXT":
        browser.type_node(element["node_id"], text)
        executed = True
    elif operation == "SUBMIT":
        browser.submit_node(element["node_id"])
        executed = True
    else:
        executed = False

    return {
        "operation": operation,
        "target": target,
        "target_name": element_description(element) if element else None,
        "executed": executed,
        "status": operation.lower() if operation in {"DONE", "BLOCKED"} else "executed",
    }


def execute_prediction(browser, observation: dict, prediction: dict) -> dict:
    """Execute one validated steering choice, stopping before text generation."""
    operation = prediction.get("operation")
    target = prediction.get("target")
    if operation == "TYPE_TEXT":
        return {
            "operation": operation,
            "target": target,
            "target_name": prediction.get("target_name"),
            "executed": False,
            "status": "text_required",
        }
    return execute_action(browser, observation, operation=operation, target=target)
