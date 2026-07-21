"""HTTP surface for the player ship designer.

Thin wrapper over ``starshot.v2.ship_designs``; all schema and game-design
validation lives there so it can be tested and reused without FastAPI.

Routers:
- ``/api/v2/ship-designs``            (signed-in) playable ships for the lobby
- ``/api/v2/my/ship-designs``         (signed-in) personal design library,
  including JSON export/import so players can download/upload designs
- ``/api/v2/admin/ship-designs``      (admin) global library management
- ``/api/v2/admin/player-ship-designs`` (admin/mod) browse every player's
  designs, clone one into the global library, or delete one
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from starshot.rules.player_ships import (
    BASE_DRAW,
    BASE_PALETTE_LIMITS,
    BASE_SHIELDS,
    BASE_TILE_TOTAL,
    DECK_SIZE,
    PRIMARY_LANE_ROLLS,
    SECONDARY_LANE_ROLLS,
    SHIP_UPGRADES,
    UPGRADE_EXTRA_POINTS,
    compile_layout_spec,
    points_breakdown,
)
from starshot.v2 import ship_designs
from starshot.v2.admin import _admin_user

ship_designer_admin_router = APIRouter(prefix="/api/v2/admin/ship-designs", tags=["v2-admin"])
player_ship_library_admin_router = APIRouter(prefix="/api/v2/admin/player-ship-designs", tags=["v2-admin"])
ship_designs_public_router = APIRouter(prefix="/api/v2/ship-designs", tags=["v2"])
my_ship_designs_router = APIRouter(prefix="/api/v2/my/ship-designs", tags=["v2"])
my_ship_router = APIRouter(prefix="/api/v2/my/ship", tags=["v2"])


def _designer_meta() -> dict:
    config = ship_designs.active_stardock_config()
    return {
        "grid_radius": ship_designs.GRID_RADIUS,
        "tile_types": list(ship_designs.TILE_TYPES),
        "base_tile_total": BASE_TILE_TOTAL,
        "deck_size": DECK_SIZE,
        "base_shields": BASE_SHIELDS,
        "base_draw": BASE_DRAW,
        "base_palette_limits": dict(BASE_PALETTE_LIMITS),
        "upgrades": list(SHIP_UPGRADES),
        "upgrade_extra_points": UPGRADE_EXTRA_POINTS,
        "primary_lane_rolls": list(PRIMARY_LANE_ROLLS),
        "secondary_lane_rolls": list(SECONDARY_LANE_ROLLS),
        "player_design_limit": ship_designs.PLAYER_DESIGN_LIMIT,
        # admin-configurable rule numbers
        "max_tiles": config["max_tiles"],
        "primary_lane_limit": config["primary_lane_limit"],
        "secondary_lane_min_severed": config["secondary_lane_min_severed"],
        "core_points": config["core_points"],
        "upgrade_defense_bonus": config["upgrade_defense_bonus"],
        "upgrade_aim_bonus": config["upgrade_aim_bonus"],
    }


def _current_user(request: Request) -> dict:
    """Any signed-in user, including guests. Guests fly and build ships just
    like registered captains; their designs are simply discarded when the
    guest voyage ends (see guest logout). Boss designs stay registered-only."""
    from starshot.v2.router import _current_user as any_signed_in_user

    return any_signed_in_user(request)


def _design_or_404(design_id: str, owner_id: int | None) -> dict:
    try:
        design = ship_designs.load_design(design_id, owner_id)
    except ship_designs.ShipDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if design is None:
        raise HTTPException(status_code=404, detail="No ship design with that id.")
    return design


def _design_payload(design: dict, owner_id: int | None = None) -> dict:
    configured = ship_designs.with_active_config(design, owner_id)
    return {
        "design": design,
        "problems": ship_designs.validate_design(configured),
        "points": points_breakdown(configured),
        "preview": compile_layout_spec(configured),
    }


# --------------------------------------------------------------------------
# Signed-in players: playable ships for the lobby pickers
# --------------------------------------------------------------------------


@ship_designs_public_router.get("")
def list_playable_ship_designs(request: Request) -> dict:
    """Ships this user may fly: battle-ready global designs, plus their own
    battle-ready designs (ids prefixed `user:<uid>:`). The standard base
    ship is always available and is represented by an empty design id."""
    from starshot.v2.router import _current_user as any_signed_in_user

    user = any_signed_in_user(request)  # guests may fly global designs
    designs = [
        {"id": entry["id"], "name": entry["name"], "points": entry["points"]}
        for entry in ship_designs.list_designs()
        if entry["valid"]
    ]
    designs.extend(
        {"id": f"user:{user['id']}:{entry['id']}", "name": f"{entry['name']} (yours)", "points": entry["points"]}
        for entry in ship_designs.list_designs(user["id"])
        if entry["valid"]
    )
    return {"designs": designs}


# --------------------------------------------------------------------------
# Player-owned ship designs (any signed-in user, capped library)
# --------------------------------------------------------------------------


@my_ship_designs_router.get("")
def list_my_ship_designs(request: Request) -> dict:
    user = _current_user(request)
    from starshot.v2.store import get_v2_store
    from starshot.v2.service import ensure_starter_ship

    store = get_v2_store()
    ensure_starter_ship(store, user["id"])
    meta = _designer_meta()
    from starshot.v2.campaign import component_catalog, inventory_for_user
    meta["bonus_components"] = inventory_for_user(user["id"])
    meta["available_reward_components"] = component_catalog()
    from starshot.v2.admin import admin_usernames
    meta["is_campaign_admin"] = user["username"].lower() in admin_usernames()
    # The designer opens from the landing-page ship card into a specific
    # design, so no first-visit auto-open is needed here anymore.
    meta["first_visit"] = False
    meta["initial_design_id"] = None
    return {"designs": ship_designs.list_designs(user["id"]), "meta": meta}


@my_ship_designs_router.get("/{design_id}")
def get_my_ship_design(design_id: str, request: Request) -> dict:
    user = _current_user(request)
    return _design_payload(_design_or_404(design_id, user["id"]), user["id"])


@my_ship_designs_router.put("")
async def put_my_ship_design(request: Request) -> dict:
    user = _current_user(request)
    try:
        design, problems = ship_designs.save_design(await request.json(), user["id"])
    except ship_designs.ShipDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc
    return {
        "ok": True,
        "design": design,
        "problems": problems,
        "points": points_breakdown(ship_designs.with_active_config(design)),
    }


@my_ship_designs_router.delete("/{design_id}")
def delete_my_ship_design(design_id: str, request: Request) -> dict:
    from starshot.v2.service import ensure_starter_ship, parse_ship_design_ref
    from starshot.v2.store import get_v2_store

    user = _current_user(request)
    try:
        removed = ship_designs.delete_design(design_id, user["id"])
    except ship_designs.ShipDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="No ship design with that id.")
    # Safety net: if the player just deleted their last ship, restore the default
    # so they always have something to fly from the main screen.
    remaining = ship_designs.list_designs(user["id"])
    if not remaining or not any(d.get("valid") for d in remaining):
        store = get_v2_store()
        # Clear the stale selection so ensure_starter_ship will re-provision rather
        # than returning the deleted design's ref.
        store.set_selected_ship_ref(user["id"], "")
        ref = ensure_starter_ship(store, user["id"])
        owner_id, bare_id = parse_ship_design_ref(ref)
        default_design = ship_designs.load_design(bare_id, owner_id)
        return {
            "ok": True,
            "restored_default": True,
            "default_ship": {
                "name": default_design.get("name", "Your Ship") if default_design else "Your Ship",
                "ref": ref,
            },
        }
    return {"ok": True, "restored_default": False}


@my_ship_designs_router.get("/{design_id}/export")
def export_my_ship_design(design_id: str, request: Request) -> Response:
    user = _current_user(request)
    design = _design_or_404(design_id, user["id"])
    return Response(
        content=json.dumps(design, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="starshot-ship-{design["id"]}.json"'},
    )


@my_ship_designs_router.post("/import")
async def import_my_ship_design(request: Request) -> dict:
    """Upload a design JSON file. An id collision gets a numeric suffix so an
    upload never silently overwrites an existing design."""
    user = _current_user(request)
    body = await request.body()
    if len(body) > 500_000:
        raise HTTPException(status_code=400, detail="Ship design file is too large.")
    try:
        raw = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Not a valid JSON design file: {exc}") from exc
    try:
        design = ship_designs.normalize_design(raw)
        base_id = design["id"]
        design["id"] = ship_designs.unique_design_id(base_id, user["id"])
        saved, problems = ship_designs.save_design(design, user["id"])
    except ship_designs.ShipDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "design": saved, "problems": problems, "renamed": saved["id"] != base_id}


# --------------------------------------------------------------------------
# The player's persistent selected ship (shown on the landing page and flown
# in every raid). Its ref is "user:<uid>:<id>" (owned), a bare global id, or
# "" for the stock base ship.
# --------------------------------------------------------------------------


def _selected_ship_view(ref: str, user_id: int) -> dict:
    """Resolve a stored ship ref to {ref, design_id, name, preview}. The base
    ship is retired, so a missing/empty ref falls back to the admin default
    starting ship rather than the stock hull."""
    from starshot.v2.service import parse_ship_design_ref

    if ref:
        owner_id, bare_id = parse_ship_design_ref(ref)
        design = ship_designs.load_design(bare_id, owner_id)
        if design is not None:
            configured = ship_designs.with_active_config(design, owner_id)
            return {
                "ref": ref,
                "design_id": bare_id,
                "owner_id": owner_id,
                "name": design.get("name", bare_id),
                "preview": compile_layout_spec(configured),
            }
    # Retired base ship or a stale selection: show the global default starter.
    from starshot.v2.settings import default_starting_ship_design_id

    default_id = default_starting_ship_design_id()
    design = ship_designs.load_design(default_id)
    if design is not None:
        configured = ship_designs.with_active_config(design)
        return {
            "ref": default_id,
            "design_id": default_id,
            "name": design.get("name", default_id),
            "preview": compile_layout_spec(configured),
        }
    return {"ref": "", "design_id": "", "name": "No ship", "preview": {"components": []}}


def _owned_ship_options(user_id: int) -> list[dict]:
    """Ships the landing-page dropdown offers: the captain's own battle-ready
    designs, as {ref, name}. The base ship is retired — captains always fly a
    real ship/deck."""
    return [
        {"ref": f"user:{user_id}:{entry['id']}", "name": entry["name"]}
        for entry in ship_designs.list_designs(user_id)
        if entry["valid"]
    ]


def _my_ship_payload(user: dict) -> dict:
    from starshot.v2.store import get_v2_store
    from starshot.v2.service import ensure_starter_ship

    store = get_v2_store()
    ref = ensure_starter_ship(store, user["id"])
    selected = _selected_ship_view(ref, user["id"])
    # Everyone (guests included) may build and fly ships; guest creations are
    # simply discarded when the voyage ends.
    return {"selected": selected, "options": _owned_ship_options(user["id"]), "can_edit": True, "is_guest": bool(user.get("is_guest"))}


@my_ship_router.get("")
def get_my_ship(request: Request) -> dict:
    return _my_ship_payload(_current_user(request))


class SelectShipRequest(BaseModel):
    ship_design_id: str = Field(default="", max_length=140)


@my_ship_router.put("")
def put_my_ship(body: SelectShipRequest, request: Request) -> dict:
    user = _current_user(request)
    from starshot.v2.store import get_v2_store
    from starshot.v2.service import _load_playable_ship_design, ensure_starter_ship, parse_ship_design_ref

    # Provision the captain's starter library first so a selection always lands
    # on a real ship.
    ensure_starter_ship(get_v2_store(), user["id"])
    ref = (body.ship_design_id or "").strip()
    if not ref:
        # The base ship is retired; a captain must fly a real ship/deck.
        raise HTTPException(status_code=400, detail="Pick a ship — the base hull is retired.")
    try:
        owner_id, _bare = parse_ship_design_ref(ref)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if owner_id is not None and owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="That ship belongs to another captain.")
    try:
        _load_playable_ship_design(ref)  # must exist and be battle-ready
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    get_v2_store().set_selected_ship_ref(user["id"], ref)
    return {"ok": True, **_my_ship_payload(user)}


# --------------------------------------------------------------------------
# Admin: global library management
# --------------------------------------------------------------------------


@ship_designer_admin_router.get("")
def list_ship_designs(request: Request) -> dict:
    _admin_user(request)
    return {"designs": ship_designs.list_designs(), "meta": _designer_meta()}


@ship_designer_admin_router.get("/{design_id}")
def get_ship_design(design_id: str, request: Request) -> dict:
    _admin_user(request)
    return _design_payload(_design_or_404(design_id, None))


@ship_designer_admin_router.put("")
async def put_ship_design(request: Request) -> dict:
    _admin_user(request)
    try:
        design, problems = ship_designs.save_design(await request.json())
    except ship_designs.ShipDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc
    return {
        "ok": True,
        "design": design,
        "problems": problems,
        "points": points_breakdown(ship_designs.with_active_config(design)),
    }


@ship_designer_admin_router.delete("/{design_id}")
def delete_ship_design(design_id: str, request: Request) -> dict:
    _admin_user(request)
    try:
        removed = ship_designs.delete_design(design_id)
    except ship_designs.ShipDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="No ship design with that id.")
    return {"ok": True}


@ship_designer_admin_router.get("/{design_id}/export")
def export_ship_design(design_id: str, request: Request) -> Response:
    _admin_user(request)
    design = _design_or_404(design_id, None)
    return Response(
        content=json.dumps(design, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="starshot-ship-{design["id"]}.json"'},
    )


# --------------------------------------------------------------------------
# Admin/mod: browse player designs, clone them into the shared library,
# and remove problem content
# --------------------------------------------------------------------------


PLAYER_LIBRARY_PAGE_SIZE = 20


@player_ship_library_admin_router.get("")
def list_player_ship_designs(request: Request, search: str = "", page: int = 1) -> dict:
    """Every player-owned ship design, searchable by ship or owner name and
    paged (the library can span hundreds of designs across every captain)."""
    _admin_user(request)
    from starshot.v2.store import get_v2_store

    store = get_v2_store()
    entries = []
    for owner_id in ship_designs.list_player_owner_ids():
        owner = store.get_user(owner_id)
        owner_name = owner["username"] if owner else f"user #{owner_id}"
        for entry in ship_designs.list_designs(owner_id):
            entries.append({**entry, "owner_id": owner_id, "owner_name": owner_name})

    query = search.strip().lower()
    if query:
        entries = [
            entry
            for entry in entries
            if query in entry["name"].lower() or query in entry["owner_name"].lower()
        ]

    total = len(entries)
    page_size = PLAYER_LIBRARY_PAGE_SIZE
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, page), total_pages)
    start = (page - 1) * page_size
    return {
        "designs": entries[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


class BulkDeleteItem(BaseModel):
    owner_id: int
    design_id: str = Field(max_length=140)


class BulkDeletePlayerDesignsRequest(BaseModel):
    items: list[BulkDeleteItem] = Field(min_length=1, max_length=500)


@player_ship_library_admin_router.post("/bulk-delete")
def bulk_delete_player_ship_designs(body: BulkDeletePlayerDesignsRequest, request: Request) -> dict:
    """Remove many player designs at once (moderation / library cleanup)."""
    _admin_user(request)
    deleted = 0
    for item in body.items:
        try:
            if ship_designs.delete_design(item.design_id, item.owner_id):
                deleted += 1
        except ship_designs.ShipDesignError:
            continue
    return {"ok": True, "deleted": deleted}


@player_ship_library_admin_router.get("/{owner_id}/{design_id}")
def get_player_ship_design(owner_id: int, design_id: str, request: Request) -> dict:
    _admin_user(request)
    return _design_payload(_design_or_404(design_id, owner_id))


@player_ship_library_admin_router.post("/{owner_id}/{design_id}/clone")
def clone_player_ship_design(owner_id: int, design_id: str, request: Request) -> dict:
    """Copy a player's design into the global library so everyone can fly it."""
    _admin_user(request)
    try:
        design, problems = ship_designs.clone_design_to_global(owner_id, design_id)
    except ship_designs.ShipDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "design": design, "problems": problems}


@player_ship_library_admin_router.delete("/{owner_id}/{design_id}")
def delete_player_ship_design(owner_id: int, design_id: str, request: Request) -> dict:
    """Remove a player's design (moderation)."""
    _admin_user(request)
    try:
        removed = ship_designs.delete_design(design_id, owner_id)
    except ship_designs.ShipDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="No ship design with that id.")
    return {"ok": True}
