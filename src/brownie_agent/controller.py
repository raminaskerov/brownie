"""Code-owned memory and stop guards for a future bounded action loop."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

MUTATING_OPERATIONS = {"CLICK", "TYPE_TEXT", "SUBMIT", "SCROLL_DOWN", "SCROLL_UP"}
SCROLL_OPERATIONS = {"SCROLL_DOWN", "SCROLL_UP"}
FORM_ROLES = {"textbox", "searchbox", "spinbutton", "combobox", "checkbox", "radio", "switch"}


def page_key(url: str) -> str:
    """Keep query parameters that distinguish result pages; discard fragments."""
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def field_scope(url: str) -> str:
    """Group the same form across query and pagination changes on one route."""
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def repeated_suffix_period(items: list[tuple]) -> int | None:
    """Return the shortest repeated suffix period, including cycles longer than two."""
    for period in range(1, len(items) // 2 + 1):
        if items[-period:] == items[-2 * period : -period]:
            return period
    return None


@dataclass
class RunState:
    """Factual state and deterministic guards; no model-authored progress summary."""

    goal: str
    max_steps: int = 20
    max_pages: int = 3
    max_scrolls_per_page: int = 10
    steps: list[dict] = field(default_factory=list)
    visited_pages: set[str] = field(default_factory=set)
    visited_views: set[tuple[str, str]] = field(default_factory=set)
    scroll_extents: dict[str, dict[str, int]] = field(default_factory=dict)
    scroll_counts: dict[str, int] = field(default_factory=dict)
    known_fields: dict[tuple[str, str, str], dict] = field(default_factory=dict)

    def __post_init__(self):
        self.goal = self.goal.strip()
        if not self.goal:
            raise ValueError("A run requires a non-empty goal.")
        if min(self.max_steps, self.max_pages) < 1 or self.max_scrolls_per_page < 0:
            raise ValueError("Step and page budgets must be positive; the scroll budget may be zero.")

    def observe(self, observation: dict) -> None:
        """Remember one factual viewport without retaining executable node references."""
        page = page_key(observation["url"])
        fingerprint = observation["fingerprint"]
        scroll_y = int(observation["viewport"]["scroll_y"])
        self.visited_pages.add(page)
        self.visited_views.add((page, fingerprint))
        extent = self.scroll_extents.setdefault(page, {"minimum": scroll_y, "maximum": scroll_y})
        extent["minimum"] = min(extent["minimum"], scroll_y)
        extent["maximum"] = max(extent["maximum"], scroll_y)

        scope = field_scope(observation["url"])
        for element in observation["elements"]:
            if element["role"] not in FORM_ROLES:
                continue
            key = (scope, element["role"], element["name"])
            self.known_fields[key] = {
                "page_scope": scope,
                "role": element["role"],
                "name": element["name"],
                "value": element.get("value", ""),
                "checked": element.get("checked"),
            }

    def budget_stop_reason(self) -> str | None:
        if len(self.steps) >= self.max_steps:
            return "step_budget"
        if len(self.visited_pages) > self.max_pages:
            return "page_budget"
        return None

    def preflight(self, prediction: dict, observation: dict) -> str | None:
        """Reject an unsafe or exhausted next action before browser execution."""
        if reason := self.budget_stop_reason():
            return reason
        operation = prediction["operation"]
        page = page_key(observation["url"])
        if operation in SCROLL_OPERATIONS and self.scroll_counts.get(page, 0) >= self.max_scrolls_per_page:
            return "scroll_budget"
        if operation in MUTATING_OPERATIONS:
            attempted = (
                observation["fingerprint"],
                operation,
                prediction.get("target_name"),
            )
            if any(step["attempt"] == attempted for step in self.steps):
                return "repeated_mutation"
        return None

    def record_step(self, before: dict, execution: dict, after: dict) -> str | None:
        """Record one result and return a deterministic reason to stop, if any."""
        self.observe(before)
        self.observe(after)
        operation = execution["operation"]
        executed = bool(execution.get("executed"))
        before_fingerprint = before["fingerprint"]
        after_fingerprint = after["fingerprint"]
        step = {
            "operation": operation,
            "target_name": execution.get("target_name"),
            "status": execution["status"],
            "executed": executed,
            "before_url": before["url"],
            "after_url": after["url"],
            "before_fingerprint": before_fingerprint,
            "after_fingerprint": after_fingerprint,
            "observation_changed": before_fingerprint != after_fingerprint,
            "url_changed": before["url"] != after["url"],
            "attempt": (before_fingerprint, operation, execution.get("target_name")),
        }
        self.steps.append(step)
        if executed and operation in SCROLL_OPERATIONS:
            page = page_key(before["url"])
            self.scroll_counts[page] = self.scroll_counts.get(page, 0) + 1

        if operation in {"DONE", "BLOCKED"}:
            return operation.lower()
        if executed and before_fingerprint == after_fingerprint:
            return "no_effect"
        signatures = [
            (
                item["before_fingerprint"],
                item["operation"],
                item["target_name"],
                item["after_fingerprint"],
            )
            for item in self.steps
        ]
        if period := repeated_suffix_period(signatures):
            return f"cycle_{period}"
        if reason := self.budget_stop_reason():
            return reason
        return None

    def recent_steps(self) -> list[dict]:
        """Return bounded factual history suitable for model state."""
        keys = (
            "operation", "target_name", "status", "before_url", "after_url",
            "observation_changed", "url_changed",
        )
        return [{key: step[key] for key in keys if key in step} for step in self.steps[-8:]]

    def memory_state(self) -> dict:
        """Return non-executable run memory for a future controller request."""
        return {
            "visited_pages": sorted(self.visited_pages),
            "visited_view_count": len(self.visited_views),
            "scroll_extents": [
                {"url": url, **extent, "scroll_count": self.scroll_counts.get(url, 0)}
                for url, extent in sorted(self.scroll_extents.items())
            ],
            "known_fields": list(self.known_fields.values()),
        }
