"""Local access-state detection before model calls or scheduled work."""

from urllib.parse import parse_qs, urlsplit

READY = "ready"
AUTH_REQUIRED = "auth_required"
CHALLENGE = "challenge"
ACCESS_BLOCKED = "access_blocked"


def classify_access(observation: dict) -> dict:
    """Classify explicit login/challenge evidence without reading credentials."""
    parsed = urlsplit(observation["url"])
    query_keys = {key.lower() for key in parse_qs(parsed.query)}
    path = parsed.path.lower()
    title = observation["title"].strip().lower()
    signals = observation.get("access", {})
    visible_text = observation.get("text", "").casefold()

    if (
        "olağandışı bir durum tespit ettik" in visible_text
        and "şu anda talebinizi gerçekleştiremiyoruz" in visible_text
        and "destek kodu:" in visible_text
    ):
        return {"status": ACCESS_BLOCKED, "reason": "temporary_access_block"}

    if (
        signals.get("challenge_marker")
        or any(key.startswith("__cf_chl") for key in query_keys)
        or "/cdn-cgi/challenge" in path
        or title in {"just a moment...", "attention required!"}
    ):
        return {"status": CHALLENGE, "reason": "challenge_page"}

    auth_segments = {"login", "log-in", "signin", "sign-in", "authenticate"}
    path_segments = set(filter(None, path.split("/")))
    if signals.get("visible_password_field"):
        return {"status": AUTH_REQUIRED, "reason": "visible_password_field"}
    if path_segments & auth_segments:
        return {"status": AUTH_REQUIRED, "reason": "login_url"}
    return {"status": READY, "reason": None}


def local_blocked_prediction(access: dict) -> dict:
    """Return a non-model BLOCKED result for explicit access barriers."""
    if access["status"] == READY:
        raise ValueError("A ready page does not need a local blocked prediction")
    return {
        "operation": "BLOCKED",
        "target": None,
        "target_name": None,
        "confidence": None,
        "operation_probabilities": {},
        "target_confidence": None,
        "target_probabilities": {},
        "model": None,
        "usage": {},
        "latency_ms": 0,
        "executed": False,
        "source": "local_access_guard",
        "blocked_reason": access["status"],
    }
