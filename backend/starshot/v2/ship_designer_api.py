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

from starshot.rules.player_ships import (
    MAX_DRAW,
    MAX_SHIELDS,
    MAX_SIGNAL_JAMMERS,
    MAX_TARGETING_SENSORS,
    MIN_DRAW,
    MIN_SHIELDS,
    PLAYER_SHIP_MAX_TILES,
    PLAYER_SHIP_POINT_BUDGET,
    compile_layout_spec,
    points_breakdown,
)
from starshot.v2 import ship_designs
from starshot.v2.admin import _admin_user

ship_designer_admin_router = APIRouter(prefix="/api/v2/admin/ship-designs", tags=["v2-admin"])
player_ship_library_admin_router = APIRouter(prefix="/api/v2/admin/player-ship-designs", tags=["v2-admin"])
ship_designs_public_router = APIRouter(prefix="/api/v2/ship-designs", tags=["v2"])
my_ship_designs_router = APIRouter(prefix="/api/v2/my/ship-designs", tags=["v2"])


def _designer_meta() -> dict:
    return {
        "grid_radius": ship_designs.GRID_RADIUS,
        "tile_types": list(ship_designs.TILE_TYPES),
        "point_budget": PLAYER_SHIP_POINT_BUDGET,
        "max_tiles": PLAYER_SHIP_MAX_TILES,
        "min_shields": MIN_SHIELDS,
        "max_shields": MAX_SHIELDS,
        "min_draw": MIN_DRAW,
        "max_draw": MAX_DRAW,
        "max_signal_jammers": MAX_SIGNAL_JAMMERS,
        "max_targeting_sensors": MAX_TARGETING_SENSORS,
        "player_design_limit": ship_designs.PLAYER_DESIGN_LIMIT,
    }


def _current_user(request: Request) -> dict:
    from starshot.v2.router import _current_user as current_user

    return current_user(request)


def _design_or_404(design_id: str, owner_id: int | None) -> dict:
    try:
        design = ship_designs.load_design(design_id, owner_id)
    except ship_designs.ShipDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if design is None:
        raise HTTPException(status_code=404, detail="No ship design with that id.")
    return design


def _design_payload(design: dict) -> dict:
    return {
        "design": design,
        "problems": ship_designs.validate_design(design),
        "points": points_breakdown(design),
        "preview": compile_layout_spec(design),
    }


# --------------------------------------------------------------------------
# Signed-in players: playable ships for the lobby pickers
# --------------------------------------------------------------------------


@ship_designs_public_router.get("")
def list_playable_ship_designs(request: Request) -> dict:
    """Ships this user may fly: battle-ready global designs, plus their own
    battle-ready designs (ids prefixed `user:<uid>:`). The standard base
    ship is always available and is represented by an empty design id."""
    user = _current_user(request)
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
    return {"designs": ship_designs.list_designs(user["id"]), "meta": _designer_meta()}


@my_ship_designs_router.get("/{design_id}")
def get_my_ship_design(design_id: str, request: Request) -> dict:
    user = _current_user(request)
    return _design_payload(_design_or_404(design_id, user["id"]))


@my_ship_designs_router.put("")
async def put_my_ship_design(request: Request) -> dict:
    user = _current_user(request)
    try:
        design, problems = ship_designs.save_design(await request.json(), user["id"])
    except ship_designs.ShipDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc
    return {"ok": True, "design": design, "problems": problems, "points": points_breakdown(design)}


@my_ship_designs_router.delete("/{design_id}")
def delete_my_ship_design(design_id: str, request: Request) -> dict:
    user = _current_user(request)
    try:
        removed = ship_designs.delete_design(design_id, user["id"])
    except ship_designs.ShipDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="No ship design with that id.")
    return {"ok": True}


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
    return {"ok": True, "design": design, "problems": problems, "points": points_breakdown(design)}


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


@player_ship_library_admin_router.get("")
def list_player_ship_designs(request: Request) -> dict:
    _admin_user(request)
    from starshot.v2.store import get_v2_store

    store = get_v2_store()
    entries = []
    for owner_id in ship_designs.list_player_owner_ids():
        owner = store.get_user(owner_id)
        owner_name = owner["username"] if owner else f"user #{owner_id}"
        for entry in ship_designs.list_designs(owner_id):
            entries.append({**entry, "owner_id": owner_id, "owner_name": owner_name})
    return {"designs": entries}


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
