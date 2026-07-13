"""Per-viewer redaction of game state for the v2 multiplayer API.

The engine's own serialization exposes everything (decks, hands, rng cursor).
Multiplayer clients must only ever receive what their player could see at a
physical table: their own hand, everyone's public piles, and the event log
with hidden draws stripped.
"""

from __future__ import annotations

from copy import deepcopy

# Event fields that reveal hidden information, per event type. For events tied
# to a player (player_id), fields are only stripped for other viewers; events
# in _ALWAYS_STRIP hide the field even from the owner (e.g. deck order).
_OWNER_ONLY_FIELDS = {
    "hand_drawn": ("card_ids",),
    "orders_submitted": ("stacks",),
    "desperation_consequence": ("desperation_card_id", "moved_to_overheat_card_id"),
    "debug_desperation_drawn": ("card_id",),
    "starfall_jolly_roger_draw": ("desperation_card_id",),
    "captain_davey_reward": ("desperation_card_id",),
}
_ALWAYS_STRIP = {
    "deck_refreshed": ("card_ids",),
}


def redact_event(event: dict, viewer_id: str | None) -> dict:
    event_type = event.get("type")
    stripped = None
    if event_type in _ALWAYS_STRIP:
        stripped = _ALWAYS_STRIP[event_type]
    elif event_type in _OWNER_ONLY_FIELDS and event.get("player_id") != viewer_id:
        stripped = _OWNER_ONLY_FIELDS[event_type]
    result = dict(event)
    if stripped:
        for field_name in stripped:
            result.pop(field_name, None)
        result["redacted"] = True
    if event_type == "bauble_awarded" and viewer_id is not None:
        awards = []
        for award in result.get("awards", []):
            award = dict(award)
            if award.get("player_id") != viewer_id:
                award.pop("desperation_card_id", None)
            awards.append(award)
        result["awards"] = awards
    return result


def redact_player(player_dict: dict, is_viewer: bool) -> dict:
    result = dict(player_dict)
    result["deck_count"] = len(player_dict.get("deck") or [])
    result["hand_count"] = len(player_dict.get("hand") or [])
    result.pop("deck", None)  # deck order/content is hidden even from the owner
    if not is_viewer:
        result.pop("hand", None)
        result["prepared_orders"] = None
        if not result.get("captain"):
            result.pop("captain_options", None)
    return result


def game_view(state_dict: dict, viewer_player_id: str | None) -> dict:
    """Redacted view of a fully-serialized state for one player (or a spectator
    when viewer_player_id is None)."""
    view = deepcopy(state_dict)
    view.pop("rng_seed", None)
    view.pop("rng_step", None)
    deck_set = view.get("deck_set") or {}
    view["deck_set"] = {
        "id": deck_set.get("id"),
        "name": deck_set.get("name"),
        "rules_version": deck_set.get("rules_version"),
    }
    desperation = view.get("desperation_deck") or {}
    view["desperation_deck"] = {"count": len(desperation.get("cards") or [])}
    view["players"] = {
        player_id: redact_player(player, player_id == viewer_player_id)
        for player_id, player in (view.get("players") or {}).items()
    }
    view["event_log"] = [redact_event(event, viewer_player_id) for event in view.get("event_log") or []]
    view["version"] = len(state_dict.get("event_log") or [])
    return view
