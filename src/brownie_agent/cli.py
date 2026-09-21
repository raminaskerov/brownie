"""Command-line entry point for Brownie's observe-and-scroll milestone."""

import argparse
import json
import sys
from contextlib import ExitStack
from pathlib import Path

from .access import READY, classify_access, local_blocked_prediction
from .actions import OPERATIONS, execute_action, execute_prediction
from .browser import BrowserSession
from .config import load_env
from .managed_chrome import ManagedChrome
from .reader import read_page
from .search import run_search
from .state import text_field_state
from .steering import steer_action
from .text_model import generate_field_text


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Open one page and list its visible controls.")
    result.add_argument("url", nargs="?", help="Page to open, including https://")
    result.add_argument("--headed", action="store_true", help="Show the isolated browser window")
    result.add_argument(
        "--keep-open",
        action="store_true",
        help="Keep Brownie's browser open after completion until Enter is pressed",
    )
    result.add_argument(
        "--profile",
        type=Path,
        help="Dedicated profile directory (default: .browser-profile or .browser-profile-cdp)",
    )
    result.add_argument("--channel", default="chrome", help="Installed Chromium channel (default: chrome)")
    browser_mode = result.add_mutually_exclusive_group()
    browser_mode.add_argument(
        "--attach",
        action="store_true",
        help="Attach to a user-launched Chrome debugging session",
    )
    browser_mode.add_argument(
        "--managed-cdp",
        action="store_true",
        help="Start ordinary headed Chrome, then attach through a private localhost CDP endpoint",
    )
    result.add_argument(
        "--use-open-tab",
        action="store_true",
        help="With --attach, reuse a matching open tab without navigating or closing it",
    )
    result.add_argument(
        "--cdp-endpoint",
        default="http://127.0.0.1:9222",
        help="Chrome debugging endpoint for --attach or --managed-cdp (default: http://127.0.0.1:9222)",
    )
    result.add_argument("--chrome-executable", type=Path, help="Chrome executable for --managed-cdp")
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--scroll-down", action="store_true", help="Scroll down once before printing")
    mode.add_argument("--read-page", action="store_true", help="Read successive viewports with a hard limit")
    mode.add_argument("--action", choices=OPERATIONS, help="Execute exactly one manually selected operation")
    mode.add_argument("--predict", action="store_true", help="Ask the steerer for one choice without executing it")
    mode.add_argument("--step", action="store_true", help="Ask the steerer and execute at most one action")
    mode.add_argument("--search", action="store_true", help="Search the web, open one source, read it, and stop")
    result.add_argument("--steerer", choices=("jev", "llm"), help="Action steering provider (default: jev)")
    mode.add_argument("--login", action="store_true", help="Open a headed browser for manual login preparation")
    result.add_argument("--target", type=int, help="Current observed element index for CLICK, TYPE_TEXT, or SUBMIT")
    result.add_argument("--text", help="Replacement field value for TYPE_TEXT")
    result.add_argument("--goal", help="Natural-language goal for --predict, --step, or --search")
    result.add_argument("--env-file", type=Path, help="Environment file (default: Brownie's .env)")
    result.add_argument("--max-scrolls", type=int, default=10, help="Maximum scrolls for --read-page (default: 10)")
    result.add_argument("--max-steps", type=int, default=8, help="Maximum browser actions for --search (default: 8)")
    result.add_argument("--max-pages", type=int, default=3, help="Maximum distinct pages for --search (default: 3)")
    result.add_argument("--json", action="store_true", help="Print the complete observation as JSON")
    return result


def print_observation(observation: dict, *, heading: str = "Current snapshot") -> None:
    print(f"{heading}: {observation['fingerprint'][:12]}")
    print(f"{observation['title']}\n{observation['url']}\n")
    for element in observation["elements"]:
        value = f" = {element['value']}" if element.get("value") else ""
        context = f" · {element['context']}" if element.get("context") else ""
        destination = f" · {element['destination']}" if element.get("destination") else ""
        print(f"[{element['index']}] {element['role']:<11} {element['name']}{value}{context}{destination}")
    if observation["omitted_elements"]:
        print(f"\n... {observation['omitted_elements']} additional visible elements omitted")
    directions = []
    if observation["can_scroll_up"]:
        directions.append("up")
    if observation["can_scroll_down"]:
        directions.append("down")
    print(f"\nVisible text: {len(observation['text'])} characters")
    print(f"Can scroll: {', '.join(directions) if directions else 'no'}")
    access = classify_access(observation)
    if access["status"] != READY:
        print(f"Access: {access['status']} ({access['reason']})")


