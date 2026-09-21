"""Private, opt-in decision traces and a small text-only HTML inspector."""

import html
import json
import time
from contextvars import ContextVar
from pathlib import Path

ACTION_EXPLANATIONS = {
    "CLICK": "Activate one currently visible indexed element.",
    "TYPE_TEXT": "Replace the value of one currently visible editable element; does not submit it.",
    "SUBMIT": "Press Enter in one currently visible form-associated editable element.",
    "SCROLL_DOWN": "Move down by about 80% of the current viewport, then observe again.",
    "SCROLL_UP": "Move up by about 80% of the current viewport, then observe again.",
    "DONE": "Stop because the visible evidence is claimed to satisfy the goal; performs no browser mutation.",
    "BLOCKED": "Stop because no offered operation is claimed to make progress; performs no browser mutation.",
}

EVENT_TITLES = {
    "run": "Run configuration",
    "controller_memory": "Controller memory before decision",
    "steering_context": "Observation and steerer context",
    "model_request": "Exact model request",
    "model_response": "Exact model response",
    "model_attempt": "Model attempt",
    "steering_result": "Steering choice",
    "execution_check": "Freshness and action check",
    "execution_result": "Executed action",
    "page_read_view": "Source-reading viewport",
    "page_read_result": "Source-reading result",
    "run_result": "Final Brownie result",
    "error": "Run error",
}

_ACTIVE_TRACE: ContextVar["TraceRecorder | None"] = ContextVar("brownie_trace", default=None)


def trace_event(event: str, data: dict) -> None:
    """Record an event only when the caller opted into a trace."""
    recorder = _ACTIVE_TRACE.get()
    if recorder is not None:
        recorder.record(event, data)


