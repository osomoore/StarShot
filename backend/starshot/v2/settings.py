"""Runtime site settings (admin-togglable, stored in the v2 database).

Read on hot paths (the auth middleware runs on every request), so values are
cached briefly; toggles take effect within a few seconds.
"""

from __future__ import annotations

import os
import time

_TTL_SECONDS = 4.0
_cache: dict[str, tuple[float, str | None]] = {}

SITE_AUTH_KEY = "site_auth"            # "on" | "off"; default from STARSHOT_SITE_AUTH env
MAINTENANCE_KEY = "maintenance"        # non-empty string = under construction message
ACTIVE_DECK_KEY = "active_deck_set_path"


def _get(key: str) -> str | None:
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and now - cached[0] < _TTL_SECONDS:
        return cached[1]
    from starshot.v2.store import get_v2_store

    try:
        value = get_v2_store().get_setting(key)
    except Exception:
        value = None  # never let a settings hiccup take the site down
    _cache[key] = (now, value)
    return value


def invalidate_cache() -> None:
    _cache.clear()


def site_auth_enabled() -> bool:
    value = _get(SITE_AUTH_KEY)
    if value is None:
        return os.environ.get("STARSHOT_SITE_AUTH", "").lower() == "on"
    return value == "on"


def maintenance_message() -> str:
    return _get(MAINTENANCE_KEY) or ""


def active_deck_setting() -> str | None:
    return _get(ACTIVE_DECK_KEY)
