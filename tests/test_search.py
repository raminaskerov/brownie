from copy import deepcopy

from brownie_agent.search import SEARCH_ENGINE_URL, run_search


def observation(url, fingerprint, *, elements=None, text="", title="Page"):
    return {
        "url": url,
        "title": title,
        "text": text,
        "viewport": {"width": 1000, "height": 700, "scroll_y": 0, "document_height": 700},
        "elements": elements or [],
        "access": {},
        "can_scroll_up": False,
        "can_scroll_down": False,
        "omitted_elements": 0,
        "fingerprint": fingerprint,
    }


class SearchBrowser:
    def __init__(self):
        self.opened = None
        self.state = "home"

    def open(self, url):
        self.opened = url

    def observe(self):
        if self.state == "home":
            return observation(SEARCH_ENGINE_URL, "home", title="DuckDuckGo", elements=[{
                "index": 1, "node_id": 10, "role": "searchbox", "name": "Search",
                "value": "", "checked": None, "operations": ["CLICK", "TYPE_TEXT", "SUBMIT"],
                "context": "", "destination": "",
            }])
        if self.state == "typed":
            page = self.observe_for("home")
            page["fingerprint"] = "typed"
            page["elements"][0]["value"] = "official solar report"
            return page
        if self.state == "results":
            return observation(
                "https://duckduckgo.com/?q=official+solar+report",
                "results",
                title="official solar report at DuckDuckGo",
                text="Official Solar Report — Example Institute",
                elements=[{
                    "index": 1, "node_id": 20, "role": "link", "name": "Official Solar Report",
                    "value": "", "checked": None, "operations": ["CLICK"],
                    "context": "Example Institute report", "destination": "https://example.test/report",
                }],
            )
        return observation(
            "https://example.test/report",
            "source",
            title="Official Solar Report",
            text="Solar capacity reached 100 GW in the published reporting period.",
        )

    def observe_for(self, state):
        current = self.state
        self.state = state
        result = deepcopy(self.observe())
        self.state = current
        return result

    def type_node(self, node_id, value):
        assert node_id == 10
        assert value == "official solar report"
        self.state = "typed"

    def submit_node(self, node_id):
        assert node_id == 10
        self.state = "results"

    def click_node(self, node_id):
        assert node_id == 20
        self.state = "source"

    def wait_for_page_ready(self, _previous_url, _previous_fingerprint=None):
        return True

    def scroll_down(self):
        return False


def test_search_runs_one_query_opens_one_source_and_returns_material():
    browser = SearchBrowser()
    choices = iter([{
        "operation": "CLICK", "target": 1, "target_name": "Official Solar Report", "text_mode": None,
    }])

    def choose(current, _goal, _recent_steps, *, provider):
        assert provider == "llm"
        assert current["url"].startswith("https://duckduckgo.com/?q=")
        return next(choices)

    contexts = []
    result = run_search(
        browser,
        "Find the official solar capacity figure",
        provider="llm",
        choose_action=choose,
        write_text=lambda context: contexts.append(context) or ("official solar report", {"model": "fixture"}),
    )

    assert browser.opened == SEARCH_ENGINE_URL
    assert result["status"] == "source_read"
    assert result["search_query"] == "official solar report"
    assert result["source"]["url"] == "https://example.test/report"
    assert "100 GW" in result["source"]["material"]
    assert [step["operation"] for step in result["steps"]] == ["TYPE_TEXT", "SUBMIT", "CLICK"]
    assert contexts == [{
        "goal": "Find the official solar capacity figure",
        "text_mode": "WEB_SEARCH_QUERY",
        "selected_field": {"role": "searchbox", "name": "Search"},
        "current_page": {"url_without_query": SEARCH_ENGINE_URL, "title": "DuckDuckGo"},
    }]


def test_search_stops_when_steerer_cannot_progress_before_opening_source():
    browser = SearchBrowser()

    result = run_search(
        browser,
        "Find a report",
        write_text=lambda _context: ("official solar report", {"model": "fixture"}),
        choose_action=lambda *_args, **_kwargs: {
            "operation": "BLOCKED", "target": None, "target_name": None, "text_mode": None,
        },
    )

    assert result["status"] == "stopped"
    assert result["stop_reason"] == "blocked"
    assert result["source"] is None


def test_search_reobserves_and_redecides_after_one_stale_prediction():
    class StaleOnceBrowser(SearchBrowser):
        def __init__(self):
            super().__init__()
            self.home_observations = 0

        def observe(self):
            result = super().observe()
            if self.state == "home":
                self.home_observations += 1
                if self.home_observations == 2:
                    result["fingerprint"] = "dynamic-home"
            return result

    browser = StaleOnceBrowser()
    choices = iter([{
        "operation": "CLICK", "target": 1, "target_name": "Official Solar Report", "text_mode": None,
    }])

    result = run_search(
        browser,
        "Find the official solar capacity figure",
        choose_action=lambda *_args, **_kwargs: next(choices),
        write_text=lambda _context: ("official solar report", {"model": "fixture"}),
    )

    assert result["status"] == "source_read"
    assert [step["operation"] for step in result["steps"]] == ["TYPE_TEXT", "SUBMIT", "CLICK"]


def test_zero_source_scrolls_still_allows_search_form_and_result_actions():
    browser = SearchBrowser()
    result = run_search(
        browser,
        "Find the official solar capacity figure",
        max_scrolls=0,
        choose_action=lambda *_args, **_kwargs: {
            "operation": "CLICK", "target": 1, "target_name": "Official Solar Report", "text_mode": None,
        },
        write_text=lambda _context: ("official solar report", {"model": "fixture"}),
    )

    assert result["status"] == "source_read"
    assert result["source"]["scrolls"] == 0
    assert [step["operation"] for step in result["steps"]] == ["TYPE_TEXT", "SUBMIT", "CLICK"]