def print_page_read(report: dict) -> None:
    print(f"{report['title']}\n{report['url']}\n")
    for offset, element in enumerate(report["seen_elements"], 1):
        value = f" = {element['value']}" if element.get("value") else ""
        print(f"[{offset}] {element['role']:<11} {element['name']}{value}")
    print(f"\nRead {len(report['views'])} view(s) with {report['scrolls']} scroll(s)")
    print(f"Stopped: {report['stop_reason']}")
    print(f"Combined text: {len(report['combined_text'])} characters")


def print_execution(result: dict) -> None:
    execution = result["execution"]
    target = f" [{execution['target']}] {execution['target_name']}" if execution["target"] else ""
    print(f"Decision snapshot: {result['decision_fingerprint'][:12]}")
    print(f"Operation: {execution['operation']}{target}")
    print(f"Status: {execution['status']}\n")
    print_observation(result["observation"], heading="After-action snapshot")


def print_prediction(result: dict) -> None:
    prediction = result["prediction"]
    target = f" [{prediction['target']}] {prediction['target_name']}" if prediction["target"] else ""
    print("Prediction only — nothing executed")
    print(f"Operation: {prediction['operation']}{target}")
    print_steering_details(prediction)
    print_observation(result["observation"], heading="Prediction snapshot")


def print_steering_details(prediction: dict) -> None:
    """Show shared fields and optional provider diagnostics without requiring probabilities."""
    print(f"Steering source: {prediction.get('source', 'unknown')}")
    if prediction.get("source") == "local_access_guard":
        print(f"Local access guard: {prediction['blocked_reason']} — no steering provider was called")
    if prediction.get("routing"):
        print(f"Routing: {prediction['routing']['reason']}")
    if prediction.get("confidence") is not None:
        print(f"Confidence: {prediction['confidence']:.3f}")
    if prediction.get("model") is not None:
        print(f"Model: {prediction['model']}")
    if prediction.get("latency_ms") is not None:
        print(f"Latency: {prediction['latency_ms']} ms")
    for attempt in prediction.get("model_attempts", []):
        print(f"Model attempt: {attempt['model']} — {attempt['status']}")
    if prediction.get("text_mode"):
        confidence = prediction.get("text_mode_confidence")
        suffix = f" ({confidence:.3f})" if confidence is not None else ""
        print(f"Text mode: {prediction['text_mode']}{suffix}")


def print_step(result: dict) -> None:
    prediction = result["prediction"]
    execution = result["execution"]
    target = f" [{prediction['target']}] {prediction['target_name']}" if prediction["target"] else ""
    print(f"Decision snapshot: {result['decision_fingerprint'][:12]}")
    print(f"Steering choice ({prediction.get('source', 'unknown')}): {prediction['operation']}{target}")
    print_steering_details(prediction)
    print(f"Execution: {execution['status']}\n")
    if execution.get("text_model"):
        metadata = execution["text_model"]
        print(f"Text model: {metadata['model']}")
        for attempt in metadata.get("model_attempts", []):
            print(f"Text model attempt: {attempt['model']} — {attempt['status']}")
    print_observation(result["observation"], heading="After-action snapshot")


def print_login(result: dict) -> None:
    access = result["access"]
    if access["status"] == READY:
        print("Login preparation complete. The dedicated browser profile was preserved.")
    else:
        print(f"Login preparation ended with {access['status']} ({access['reason']}).")
        print("Run --login again when you are ready to complete the browser interaction.")
    print_observation(result["observation"])


def print_search(result: dict) -> None:
    print(f"Search status: {result['status']} ({result['stop_reason']})")
    if result.get("search_query"):
        print(f"Query: {result['search_query']}")
    source = result.get("source")
    if source is None:
        page = result["last_page"]
        print(f"Stopped at: {page['title']}\n{page['url']}")
        return
    print(f"Source: {source['title']}\n{source['url']}")
    print(f"Read with {source['scrolls']} scroll(s); stopped: {source['stop_reason']}\n")
    print(source["material"])


