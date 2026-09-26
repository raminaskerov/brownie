"""Deterministic Basic-mode task contracts over Brownie's validated executor."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from .access import READY, classify_access
from .actions import StaleObservation, element_description, execute_action
from .reader import read_page
from .trace import trace_event

BASIC_TASK_VERSION = 1
BASIC_OPERATIONS = frozenset({
    "TYPE_TEXT",
    "CAPTURE_TEXT",
    "SUBMIT",
    "CLICK",
    "SCROLL_DOWN",
    "SCROLL_UP",
    "ASSERT",
    "READ_PAGE",
    "DONE",
})
TARGETED_OPERATIONS = frozenset({"TYPE_TEXT", "SUBMIT", "CLICK"})
MAX_BASIC_STEPS = 50
MAX_BASIC_SCROLLS = 10
MAX_CAPTURES = 20
MAX_CAPTURE_CHARS = 2000
MAX_STALE_REFRESHES = 3
INPUT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class TargetSpec:
    role: str
    name: str
    context_contains: str | None = None
    destination_contains: str | None = None


@dataclass(frozen=True)
class BasicStep:
    operation: str
    target: TargetSpec | None = None
    input_name: str | None = None
    capture_name: str | None = None
    value: str | None = None
    line_contains: str | None = None
    extract_after: str | None = None
    check: dict[str, str] | None = None
    max_scrolls: int = 0


@dataclass(frozen=True)
class BasicTask:
    version: int
    name: str
    start_url: str
    allowed_origins: tuple[str, ...]
    input_names: tuple[str, ...]
    steps: tuple[BasicStep, ...]


def _require_object(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _check_keys(value: dict, label: str, *, allowed: set[str], required: set[str] = frozenset()) -> None:
    unknown = sorted(set(value) - allowed)
    missing = sorted(required - set(value))
    if unknown:
        raise ValueError(f"{label} has unsupported fields: {', '.join(unknown)}")
    if missing:
        raise ValueError(f"{label} is missing required fields: {', '.join(missing)}")


def _non_empty_string(value, label: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    result = value.strip()
    if len(result) > maximum:
        raise ValueError(f"{label} is limited to {maximum} characters")
    return result


def _origin(url: str, label: str = "URL") -> str:
    parsed = urlsplit(url)
    if parsed.scheme == "file" and not parsed.netloc:
        return "file://"
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{label} must use http, https, or a local file URL")
    try:
        port = parsed.port
    except ValueError:
        raise ValueError(f"{label} has an invalid port") from None
    default_port = 443 if parsed.scheme == "https" else 80
    suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parsed.scheme}://{parsed.hostname.lower()}{suffix}"


def _parse_target(raw, label: str) -> TargetSpec:
    value = _require_object(raw, label)
    _check_keys(
        value,
        label,
        allowed={"role", "name", "context_contains", "destination_contains"},
        required={"role", "name"},
    )
    role = _non_empty_string(value["role"], f"{label}.role", maximum=40).casefold()
    name = _non_empty_string(value["name"], f"{label}.name", maximum=300)
    context = value.get("context_contains")
    destination = value.get("destination_contains")
    return TargetSpec(
        role=role,
        name=name,
        context_contains=(
            _non_empty_string(context, f"{label}.context_contains", maximum=300)
            if context is not None else None
        ),
        destination_contains=(
            _non_empty_string(destination, f"{label}.destination_contains", maximum=500)
            if destination is not None else None
        ),
    )


def _parse_step(raw, offset: int, input_names: set[str]) -> BasicStep:
    label = f"steps[{offset}]"
    value = _require_object(raw, label)
    _check_keys(
        value,
        label,
        allowed={
            "operation", "target", "input", "capture", "save_as", "line_contains", "extract_after",
            "value", "check", "max_scrolls",
        },
        required={"operation"},
    )
    operation = _non_empty_string(value["operation"], f"{label}.operation", maximum=30).upper()
    if operation not in BASIC_OPERATIONS:
        available = ", ".join(sorted(BASIC_OPERATIONS))
        raise ValueError(f"{label}.operation must be one of: {available}")

    target = _parse_target(value["target"], f"{label}.target") if "target" in value else None
    if operation in TARGETED_OPERATIONS and target is None:
        raise ValueError(f"{label}.target is required for {operation}")
    if operation not in TARGETED_OPERATIONS and target is not None:
        raise ValueError(f"{label}.target is not accepted for {operation}")

    input_name = value.get("input")
    capture_name = value.get("capture")
    literal = value.get("value")
    if operation == "TYPE_TEXT":
        if sum(item is not None for item in (input_name, capture_name, literal)) != 1:
            raise ValueError(f"{label} TYPE_TEXT requires exactly one of input, capture, or value")
        if input_name is not None:
            input_name = _non_empty_string(input_name, f"{label}.input", maximum=64)
            if input_name not in input_names:
                raise ValueError(f"{label}.input names an undeclared task input: {input_name}")
        if capture_name is not None:
            capture_name = _non_empty_string(capture_name, f"{label}.capture", maximum=64)
            if not INPUT_NAME.fullmatch(capture_name):
                raise ValueError(f"{label}.capture has an invalid name")
        if literal is not None:
            literal = _non_empty_string(literal, f"{label}.value", maximum=2000)
    elif input_name is not None or literal is not None or capture_name is not None:
        raise ValueError(f"{label} accepts input, capture, or value only for TYPE_TEXT")

    save_as = value.get("save_as")
    line_contains = value.get("line_contains")
    extract_after = value.get("extract_after")
    if operation == "CAPTURE_TEXT":
        save_as = _non_empty_string(save_as, f"{label}.save_as", maximum=64)
        if not INPUT_NAME.fullmatch(save_as):
            raise ValueError(f"{label}.save_as has an invalid name")
        line_contains = _non_empty_string(line_contains, f"{label}.line_contains", maximum=300)
        if extract_after is not None:
            extract_after = _non_empty_string(extract_after, f"{label}.extract_after", maximum=300)
    elif any(item is not None for item in (save_as, line_contains, extract_after)):
        raise ValueError(f"{label} accepts save_as, line_contains, or extract_after only for CAPTURE_TEXT")

    check = value.get("check")
    if operation == "ASSERT":
        check = _require_object(check, f"{label}.check")
        _check_keys(
            check,
            f"{label}.check",
            allowed={"text_contains", "title_contains", "url_contains"},
        )
        if not check:
            raise ValueError(f"{label}.check must contain at least one assertion")
        check = {
            key: _non_empty_string(item, f"{label}.check.{key}", maximum=500)
            for key, item in check.items()
        }
    elif check is not None:
        raise ValueError(f"{label}.check is accepted only for ASSERT")

    max_scrolls = value.get("max_scrolls", 0)
    if operation == "READ_PAGE":
        if type(max_scrolls) is not int or not 0 <= max_scrolls <= MAX_BASIC_SCROLLS:
            raise ValueError(f"{label}.max_scrolls must be from 0 to {MAX_BASIC_SCROLLS}")
    elif "max_scrolls" in value:
        raise ValueError(f"{label}.max_scrolls is accepted only for READ_PAGE")

    return BasicStep(
        operation=operation,
        target=target,
        input_name=input_name,
        capture_name=capture_name if operation == "TYPE_TEXT" else save_as,
        value=literal,
        line_contains=line_contains,
        extract_after=extract_after,
        check=check,
        max_scrolls=max_scrolls,
    )


def parse_basic_task(raw) -> BasicTask:
    """Validate and detach one versioned Basic-mode task contract."""
    value = _require_object(raw, "task")
    _check_keys(
        value,
        "task",
        allowed={"version", "name", "start_url", "allowed_origins", "inputs", "steps"},
        required={"version", "name", "start_url", "allowed_origins", "inputs", "steps"},
    )
    if value["version"] != BASIC_TASK_VERSION:
        raise ValueError(f"task.version must be {BASIC_TASK_VERSION}")
    name = _non_empty_string(value["name"], "task.name", maximum=100)
    start_url = _non_empty_string(value["start_url"], "task.start_url", maximum=2000)
    start_origin = _origin(start_url, "task.start_url")

    raw_origins = value["allowed_origins"]
    if not isinstance(raw_origins, list) or not raw_origins:
        raise ValueError("task.allowed_origins must be a non-empty array")
    allowed_origins = tuple(
        dict.fromkeys(_origin(_non_empty_string(item, "task.allowed_origins item"), "allowed origin")
                      for item in raw_origins)
    )
    if start_origin not in allowed_origins:
        raise ValueError("task.allowed_origins must include the start URL origin")

    raw_inputs = value["inputs"]
    if not isinstance(raw_inputs, list):
        raise ValueError("task.inputs must be an array of input names")
    input_names = []
    for item in raw_inputs:
        item = _non_empty_string(item, "task.inputs item", maximum=64)
        if not INPUT_NAME.fullmatch(item):
            raise ValueError(f"Invalid task input name: {item}")
        if item in input_names:
            raise ValueError(f"Duplicate task input name: {item}")
        input_names.append(item)

    raw_steps = value["steps"]
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_BASIC_STEPS:
        raise ValueError(f"task.steps must contain from 1 to {MAX_BASIC_STEPS} steps")
    steps = tuple(_parse_step(step, offset, set(input_names)) for offset, step in enumerate(raw_steps))
    captures_seen = set()
    for offset, step in enumerate(steps):
        if step.operation == "CAPTURE_TEXT":
            if step.capture_name in captures_seen or step.capture_name in input_names:
                raise ValueError(f"steps[{offset}].save_as must be unique and cannot shadow an input")
            captures_seen.add(step.capture_name)
            if len(captures_seen) > MAX_CAPTURES:
                raise ValueError(f"task may capture at most {MAX_CAPTURES} values")
        elif step.operation == "TYPE_TEXT" and step.capture_name and step.capture_name not in captures_seen:
            raise ValueError(f"steps[{offset}].capture must name an earlier CAPTURE_TEXT step")
    if any(step.operation in {"DONE", "READ_PAGE"} for step in steps[:-1]):
        raise ValueError("DONE and READ_PAGE may appear only as the final task step")
    return BasicTask(
        version=BASIC_TASK_VERSION,
        name=name,
        start_url=start_url,
        allowed_origins=allowed_origins,
        input_names=tuple(input_names),
        steps=steps,
    )


def load_basic_task(path: str | Path) -> BasicTask:
    """Load one UTF-8 JSON Basic-mode contract."""
    task_path = Path(path).expanduser().resolve()
    try:
        raw = json.loads(task_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Could not read Basic task: {task_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Basic task is not valid JSON: {exc}") from exc
    return parse_basic_task(raw)


def parse_basic_inputs(values) -> dict[str, str]:
    """Parse repeated NAME=VALUE CLI inputs without accepting duplicates."""
    result = {}
    for raw in values or ():
        if not isinstance(raw, str) or "=" not in raw:
            raise ValueError("Each --input must use NAME=VALUE")
        name, value = raw.split("=", 1)
        if not INPUT_NAME.fullmatch(name):
            raise ValueError(f"Invalid Basic task input name: {name}")
        if name in result:
            raise ValueError(f"Duplicate Basic task input: {name}")
        if len(value) > 2000:
            raise ValueError(f"Basic task input {name} is limited to 2000 characters")
        result[name] = value
    return result


def validate_basic_inputs(task: BasicTask, inputs: dict[str, str]) -> dict[str, str]:
    """Require exactly the inputs declared by a validated task."""
    if not isinstance(task, BasicTask):
        raise TypeError("validate_basic_inputs requires a validated BasicTask")
    if not isinstance(inputs, dict):
        raise ValueError("Basic task inputs must be a mapping")
    expected = set(task.input_names)
    supplied = set(inputs)
    if missing := sorted(expected - supplied):
        raise ValueError(f"Missing Basic task inputs: {', '.join(missing)}")
    if unknown := sorted(supplied - expected):
        raise ValueError(f"Unknown Basic task inputs: {', '.join(unknown)}")
    for name, value in inputs.items():
        if not isinstance(value, str) or len(value) > 2000:
            raise ValueError(f"Basic task input {name} must be a string of at most 2000 characters")
    return dict(inputs)


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def _matching_elements(observation: dict, spec: TargetSpec, operation: str) -> list[dict]:
    matches = []
    for element in observation["elements"]:
        if operation not in element["operations"]:
            continue
        if element["role"].casefold() != spec.role or _normalize(element["name"]) != _normalize(spec.name):
            continue
        if spec.context_contains and _normalize(spec.context_contains) not in _normalize(element.get("context", "")):
            continue
        if (
            spec.destination_contains
            and spec.destination_contains.casefold() not in element.get("destination", "").casefold()
        ):
            continue
        matches.append(element)
    return matches


def _perception_gap(observation: dict) -> bool:
    perception = observation.get("perception", {})
    visible_frames = perception.get("visible_frame_count", perception.get("frame_count", 0))
    inspected_frames = perception.get("inspected_frame_count", 0)
    shadow_roots = perception.get("open_shadow_root_count", 0)
    inspected_shadow_roots = perception.get("inspected_open_shadow_root_count", 0)
    return bool(
        observation.get("omitted_elements")
        or visible_frames > inspected_frames
        or shadow_roots > inspected_shadow_roots
        or perception.get("inaccessible_frame_count")
        or perception.get("accessibility_limit_reached")
        or perception.get("accessibility_unavailable_count")
        or perception.get("text_limit_reached")
        or perception.get("element_limit_reached")
    )


def _target_for_step(observation: dict, step: BasicStep) -> tuple[dict | None, str | None]:
    matches = _matching_elements(observation, step.target, step.operation)
    if not matches:
        return None, "perception_incomplete" if _perception_gap(observation) else "target_not_found"
    if len(matches) > 1:
        return None, "target_ambiguous"
    return matches[0], None


def _safe_target_reason(
    step: BasicStep,
    element: dict,
    observation: dict,
    allowed_origins: tuple[str, ...],
) -> str | None:
    if step.operation == "SUBMIT" and element["role"] != "searchbox":
        return "unsupported_submit"
    if step.operation != "CLICK":
        return None
    if element["role"] in {"checkbox", "radio", "switch"}:
        return None
    if element["role"] != "link" or not element.get("destination"):
        return "unsupported_click"
    destination = urljoin(observation["url"], element["destination"])
    if _origin(destination, "link destination") not in allowed_origins:
        return "origin_not_allowed"
    return None


def _assertion_failure(observation: dict, check: dict[str, str]) -> str | None:
    comparisons = {
        "text_contains": observation["text"],
        "title_contains": observation["title"],
        "url_contains": observation["url"],
    }
    for key, expected in check.items():
        if expected.casefold() not in comparisons[key].casefold():
            return key
    return None


def _page_summary(observation: dict) -> dict:
    return {"url": observation["url"], "title": observation["title"]}


def _origin_allowed(url: str, allowed_origins: tuple[str, ...]) -> bool:
    try:
        return _origin(url) in allowed_origins
    except ValueError:
        return False


def _stop_result(
    task: BasicTask, observation: dict, steps: list[dict], reason: str,
    *, captures: dict[str, dict] | None = None, **extra,
) -> dict:
    result = {
        "mode": "basic",
        "task": task.name,
        "status": "stopped",
        "stop_reason": reason,
        "steps": steps,
        "last_page": _page_summary(observation),
        "output": None,
        "captures": dict(captures or {}),
    }
    result.update(extra)
    return result


def _capture_visible_line(observation: dict, step: BasicStep) -> tuple[str | None, str | None]:
    """Capture one unique line from the bounded, currently visible DOM text."""
    if _perception_gap(observation):
        return None, "perception_incomplete"
    visible_text = observation["text"].split("[Accessibility structure; non-executable]", 1)[0]
    matching = [
        line.strip() for line in visible_text.splitlines()
        if step.line_contains.casefold() in line.casefold()
    ]
    if not matching:
        return None, "capture_not_found"
    if len(matching) != 1:
        return None, "capture_ambiguous"
    captured = matching[0]
    if step.extract_after is not None:
        marker = step.extract_after.casefold()
        if captured.casefold().count(marker) != 1:
            return None, "capture_marker_ambiguous"
        position = captured.casefold().index(marker) + len(step.extract_after)
        captured = captured[position:].strip()
    if not captured or len(captured) > MAX_CAPTURE_CHARS:
        return None, "capture_invalid"
    return captured, None


def run_basic_task(browser, task: BasicTask, inputs: dict[str, str] | None = None) -> dict:
    """Run one finite deterministic task without model calls or mutation retries."""
    if not isinstance(task, BasicTask):
        raise TypeError("run_basic_task requires a validated BasicTask")
    inputs = validate_basic_inputs(task, inputs or {})
    browser.open(task.start_url)
    observation = browser.observe()
    steps = []
    captures: dict[str, dict] = {}

    def stop(reason: str, **extra) -> dict:
        return _stop_result(task, observation, steps, reason, captures=captures, **extra)

    if not _origin_allowed(observation["url"], task.allowed_origins):
        return stop("origin_not_allowed")

    for offset, step in enumerate(task.steps):
        trace_event("basic_step", {"index": offset, "operation": step.operation})
        access = classify_access(observation)
        if access["status"] != READY:
            return stop(access["status"])

        if step.operation == "ASSERT":
            failed = _assertion_failure(observation, step.check)
            if failed:
                reason = "perception_incomplete" if failed == "text_contains" and _perception_gap(observation) \
                    else "assertion_failed"
                return stop(reason, failed_assertion=failed)
            steps.append({"index": offset, "operation": "ASSERT", "status": "passed"})
            continue

        if step.operation == "CAPTURE_TEXT":
            captured, reason = _capture_visible_line(observation, step)
            if reason:
                return stop(reason, failed_step=offset)
            captures[step.capture_name] = {"value": captured, "url": observation["url"]}
            steps.append({
                "index": offset, "operation": "CAPTURE_TEXT", "status": "captured", "name": step.capture_name,
            })
            continue

        if step.operation == "READ_PAGE":
            report = read_page(browser, max_scrolls=step.max_scrolls)
            steps.append({
                "index": offset,
                "operation": "READ_PAGE",
                "status": "read",
                "scrolls": report["scrolls"],
                "stop_reason": report["stop_reason"],
            })
            observation = report["views"][-1]
            return {
                "mode": "basic",
                "task": task.name,
                "status": "completed",
                "stop_reason": "task_complete",
                "steps": steps,
                "last_page": _page_summary(observation),
                "output": {
                    "url": report["url"],
                    "title": report["title"],
                    "material": report["combined_text"],
                    "seen_elements": report["seen_elements"],
                    "scrolls": report["scrolls"],
                    "stop_reason": report["stop_reason"],
                },
                "captures": captures,
            }

        if step.operation == "DONE":
            steps.append({"index": offset, "operation": "DONE", "status": "done"})
            return {
                "mode": "basic",
                "task": task.name,
                "status": "completed",
                "stop_reason": "task_complete",
                "steps": steps,
                "last_page": _page_summary(observation),
                "output": None,
                "captures": captures,
            }

        stale_refreshes = 0
        while True:
            element = None
            if step.operation in TARGETED_OPERATIONS:
                element, reason = _target_for_step(observation, step)
                if reason:
                    return stop(reason, failed_step=offset)
                if reason := _safe_target_reason(step, element, observation, task.allowed_origins):
                    return stop(reason, failed_step=offset)
            text = (
                inputs[step.input_name] if step.operation == "TYPE_TEXT" and step.input_name
                else captures[step.capture_name]["value"] if step.operation == "TYPE_TEXT" and step.capture_name
                else step.value if step.operation == "TYPE_TEXT" else None
            )
            try:
                execution = execute_action(
                    browser,
                    observation,
                    operation=step.operation,
                    target=element["index"] if element else None,
                    text=text,
                )
                break
            except StaleObservation:
                stale_refreshes += 1
                observation = browser.observe()
                if not _origin_allowed(observation["url"], task.allowed_origins):
                    return stop("origin_not_allowed")
                if stale_refreshes >= MAX_STALE_REFRESHES:
                    return stop(
                        "stale_observation_limit",
                        failed_step=offset,
                    )
            except ValueError:
                return stop(
                    "operation_unavailable",
                    failed_step=offset,
                )

        if execution["executed"] and step.operation in {"CLICK", "SUBMIT"}:
            execution["page_ready"] = browser.wait_for_page_ready(
                observation["url"],
                observation["fingerprint"],
            )
        after = browser.observe()
        step_result = {
            "index": offset,
            "operation": step.operation,
            "status": execution["status"],
            "target_name": element_description(element) if element else None,
            "before_url": observation["url"],
            "after_url": after["url"],
            "observation_changed": observation["fingerprint"] != after["fingerprint"],
            "url_changed": observation["url"] != after["url"],
        }
        if "page_ready" in execution:
            step_result["page_ready"] = execution["page_ready"]
        steps.append(step_result)
        observation = after
        if not _origin_allowed(observation["url"], task.allowed_origins):
            return stop("origin_not_allowed")
        if execution["executed"] and not step_result["observation_changed"]:
            return stop("no_effect", failed_step=offset)

    return {
        "mode": "basic",
        "task": task.name,
        "status": "completed",
        "stop_reason": "task_complete",
        "steps": steps,
        "last_page": _page_summary(observation),
        "output": None,
        "captures": captures,
    }
