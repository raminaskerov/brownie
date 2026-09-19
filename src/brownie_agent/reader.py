"""Bounded, read-only traversal of successive page viewports."""

from collections.abc import Iterable
from typing import Protocol


class ObservableBrowser(Protocol):
    def observe(self) -> dict: ...

    def scroll_down(self) -> bool: ...


def _unique_lines(chunks: Iterable[str]) -> str:
    lines = []
    seen = set()
    for chunk in chunks:
        for raw_line in chunk.splitlines():
            line = raw_line.strip()
            if line and line not in seen:
                seen.add(line)
                lines.append(line)
    return "\n".join(lines)


def _descriptive_element(element: dict, view: int) -> dict:
    """Drop current-viewport identifiers so accumulated elements cannot execute."""
    return {
        "role": element["role"],
        "name": element["name"],
        "value": element.get("value", ""),
        "checked": element.get("checked"),
        "context": element.get("context", ""),
        "destination": element.get("destination", ""),
        "first_seen_view": view,
    }


def read_page(browser: ObservableBrowser, *, max_scrolls: int = 10) -> dict:
    """Read successive viewports with explicit bounds and repeated-view detection."""
    if type(max_scrolls) is not int or max_scrolls < 0:
        raise ValueError("max_scrolls must be a non-negative integer")

    views = []
    seen_views = set()
    seen_elements = {}
    scrolls = 0
    stop_reason = "max_scrolls"

    while True:
        observation = browser.observe()
        view_key = (
            observation["url"],
            observation["viewport"]["scroll_y"],
            observation["text"],
            tuple(element["node_id"] for element in observation["elements"]),
        )
        if view_key in seen_views:
            stop_reason = "repeated_view"
            break
        seen_views.add(view_key)
        view_number = len(views) + 1
        views.append(observation)

        for element in observation["elements"]:
            descriptive = _descriptive_element(element, view_number)
            identity = (
                descriptive["role"],
                descriptive["name"],
                descriptive["value"],
                descriptive["checked"],
                descriptive["context"],
                descriptive["destination"],
            )
            seen_elements.setdefault(identity, descriptive)

        if not observation["can_scroll_down"]:
            stop_reason = "bottom"
            break
        if scrolls >= max_scrolls:
            stop_reason = "max_scrolls"
            break
        if not browser.scroll_down():
            stop_reason = "scroll_stopped"
            break
        scrolls += 1

    first = views[0]
    return {
        "url": first["url"],
        "title": first["title"],
        "combined_text": _unique_lines(view["text"] for view in views),
        "seen_elements": list(seen_elements.values()),
        "views": views,
        "scrolls": scrolls,
        "stop_reason": stop_reason,
    }
