"""Admin HTTP surface for the boss ship designer.

Thin wrapper over ``starshot.v2.boss_designs``; all schema and game-design
validation lives there so it can be tested and reused without FastAPI.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request, Response

from starshot.v2 import boss_designs
from starshot.v2.admin import _admin_user

boss_designer_router = APIRouter(prefix="/api/v2/admin/boss-designs", tags=["v2-admin"])

# Admin browsing/cloning of player-made designs (separate prefix so paths
# never collide with the /{design_id} routes above).
player_library_admin_router = APIRouter(prefix="/api/v2/admin/player-boss-designs", tags=["v2-admin"])

# Non-admin surface: lets the lobby offer playable designs as StarBreach foes.
boss_designs_public_router = APIRouter(prefix="/api/v2/boss-designs", tags=["v2"])

# Player-owned boss designer (any signed-in user, capped library).
my_boss_designs_router = APIRouter(prefix="/api/v2/my/boss-designs", tags=["v2"])


def _designer_meta() -> dict:
    return {
        "grid_radius": boss_designs.GRID_RADIUS,
        "tile_types": list(boss_designs.TILE_TYPES),
        "action_stacks": list(boss_designs.ACTION_STACKS),
        "lane_rolls": list(boss_designs.LANE_ROLLS),
        "default_lane_count": boss_designs.DEFAULT_LANE_COUNT,
        "max_lane_count": boss_designs.MAX_LANE_COUNT,
        "step_kinds": list(boss_designs.STEP_KINDS),
        "trigger_types": list(boss_designs.TRIGGER_TYPES),
        "spawn_locations": list(boss_designs.SPAWN_LOCATIONS),
        "spawn_max_count": boss_designs.SPAWN_MAX_COUNT,
        "fleet_max_action_count": boss_designs.FLEET_MAX_ACTION_COUNT,
        "player_design_limit": boss_designs.PLAYER_DESIGN_LIMIT,
    }


@boss_designs_public_router.get("")
def list_playable_boss_designs(request: Request) -> dict:
    """Bosses this user may fight: the shared library, plus their own designs
    (playable only by their creator, ids prefixed `user:<uid>:`)."""
    from starshot.v2.router import _current_user
    from starshot.v2.settings import allowed_starbreach_boss_design_ids, default_starbreach_boss_design_id

    user = _current_user(request)
    allowed = allowed_starbreach_boss_design_ids()
    designs = [
        {"id": entry["id"], "name": entry["name"]}
        for entry in boss_designs.list_designs()
        if entry["valid"] and (not allowed or entry["id"] in allowed)
    ]
    designs.extend(
        {"id": f"user:{user['id']}:{entry['id']}", "name": f"{entry['name']} (yours)"}
        for entry in boss_designs.list_designs(user["id"])
        if entry["valid"]
    )
    default_id = default_starbreach_boss_design_id()
    if default_id and allowed and default_id not in allowed:
        default_id = ""
    return {"designs": designs, "default_design_id": default_id}


@boss_designer_router.get("")
def list_boss_designs(request: Request) -> dict:
    _admin_user(request)
    return {"designs": boss_designs.list_designs(), "meta": _designer_meta()}


@boss_designer_router.get("/{design_id}")
def get_boss_design(design_id: str, request: Request) -> dict:
    _admin_user(request)
    try:
        design = boss_designs.load_design(design_id)
    except boss_designs.BossDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if design is None:
        raise HTTPException(status_code=404, detail="No boss design with that id.")
    return {"design": design, "problems": boss_designs.validate_design(design)}


@boss_designer_router.put("")
async def put_boss_design(request: Request) -> dict:
    _admin_user(request)
    try:
        design, problems = boss_designs.save_design(await request.json())
    except boss_designs.BossDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc
    return {"ok": True, "design": design, "problems": problems}


@boss_designer_router.get("/{design_id}/export")
def export_boss_design(design_id: str, request: Request) -> Response:
    _admin_user(request)
    try:
        design = boss_designs.load_design(design_id)
    except boss_designs.BossDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if design is None:
        raise HTTPException(status_code=404, detail="No boss design with that id.")
    return Response(
        content=json.dumps(design, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="starshot-boss-{design["id"]}.json"'
        },
    )


@boss_designer_router.post("/import")
async def import_boss_design(request: Request) -> dict:
    """Upload a design JSON file. An id collision gets a numeric suffix so an
    upload never silently overwrites an existing design."""
    _admin_user(request)
    body = await request.body()
    if len(body) > 2_000_000:
        raise HTTPException(status_code=400, detail="Boss design file is too large.")
    try:
        raw = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Not a valid JSON design file: {exc}") from exc
    try:
        design = boss_designs.normalize_design(raw)
        base_id = design["id"]
        existing = {entry["id"] for entry in boss_designs.list_designs()}
        candidate = base_id
        suffix = 2
        while candidate in existing:
            candidate = f"{base_id}_{suffix}"
            suffix += 1
        design["id"] = candidate
        saved, problems = boss_designs.save_design(design)
    except boss_designs.BossDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "design": saved, "problems": problems, "renamed": saved["id"] != base_id}


@boss_designer_router.delete("/{design_id}")
def delete_boss_design(design_id: str, request: Request) -> dict:
    _admin_user(request)
    try:
        removed = boss_designs.delete_design(design_id)
    except boss_designs.BossDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="No boss design with that id.")
    return {"ok": True}


# --------------------------------------------------------------------------
# Player-owned boss designs (any signed-in user; play against your own)
# --------------------------------------------------------------------------


def _my_user(request: Request) -> dict:
    from starshot.v2.router import _current_user

    return _current_user(request)


@my_boss_designs_router.get("")
def list_my_boss_designs(request: Request) -> dict:
    user = _my_user(request)
    return {"designs": boss_designs.list_designs(user["id"]), "meta": _designer_meta()}


@my_boss_designs_router.get("/{design_id}")
def get_my_boss_design(design_id: str, request: Request) -> dict:
    user = _my_user(request)
    try:
        design = boss_designs.load_design(design_id, user["id"])
    except boss_designs.BossDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if design is None:
        raise HTTPException(status_code=404, detail="No boss design with that id.")
    return {"design": design, "problems": boss_designs.validate_design(design)}


@my_boss_designs_router.put("")
async def put_my_boss_design(request: Request) -> dict:
    user = _my_user(request)
    try:
        design, problems = boss_designs.save_design(await request.json(), user["id"])
    except boss_designs.BossDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc
    return {"ok": True, "design": design, "problems": problems}


@my_boss_designs_router.delete("/{design_id}")
def delete_my_boss_design(design_id: str, request: Request) -> dict:
    user = _my_user(request)
    try:
        removed = boss_designs.delete_design(design_id, user["id"])
    except boss_designs.BossDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="No boss design with that id.")
    return {"ok": True}


# --------------------------------------------------------------------------
# Admin: browse player designs and clone them into the shared library
# --------------------------------------------------------------------------


@player_library_admin_router.get("")
def list_player_boss_designs(request: Request) -> dict:
    _admin_user(request)
    from starshot.v2.store import get_v2_store

    store = get_v2_store()
    entries = []
    for owner_id in boss_designs.list_player_owner_ids():
        owner = store.get_user(owner_id)
        owner_name = owner["username"] if owner else f"user #{owner_id}"
        for entry in boss_designs.list_designs(owner_id):
            entries.append({**entry, "owner_id": owner_id, "owner_name": owner_name})
    return {"designs": entries}


@player_library_admin_router.post("/{owner_id}/{design_id}/clone")
def clone_player_boss_design(owner_id: int, design_id: str, request: Request) -> dict:
    """Copy a player's design into the global library so everyone can fight it."""
    _admin_user(request)
    try:
        design, problems = boss_designs.clone_design_to_global(owner_id, design_id)
    except boss_designs.BossDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "design": design, "problems": problems}
