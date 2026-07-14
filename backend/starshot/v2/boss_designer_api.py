"""Admin HTTP surface for the boss ship designer.

Thin wrapper over ``starshot.v2.boss_designs``; all schema and game-design
validation lives there so it can be tested and reused without FastAPI.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from starshot.v2 import boss_designs
from starshot.v2.admin import _admin_user

boss_designer_router = APIRouter(prefix="/api/v2/admin/boss-designs", tags=["v2-admin"])


@boss_designer_router.get("")
def list_boss_designs(request: Request) -> dict:
    _admin_user(request)
    return {
        "designs": boss_designs.list_designs(),
        "meta": {
            "grid_radius": boss_designs.GRID_RADIUS,
            "tile_types": list(boss_designs.TILE_TYPES),
            "action_stacks": list(boss_designs.ACTION_STACKS),
            "lane_rolls": list(boss_designs.LANE_ROLLS),
            "step_kinds": list(boss_designs.STEP_KINDS),
            "trigger_types": list(boss_designs.TRIGGER_TYPES),
        },
    }


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
