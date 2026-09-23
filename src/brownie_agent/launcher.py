"""Small source/frozen-process launch boundary."""

import sys

WORKER_FLAG = "--brownie-worker"
SELF_CHECK_FLAG = "--self-check"


def worker_command() -> list[str]:
    """Return the CLI prefix for a source checkout or the packaged app."""
    if getattr(sys, "frozen", False):
        return [sys.executable, WORKER_FLAG]
    return [sys.executable, "-m", "brownie_agent.cli"]
