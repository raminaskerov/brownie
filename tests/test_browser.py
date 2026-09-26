import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from brownie_agent.browser import BrowserSession, _sanitize_accessibility_snapshot


def test_accessibility_snapshot_sanitizer_drops_values_and_urls():
    sanitized = _sanitize_accessibility_snapshot(
        '- heading "Account" [level=1]\n'
        '- textbox "Email": private@example.test\n'
        '- searchbox: secret query\n'
        '- link "Profile":\n'
        '  - /url: https://example.test/profile?token=private\n'
    )

    assert 'heading "Account"' in sanitized
    assert 'textbox "Email"' in sanitized
    assert "private@example.test" not in sanitized
    assert "secret query" not in sanitized
    assert "token=private" not in sanitized


def test_browser_launch_requires_chromium_sandbox(monkeypatch, tmp_path):
    launch_options = {}

    class FakeContext:
        pages = [object()]

        def close(self):
            pass

    class FakeChromium:
        def launch_persistent_context(self, **options):
            launch_options.update(options)
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()

        def stop(self):
            pass

    class FakeManager:
        def start(self):
            return FakePlaywright()

    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: FakeManager())

    with BrowserSession(profile_dir=tmp_path / "profile"):
        pass

    assert launch_options["chromium_sandbox"] is True


def test_attach_uses_existing_context_and_only_closes_its_own_page(monkeypatch, tmp_path):
    connection_options = {}

    class FakePage:
        def __init__(self):
            self.opened = None
            self.closed = False

        def goto(self, url, **_options):
            self.opened = url

        def close(self):
            self.closed = True

    class FakeContext:
        def __init__(self):
            self.page = FakePage()
            self.closed = False

        def new_page(self):
            return self.page

        def close(self):
            self.closed = True

    context = FakeContext()

    class FakeBrowser:
        contexts = [context]

        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    connected_browser = FakeBrowser()

    class FakeChromium:
        def connect_over_cdp(self, endpoint, **options):
            connection_options.update(endpoint=endpoint, **options)
            return connected_browser

    class FakePlaywright:
        chromium = FakeChromium()

        def stop(self):
            pass

    class FakeManager:
        def start(self):
            return FakePlaywright()

    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: FakeManager())

    with BrowserSession(profile_dir=tmp_path / "unused", cdp_url="http://127.0.0.1:9222") as session:
        session.open("https://example.test")

    assert connection_options == {
        "endpoint": "http://127.0.0.1:9222",
        "is_local": True,
        "no_defaults": True,
    }
    assert context.page.opened == "https://example.test"
    assert context.page.closed is True
    assert context.closed is False
    assert connected_browser.closed is True


def test_attach_can_reuse_matching_open_tab_without_navigating_or_closing_it(monkeypatch, tmp_path):
    class FakePage:
        def __init__(self, url):
            self.url = url
            self.closed = False

        def goto(self, *_args, **_options):
            raise AssertionError("An existing user tab must not be navigated.")

        def close(self):
            self.closed = True

    unrelated_page = FakePage("https://example.test/")
    verified_page = FakePage("https://marketplace.example/listings?verified=true")

    class FakeContext:
        pages = [unrelated_page, verified_page]

        def new_page(self):
            raise AssertionError("Reusing a tab must not create a page.")

    context = FakeContext()

    class FakeBrowser:
        contexts = [context]

        def close(self):
            pass

    class FakeChromium:
        def connect_over_cdp(self, *_args, **_options):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def stop(self):
            pass

    class FakeManager:
        def start(self):
            return FakePlaywright()

    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: FakeManager())

    with BrowserSession(profile_dir=tmp_path / "unused", cdp_url="http://127.0.0.1:9222") as session:
        session.open("https://marketplace.example/wanted/path", use_open_tab=True)
        assert session.page is verified_page

    assert unrelated_page.closed is False
    assert verified_page.closed is False


@pytest.mark.parametrize(
    ("method", "position"),
    [("scroll_down", {"before": 0, "distance": 500, "canScroll": True}),
     ("scroll_up", {"before": 500, "distance": 500, "canScroll": True})],
)
def test_scroll_returns_false_when_page_ignores_wheel(method, position):
    class Mouse:
        def wheel(self, _x, _y):
            pass

    class Page:
        mouse = Mouse()

        def evaluate(self, _script):
            return position

        def wait_for_function(self, *_args, **_kwargs):
            raise PlaywrightTimeoutError("Page did not move")

    session = BrowserSession()
    session.page = Page()

    assert getattr(session, method)() is False
