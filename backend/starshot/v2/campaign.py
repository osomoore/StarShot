"""Persistent campaign component catalog, player inventory, and rewards."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from copy import deepcopy

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from starshot.rules.deck_data import expand_card_definition, load_deck_catalog
from starshot.rules.decks import _base_card_kind
from starshot.rules.models import CardFamily
from starshot.rules.serialization import card_to_dict
from starshot.v2.store import V2Store, get_v2_store

CATALOG_SETTING = "campaign_component_awards_v1"
campaign_router = APIRouter(prefix="/api/v2/campaign", tags=["v2"])
campaign_admin_router = APIRouter(prefix="/api/v2/admin/component-awards", tags=["v2-admin"])


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:60] or "component"


def _active_v2_catalog():
    from starshot.v2.service import core_deck_path

    return load_deck_catalog(core_deck_path())


def _default_catalog() -> list[dict]:
    """One reward component for every physical card in the active starting deck."""
    result = []
    name_counts: dict[str, int] = {}
    deck_catalog = _active_v2_catalog()
    definitions_by_id: dict[str, dict] = {}
    with (deck_catalog.path / "base_deck.toml").open("rb") as handle:
        base_data = tomllib.load(handle)
    physical_cards = iter(deck_catalog.base_cards)
    for entry_index, raw_definition in enumerate(base_data.get("cards", []), start=1):
        definition = deepcopy(raw_definition)
        expanded = expand_card_definition(
            definition,
            source=f"base deck card #{entry_index}",
        )
        for _ in expanded:
            card = next(physical_cards)
            physical_definition = deepcopy(definition)
            physical_definition["id"] = card.id
            physical_definition["copies"] = 1
            definitions_by_id[card.id] = physical_definition

    for card in deck_catalog.base_cards:
        kind = _base_card_kind(card)
        name_counts[card.name] = name_counts.get(card.name, 0) + 1
        suffix = name_counts[card.name]
        label = card.name if sum(c.name == card.name for c in deck_catalog.base_cards) == 1 else f"{card.name} {suffix}"
        component_type = "engine" if card.family == CardFamily.MOVE else "weapon"
        cost = 2 if (kind or "").endswith("_2") or card.value >= 2 else 1
        definition = definitions_by_id.get(card.id, {
            "id": card.id,
            "name": card.name,
            "copies": 1,
            "side_a_type": "Basic",
            "side_a_1": card.name,
        })
        result.append(_catalog_entry({
            "id": _slug(card.id),
            "name": label,
            "description": f"A {component_type} component that adds {card.name} to this ship's starting deck.",
            "cost": cost,
            "component_type": component_type,
            "card": definition,
            "legacy_card_id": card.id,
            "reward_rule": "random",
        }, len(result) + 1))
    return result


def _catalog_entry(item: dict, index: int, legacy_cards: dict[str, dict] | None = None) -> dict:
    component_id = _slug(str(item.get("id") or item.get("name") or ""))
    name = str(item.get("name") or "").strip()[:80]
    if not name:
        raise ValueError(f"Component {index} needs a name.")
    try:
        cost = int(item.get("cost", 1))
    except (TypeError, ValueError):
        raise ValueError(f"{name} has an invalid point cost.") from None
    if cost not in (1, 2):
        raise ValueError(f"{name} must cost 1 or 2 Core Component points.")
    component_type = str(item.get("component_type") or "engine").lower()
    if component_type not in ("engine", "weapon"):
        raise ValueError(f"{name} component type must be engine or weapon.")

    raw_card = item.get("card")
    if not isinstance(raw_card, dict) and legacy_cards is not None:
        raw_card = legacy_cards.get(str(item.get("card_id") or ""))
    if not isinstance(raw_card, dict):
        raise ValueError(f"{name} needs a starting-deck card definition.")
    card_definition = deepcopy(raw_card)
    card_definition["id"] = f"campaign_{component_id}_card"
    card_definition["name"] = str(card_definition.get("name") or name).strip()[:80]
    try:
        copies = int(card_definition.get("copies", 1))
    except (TypeError, ValueError):
        raise ValueError(f"{name}'s card copies must be a number.") from None
    card_definition["copies"] = copies
    compiled = expand_card_definition(card_definition, source=f"Campaign component {name!r} card")
    if not compiled:
        raise ValueError(f"{name}'s card definition did not create a card.")
    return {
        "id": component_id,
        "name": name,
        "description": str(item.get("description") or "")[:500],
        "cost": cost,
        "component_type": component_type,
        "card": card_definition,
        "card_id": compiled[0].id,
        "card_name": compiled[0].name,
        "starting_cards": [card_to_dict(card) for card in compiled],
        **({"legacy_card_id": str(item["legacy_card_id"])} if item.get("legacy_card_id") else {}),
        "reward_rule": "random",
    }


def normalize_catalog(raw: object, *, validate_cards: bool = True) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("The component award catalog must be a list.")
    # Upgrade the first campaign implementation, whose entries only pointed
    # at active-deck card ids, into owned Deck Editor card definitions.
    legacy_cards: dict[str, dict] = {}
    if any(isinstance(item, dict) and not isinstance(item.get("card"), dict) for item in raw):
        for default in _default_catalog():
            legacy_cards[str(default.get("card_id") or "")] = default["card"]
            legacy_cards[str(default.get("legacy_card_id") or "")] = default["card"]
    result: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Component {index + 1} must be an object.")
        component_id = _slug(str(item.get("id") or item.get("name") or ""))
        if component_id in seen:
            raise ValueError(f"Duplicate component id: {component_id}")
        seen.add(component_id)
        result.append(_catalog_entry(item, index + 1, legacy_cards))
    return result


def component_catalog(store: V2Store | None = None) -> list[dict]:
    store = store or get_v2_store()
    raw = store.get_setting(CATALOG_SETTING)
    if raw:
        try:
            return normalize_catalog(json.loads(raw), validate_cards=False)
        except (ValueError, json.JSONDecodeError):
            pass
    catalog = _default_catalog()
    store.set_setting(CATALOG_SETTING, json.dumps(catalog))
    return catalog


def catalog_map(store: V2Store | None = None) -> dict[str, dict]:
    return {entry["id"]: entry for entry in component_catalog(store)}


def inventory_for_user(user_id: int, store: V2Store | None = None) -> list[dict]:
    store = store or get_v2_store()
    by_id = catalog_map(store)
    return [by_id[item_id] for item_id in store.campaign_component_ids(user_id) if item_id in by_id]


def award_for_completed_match(store: V2Store, match: dict, state) -> None:
    """Award each qualifying registered human one random not-yet-owned item."""
    vp_winners = set(
        state.result.winner_ids
        if state.result and state.result.reason == "round_six_victory_points"
        else ()
    )
    destroyed_by: set[str] = set()
    for event in state.event_log:
        if event.get("type") == "volley_resolved" and event.get("target_destroyed"):
            attacker_id = event.get("attacker_id")
            target_id = event.get("target_id")
            if attacker_id in state.players and target_id in state.players and attacker_id != target_id:
                destroyed_by.add(attacker_id)
    catalog = component_catalog(store)
    for seat in match.get("seat_list", []):
        user_id = seat.get("user_id")
        player_id = seat.get("player_id")
        if not user_id or seat.get("stats_exempt") or player_id not in vp_winners | destroyed_by:
            continue
        user = store.get_user(user_id)
        if not user or user.get("is_guest") or store.campaign_award_for_match(user_id, match["id"]):
            continue
        owned = set(store.campaign_component_ids(user_id))
        choices = [entry for entry in catalog if entry["id"] not in owned]
        if not choices:
            continue
        digest = hashlib.sha256(f"{match['id']}:{user_id}".encode()).digest()
        component = choices[int.from_bytes(digest[:8], "big") % len(choices)]
        source_kind = "wreckage" if player_id in destroyed_by else "dominance"
        if store.award_campaign_component(user_id, component["id"], match_id=match["id"], source_kind=source_kind):
            store.record_campaign_award(user_id, match["id"], component["id"], source_kind)


def match_award_payload(store: V2Store, user_id: int, match_id: str) -> dict | None:
    award = store.campaign_award_for_match(user_id, match_id)
    if not award:
        return None
    component = catalog_map(store).get(award["component_id"])
    return {**award, "component": component} if component else None


class ManualAward(BaseModel):
    component_id: str = Field(max_length=80)


@campaign_router.get("")
def get_campaign(request: Request) -> dict:
    from starshot.v2.admin import admin_usernames
    from starshot.v2.router import _registered_user

    user = _registered_user(request)
    return {
        "components": inventory_for_user(user["id"]),
        "available_components": component_catalog(),
        "is_admin": user["username"].lower() in admin_usernames(),
        "initial_ship": {"id": "lightningbug", "name": "LightningBug"},
    }


@campaign_router.post("/admin-award")
def manual_award(body: ManualAward, request: Request) -> dict:
    from starshot.v2.admin import _admin_user

    user = _admin_user(request)
    component = catalog_map().get(body.component_id)
    if component is None:
        raise HTTPException(status_code=404, detail="Unknown component reward.")
    added = get_v2_store().award_campaign_component(user["id"], component["id"], source_kind="admin")
    return {"ok": True, "added": added, "components": inventory_for_user(user["id"])}


@campaign_admin_router.get("")
def admin_catalog(request: Request) -> dict:
    from starshot.v2.admin import _admin_user

    _admin_user(request)
    return {
        "components": component_catalog(),
    }


@campaign_admin_router.put("")
async def save_admin_catalog(request: Request) -> dict:
    from starshot.v2.admin import _admin_user

    _admin_user(request)
    try:
        components = normalize_catalog((await request.json()).get("components"))
    except (AttributeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    get_v2_store().set_setting(CATALOG_SETTING, json.dumps(components))
    return {"ok": True, "components": components}
