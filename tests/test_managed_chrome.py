import subprocess

import pytest

from brownie_agent import managed_chrome
from brownie_agent.managed_chrome import ManagedChrome, find_chrome_executable


def test_managed_chrome_uses_only_required_local_debugging_flags(monkeypatch, tmp_path):
    events = []

    class Process:
        returncode = None

        def __init__(self, command, **options):
            events.append(("launch", command, options))

        def poll(self):
            return None

        def terminate(self):
            events.append(("terminate",))

        def wait(self, timeout):
            events.append(("wait", timeout))
            self.returncode = 0
            return 0

    ready = iter([False, True])
    monkeypatch.setattr(managed_chrome, "_cdp_ready", lambda _endpoint: next(ready))
    monkeypatch.setattr(managed_chrome.subprocess, "Popen", Process)
    chrome = tmp_path / "chrome"
    chrome.touch()
    profile = tmp_path / "profile"

    with ManagedChrome(profile_dir=profile, executable=chrome):
        assert profile.is_dir()

    command = events[0][1]
    assert command == [
        str(chrome),
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=9222",
        f"--user-data-dir={profile}",
    ]
    assert "--no-sandbox" not in command
    assert events[-2:] == [("terminate",), ("wait", 5)]


def test_managed_chrome_refuses_an_existing_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(managed_chrome, "_cdp_ready", lambda _endpoint: True)
    monkeypatch.setattr(
        managed_chrome.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("Existing endpoints must not launch another Chrome"),
    )

    with pytest.raises(RuntimeError, match="Use --attach"):
        ManagedChrome(profile_dir=tmp_path / "profile").__enter__()


@pytest.mark.parametrize("endpoint", [
    "http://0.0.0.0:9222",
    "http://192.168.1.2:9222",
    "https://127.0.0.1:9222",
    "http://127.0.0.1:9222/json",
])
def test_managed_chrome_rejects_non_private_or_malformed_endpoints(endpoint, tmp_path):
    with pytest.raises(ValueError, match="127.0.0.1"):
        ManagedChrome(profile_dir=tmp_path / "profile", endpoint=endpoint).__enter__()


def test_managed_chrome_kills_process_that_does_not_stop(monkeypatch):
    events = []

    class Process:
        def poll(self):
            return None

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout):
            events.append(("wait", timeout))
            if len([event for event in events if isinstance(event, tuple)]) == 1:
                raise subprocess.TimeoutExpired("chrome", timeout)
            return 0

        def kill(self):
            events.append("kill")

    launcher = ManagedChrome()
    launcher.process = Process()
    launcher._stop()

    assert events == ["terminate", ("wait", 5), "kill", ("wait", 5)]


def test_explicit_chrome_executable_must_exist(tmp_path):
    missing = tmp_path / "missing-chrome"
    with pytest.raises(RuntimeError) as error:
        find_chrome_executable(missing)

    assert str(missing) in str(error.value)
