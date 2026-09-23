from brownie_agent.controller import RunState, repeated_suffix_period


def observation(url, fingerprint, scroll_y=0, elements=None):
    return {
        "url": url,
        "title": "Results",
        "text": "",
        "viewport": {"width": 1000, "height": 700, "scroll_y": scroll_y, "document_height": 3000},
        "elements": elements or [],
        "can_scroll_up": scroll_y > 0,
        "can_scroll_down": scroll_y < 2300,
        "fingerprint": fingerprint,
    }


def execution(operation, target_name=None, executed=True):
    return {
        "operation": operation,
        "target": None,
        "target_name": target_name,
        "executed": executed,
        "status": "executed" if executed else operation.lower(),
    }


def test_run_state_remembers_offscreen_field_values_without_node_references():
    state = RunState("Find an RTX 5070")
    field = {
        "index": 2,
        "node_id": 91,
        "role": "searchbox",
        "name": "Search",
        "value": "rtx 5070",
        "checked": None,
        "operations": ["CLICK", "TYPE_TEXT"],
    }

    state.observe(observation("https://example.test/results?q=rtx", "top", elements=[field]))
    state.observe(observation("https://example.test/results?q=rtx", "lower", scroll_y=1200))
    memory = state.memory_state()

    assert memory["known_fields"][0]["value"] == "rtx 5070"
    assert memory["scroll_extents"][0]["minimum"] == 0
    assert memory["scroll_extents"][0]["maximum"] == 1200
    assert "node_id" not in repr(memory)


def test_repeated_suffix_detects_two_three_and_longer_step_cycles():
    assert repeated_suffix_period([("a",), ("b",), ("a",), ("b",)]) == 2
    assert repeated_suffix_period([("a",), ("b",), ("c",), ("a",), ("b",), ("c",)]) == 3
    assert repeated_suffix_period([("a",), ("b",), ("c",), ("d",)] * 2) == 4
    assert repeated_suffix_period([("a",), ("b",), ("c",)]) is None


def test_record_step_stops_a_scroll_bounce_cycle():
    state = RunState("Inspect results")
    top = observation("https://example.test/results", "top", 0)
    bottom = observation("https://example.test/results", "bottom", 1000)

    assert state.record_step(top, execution("SCROLL_DOWN"), bottom) is None
    assert state.record_step(bottom, execution("SCROLL_UP"), top) is None
    assert state.record_step(top, execution("SCROLL_DOWN"), bottom) is None
    assert state.record_step(bottom, execution("SCROLL_UP"), top) == "cycle_2"


def test_preflight_prevents_repeating_a_mutation_from_the_same_state():
    state = RunState("Open a result")
    before = observation("https://example.test/results", "results")
    after = observation("https://example.test/item", "item")
    state.record_step(before, execution("CLICK", "Listing A"), after)

    reason = state.preflight(
        {"operation": "CLICK", "target_name": "Listing A"},
        before,
    )

    assert reason == "repeated_mutation"


def test_no_effect_and_budgets_stop_without_model_judgment():
    unchanged = observation("https://example.test/results", "same")
    no_effect = RunState("Try one click")
    assert no_effect.record_step(unchanged, execution("CLICK", "Broken"), unchanged) == "no_effect"

    step_limited = RunState("One step only", max_steps=1)
    changed = observation("https://example.test/results", "changed")
    assert step_limited.record_step(unchanged, execution("CLICK", "Working"), changed) == "step_budget"

    scroll_limited = RunState("One scroll only", max_scrolls_per_page=1)
    assert scroll_limited.record_step(unchanged, execution("SCROLL_DOWN"), changed) is None
    assert scroll_limited.preflight({"operation": "SCROLL_DOWN"}, changed) == "scroll_budget"


def test_zero_scroll_budget_allows_a_run_but_rejects_scroll_actions():
    state = RunState("Open one result without reading down the page", max_scrolls_per_page=0)
    current = observation("https://example.test/", "top")

    assert state.preflight({"operation": "SCROLL_DOWN"}, current) == "scroll_budget"


def test_zero_scroll_budget_does_not_stop_non_scroll_progress():
    state = RunState("Enter and submit a query", max_scrolls_per_page=0)
    before = observation("https://example.test/", "empty")
    typed = observation("https://example.test/", "typed")

    assert state.record_step(before, execution("TYPE_TEXT", "Search"), typed) is None
    assert state.preflight({"operation": "SUBMIT", "target_name": "Search"}, typed) is None


def test_page_budget_counts_distinct_query_pages_but_not_fragments():
    state = RunState("Compare listings", max_pages=1)
    first = observation("https://example.test/results?q=gpu#top", "first")
    second = observation("https://example.test/results?q=gpu&offset=20", "second")

    state.observe(first)
    assert state.budget_stop_reason() is None
    state.observe(second)

    assert state.budget_stop_reason() == "page_budget"