def _pretty(value) -> str:
    return html.escape(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


def _details(label: str, value, *, opened: bool = False) -> str:
    open_attribute = " open" if opened else ""
    return f"<details{open_attribute}><summary>{html.escape(label)}</summary><pre>{_pretty(value)}</pre></details>"


def _summary(event: dict) -> str:
    kind = event["event"]
    data = event["data"]
    if kind == "steering_context":
        observation = data["observer_output"]
        state = data["provider_input"]
        return (
            f"<p><b>{html.escape(data['route']['provider'])}</b> receives "
            f"{len(state['current_elements'])} elements, {len(state['current_page']['visible_text'])} text characters, "
            f"and {len(state['recent_steps'])} prior steps. Observer omitted "
            f"{observation.get('omitted_elements', 0)} additional visible elements.</p>"
            + _details("Observer output before privacy reduction", observation)
            + _details("Exact factual state sent to the provider", state, opened=True)
            + _details("Exact offered action space", data["action_space"], opened=True)
            + _details("Routing decision", data["route"])
        )
    if kind == "controller_memory":
        return (
            f"<p>{len(data['sent_to_provider'])} recent steps are sent. The remaining controller memory is stored "
            "locally and is not currently retrieved into the provider context.</p>"
            + _details("Memory sent to provider", data["sent_to_provider"], opened=True)
            + _details("Stored controller memory not sent", data["stored_not_sent"], opened=True)
        )
    if kind == "model_request":
        body = data["body"]
        size = len(json.dumps(body, ensure_ascii=False))
        return (
            f"<p>{html.escape(data['provider'])} / {html.escape(data['role'])} / "
            f"{html.escape(str(data['model']))} — {size:,} JSON characters before transport encoding.</p>"
            + _details("Exact request body, without credentials", body, opened=True)
        )
    if kind == "model_response":
        response = data["response"]
        answers = response.get("answers") if isinstance(response, dict) else None
        rendered = ""
        if isinstance(answers, dict):
            score_rows = []
            for question, answer in answers.items():
                if not isinstance(answer, dict) or "choice" not in answer:
                    continue
                score_rows.append(
                    "<tr><td>" + html.escape(question) + "</td><td>" + html.escape(str(answer.get("choice")))
                    + "</td><td>" + html.escape(str(answer.get("confidence"))) + "</td><td><pre>"
                    + _pretty(answer.get("probabilities", {})) + "</pre></td></tr>"
                )
            if score_rows:
                rendered = (
                    "<table><thead><tr><th>Question</th><th>Choice</th><th>Confidence</th>"
                    "<th>Probabilities</th></tr></thead><tbody>" + "".join(score_rows) + "</tbody></table>"
                )
        return rendered + _details("Exact raw response", response, opened=True)
    if kind == "steering_result":
        choice = data["choice"]
        target = f" target {choice.get('target')} ({choice.get('target_name')})" if choice.get("target") else ""
        explanation = ACTION_EXPLANATIONS.get(choice.get("operation"), "Unknown operation")
        return (
            f"<p><b>{html.escape(choice.get('operation', 'unknown'))}</b>{html.escape(target)} — "
            f"{html.escape(explanation)}</p>" + _details("Complete parsed choice", choice, opened=True)
        )
    if kind == "execution_result":
        result = data["result"]
        return (
            f"<p><b>{html.escape(result['operation'])}</b>: {html.escape(result['status'])}; "
            f"browser mutation executed={str(result['executed']).lower()}.</p>"
            + _details("Execution result", result, opened=True)
        )
    if kind == "page_read_view":
        observation = data["observation"]
        viewport = observation["viewport"]
        return (
            f"<p>scroll_y={viewport['scroll_y']}; {len(observation['text'])} text characters; "
            f"{len(observation['elements'])} visible elements; can_scroll_down="
            f"{str(observation['can_scroll_down']).lower()}.</p>"
            + _details("Exact viewport observation", observation)
        )
    return _details("Event data", data, opened=True)


def _render_html(events: list[dict]) -> str:
    legend = "".join(
        f"<tr><td><code>{html.escape(operation)}</code></td><td>{html.escape(description)}</td></tr>"
        for operation, description in ACTION_EXPLANATIONS.items()
    )
    cards = "".join(
        "<section><h2>"
        f"{event['sequence']}. {html.escape(EVENT_TITLES.get(event['event'], event['event']))}"
        f" <small>+{event['elapsed_ms']} ms</small></h2>{_summary(event)}</section>"
        for event in events
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Brownie run inspector</title>
<style>
body {{ background:#f5f4ef; color:#222; font:15px/1.45 system-ui,sans-serif;
        margin:0 auto; max-width:1100px; padding:24px; }}
h1 {{ margin-bottom:4px; }} h2 {{ font-size:18px; }} small {{ color:#666; font-weight:normal; }}
section {{ background:white; border:1px solid #d8d5cc; border-radius:8px; margin:16px 0; padding:16px; }}
details {{ border-top:1px solid #ece9e1; margin-top:10px; padding-top:8px; }}
summary {{ cursor:pointer; font-weight:600; }}
pre {{ background:#171717; color:#eee; overflow:auto; padding:12px; white-space:pre-wrap; word-break:break-word; }}
table {{ border-collapse:collapse; width:100%; }}
th,td {{ border:1px solid #ddd; padding:7px; text-align:left; vertical-align:top; }}
td pre {{ margin:0; }} code {{ font-weight:700; }} .notice {{ color:#664d03; }}
</style></head><body>
<h1>Brownie run inspector</h1>
<p class="notice">Local opt-in trace. It can contain page text, URLs, and entered field values.
The viewer makes no network requests.</p>
<section><h2>What the action words mean</h2><table><tbody>{legend}</tbody></table></section>
{cards}
</body></html>"""


class TraceRecorder:
    """Append exact JSON events and generate a text-only companion HTML file."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        if self.path.suffix.lower() != ".jsonl":
            raise ValueError("--trace must name a .jsonl file")
        self.html_path = self.path.with_suffix(".html")
        self.events: list[dict] = []
        self.started = 0.0
        self._token = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        self.path.chmod(0o600)
        self.started = time.perf_counter()
        self._token = _ACTIVE_TRACE.set(self)
        return self

    def record(self, event: str, data: dict) -> None:
        detached = json.loads(json.dumps(data, ensure_ascii=False))
        item = {
            "sequence": len(self.events) + 1,
            "event": event,
            "elapsed_ms": round((time.perf_counter() - self.started) * 1000),
            "data": detached,
        }
        self.events.append(item)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        self._write_html()

    def _write_html(self) -> None:
        temporary = self.html_path.with_suffix(".html.tmp")
        temporary.write_text(_render_html(self.events), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(self.html_path)

    def __exit__(self, exc_type, exc, _traceback):
        if exc is not None:
            self.record("error", {"type": exc_type.__name__, "message": str(exc)})
        self._write_html()
        if self._token is not None:
            _ACTIVE_TRACE.reset(self._token)
