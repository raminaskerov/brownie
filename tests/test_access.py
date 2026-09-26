from brownie_agent.access import (
    ACCESS_BLOCKED,
    AUTH_REQUIRED,
    CHALLENGE,
    READY,
    classify_access,
    local_blocked_prediction,
)


def observation(url="https://example.test/listings", title="Listings", **access):
    return {"url": url, "title": title, "access": access}


def test_classify_access_recognizes_ready_login_and_challenge_pages():
    assert classify_access(observation()) == {"status": READY, "reason": None}
    assert classify_access(observation(visible_password_field=True)) == {
        "status": AUTH_REQUIRED,
        "reason": "visible_password_field",
    }
    assert classify_access(observation(url="https://example.test/login")) == {
        "status": AUTH_REQUIRED,
        "reason": "login_url",
    }
    assert classify_access(observation(url="https://example.test/?__cf_chl_rt_tk=temporary")) == {
        "status": CHALLENGE,
        "reason": "challenge_page",
    }


def test_local_access_block_does_not_claim_model_confidence():
    prediction = local_blocked_prediction({"status": CHALLENGE, "reason": "challenge_page"})

    assert prediction["operation"] == "BLOCKED"
    assert prediction["source"] == "local_access_guard"
    assert prediction["model"] is None
    assert prediction["confidence"] is None
    assert prediction["executed"] is False


def test_captured_sahibinden_temporary_block_stops_before_steering():
    page = observation(url="https://www.sahibinden.com/", title="")
    page["text"] = (
        "Olağandışı bir durum tespit ettik...\n"
        "Şu anda talebinizi gerçekleştiremiyoruz, kısa bir süre sonra tekrar deneyebilirsiniz.\n"
        "Destek Kodu: F-example"
    )
    classified = classify_access(page)
    assert classified == {"status": ACCESS_BLOCKED, "reason": "temporary_access_block"}
    assert local_blocked_prediction(classified)["blocked_reason"] == ACCESS_BLOCKED
