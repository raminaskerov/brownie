"""Entry point shared by the double-click app and its internal worker."""

import multiprocessing
import sys

from .launcher import SELF_CHECK_FLAG, WORKER_FLAG


def _line_buffer_worker_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True)


def main() -> None:
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == WORKER_FLAG:
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        _line_buffer_worker_streams()
        from .cli import main as cli_main

        cli_main()
        return
    if len(sys.argv) > 1 and sys.argv[1] == SELF_CHECK_FLAG:
        from playwright.sync_api import sync_playwright

        from .browser import OBSERVER

        if "window.__brownie" not in OBSERVER:
            raise SystemExit(1)
        with sync_playwright() as playwright:
            if playwright.chromium.name != "chromium":
                raise SystemExit(1)
        return
    from .ui import main as ui_main

    ui_main()


if __name__ == "__main__":
    main()
