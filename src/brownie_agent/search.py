"""One bounded search-to-source run built on Brownie's validated action boundary."""

from urllib.parse import urlsplit

from .access import READY, classify_access
from .actions import StaleObservation, execute_action, execute_prediction
from .controller import RunState
from .evidence import evidence_candidates
from .reader import read_page
from .state import text_field_state
from .steering import steer_action
from .text_model import generate_field_text

SEARCH_ENGINE_URL = "https://duckduckgo.com/"
SEARCH_ENGINE_DOMAIN = "duckduckgo.com"
MAX_STALE_REFRESHES = 3


def _is_search_engine_page(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == SEARCH_ENGINE_DOMAIN or host.endswith("." + SEARCH_ENGINE_DOMAIN)


def _search_objective(goal: str) -> str:
    return (
        f"Research goal: {goal}\n"
        "Search the web, inspect the visible search results, and open exactly one external source that is most "
        "likely to contain material relevant to the research goal. Do not finish from search-result snippets alone."
    )


def _public_page(observation: dict) -> dict:
    return {
        "url": observation["url"],
        "title": observation["title"],
        "visible_text": observation["text"],
    }


def _stop_result(state: RunState, observation: dict, *, reason: str, query: str | None) -> dict:
    return {
        "goal": state.goal,
        "status": "stopped",
        "stop_reason": reason,
        "search_engine": SEARCH_ENGINE_URL,
        "search_query": query,
        "steps": state.recent_steps(),
        "last_page": _public_page(observation),
        "source": None,
    }


def _source_result(state: RunState, report: dict, *, query: str | None) -> dict:
    return {
        "goal": state.goal,
        "status": "source_read",
        "stop_reason": "one_source_read",
        "search_engine": SEARCH_ENGINE_URL,
        "search_query": query,
        "steps": state.recent_steps(),
        "last_page": {"url": report["url"], "title": report["title"]},
        "source": {
            "url": report["url"],
            "title": report["title"],
            "material": report["combined_text"],
            "evidence_candidates": evidence_candidates(state.goal, report["combined_text"]),
            "seen_elements": report["seen_elements"],
            "scrolls": report["scrolls"],
            "stop_reason": report["stop_reason"],
        },
    }


def run_search(
    browser,
    goal: str,
    *,
    provider: str | None = None,
    max_steps: int = 8,
    max_pages: int = 3,
    max_scrolls: int = 10,
    choose_action=steer_action,
    write_text=generate_field_text,
) -> dict:
    """Search, open one external result, read it, and stop."""
    state = RunState(
        goal,
        max_steps=max_steps,
        max_pages=max_pages,
        max_scrolls_per_page=max_scrolls,
    )
    objective = _search_objective(state.goal)
    query = None
    stale_refreshes = 0
    browser.open(SEARCH_ENGINE_URL)
    observation = browser.observe()
    state.observe(observation)

    while True:
        access = classify_access(observation)
        if access["status"] != READY:
            return _stop_result(state, observation, reason=access["status"], query=query)
        if not _is_search_engine_page(observation["url"]):
            report = read_page(browser, max_scrolls=max_scrolls)
            return _source_result(state, report, query=query)
        if reason := state.budget_stop_reason():
            return _stop_result(state, observation, reason=reason, query=query)

        prediction = choose_action(
            observation,
            objective,
            state.recent_steps(),
            provider=provider,
        )
        if reason := state.preflight(prediction, observation):
            return _stop_result(state, observation, reason=reason, query=query)

        try:
            if prediction["operation"] == "TYPE_TEXT":
                context = text_field_state(observation, objective, prediction, state.recent_steps())
                value, text_metadata = write_text(context)
                if prediction.get("text_mode") == "SEARCH_SEED":
                    query = value
                execution = execute_action(
                    browser,
                    observation,
                    operation="TYPE_TEXT",
                    target=prediction["target"],
                    text=value,
                )
                execution["text_model"] = text_metadata
            else:
                execution = execute_prediction(browser, observation, prediction)
        except StaleObservation:
            stale_refreshes += 1
            observation = browser.observe()
            state.observe(observation)
            if stale_refreshes >= MAX_STALE_REFRESHES:
                return _stop_result(state, observation, reason="stale_observation_limit", query=query)
            continue
        stale_refreshes = 0

        if execution["executed"] and execution["operation"] in {"CLICK", "SUBMIT"}:
            execution["page_ready"] = browser.wait_for_page_ready(observation["url"])
        after = browser.observe()
        stop_reason = state.record_step(observation, execution, after)

        if not _is_search_engine_page(after["url"]):
            access = classify_access(after)
            if access["status"] != READY:
                return _stop_result(state, after, reason=access["status"], query=query)
            report = read_page(browser, max_scrolls=max_scrolls)
            return _source_result(state, report, query=query)
        if stop_reason:
            return _stop_result(state, after, reason=stop_reason, query=query)
        observation = after
