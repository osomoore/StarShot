from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from starshot.persistence import SQLiteGameStore
from starshot.rules import GameConfig, RulesError, create_initial_state, resolve_next_step, submit_orders
from starshot.rules.serialization import orders_from_dict, state_to_dict
from starshot.rules.ship_simulation import simulate_ship_kills

app = FastAPI(title="StarShot")
ROOT = Path(__file__).resolve().parents[3]
FRONTEND_DIR = ROOT / "frontend" / "debug"
RESOURCES_DIR = ROOT / "resources"
DEFAULT_DB_PATH = ROOT / ".starshot" / "games.sqlite3"

if (FRONTEND_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")

if RESOURCES_DIR.exists():
    app.mount("/resources", StaticFiles(directory=RESOURCES_DIR), name="resources")


class CreateGameRequest(BaseModel):
    player_ids: list[str] = Field(min_length=2, max_length=4)
    seed: int | None = None
    debug_start_with_attack_desperation_card: bool = False


class SubmitOrdersRequest(BaseModel):
    player_id: str
    orders: dict


def get_store() -> SQLiteGameStore:
    return SQLiteGameStore(Path(os.environ.get("STARSHOT_DB", DEFAULT_DB_PATH)))


@app.get("/")
def index() -> FileResponse:
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Debug UI not found.")
    return FileResponse(index_path)


@app.get("/ship-sim")
def ship_simulator() -> FileResponse:
    index_path = FRONTEND_DIR / "ship-sim.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Ship simulator UI not found.")
    return FileResponse(index_path)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/simulations/ship-kill")
def run_ship_kill_simulation(
    runs: int = 1000,
    seed: int | None = 1,
    damage_per_volley: int = 1,
    initial_shields: int = 0,
    defense_threshold: int = 7,
    aim_bonus: int = 0,
    attack_dice_count: int = 2,
    attack_die_sides: int = 12,
    double_max_auto_hit: bool = False,
    max_steps: int = 500,
) -> dict:
    try:
        return simulate_ship_kills(
            runs=runs,
            seed=seed,
            damage_per_volley=damage_per_volley,
            initial_shields=initial_shields,
            defense_threshold=defense_threshold,
            aim_bonus=aim_bonus,
            attack_dice_count=attack_dice_count,
            attack_die_sides=attack_die_sides,
            double_max_auto_hit=double_max_auto_hit,
            max_steps=max_steps,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/games")
def list_games() -> dict:
    return {"games": get_store().list_games()}


@app.post("/api/games")
def create_game(request: CreateGameRequest) -> dict:
    try:
        state = create_initial_state(
            GameConfig(
                player_ids=tuple(request.player_ids),
                seed=request.seed,
                debug_start_with_attack_desperation_card=request.debug_start_with_attack_desperation_card,
            )
        )
        game_id = get_store().create_game(state)
        return {"game_id": game_id, "state": state_to_dict(state, reveal_orders=False)}
    except RulesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/games/{game_id}")
def get_game(game_id: str, reveal_orders: bool = False) -> dict:
    try:
        state = get_store().load_game(game_id)
        return {"game_id": game_id, "state": state_to_dict(state, reveal_orders=reveal_orders)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/games/{game_id}/orders")
def submit_game_orders(game_id: str, request: SubmitOrdersRequest) -> dict:
    try:
        store = get_store()
        state = store.load_game(game_id)
        next_state = submit_orders(state, request.player_id, orders_from_dict(request.orders))
        store.save_game(game_id, next_state)
        return {"game_id": game_id, "state": state_to_dict(next_state, reveal_orders=False)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RulesError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/games/{game_id}/resolve")
def resolve_game(game_id: str) -> dict:
    try:
        store = get_store()
        state = store.load_game(game_id)
        next_state = resolve_next_step(state)
        store.save_game(game_id, next_state)
        return {"game_id": game_id, "state": state_to_dict(next_state, reveal_orders=False)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RulesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
