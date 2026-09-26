"""A deliberately small Playwright boundary for an isolated browser."""

import hashlib
import json
from pathlib import Path
from time import monotonic
from urllib.parse import urljoin, urlsplit

from .trace import trace_event

OBSERVER = Path(__file__).with_name("observe.js").read_text()
MAX_ACCESSIBILITY_CHARS = 2000


def _sanitize_accessibility_snapshot(snapshot: str) -> str:
    """Keep bounded structure while dropping control values and destination URLs."""
    output = []
    editable_roles = ("textbox", "searchbox", "combobox", "spinbutton")
    for raw_line in snapshot.splitlines():
        line = raw_line.rstrip()
        stripped = line.lstrip()
        if stripped.startswith("- /url:"):
            continue
        if any(stripped.startswith(f"- {role}") for role in editable_roles):
            quoted_value = line.rfind('": ')
            if quoted_value >= 0:
                line = line[:quoted_value + 1]
            else:
                role_value = line.find(": ", len(line) - len(stripped))
                if role_value >= 0:
                    line = line[:role_value]
        output.append(line)
    return "\n".join(output).strip()


def _fingerprint(observation: dict) -> str:
    content = {
        key: observation[key]
        for key in ("url", "title", "viewport", "text", "elements", "access", "perception")
    }
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
        browser_type: str = "chromium",
    ):
        self.profile_dir = Path(profile_dir).expanduser().resolve()
        self.headed = headed
        if browser_type not in {"chromium", "firefox", "webkit"}:
            raise ValueError("browser_type must be chromium, firefox, or webkit")
        if cdp_url and browser_type != "chromium":
            raise ValueError("CDP attachment is available only for Chromium")
        self.channel = channel
        self.cdp_url = cdp_url
        self.browser_type = browser_type
        self._playwright = None
        self._browser = None
        self._attached = False
        self._created_pages = []
        self._pages_before_action = None
        self._observed_nodes = {}
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
                launch_options = {
                    "user_data_dir": self.profile_dir,
                    "headless": not self.headed,
                    "viewport": {"width": 1120, "height": 780},
                }
                if self.browser_type == "chromium":
                    launch_options.update(channel=self.channel, chromium_sandbox=True)
                engine = getattr(self._playwright, self.browser_type)
                self.context = engine.launch_persistent_context(**launch_options)
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
            if self.browser_type == "chromium":
                raise RuntimeError(
                    "Chrome failed to start while its security sandbox was required. "
                    "Brownie will not retry with --no-sandbox."
                ) from exc
            raise RuntimeError(
                f"{self.browser_type.capitalize()} failed to start. "
                "Check its Playwright browser build and system dependencies."
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
            self._created_pages.append(self.page)
        if self.page is None:
            raise RuntimeError("Start BrowserSession with a `with` block before opening a page.")
        self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)

    def observe(self) -> dict:
        """Return layered viewport text and controls without mutating the page."""
        if self.page is None:
            raise RuntimeError("Start BrowserSession with a `with` block before observing a page.")
        top_frame = self.page.main_frame
        top = top_frame.evaluate(OBSERVER)
        if top is None:
            raise RuntimeError("The page has no readable document body yet.")
        viewport = top["viewport"]
        surfaces = [(top_frame, top, "top document")]
        child_frames = [frame for frame in self.page.frames if frame is not top_frame]
        visible_frames = 0
        inaccessible_frames = 0

        for frame in child_frames:
            frame_element = None
            try:
                frame_element = frame.frame_element()
                box = frame_element.bounding_box()
                if box is None or box["width"] <= 0 or box["height"] <= 0:
                    continue
                if (
                    box["x"] + box["width"] <= 0
                    or box["y"] + box["height"] <= 0
                    or box["x"] >= viewport["width"]
                    or box["y"] >= viewport["height"]
                ):
                    continue
                visible_frames += 1
                label = frame_element.get_attribute("title") or frame.name or frame.url or "embedded frame"
                observed = frame.evaluate(OBSERVER)
                if observed is None:
                    inaccessible_frames += 1
                    continue
                surfaces.append((frame, observed, f"frame: {label[:180]}"))
            except Exception:
                inaccessible_frames += 1
            finally:
                if frame_element is not None:
                    try:
                        frame_element.dispose()
                    except Exception:
                        pass

        combined_text = []
        combined_elements = []
        omitted_elements = 0
        open_shadow_roots = 0
        inspected_shadow_roots = 0
        text_limit_reached = False
        self._observed_nodes = {}
        next_node_id = 1
        for frame, observed, surface in surfaces:
            text = observed.get("text", "").strip()
            if text:
                combined_text.append(text if frame is top_frame else f"[{surface}]\n{text}")
            perception = observed.get("perception", {})
            open_shadow_roots += perception.get("open_shadow_root_count", 0)
            inspected_shadow_roots += perception.get("inspected_open_shadow_root_count", 0)
            text_limit_reached = text_limit_reached or perception.get("text_limit_reached", False)
            omitted_elements += observed.get("omitted_elements", 0)
            for element in observed.get("elements", []):
                local_node_id = element["node_id"]
                element = dict(element)
                element["node_id"] = next_node_id
                if frame is not top_frame:
                    context = element.get("context", "")
                    element["context"] = f"{surface} · {context}" if context else surface
                    if element.get("destination"):
                        element["destination"] = urljoin(frame.url, element["destination"])
                self._observed_nodes[next_node_id] = (frame, local_node_id)
                combined_elements.append(element)
                next_node_id += 1

        limit = 100
        omitted_elements += max(0, len(combined_elements) - limit)
        elements = combined_elements[:limit]
        for offset, element in enumerate(elements, 1):
            element["index"] = offset
        text = "\n".join(combined_text)
        if len(text) > 6000:
            text_limit_reached = True
            text = text[:6000]

        top["text"] = text
        top["elements"] = elements
        top["access"] = {
            "visible_password_field": any(observed["access"]["visible_password_field"] for _, observed, _ in surfaces),
            "password_field_present": any(
                observed["access"].get("password_field_present") for _, observed, _ in surfaces
            ),
            "challenge_marker": any(observed["access"]["challenge_marker"] for _, observed, _ in surfaces),
        }
        accessibility_parts = []
        accessibility_unavailable = 0
        accessibility_limit_reached = False
        if len(text.strip()) < 200 and len(elements) < 2 and not top["access"]["password_field_present"]:
            for frame, _observed, surface in surfaces:
                try:
                    snapshot = _sanitize_accessibility_snapshot(
                        frame.locator("body").aria_snapshot(timeout=1_000)
                    )
                except Exception:
                    accessibility_unavailable += 1
                    continue
                if snapshot:
                    accessibility_parts.append(snapshot if frame is top_frame else f"[{surface}]\n{snapshot}")
            accessibility_text = "\n".join(accessibility_parts)
            if len(accessibility_text) > MAX_ACCESSIBILITY_CHARS:
                accessibility_limit_reached = True
                accessibility_text = accessibility_text[:MAX_ACCESSIBILITY_CHARS]
            if accessibility_text:
                prefix = "\n" if top["text"] else ""
                top["text"] += f"{prefix}[Accessibility structure; non-executable]\n{accessibility_text}"
        top["perception"] = {
            "surface": "layered_viewport_dom",
            "frame_count": len(child_frames),
            "visible_frame_count": visible_frames,
            "inspected_frame_count": len(surfaces) - 1,
            "inaccessible_frame_count": inaccessible_frames,
            "open_shadow_root_count": open_shadow_roots,
            "inspected_open_shadow_root_count": inspected_shadow_roots,
            "accessibility_fallback_used": bool(accessibility_parts),
            "accessibility_limit_reached": accessibility_limit_reached,
            "accessibility_unavailable_count": accessibility_unavailable,
            "text_limit_reached": text_limit_reached,
            "element_limit_reached": omitted_elements > 0,
        }
        top["omitted_elements"] = omitted_elements
        top["fingerprint"] = _fingerprint(top)
        return top

    def scroll_down(self) -> bool:
        """Scroll down once by 80% of the viewport; return whether the page moved."""
        if self.page is None:
            raise RuntimeError("Start BrowserSession with a `with` block before scrolling.")
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

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
        try:
            self.page.wait_for_function("before => scrollY > before", arg=position["before"], timeout=2_000)
        except PlaywrightTimeoutError:
            return False
        return True

    def scroll_up(self) -> bool:
        """Scroll up once by 80% of the viewport; return whether the page moved."""
        if self.page is None:
            raise RuntimeError("Start BrowserSession with a `with` block before scrolling.")
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

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
        try:
            self.page.wait_for_function("before => scrollY < before", arg=position["before"], timeout=2_000)
        except PlaywrightTimeoutError:
            return False
        return True

    def _element_handle(self, node_id: int):
        if self.page is None:
            raise RuntimeError("Start BrowserSession with a `with` block before using an element.")
        observed = self._observed_nodes.get(node_id)
        if observed is None:
            raise ValueError("The observed element is no longer available.")
        frame, local_node_id = observed
        handle = frame.evaluate_handle(
            "nodeId => window.__brownie?.nodes.get(nodeId) ?? null",
            local_node_id,
        )
        element = handle.as_element()
        if element is None:
            handle.dispose()
            raise ValueError("The observed element is no longer available.")
        return element

    def _adopt_new_page(self, pages_before) -> bool:
        """Make a newly opened tab the active task page without guessing from URLs."""
        if self.context is None:
            return False
        previous_ids = {id(page) for page in pages_before}
        new_pages = [page for page in self.context.pages if id(page) not in previous_ids]
        if not new_pages:
            return False
        if new_pages[-1] is self.page:
            return False
        previous_page = self.page
        self.page = new_pages[-1]
        created_ids = {id(page) for page in self._created_pages}
        if self._attached and self._created_pages and id(self.page) not in created_ids:
            self._created_pages.append(self.page)
        trace_event("page_activated", {
            "reason": "new_page",
            "previous_url": previous_page.url if previous_page is not None else None,
            "url": self.page.url,
        })
        return True

    def click_node(self, node_id: int) -> None:
        """Click one code-owned observed node once."""
        element = self._element_handle(node_id)
        pages_before = tuple(self.context.pages) if self.context is not None else ()
        self._pages_before_action = pages_before
        try:
            element.click(timeout=2_000)
            self._adopt_new_page(pages_before)
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
        pages_before = tuple(self.context.pages) if self.context is not None else ()
        self._pages_before_action = pages_before
        try:
            element.press("Enter", timeout=2_000)
            self._adopt_new_page(pages_before)
        finally:
            try:
                element.dispose()
            except Exception:
                pass

    def wait_for_page_ready(
        self,
        previous_url: str,
        previous_fingerprint: str | None = None,
        *,
        timeout_ms: int = 3_000,
    ) -> bool:
        """Wait for a popup, navigation, or observable same-page outcome."""
        if self.page is None:
            raise RuntimeError("Start BrowserSession with a `with` block before waiting for a page.")
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        try:
            deadline = monotonic() + timeout_ms / 1000
            pages_before = self._pages_before_action or ()
            while monotonic() < deadline:
                self._adopt_new_page(pages_before)
                if self.page.url != previous_url:
                    break
                if previous_fingerprint is not None:
                    try:
                        if self.observe()["fingerprint"] != previous_fingerprint:
                            return True
                    except RuntimeError:
                        pass
                remaining_ms = max(1, int((deadline - monotonic()) * 1000))
                self.page.wait_for_timeout(min(50, remaining_ms))
            else:
                return previous_fingerprint is None

            remaining_ms = max(1, int((deadline - monotonic()) * 1000))
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=remaining_ms)
            except PlaywrightTimeoutError:
                pass
            remaining_ms = max(1, int((deadline - monotonic()) * 1000))
            self.page.wait_for_function(
                """() => {
                    if (document.readyState === 'loading' || !document.body) return false;
                    const hasText = document.body.innerText.trim().length > 0;
                    const hasControl = Boolean(document.querySelector(
                        'a[href],button,input,textarea,select,summary,[contenteditable="true"]'
                    ));
                    const canScroll = document.documentElement.scrollHeight > innerHeight + 2;
                    return hasText || hasControl || canScroll;
                }""",
                timeout=remaining_ms,
            )
            return True
        except PlaywrightTimeoutError:
            return False
        finally:
            self._pages_before_action = None

    def __exit__(self, *_exc):
        if self._attached:
            try:
                for page in reversed(self._created_pages):
                    try:
                        page.close()
                    except Exception:
                        pass
            finally:
                if self._browser is not None:
                    self._browser.close()
                    self._browser = None
        elif self.context is not None:
            self.context.close()
        self.context = None
        self.page = None
        self._created_pages = []
        self._pages_before_action = None
        self._observed_nodes = {}
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
