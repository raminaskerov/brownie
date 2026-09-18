"""Command-line entry point for Brownie's observe-and-scroll milestone."""

import argparse
import json
from pathlib import Path

from .access import READY, classify_access, local_blocked_prediction
from .actions import OPERATIONS, execute_action, execute_prediction
from .browser import BrowserSession
from .config import load_env
from .model import predict_action
from .reader import read_page
from .state import text_field_state
from .text_model import generate_field_text


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Open one page and list its visible controls.")
    result.add_argument("url", help="Page to open, including https://")
    result.add_argument("--headed", action="store_true", help="Show the isolated browser window")
    result.add_argument("--profile", type=Path, default=Path(".browser-profile"), help="Dedicated profile directory")
    result.add_argument("--channel", default="chrome", help="Installed Chromium channel (default: chrome)")
    result.add_argument("--attach", action="store_true", help="Attach to a user-launched Chrome debugging session")
    result.add_argument(
        "--use-open-tab",
        action="store_true",
        help="With --attach, reuse a matching open tab without navigating or closing it",
    )
    result.add_argument(
        "--cdp-endpoint",
        default="http://127.0.0.1:9222",
        help="Chrome debugging endpoint for --attach (default: http://127.0.0.1:9222)",
    )
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--scroll-down", action="store_true", help="Scroll down once before printing")
    mode.add_argument("--read-page", action="store_true", help="Read successive viewports with a hard limit")
    mode.add_argument("--action", choices=OPERATIONS, help="Execute exactly one manually selected operation")
    mode.add_argument("--predict", action="store_true", help="Ask Jev for one choice without executing it")
    mode.add_argument("--step", action="store_true", help="Ask Jev and execute at most one non-text action")
    mode.add_argument("--login", action="store_true", help="Open a headed browser for manual login preparation")
    result.add_argument("--target", type=int, help="Current observed element index for CLICK or TYPE_TEXT")
    result.add_argument("--text", help="Replacement field value for TYPE_TEXT")
    result.add_argument("--goal", help="Natural-language goal for --predict")
    result.add_argument("--env-file", type=Path, help="Environment file (default: Brownie's .env)")
    result.add_argument("--max-scrolls", type=int, default=10, help="Maximum scrolls for --read-page (default: 10)")
    result.add_argument("--json", action="store_true", help="Print the complete observation as JSON")
    return result


def print_observation(observation: dict) -> None:
    print(f"{observation['title']}\n{observation['url']}\n")
    for element in observation["elements"]:
        value = f" = {element['value']}" if element.get("value") else ""
        print(f"[{element['index']}] {element['role']:<11} {element['name']}{value}")
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
    print(f"Operation: {execution['operation']}{target}")
    print(f"Status: {execution['status']}\n")
    print_observation(result["observation"])


def print_prediction(result: dict) -> None:
    prediction = result["prediction"]
    target = f" [{prediction['target']}] {prediction['target_name']}" if prediction["target"] else ""
    print("Prediction only — nothing executed")
    print(f"Operation: {prediction['operation']}{target}")
    if prediction.get("source") == "local_access_guard":
        print(f"Local access guard: {prediction['blocked_reason']} — Jev was not called\n")
    else:
        print(f"Confidence: {prediction['confidence']:.3f}")
        print(f"Model: {prediction['model']} · {prediction['latency_ms']} ms\n")
    print_observation(result["observation"])


def print_step(result: dict) -> None:
    prediction = result["prediction"]
    execution = result["execution"]
    target = f" [{prediction['target']}] {prediction['target_name']}" if prediction["target"] else ""
    print(f"Jev choice: {prediction['operation']}{target}")
    if prediction.get("source") == "local_access_guard":
        print(f"Local access guard: {prediction['blocked_reason']} — Jev was not called")
    else:
        print(f"Confidence: {prediction['confidence']:.3f}")
        print(f"Model: {prediction['model']} · {prediction['latency_ms']} ms")
    print(f"Execution: {execution['status']}\n")
    print_observation(result["observation"])


def print_login(result: dict) -> None:
    access = result["access"]
    if access["status"] == READY:
        print("Login preparation complete. The dedicated browser profile was preserved.")
    else:
        print(f"Login preparation ended with {access['status']} ({access['reason']}).")
        print("Run --login again when you are ready to complete the browser interaction.")
    print_observation(result["observation"])


def main() -> None:
    argument_parser = parser()
    args = argument_parser.parse_args()
    if (args.predict or args.step) and not args.goal:
        argument_parser.error("--predict and --step require --goal")
    if args.goal and not (args.predict or args.step):
        argument_parser.error("--goal is currently used only with --predict or --step")
    if args.use_open_tab and not args.attach:
        argument_parser.error("--use-open-tab requires --attach")
    if args.predict or args.step:
        load_env(args.env_file)
    with BrowserSession(
        profile_dir=args.profile,
        headed=args.headed or args.login,
        channel=args.channel,
        cdp_url=args.cdp_endpoint if args.attach else None,
    ) as browser:
        browser.open(args.url, use_open_tab=args.use_open_tab)
        if args.login:
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
                    predict_action(result, args.goal)
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
                    if execution["executed"] and execution["operation"] == "CLICK":
                        execution["page_ready"] = browser.wait_for_page_ready(result["url"])
                    result = {
                        "prediction": prediction,
                        "execution": execution,
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
                if execution["executed"] and args.action == "CLICK":
                    execution["page_ready"] = browser.wait_for_page_ready(result["url"])
                result = {"execution": execution, "observation": browser.observe()}
            elif args.scroll_down and result["can_scroll_down"]:
                browser.scroll_down()
                result = browser.observe()
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
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
