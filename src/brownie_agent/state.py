"""Compact evidence states for Jev decisions and text generation."""

from urllib.parse import urlsplit, urlunsplit

PUBLIC_ELEMENT_KEYS = ("index", "role", "name", "value", "checked", "operations")
DECISION_HISTORY_KEYS = (
    "operation",
    "target_name",
    "text",
    "status",
    "before_url",
    "after_url",
    "page_changed",
)
TEXT_HISTORY_KEYS = ("operation", "target_name", "status", "page_changed")


def public_element(element: dict) -> dict:
    return {key: element[key] for key in PUBLIC_ELEMENT_KEYS if key in element}


def _recent_steps(recent_steps, keys) -> list[dict]:
    return [{key: step[key] for key in keys if key in step} for step in list(recent_steps or ())[-8:]]


def decision_state(observation: dict, goal: str, recent_steps=()) -> dict:
    """Return the shared factual state used by Jev's independent questions."""
    viewport = observation["viewport"]
    return {
        "goal": goal,
        "current_page": {
            "url": observation["url"],
            "title": observation["title"],
            "visible_text": observation["text"],
        },
        "current_viewport": {
            "scroll_y": viewport["scroll_y"],
            "document_height": viewport["document_height"],
            "can_scroll_up": observation["can_scroll_up"],
            "can_scroll_down": observation["can_scroll_down"],
        },
        "current_elements": [public_element(element) for element in observation["elements"]],
        "recent_steps": _recent_steps(recent_steps, DECISION_HISTORY_KEYS),
    }


def _url_without_query(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def text_field_state(observation: dict, goal: str, prediction: dict, recent_steps=()) -> dict:
    """Return a privacy-reduced state for writing the selected field value."""
    target = prediction.get("target")
    selected = next((element for element in observation["elements"] if element["index"] == target), None)
    if selected is None or "TYPE_TEXT" not in selected["operations"]:
        raise ValueError("TYPE_TEXT prediction does not identify an observed editable field.")
    other_fields = [
        {
            "role": element["role"],
            "name": element["name"],
            "filled": bool(element.get("value")),
            **({"checked": element["checked"]} if element.get("checked") is not None else {}),
        }
        for element in observation["elements"]
        if element["index"] != target
        and (
            "TYPE_TEXT" in element["operations"]
            or element["role"] in {"checkbox", "radio", "switch", "combobox"}
        )
    ]
    return {
        "goal": goal,
        "selected_field": {"role": selected["role"], "name": selected["name"]},
        "other_visible_fields": other_fields,
        "current_page": {
            "url_without_query": _url_without_query(observation["url"]),
            "title": observation["title"],
        },
        "recent_steps": _recent_steps(recent_steps, TEXT_HISTORY_KEYS),
    }
