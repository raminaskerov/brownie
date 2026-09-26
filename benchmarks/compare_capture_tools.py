"""Compare model-free copy/paste through Brownie, direct Playwright, and agent-browser."""

import argparse
import json
import os
import re
import statistics
import subprocess
import tempfile
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright

from brownie_agent.basic import parse_basic_task, run_basic_task
from brownie_agent.browser import BrowserSession

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests"
EXPECTED = "solar report"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args) -> None:
        pass


def _brownie(url: str, profile: Path) -> None:
    task = parse_basic_task({
        "version": 1,
        "name": "Copy report reference",
        "start_url": url,
        "allowed_origins": [url.rsplit("/", 1)[0]],
        "inputs": [],
        "steps": [
            {"operation": "CAPTURE_TEXT", "line_contains": "Reference: solar report",
             "extract_after": "Reference:", "save_as": "reference"},
            {"operation": "TYPE_TEXT", "target": {"role": "textbox", "name": "Reference"},
             "capture": "reference"},
            {"operation": "DONE"},
        ],
    })
    with BrowserSession(profile_dir=profile) as browser:
        result = run_basic_task(browser, task)
        actual = browser.observe()["elements"][0]["value"]
    if result["status"] != "completed" or actual != EXPECTED:
        raise AssertionError(f"Brownie result: {result['status']}; field: {actual!r}")


def _playwright(url: str, profile: Path) -> None:
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            profile,
            channel="chrome",
            chromium_sandbox=True,
            headless=True,
            viewport={"width": 1120, "height": 780},
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            line = page.get_by_text("Reference: solar report", exact=True).inner_text()
            captured = line.split("Reference:", 1)[1].strip()
            field = page.get_by_role("textbox", name="Reference", exact=True)
            field.fill(captured)
            if field.input_value() != EXPECTED:
                raise AssertionError("Direct Playwright field value did not match")
        finally:
            context.close()


def _agent_browser(url: str, profile: Path, binary: Path, repetition: int) -> None:
    environment = os.environ.copy()
    environment.update({
        "AGENT_BROWSER_NAMESPACE": f"brownie-capture-benchmark-{os.getpid()}-{repetition}",
        "AGENT_BROWSER_EXECUTABLE_PATH": "/usr/bin/google-chrome",
        "AGENT_BROWSER_PROFILE": str(profile),
    })

    def call(*arguments: str) -> str:
        process = subprocess.run(
            [str(binary), *arguments],
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=True,
        )
        return process.stdout.strip()

    opened = False
    try:
        call("open", url)
        opened = True
        snapshot = call("snapshot", "-i")
        references = re.findall(r'textbox "Reference" \[ref=(\w+)\]', snapshot)
        if len(references) != 1:
            raise AssertionError("agent-browser did not expose one Reference textbox")
        line = call("get", "text", "p")
        if not line.startswith("Reference:"):
            raise AssertionError("agent-browser did not read the reference line")
        captured = line.split("Reference:", 1)[1].strip()
        call("fill", "@" + references[0], captured)
        if call("get", "value", "@" + references[0]) != EXPECTED:
            raise AssertionError("agent-browser field value did not match")
    finally:
        if opened:
            call("close")


def compare(repetitions: int, binary: Path | None) -> dict:
    if type(repetitions) is not int or not 1 <= repetitions <= 20:
        raise ValueError("repetitions must be from 1 to 20")
    if binary is not None and not binary.is_file():
        raise ValueError("agent-browser binary was not found")
    handler = partial(QuietHandler, directory=str(FIXTURE_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/capture_fixture.html"
    runners = {
        "brownie": lambda profile, _repetition: _brownie(url, profile),
        "playwright": lambda profile, _repetition: _playwright(url, profile),
    }
    if binary is not None:
        runners["agent-browser"] = lambda profile, repetition: _agent_browser(url, profile, binary, repetition)
    records = []
    try:
        names = list(runners)
        for repetition in range(repetitions):
            ordered = names[repetition % len(names):] + names[:repetition % len(names)]
            for name in ordered:
                with tempfile.TemporaryDirectory(prefix="brownie-capture-compare-") as temporary:
                    started = time.perf_counter()
                    try:
                        runners[name](Path(temporary), repetition)
                        outcome, reason = "completed", None
                    except Exception as exc:
                        outcome, reason = "error", f"{type(exc).__name__}: {exc}"
                    elapsed_ms = round((time.perf_counter() - started) * 1000)
                records.append({
                    "tool": name,
                    "repetition": repetition + 1,
                    "outcome": outcome,
                    "reason": reason,
                    "elapsed_ms": elapsed_ms,
                    "model_calls": 0,
                })
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    summary = [{
        "tool": name,
        "verified_runs": sum(record["outcome"] == "completed" for record in records if record["tool"] == name),
        "runs": repetitions,
        "median_elapsed_ms": round(statistics.median(
            record["elapsed_ms"] for record in records if record["tool"] == name
        )),
        "model_calls": 0,
    } for name in runners]
    return {
        "fixture": "capture_fixture.html over one localhost HTTP server",
        "browser": "installed Google Chrome, fresh isolated profile, security sandbox required",
        "timing": "browser startup through close and verified final field value",
        "summary": summary,
        "runs": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--agent-browser-binary", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = compare(arguments.repetitions, arguments.agent_browser_binary)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if any(record["outcome"] != "completed" for record in result["runs"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
