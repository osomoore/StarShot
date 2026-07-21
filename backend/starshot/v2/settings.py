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
DEFAULT_STARBREACH_BOSS_KEY = "default_starbreach_boss_design_id"
ALLOWED_STARBREACH_BOSSES_KEY = "allowed_starbreach_boss_design_ids"
DEFAULT_STARTING_SHIP_KEY = "default_starting_ship_design_id"

# The global ship design new players receive as their starting ship.
DEFAULT_STARTING_SHIP_FALLBACK = "lightningbug"

# StarDock (player ship designer) admin-configurable rule numbers. Stored as
# individual settings named f"stardock_{key}"; missing/invalid values fall
# back to the rules defaults (see rules.player_ships.DEFAULT_STARDOCK_CONFIG).
STARDOCK_CONFIG_KEYS = (
    "max_tiles",
    "primary_lane_limit",
    "secondary_lane_min_severed",
    "upgrade_defense_bonus",
    "upgrade_aim_bonus",
)


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


def default_starbreach_boss_design_id() -> str:
    return _get(DEFAULT_STARBREACH_BOSS_KEY) or ""


def default_starting_ship_design_id() -> str:
    """The global ship design id new players receive as their starting ship."""
    return _get(DEFAULT_STARTING_SHIP_KEY) or DEFAULT_STARTING_SHIP_FALLBACK


def allowed_starbreach_boss_design_ids() -> set[str]:
    raw = _get(ALLOWED_STARBREACH_BOSSES_KEY) or ""
    return {entry.strip() for entry in raw.split(",") if entry.strip()}


def stardock_config() -> dict:
    """The active StarDock rule numbers: admin-stored overrides on top of the
    rules defaults, clamped to sane ranges by the rules layer."""
    from starshot.rules.player_ships import stardock_config as merge_config

    overrides = {}
    for key in STARDOCK_CONFIG_KEYS:
        value = _get(f"stardock_{key}")
        if value is not None and str(value).strip().lstrip("-").isdigit():
            overrides[key] = int(value)
    return merge_config({"config": overrides})
