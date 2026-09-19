import io
import json
import urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from brownie_agent.chat_model import (
    Cooldowns,
    ModelHTTPError,
    complete_chat,
    model_settings,
    post_chat,
    rate_limit_policy,
    response_object,
)


def quota_error(*, model="primary", daily=False, retry="90s"):
    return ModelHTTPError(429, {"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
            "quotaId": "RequestsPerDayPerProjectPerModel" if daily else "RequestsPerMinute",
            "quotaDimensions": {"model": model} if model else {},
        }]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry},
    ]}})


def configure(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "private-test-key")
    monkeypatch.setenv("STEERING_MODEL", "primary")
    monkeypatch.setenv("STEERING_MODEL_FALLBACKS", "backup,primary,backup")


def test_rate_limit_switches_once_and_cooldown_survives_a_new_client(monkeypatch, tmp_path):
    configure(monkeypatch)
    path = tmp_path / "persisted.json"
    called = []

    def post(_url, key, body):
        assert key == "private-test-key"
        called.append(body["model"])
        if body["model"] == "primary":
            raise quota_error()
        return {"choices": []}

    _, metadata = complete_chat("STEERING", {}, post=post, cooldowns=Cooldowns(path), clock=lambda: 100)
    assert called == ["primary", "backup"]
    assert metadata["model"] == "backup"
    assert metadata["model_attempts"][0]["status"] == "rate_limited"
    assert metadata["model_attempts"][0]["retry_after_seconds"] == 90
    assert "private-test-key" not in path.read_text()

    _, metadata = complete_chat("STEERING", {}, post=post, cooldowns=Cooldowns(path), clock=lambda: 150)
    assert called == ["primary", "backup", "backup"]
    assert metadata["model_attempts"][0]["status"] == "cooldown"
    complete_chat("STEERING", {}, post=post, cooldowns=Cooldowns(path), clock=lambda: 191)
    assert called[-2:] == ["primary", "backup"]


def test_cooldowns_are_shared_between_roles_using_the_same_key_and_endpoint(monkeypatch, tmp_path):
    configure(monkeypatch)
    monkeypatch.setenv("TEXT_MODEL", "primary")
    monkeypatch.setenv("TEXT_MODEL_FALLBACKS", "backup")
    cooldowns = Cooldowns(tmp_path / "quota.json")
    calls = []

    def post(_url, _key, body):
        calls.append(body["model"])
        if body["model"] == "primary":
            raise quota_error()
        return {}

    complete_chat("STEERING", {}, post=post, cooldowns=cooldowns, clock=lambda: 100)
    complete_chat("TEXT", {}, post=post, cooldowns=cooldowns, clock=lambda: 110)
    assert calls == ["primary", "backup", "backup"]


@pytest.mark.parametrize("error", [quota_error(model=None), ModelHTTPError(429), ModelHTTPError(429, [])])
def test_shared_or_unknown_429_stops_without_trying_another_model(monkeypatch, error):
    configure(monkeypatch)
    calls = []

    def post(_url, _key, body):
        calls.append(body["model"])
        raise error

    with pytest.raises(RuntimeError, match="shared or unclassified"):
        complete_chat("STEERING", {}, post=post)
    with pytest.raises(RuntimeError, match="cooldown is active"):
        complete_chat("STEERING", {}, post=post)
    assert calls == ["primary"]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
def test_non_quota_errors_never_fall_back(monkeypatch, status):
    configure(monkeypatch)
    calls = []

    def post(_url, _key, body):
        calls.append(body["model"])
        raise ModelHTTPError(status)

    with pytest.raises(ModelHTTPError):
        complete_chat("STEERING", {}, post=post)
    assert calls == ["primary"]


def test_exhausted_candidates_stop_after_one_attempt_each(monkeypatch):
    configure(monkeypatch)
    calls = []

    def post(_url, _key, body):
        calls.append(body["model"])
        raise quota_error(model=body["model"])

    with pytest.raises(RuntimeError, match="All configured models"):
        complete_chat("STEERING", {}, post=post)
    assert calls == ["primary", "backup"]


def test_daily_limit_waits_for_pacific_midnight_and_honors_retry_after():
    now = datetime(2026, 9, 19, 23, 0, tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()
    scope, delay = rate_limit_policy(quota_error(daily=True), now)
    assert (scope, delay) == ("model", 3600)
    error = quota_error()
    error.retry_after = "Sun, 20 Sep 2026 08:00:00 GMT"
    assert rate_limit_policy(error, now)[1] == 7200


def test_mixed_project_and_model_quotas_do_not_allow_fallback():
    error = quota_error()
    error.payload["error"]["details"][0]["violations"].append({"quotaId": "SpendPerProject"})
    assert rate_limit_policy(error, 100)[0] == "shared_or_unknown"


def test_compatible_endpoint_array_wrapped_quota_error():
    error = quota_error()
    error.payload = [error.payload]
    assert rate_limit_policy(error, 100) == ("model", 90)


def test_settings_share_a_key_but_keep_model_chains_independent(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv("TEXT_MODEL", "text-primary")
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "text-override")
    assert model_settings("STEERING")[0] == "private-test-key"
    assert model_settings("STEERING")[2] == ["primary", "backup"]
    assert model_settings("TEXT")[0] == "text-override"
    assert model_settings("TEXT")[2] == ["text-primary"]
    monkeypatch.setenv("STEERING_MODEL_FALLBACKS", "a,b,c")
    with pytest.raises(ValueError, match="at most 2"):
        model_settings("STEERING")


def test_http_transport_preserves_quota_details_without_exposing_error_body(monkeypatch):
    payload = quota_error().payload
    payload["error"]["message"] = "sensitive-debug-detail"

    def urlopen(request, timeout):
        assert timeout == 25
        assert request.get_header("Authorization") == "Bearer secret"
        raise urllib.error.HTTPError(
            request.full_url, 429, "private", {"Retry-After": "120"}, io.BytesIO(json.dumps(payload).encode()),
        )

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(ModelHTTPError) as caught:
        post_chat("https://example.test/chat/completions", "secret", {"model": "primary"})
    assert "sensitive-debug-detail" not in str(caught.value)
    assert rate_limit_policy(caught.value, 100) == ("model", 120)


@pytest.mark.parametrize("response", [
    {"choices": [{"finish_reason": "length", "message": {"content": '{}'}}]},
    {"choices": [{"message": {"content": '{}', "refusal": "refused"}}]},
    {"choices": [{"message": {"content": '[]'}}]},
    {"choices": [{"message": {"content": '{}', "tool_calls": [{}]}}]},
    {"choices": []},
    {"choices": [None]},
])
def test_incomplete_or_non_object_outputs_are_rejected(response):
    with pytest.raises(ValueError, match="complete JSON object"):
        response_object(response)
