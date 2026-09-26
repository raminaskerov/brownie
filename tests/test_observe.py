from pathlib import Path

import pytest

from brownie_agent import (
    AUTH_REQUIRED,
    BrowserSession,
    StaleObservation,
    action_space,
    classify_access,
    execute_action,
    execute_prediction,
    read_page,
)

FIXTURE = Path(__file__).with_name("fixture.html")
LOGIN_FIXTURE = Path(__file__).with_name("login_fixture.html")
PAGINATION_FIXTURE = Path(__file__).with_name("pagination_fixture.html")
POPUP_FIXTURE = Path(__file__).with_name("popup_fixture.html")
PERCEPTION_FIXTURE = Path(__file__).with_name("perception_fixture.html")
SETTLE_FIXTURE = Path(__file__).with_name("settle_fixture.html")


def test_observe_returns_only_safe_visible_controls(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(FIXTURE.as_uri())
        observation = browser.observe()

    assert observation["title"] == "Brownie observation fixture"
    assert observation["can_scroll_up"] is False
    assert observation["can_scroll_down"] is True
    assert "Find a quiet place" in observation["text"]

    controls = [(element["role"], element["name"], element["value"]) for element in observation["elements"]]
    assert controls == [
        ("searchbox", "Destination", "Baku"),
        ("checkbox", "Free cancellation", "on"),
        ("button", "Find stays", ""),
        ("link", "Read details", ""),
        ("link", "Open delayed page", ""),
    ]

    names = {element["name"] for element in observation["elements"]}
    assert "Unavailable action" not in names
    assert "Hidden action" not in names
    assert "Below-fold action" not in names

    space = action_space(observation)
    assert space["CLICK"] == [1, 2, 3, 4, 5]
    assert space["TYPE_TEXT"] == [1]
    assert space["SUBMIT"] == [1]
    assert "SCROLL_DOWN" in space
    assert "SCROLL_UP" not in space


def test_observe_reports_login_without_exposing_password(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(LOGIN_FIXTURE.as_uri())
        observation = browser.observe()

    assert classify_access(observation) == {"status": AUTH_REQUIRED, "reason": "visible_password_field"}
    assert "must-not-be-observed" not in repr(observation)
    assert {element["name"] for element in observation["elements"]} == {"Email", "Continue"}


def test_observe_adds_generic_link_destination_and_context(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(PAGINATION_FIXTURE.as_uri())
        observation = browser.observe()

    listing, first, second, third = observation["elements"]
    assert listing["context"] == "RTX 5070 listing 25,000 TL · Kadıköy"
    assert listing["destination"] == "/item/rtx-5070"
    assert [link["context"] for link in (first, second, third)] == ["pagination"] * 3
    assert second["destination"] == "/results?query=rtx+5070&offset=20"


def test_observe_removes_windows_drive_from_file_fixture_destination(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(PAGINATION_FIXTURE.as_uri())
        browser.page.eval_on_selector(
            'a[href="/item/rtx-5070"]',
            "(link) => link.setAttribute('href', 'file:///D:/item/rtx-5070')",
        )
        observation = browser.observe()

    assert observation["elements"][0]["destination"] == "/item/rtx-5070"


def test_observe_and_execute_inside_visible_frame_and_open_shadow_root(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(PERCEPTION_FIXTURE.as_uri())
        observation = browser.observe()
        shadow = next(element for element in observation["elements"] if element["name"] == "Inside shadow root")
        frame = next(element for element in observation["elements"] if element["name"] == "Inside frame")

        execute_action(browser, observation, operation="CLICK", target=shadow["index"])
        after_shadow = browser.observe()
        frame = next(element for element in after_shadow["elements"] if element["name"] == "Inside frame")
        execute_action(browser, after_shadow, operation="CLICK", target=frame["index"])
        after_frame = browser.observe()

    assert observation["perception"] == {
        "surface": "layered_viewport_dom",
        "frame_count": 1,
        "visible_frame_count": 1,
        "inspected_frame_count": 1,
        "inaccessible_frame_count": 0,
        "open_shadow_root_count": 1,
        "inspected_open_shadow_root_count": 1,
        "accessibility_fallback_used": False,
        "accessibility_limit_reached": False,
        "accessibility_unavailable_count": 0,
        "text_limit_reached": False,
        "element_limit_reached": False,
    }
    assert "Inside frame" in observation["text"]
    assert "Inside shadow root" in observation["text"]
    assert shadow["context"] == "shadow: shadow-host"
    assert frame["context"] == "frame: Embedded controls"
    assert "Shadow clicked" in after_shadow["text"]
    assert "Frame clicked" in after_frame["text"]


def test_observe_detects_framed_password_without_exposing_it(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.page.set_content(
            '<iframe title="Sign in" '
            'srcdoc="<label>Email <input type=email></label>'
            '<label>Password <input type=password value=private-secret></label>"></iframe>'
        )
        observation = browser.observe()

    assert classify_access(observation) == {"status": AUTH_REQUIRED, "reason": "visible_password_field"}
    assert "private-secret" not in repr(observation)
    assert {element["name"] for element in observation["elements"]} == {"Email"}
    assert observation["perception"]["inspected_frame_count"] == 1
    assert observation["perception"]["accessibility_fallback_used"] is False


def test_sparse_page_uses_non_executable_accessibility_structure(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.page.set_content('<main><div role="heading" aria-label="Dashboard overview"></div></main>')
        observation = browser.observe()

    assert observation["elements"] == []
    assert "[Accessibility structure; non-executable]" in observation["text"]
    assert 'heading "Dashboard overview"' in observation["text"]
    assert observation["perception"]["accessibility_fallback_used"] is True
    assert observation["perception"]["accessibility_limit_reached"] is False


def test_scroll_down_once_reveals_below_fold_controls(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(FIXTURE.as_uri())
        before = browser.observe()

        moved = browser.scroll_down()
        after = browser.observe()

    assert moved is True
    assert before["viewport"]["scroll_y"] == 0
    assert after["viewport"]["scroll_y"] > 0
    assert after["can_scroll_up"] is True
    assert "Below-fold action" not in {element["name"] for element in before["elements"]}
    assert "Below-fold action" in {element["name"] for element in after["elements"]}


def test_read_page_collects_views_without_executable_targets(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(FIXTURE.as_uri())
        report = read_page(browser, max_scrolls=3)

    assert report["scrolls"] == 1
    assert report["stop_reason"] == "bottom"
    assert len(report["views"]) == 2
    assert "Find a quiet place" in report["combined_text"]
    assert "Below-fold action" in report["combined_text"]

    names = {element["name"] for element in report["seen_elements"]}
    assert names == {
        "Destination",
        "Free cancellation",
        "Find stays",
        "Read details",
        "Open delayed page",
        "Below-fold action",
    }
    assert all("index" not in element and "node_id" not in element for element in report["seen_elements"])


def test_execute_type_text_uses_current_observed_target(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(FIXTURE.as_uri())
        observation = browser.observe()

        result = execute_action(browser, observation, operation="TYPE_TEXT", target=1, text="Istanbul")
        after = browser.observe()

    assert result["target_name"] == "Destination"
    assert result["executed"] is True
    assert after["elements"][0]["value"] == "Istanbul"


def test_execute_click_uses_current_observed_target(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(FIXTURE.as_uri())
        observation = browser.observe()

        result = execute_action(browser, observation, operation="CLICK", target=3)
        status = browser.page.locator("#status").text_content()

    assert result["target_name"] == "Find stays"
    assert result["executed"] is True
    assert status == "searched"


def test_execute_submit_uses_observed_form_field_once(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(FIXTURE.as_uri())
        observation = browser.observe()

        result = execute_action(browser, observation, operation="SUBMIT", target=1)
        status = browser.page.locator("#status").text_content()

    assert result["target_name"] == "Destination"
    assert result["executed"] is True
    assert status == "searched"


def test_click_destination_waits_for_asynchronously_rendered_content(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(FIXTURE.as_uri())
        observation = browser.observe()

        execute_action(browser, observation, operation="CLICK", target=5)
        ready = browser.wait_for_page_ready(observation["url"], observation["fingerprint"])
        after = browser.observe()

    assert ready is True
    assert after["title"] == "Delayed page"
    assert "Content rendered after navigation" in after["text"]
    assert after["elements"][0]["name"] == "Ready"


def test_click_adopts_new_tab_and_waits_for_its_content(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(POPUP_FIXTURE.as_uri())
        observation = browser.observe()

        execute_action(browser, observation, operation="CLICK", target=1)
        ready = browser.wait_for_page_ready(observation["url"], observation["fingerprint"])
        after = browser.observe()

    assert ready is True
    assert after["url"].endswith("/delayed_fixture.html")
    assert after["title"] == "Delayed page"
    assert "Content rendered after navigation" in after["text"]
    assert after["elements"][0]["name"] == "Ready"


def test_click_waits_for_asynchronous_same_page_change(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(SETTLE_FIXTURE.as_uri())
        observation = browser.observe()

        execute_action(browser, observation, operation="CLICK", target=1)
        ready = browser.wait_for_page_ready(observation["url"], observation["fingerprint"])
        after = browser.observe()

    assert ready is True
    assert after["url"] == observation["url"]
    assert "Loaded result" in after["text"]


def test_execute_rejects_stale_observation_before_click(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(FIXTURE.as_uri())
        observation = browser.observe()
        browser.page.locator("#query").fill("Changed outside Brownie")

        with pytest.raises(StaleObservation):
            execute_action(browser, observation, operation="CLICK", target=3)

        status = browser.page.locator("#status").text_content()

    assert status == "idle"


def test_execute_allows_incidental_text_change_when_action_structure_is_fresh(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(FIXTURE.as_uri())
        observation = browser.observe()
        details = next(element for element in observation["elements"] if element["name"] == "Read details")
        browser.page.locator("#status").evaluate("node => { node.textContent = 'transient status'; }")

        result = execute_action(browser, observation, operation="CLICK", target=details["index"])

    assert result["executed"] is True


def test_execute_prediction_clicks_jev_selected_observed_target(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(FIXTURE.as_uri())
        observation = browser.observe()
        prediction = {"operation": "CLICK", "target": 3, "target_name": "Find stays"}

        result = execute_prediction(browser, observation, prediction)
        status = browser.page.locator("#status").text_content()

    assert result["executed"] is True
    assert result["target_name"] == "Find stays"
    assert status == "searched"


def test_execute_prediction_stops_before_type_text(tmp_path):
    with BrowserSession(profile_dir=tmp_path / "profile") as browser:
        browser.open(FIXTURE.as_uri())
        observation = browser.observe()
        prediction = {"operation": "TYPE_TEXT", "target": 1, "target_name": "Destination"}

        result = execute_prediction(browser, observation, prediction)
        after = browser.observe()

    assert result["executed"] is False
    assert result["status"] == "text_required"
    assert after["elements"][0]["value"] == "Baku"
