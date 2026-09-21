"""Shared Gemini-compatible transport and bounded model-rate-limit fallback."""

import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import runtime_root
from .trace import trace_event

if os.name == "nt":
    import msvcrt
else:
    import fcntl

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
MAX_MODELS = 3


def _lock_file(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        fcntl.flock(handle, fcntl.LOCK_EX)


def _unlock_file(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def _exclusive_file(handle):
    """Lock one cooldown file with the native Windows or Unix mechanism."""
    _lock_file(handle)
    try:
        yield
    finally:
        _unlock_file(handle)


class ModelHTTPError(RuntimeError):
    """HTTP failure with private quota details used only by the fallback policy."""

    def __init__(self, status: int, payload=None, retry_after=None):
        super().__init__(f"Model returned HTTP {status}; no browser action executed.")
        self.status = status
        self.payload = payload
        self.retry_after = retry_after


def post_chat(url: str, key: str, body: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read(65536))
        except (ValueError, OSError):
            payload = None
        raise ModelHTTPError(error.code, payload, error.headers.get("Retry-After")) from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise RuntimeError("Model connection or response failed; no browser action executed.") from None


class Cooldowns:
    """Persist only hashed endpoint/key/model identities and expiry times, never prompts or keys."""

    def __init__(self, path: Path):
        self.path = path

    def access(self, identity: str, now: float, until: float | None = None) -> float:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "r+", encoding="utf-8") as handle:
            with _exclusive_file(handle):
                try:
                    entries = json.load(handle)
                except ValueError:
                    entries = {}
                if not isinstance(entries, dict):
                    entries = {}
                entries = {
                    k: v for k, v in entries.items()
                    if isinstance(k, str) and type(v) in (int, float) and math.isfinite(v) and v > now
                }
                if until is not None:
                    entries[identity] = max(entries.get(identity, 0), until)
                handle.seek(0)
                handle.truncate()
                json.dump(entries, handle)
                return entries.get(identity, 0)


COOLDOWNS = Cooldowns(runtime_root() / "artifacts" / "model-cooldowns.json")


def _seconds(value) -> float:
    try:
        seconds = float(value)
        return seconds if math.isfinite(seconds) and seconds >= 0 else 0
    except (TypeError, ValueError):
        return 0


def rate_limit_policy(error: ModelHTTPError, now: float) -> tuple[str, float]:
    """Only structured, wholly model-scoped quotas permit switching models."""
    delay = _seconds(error.retry_after)
    if error.retry_after and not delay:
        try:
            delay = max(0, parsedate_to_datetime(error.retry_after).timestamp() - now)
        except (TypeError, ValueError, OverflowError):
            pass
    payload = error.payload
    # Gemini's compatible endpoint can wrap errors in a singleton array.
    if isinstance(payload, list) and len(payload) == 1:
        payload = payload[0]
    payload = payload if isinstance(payload, dict) else {}
    data = payload.get("error", {})
    data = data if isinstance(data, dict) else {}
    details = data.get("details", [])
    details = details if isinstance(details, list) else []
    violations = []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        if str(detail.get("@type", "")).endswith("/google.rpc.RetryInfo"):
            retry = detail.get("retryDelay", "")
            if isinstance(retry, str) and retry.endswith("s"):
                delay = max(delay, _seconds(retry[:-1]))
        if str(detail.get("@type", "")).endswith("/google.rpc.QuotaFailure"):
            values = detail.get("violations", [])
            if isinstance(values, list):
                violations.extend(values)

    def model_scoped(violation):
        if not isinstance(violation, dict):
            return False
        dimensions = violation.get("quotaDimensions", {})
        return (
            isinstance(dimensions, dict) and bool(dimensions.get("model"))
        ) or "permodel" in str(violation.get("quotaId", "")).lower()

    scope = "model" if violations and all(model_scoped(v) for v in violations) else "shared_or_unknown"
    quota_ids = " ".join(str(v.get("quotaId", "")) for v in violations if isinstance(v, dict)).lower()
    if "perday" in quota_ids:
        pacific = datetime.fromtimestamp(now, ZoneInfo("America/Los_Angeles"))
        midnight = (pacific + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        delay = max(delay, midnight.timestamp() - now)
    return scope, max(delay, 60)


def model_settings(role: str) -> tuple[str, str, list[str]]:
    if role not in {"TEXT", "STEERING"}:
        raise ValueError("Unknown model role")
    prefix = role + "_MODEL"
    key = os.environ.get(prefix + "_API_KEY", "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise ValueError(f"Set GEMINI_API_KEY or {prefix}_API_KEY; no browser action executed.")
    base = (os.environ.get(prefix + "_BASE_URL", "").strip() or GEMINI_BASE_URL).rstrip("/")
    default = "gemini-3.5-flash-lite" if role == "TEXT" else "gemini-3.6-flash"
    primary = os.environ.get(prefix, default).strip()
    models = list(dict.fromkeys([primary, *[
        value.strip() for value in os.environ.get(prefix + "_FALLBACKS", "").split(",") if value.strip()
    ]]))
    if not primary or len(models) > MAX_MODELS:
        raise ValueError(f"{prefix} requires a primary and at most {MAX_MODELS - 1} distinct fallback models.")
    return key, base + "/chat/completions", models


def complete_chat(role: str, body: dict, *, post=post_chat, cooldowns=None, clock=time.time) -> tuple[dict, dict]:
    """Try each candidate once; no retry of successful, malformed, or non-429 responses."""
    key, url, models = model_settings(role)
    cooldowns = COOLDOWNS if cooldowns is None else cooldowns
    attempts = []
    started = time.perf_counter()

    def identity(model):
        return hashlib.sha256(json.dumps([url, key, model]).encode()).hexdigest()

    for model in models:
        now = clock()
        shared_until = cooldowns.access(identity("*"), now)
        if shared_until > now:
            raise RuntimeError("Shared or unclassified quota cooldown is active; no browser action executed.")
        until = cooldowns.access(identity(model), now)
        if until > now:
            attempts.append({"model": model, "status": "cooldown", "retry_after_seconds": math.ceil(until - now)})
            trace_event("model_attempt", {"provider": "llm", "role": role.lower(), **attempts[-1]})
            continue
        request_body = {**body, "model": model}
        trace_event("model_request", {
            "provider": "llm", "role": role.lower(), "model": model, "body": request_body,
        })
        try:
            result = post(url, key, request_body)
        except ModelHTTPError as error:
            if error.status != 429:
                raise
            scope, delay = rate_limit_policy(error, clock())
            cooldowns.access(identity(model if scope == "model" else "*"), clock(), clock() + delay)
            if scope != "model":
                raise RuntimeError(
                    "HTTP 429 quota is shared or unclassified; model fallback stopped; no browser action executed."
                ) from None
            attempts.append({"model": model, "status": "rate_limited", "retry_after_seconds": math.ceil(delay)})
            trace_event("model_attempt", {"provider": "llm", "role": role.lower(), **attempts[-1]})
            continue
        if not isinstance(result, dict):
            raise ValueError("Model returned an invalid response; no browser action executed.")
        trace_event("model_response", {
            "provider": "llm", "role": role.lower(), "model": model, "response": result,
        })
        attempts.append({"model": model, "status": "answered"})
        return result, {
            "model": model,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "usage": result.get("usage", {}),
            "model_attempts": attempts,
        }
    raise RuntimeError("All configured models are rate-limited or cooling down; no browser action executed.")


def response_object(result: dict) -> dict:
    """Require one complete JSON-object answer, rejecting refusals and truncation."""
    try:
        choices = result["choices"]
        if len(choices) != 1 or choices[0].get("finish_reason", "stop") != "stop":
            raise ValueError()
        message = choices[0]["message"]
        if message.get("refusal") or message.get("tool_calls"):
            raise ValueError()
        output = json.loads(message["content"])
        if not isinstance(output, dict):
            raise ValueError()
        return output
    except (IndexError, KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("Model returned no complete JSON object; no browser action executed.") from None