def main() -> None:
    argument_parser = parser()
    args = argument_parser.parse_args()
    if (args.predict or args.step or args.search) and not args.goal:
        argument_parser.error("--predict, --step, and --search require --goal")
    if args.goal and not (args.predict or args.step or args.search):
        argument_parser.error("--goal is currently used only with --predict, --step, or --search")
    if args.search and args.url:
        argument_parser.error("--search chooses its own search-engine URL; do not supply a URL")
    if not args.search and not args.url:
        argument_parser.error("a URL is required unless --search is used")
    if args.search and args.attach:
        argument_parser.error("--search cannot use a user-owned --attach session; use --managed-cdp instead")
    if args.use_open_tab and not args.attach:
        argument_parser.error("--use-open-tab requires --attach")
    if args.chrome_executable and not args.managed_cdp:
        argument_parser.error("--chrome-executable requires --managed-cdp")
    if args.steerer and not (args.predict or args.step or args.search):
        argument_parser.error("--steerer requires --predict, --step, or --search")
    if args.predict or args.step or args.search:
        load_env(args.env_file)
    profile_dir = args.profile or Path(".browser-profile-cdp" if args.managed_cdp else ".browser-profile")
    cdp_url = args.cdp_endpoint if args.attach or args.managed_cdp else None
    with ExitStack() as stack:
        if args.managed_cdp:
            stack.enter_context(
                ManagedChrome(
                    profile_dir=profile_dir,
                    endpoint=args.cdp_endpoint,
                    executable=args.chrome_executable,
                )
            )
        browser = stack.enter_context(
            BrowserSession(
                profile_dir=profile_dir,
                headed=args.headed or args.login or args.search or args.keep_open,
                channel=args.channel,
                cdp_url=cdp_url,
            )
        )
        if args.search:
            result = run_search(
                browser,
                args.goal,
                provider=args.steerer,
                max_steps=args.max_steps,
                max_pages=args.max_pages,
                max_scrolls=args.max_scrolls,
            )
        else:
            browser.open(args.url, use_open_tab=args.use_open_tab)
        if args.search:
            pass
        elif args.login:
            print("Complete login or the human challenge in the browser window.")
            print("Do not close the browser. Return here and press Enter when the destination page is ready.")
            try:
                input()
            except EOFError:
                raise RuntimeError("--login requires an interactive terminal") from None
            observation = browser.observe()
            result = {"access": classify_access(observation), "observation": observation}
        elif args.read_page:
            result = read_page(browser, max_scrolls=args.max_scrolls)
        else:
            result = browser.observe()
            if args.predict or args.step:
                access = classify_access(result)
                prediction = (
                    steer_action(result, args.goal, provider=args.steerer)
                    if access["status"] == READY
                    else local_blocked_prediction(access)
                )
                if args.step:
                    if access["status"] != READY:
                        execution = {
                            "operation": "BLOCKED",
                            "target": None,
                            "target_name": None,
                            "executed": False,
                            "status": "access_blocked",
                        }
                    elif prediction["operation"] == "TYPE_TEXT":
                        text_context = text_field_state(result, args.goal, prediction)
                        value, text_metadata = generate_field_text(text_context)
                        execution = execute_action(
                            browser,
                            result,
                            operation="TYPE_TEXT",
                            target=prediction["target"],
                            text=value,
                        )
                        execution["text_model"] = text_metadata
                    else:
                        execution = execute_prediction(browser, result, prediction)
                    if execution["executed"] and execution["operation"] in {"CLICK", "SUBMIT"}:
                        execution["page_ready"] = browser.wait_for_page_ready(result["url"])
                    result = {
                        "prediction": prediction,
                        "execution": execution,
                        "decision_fingerprint": result["fingerprint"],
                        "observation": browser.observe(),
                    }
                else:
                    result = {"prediction": prediction, "observation": result}
            elif args.action:
                execution = execute_action(
                    browser,
                    result,
                    operation=args.action,
                    target=args.target,
                    text=args.text,
                )
                if execution["executed"] and args.action in {"CLICK", "SUBMIT"}:
                    execution["page_ready"] = browser.wait_for_page_ready(result["url"])
                result = {
                    "execution": execution,
                    "decision_fingerprint": result["fingerprint"],
                    "observation": browser.observe(),
                }
            elif args.scroll_down and result["can_scroll_down"]:
                browser.scroll_down()
                result = browser.observe()
        if args.keep_open and not args.login:
            print("Brownie finished. Press Enter to close its browser.", file=sys.stderr)
            try:
                input()
            except EOFError:
                raise RuntimeError("--keep-open requires an interactive terminal") from None
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.search:
        print_search(result)
    elif args.read_page:
        print_page_read(result)
    elif args.action:
        print_execution(result)
    elif args.predict:
        print_prediction(result)
    elif args.step:
        print_step(result)
    elif args.login:
        print_login(result)
    else:
        print_observation(result)


if __name__ == "__main__":
    main()
