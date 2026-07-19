"""In-process throttling for login and guest-session endpoints.

Login attempts are throttled to one per 5 seconds per key (username or client
IP). Guest-session creation additionally has an hourly per-IP cap so a script
can't mint unlimited throwaway accounts. State is in-memory: a restart clears
it, which is acceptable for abuse throttling.

STARSHOT_LOGIN_THROTTLE_SECONDS overrides the interval (tests set it to 0).
"""

from __future__ import annotations

import os
import threading
import time

from fastapi import HTTPException, Request

DEFAULT_INTERVAL_SECONDS = 5.0
GUEST_HOURLY_LIMIT = 20

_lock = threading.Lock()
_last_attempt: dict[str, float] = {}
_hourly_counts: dict[str, list[float]] = {}


def _interval() -> float:
    raw = os.environ.get("STARSHOT_LOGIN_THROTTLE_SECONDS", "")
    try:
        return float(raw) if raw != "" else DEFAULT_INTERVAL_SECONDS
    except ValueError:
        return DEFAULT_INTERVAL_SECONDS


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def throttle_login(key: str) -> None:
    """Raise 429 when *key* attempted a login within the last interval."""
    interval = _interval()
    if interval <= 0:
        return
    now = time.monotonic()
    with _lock:
        # Keep the table from growing without bound.
        if len(_last_attempt) > 10_000:
            cutoff = now - interval
            for stale in [k for k, t in _last_attempt.items() if t < cutoff]:
                del _last_attempt[stale]
        last = _last_attempt.get(key)
        _last_attempt[key] = now
        if last is not None and now - last < interval:
            raise HTTPException(
                status_code=429,
                detail="Too many sign-in attempts. Wait a few seconds and try again.",
            )


def throttle_guest_creation(ip: str) -> None:
    """Guest sessions: normal login throttle plus an hourly per-IP cap."""
    throttle_login(f"guest:{ip}")
    if _interval() <= 0:
        return
    now = time.monotonic()
    with _lock:
        window = [t for t in _hourly_counts.get(ip, []) if now - t < 3600]
        if len(window) >= GUEST_HOURLY_LIMIT:
            _hourly_counts[ip] = window
            raise HTTPException(
                status_code=429,
                detail="Too many guest voyages from this port today. Try again later.",
            )
        window.append(now)
        _hourly_counts[ip] = window


def reset() -> None:
    """Clear throttle state (tests)."""
    with _lock:
        _last_attempt.clear()
        _hourly_counts.clear()
