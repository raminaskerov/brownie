"""Compare Brownie Basic with direct Playwright on a fixed local Chrome task set."""

import argparse
import json
import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from brownie_agent.basic import parse_basic_task, run_basic_task
from brownie_agent.browser import BrowserSession

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Case:
    name: str
    start_url: str
    steps: tuple[dict, ...]
    expected: str


CASES = (
    Case(
        "capture_and_paste",
        (TESTS / "capture_fixture.html").as_uri(),
        (
            {"operation": "CAPTURE_TEXT", "line_contains": "Reference: solar report",
             "extract_after": "Reference:", "save_as": "reference"},
            {"operation": "TYPE_TEXT", "target": {"role": "textbox", "name": "Reference"},
             "capture": "reference"},
            {"operation": "DONE"},
        ),
        "completed",
    ),
    Case(
        "search_submission",
        (TESTS / "fixture.html").as_uri(),
        (
            {"operation": "TYPE_TEXT", "target": {"role": "searchbox", "name": "Destination"},
             "value": "Istanbul"},
            {"operation": "SUBMIT", "target": {"role": "searchbox", "name": "Destination"}},
            {"operation": "ASSERT", "check": {"text_contains": "searched"}},
            {"operation": "DONE"},
        ),
        "completed",
    ),
    Case(
        "delayed_navigation",
        (TESTS / "fixture.html").as_uri(),
        (
            {"operation": "CLICK", "target": {"role": "link", "name": "Open delayed page"}},
            {"operation": "ASSERT", "check": {"text_contains": "Content rendered after navigation"}},
            {"operation": "DONE"},
        ),
        "completed",
    ),
    Case(
        "ambiguous_target",
        (HERE / "ambiguous_fixture.html").as_uri(),
        (
            {"operation": "TYPE_TEXT", "target": {"role": "textbox", "name": "Reference"},
             "value": "solar report"},
            {"operation": "DONE"},
        ),
        "safe_stop",
    ),
)


def _brownie(case: Case, profile: Path) -> tuple[str, str]:
    task = parse_basic_task({
        "version": 1,
        "name": case.name,
        "start_url": case.start_url,
        "allowed_origins": ["file://"],
        "inputs": [],
        "steps": list(case.steps),
    })
    with BrowserSession(profile_dir=profile) as browser:
        result = run_basic_task(browser, task)
        current = browser.observe()
    if case.name == "capture_and_paste" and result["status"] == "completed":
        if result["captures"]["reference"]["value"] != "solar report":
            return "wrong_result", "captured value was wrong"
        if current["elements"][0]["value"] != "solar report":
            return "wrong_result", "typed value was wrong"
    if case.name == "ambiguous_target":
        if result["status"] == "stopped" and result["stop_reason"] == "target_ambiguous":
            return "safe_stop", result["stop_reason"]
        return "wrong_result", result["stop_reason"]
    return result["status"], result["stop_reason"]


def _playwright(case: Case, profile: Path) -> tuple[str, str]:
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
            page.goto(case.start_url, wait_until="domcontentloaded")
            if case.name == "capture_and_paste":
                source = page.get_by_text("Reference: solar report", exact=True)
                captured = source.inner_text().split("Reference:", 1)[1].strip()
                page.get_by_role("textbox", name="Reference", exact=True).fill(captured)
                return ("completed", "task_complete") if (
                    captured == "solar report"
                    and page.get_by_role("textbox", name="Reference", exact=True).input_value() == "solar report"
                ) else ("wrong_result", "captured or typed value was wrong")
            if case.name == "search_submission":
                field = page.get_by_role("searchbox", name="Destination", exact=True)
                field.fill("Istanbul")
                field.press("Enter")
                return ("completed", "task_complete") if page.get_by_text("searched", exact=True).is_visible() \
                    else ("wrong_result", "searched status was not visible")
            if case.name == "delayed_navigation":
                page.get_by_role("link", name="Open delayed page", exact=True).click()
                page.get_by_role("heading", name="Content rendered after navigation", exact=True).wait_for(
                    state="visible",
                )
                return "completed", "task_complete"
            if case.name == "ambiguous_target":
                try:
                    page.get_by_role("textbox", name="Reference", exact=True).fill("solar report")
                except PlaywrightError as exc:
                    if "strict mode violation" in str(exc):
                        return "safe_stop", "strict_mode_violation"
                    raise
                return "wrong_result", "ambiguous field was filled"
            raise ValueError(f"Unknown case: {case.name}")
        finally:
            context.close()


def run_comparison(repetitions: int) -> dict:
    if type(repetitions) is not int or not 1 <= repetitions <= 20:
        raise ValueError("repetitions must be from 1 to 20")
    records = []
    for repetition in range(repetitions):
        tools = ("brownie", "playwright") if repetition % 2 == 0 else ("playwright", "brownie")
        for case in CASES:
            for tool in tools:
                with tempfile.TemporaryDirectory(prefix="brownie-benchmark-") as temporary:
                    started = time.perf_counter()
                    try:
                        outcome, reason = (
                            _brownie(case, Path(temporary))
                            if tool == "brownie" else _playwright(case, Path(temporary))
                        )
                    except Exception as exc:
                        outcome, reason = "error", f"{type(exc).__name__}: {exc}"
                    elapsed_ms = round((time.perf_counter() - started) * 1000)
                records.append({
                    "case": case.name,
                    "tool": tool,
                    "repetition": repetition + 1,
                    "outcome": outcome,
                    "reason": reason,
                    "expected": case.expected,
                    "verified": outcome == case.expected,
                    "elapsed_ms": elapsed_ms,
                    "model_calls": 0,
                })
    summary = []
    for case in CASES:
        for tool in ("brownie", "playwright"):
            group = [record for record in records if record["case"] == case.name and record["tool"] == tool]
            summary.append({
                "case": case.name,
                "tool": tool,
                "verified_runs": sum(record["verified"] for record in group),
                "runs": len(group),
                "median_elapsed_ms": round(statistics.median(record["elapsed_ms"] for record in group)),
                "model_calls": 0,
            })
    return {
        "environment": "local fixture, installed Google Chrome, fresh persistent profile per run",
        "repetitions": repetitions,
        "summary": summary,
        "runs": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    arguments = parser.parse_args()
    result = run_comparison(arguments.repetitions)
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if any(not record["verified"] for record in result["runs"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
