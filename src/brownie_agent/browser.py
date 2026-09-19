"""A deliberately small Playwright boundary for an isolated browser."""

import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

OBSERVER = Path(__file__).with_name("observe.js").read_text()


def _fingerprint(observation: dict) -> str:
    content = {key: observation[key] for key in ("url", "title", "viewport", "text", "elements", "access")}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def _web_origin(url: str) -> tuple[str, str, int] | None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    return parsed.scheme, parsed.hostname.lower(), port or (443 if parsed.scheme == "https" else 80)


class BrowserSession:
    """Launch one persistent browser context for observation and explicit scrolling."""

    def __init__(
        self,
        *,
        profile_dir: str | Path = ".browser-profile",
        headed: bool = False,
        channel: str = "chrome",
        cdp_url: str | None = None,
    ):
        self.profile_dir = Path(profile_dir).expanduser().resolve()
        self.headed = headed
        self.channel = channel
        self.cdp_url = cdp_url
        self._playwright = None
        self._browser = None
        self._attached = False
        self._created_page = False
        self.context = None
        self.page = None

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("Playwright is not installed. Run `uv sync` inside brownie/.") from None

        self._playwright = sync_playwright().start()
        try:
            if self.cdp_url:
                self._browser = self._playwright.chromium.connect_over_cdp(
                    self.cdp_url,
                    is_local=True,
                    no_defaults=True,
                )
                if not self._browser.contexts:
                    raise RuntimeError("The attached Chrome has no default browser context.")
                self.context = self._browser.contexts[0]
                self._attached = True
            else:
                self.profile_dir.mkdir(parents=True, exist_ok=True)
                self.context = self._playwright.chromium.launch_persistent_context(
                    user_data_dir=self.profile_dir,
                    channel=self.channel,
                    headless=not self.headed,
                    chromium_sandbox=True,
                    viewport={"width": 1120, "height": 780},
                )
                self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        except Exception as exc:
            if self._browser is not None:
                self._browser.close()
                self._browser = None
            self._playwright.stop()
            self._playwright = None
            if self.cdp_url:
                raise RuntimeError(
                    f"Brownie could not attach to Chrome at {self.cdp_url}. "
                    "Start the dedicated Chrome debugging session first."
                ) from exc
            raise RuntimeError(
                "Chrome failed to start while its security sandbox was required. "
                "Brownie will not retry with --no-sandbox."
            ) from exc
        return self

    def open(self, url: str, *, use_open_tab: bool = False):
        """Select an attached matching tab or navigate Brownie's owned page."""
        if use_open_tab:
            if not self._attached or self.context is None:
                raise ValueError("use_open_tab requires an attached Chrome session.")
            requested_origin = _web_origin(url)
            if requested_origin is None:
                raise ValueError("use_open_tab requires an HTTP or HTTPS URL with a valid host.")
            matches = [page for page in self.context.pages if _web_origin(page.url) == requested_origin]
            if not matches:
                raise RuntimeError(
                    f"No open Chrome tab matches {requested_origin[0]}://{requested_origin[1]}. "
                    "Open and verify the site manually before attaching Brownie."
                )
            self.page = matches[-1]
            return
        if self._attached and self.context is not None and self.page is None:
            self.page = self.context.new_page()
            self._created_page = True
        if self.page is None:
            raise RuntimeError("Start BrowserSession with a `with` block before opening a page.")
        self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)

    def observe(self) -> dict:
        """Return visible text and indexed controls without mutating the page."""
        if self.page is None:
            raise RuntimeError("Start BrowserSession with a `with` block before observing a page.")
        result = self.page.evaluate(OBSERVER)
        if result is None:
            raise RuntimeError("The page has no readable document body yet.")
        result["fingerprint"] = _fingerprint(result)
        return result

    def scroll_down(self) -> bool:
        """Scroll down once by 80% of the viewport; return whether the page moved."""
        if self.page is None:
            raise RuntimeError("Start BrowserSession with a `with` block before scrolling.")
        position = self.page.evaluate(
            """() => ({
                before: scrollY,
                distance: Math.max(1, Math.floor(innerHeight * 0.8)),
                canScroll: scrollY + innerHeight < document.documentElement.scrollHeight - 2,
            })"""
        )
        if not position["canScroll"]:
            return False
        self.page.mouse.wheel(0, position["distance"])
        self.page.wait_for_function("before => scrollY > before", arg=position["before"], timeout=2_000)
        return True

    def scroll_up(self) -> bool:
        """Scroll up once by 80% of the viewport; return whether the page moved."""
        if self.page is None:
            raise RuntimeError("Start BrowserSession with a `with` block before scrolling.")
        position = self.page.evaluate(
            """() => ({
                before: scrollY,
                distance: Math.max(1, Math.floor(innerHeight * 0.8)),
                canScroll: scrollY > 0,
            })"""
        )
        if not position["canScroll"]:
            return False
        self.page.mouse.wheel(0, -position["distance"])
        self.page.wait_for_function("before => scrollY < before", arg=position["before"], timeout=2_000)
        return True

    def _element_handle(self, node_id: int):
        if self.page is None:
            raise RuntimeError("Start BrowserSession with a `with` block before using an element.")
        handle = self.page.evaluate_handle("nodeId => window.__brownie?.nodes.get(nodeId) ?? null", node_id)
        element = handle.as_element()
        if element is None:
            handle.dispose()
            raise ValueError("The observed element is no longer available.")
        return element

    def click_node(self, node_id: int) -> None:
        """Click one code-owned observed node once."""
        element = self._element_handle(node_id)
        try:
            element.click(timeout=2_000)
        finally:
            try:
                element.dispose()
            except Exception:
                pass

    def type_node(self, node_id: int, text: str) -> None:
        """Replace the value of one code-owned editable node once."""
        element = self._element_handle(node_id)
        try:
            element.fill(text, timeout=2_000)
        finally:
            try:
                element.dispose()
            except Exception:
                pass

    def submit_node(self, node_id: int) -> None:
        """Submit through one observed form-associated editable node once."""
        element = self._element_handle(node_id)
        try:
            element.press("Enter", timeout=2_000)
        finally:
            try:
                element.dispose()
            except Exception:
                pass

    def wait_for_page_ready(self, previous_url: str, *, timeout_ms: int = 3_000) -> bool:
        """Wait briefly for a click destination to expose observable content."""
        if self.page is None:
            raise RuntimeError("Start BrowserSession with a `with` block before waiting for a page.")
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        self.page.evaluate(
            "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
        )
        try:
            self.page.wait_for_function(
                """previousUrl => {
                    if (document.readyState === 'loading' || !document.body) return false;
                    if (location.href === previousUrl) return true;
                    const hasText = document.body.innerText.trim().length > 0;
                    const hasControl = Boolean(document.querySelector(
                        'a[href],button,input,textarea,select,summary,[contenteditable="true"]'
                    ));
                    const canScroll = document.documentElement.scrollHeight > innerHeight + 2;
                    return hasText || hasControl || canScroll;
                }""",
                arg=previous_url,
                timeout=timeout_ms,
            )
        except PlaywrightTimeoutError:
            return False
        return True

    def __exit__(self, *_exc):
        if self._attached:
            try:
                if self._created_page and self.page is not None:
                    self.page.close()
            finally:
                if self._browser is not None:
                    self._browser.close()
                    self._browser = None
        elif self.context is not None:
            self.context.close()
        self.context = None
        self.page = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
