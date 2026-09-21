"""Launch ordinary Chrome with a private local CDP endpoint."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


def _local_cdp_port(endpoint: str) -> int:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.port is None
    ):
        raise ValueError("Managed CDP requires an endpoint like http://127.0.0.1:9222.")
    return parsed.port


def _chrome_candidates() -> list[Path | str]:
    if sys.platform == "win32":
        roots = [
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        return [
            Path(root) / "Google/Chrome/Application/chrome.exe"
            for root in roots
            if root
        ]
    if sys.platform == "darwin":
        return [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    return ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]


def find_chrome_executable(explicit: str | Path | None = None) -> Path:
    """Resolve a Chrome executable without asking Playwright to launch it."""
    if explicit is not None:
        candidate = Path(explicit).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise RuntimeError(f"Chrome executable not found: {candidate}")

    for candidate in _chrome_candidates():
        if isinstance(candidate, Path):
            if candidate.is_file():
                return candidate.resolve()
        else:
            resolved = shutil.which(candidate)
            if resolved:
                return Path(resolved).resolve()
    raise RuntimeError("Google Chrome was not found. Pass --chrome-executable with its full path.")


def _cdp_ready(endpoint: str) -> bool:
    try:
        with urlopen(f"{endpoint.rstrip('/')}/json/version", timeout=0.25) as response:
            return response.status == 200
    except (OSError, URLError, ValueError):
        return False


class ManagedChrome:
    """Own one normally launched Chrome process and its localhost CDP endpoint."""

    def __init__(
        self,
        *,
        profile_dir: str | Path = ".browser-profile-cdp",
        endpoint: str = "http://127.0.0.1:9222",
        executable: str | Path | None = None,
        startup_timeout: float = 10.0,
    ):
        self.profile_dir = Path(profile_dir).expanduser().resolve()
        self.endpoint = endpoint.rstrip("/")
        self.executable = executable
        self.startup_timeout = startup_timeout
        self.process: subprocess.Popen | None = None

    def __enter__(self):
        port = _local_cdp_port(self.endpoint)
        if _cdp_ready(self.endpoint):
            raise RuntimeError(
                f"A Chrome debugging session is already available at {self.endpoint}. "
                "Use --attach to connect to it instead of --managed-cdp."
            )

        chrome = find_chrome_executable(self.executable)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        command = [
            str(chrome),
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={self.profile_dir}",
        ]
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise RuntimeError(f"Chrome could not be started from {chrome}.") from exc

        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                code = self.process.returncode
                self.process = None
                raise RuntimeError(
                    f"Chrome exited before its debugging endpoint became ready (exit code {code}). "
                    "Make sure the dedicated profile is not open in another Chrome process."
                )
            if _cdp_ready(self.endpoint):
                return self
            time.sleep(0.1)

        self._stop()
        raise RuntimeError(f"Chrome did not expose {self.endpoint} within {self.startup_timeout:g} seconds.")

    def _stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None

    def __exit__(self, *_exc):
        self._stop()
