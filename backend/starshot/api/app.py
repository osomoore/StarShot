from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from starshot.persistence import SQLiteGameStore
from starshot.rules.deck_data import active_catalog
from starshot.rules import GameConfig, GameState, RulesError, create_initial_state, resolve_next_step, submit_orders
from starshot.rules.serialization import orders_from_dict, state_to_dict
from starshot.rules.ship_simulation import simulate_ship_kills
from starshot.v2 import security as v2_security
from starshot.v2.router import router as v2_router

app = FastAPI(title="StarShot")
ROOT = Path(__file__).resolve().parents[3]
V2_FRONTEND_DIR = ROOT / "frontend" / "v2"
RESOURCES_DIR = ROOT / "resources"
DEFAULT_DB_PATH = ROOT / ".starshot" / "games.sqlite3"
SITE_HTPASSWD_PATH = Path(os.environ.get("STARSHOT_SITE_HTPASSWD", ROOT / ".htpasswd"))

# Site-wide HTTP Basic auth (the Apache vhost proxies everything to this app,
# so the password gate has to live here). Default comes from STARSHOT_SITE_AUTH
# in docker-compose; the admin console can toggle it at runtime.
import base64
import logging

from fastapi import Request
from fastapi.responses import Response as PlainResponse

from starshot.v2.settings import site_auth_enabled


device_logger = logging.getLogger("starshot.device")


def site_htpasswd_path() -> Path:
    return Path(os.environ.get("STARSHOT_SITE_HTPASSWD", SITE_HTPASSWD_PATH))


@app.middleware("http")
async def site_basic_auth(request: Request, call_next):
    if not site_auth_enabled():
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8")
            username, _, password = decoded.partition(":")
        except Exception:
            username, password = "", ""
        users = v2_security.load_htpasswd(site_htpasswd_path())
        stored = users.get(username)
        if stored and v2_security.verify_htpasswd_password(password, stored):
            return await call_next(request)
    return PlainResponse(
        content="Authentication required.",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="StarShot"'},
    )


app.include_router(v2_router)

from starshot.v2.admin import admin_router  # noqa: E402

app.include_router(admin_router)

from starshot.v2.boss_designer_api import (  # noqa: E402
    boss_designer_router,
    boss_designs_public_router,
    my_boss_designs_router,
    player_library_admin_router,
)

app.include_router(boss_designer_router)
app.include_router(boss_designs_public_router)
app.include_router(my_boss_designs_router)
app.include_router(player_library_admin_router)

from starshot.v2.ship_designer_api import (  # noqa: E402
    my_ship_designs_router,
    player_ship_library_admin_router,
    ship_designer_admin_router,
    ship_designs_public_router,
)

app.include_router(ship_designer_admin_router)
app.include_router(ship_designs_public_router)
app.include_router(my_ship_designs_router)
app.include_router(player_ship_library_admin_router)

if (V2_FRONTEND_DIR / "static").exists():
    app.mount("/v2/static", StaticFiles(directory=V2_FRONTEND_DIR / "static"), name="v2static")

if RESOURCES_DIR.exists():
    app.mount("/resources", StaticFiles(directory=RESOURCES_DIR), name="resources")


@app.get("/v2")
@app.get("/v2/")
def v2_index() -> FileResponse:
    index_path = V2_FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="v2 frontend not built")
    return FileResponse(index_path, headers={"Cache-Control": "no-store"})


@app.get("/v2/admin")
def v2_admin_page() -> FileResponse:
    page = V2_FRONTEND_DIR / "admin.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="admin page not built")
    return FileResponse(page, headers={"Cache-Control": "no-store"})


@app.get("/v2/about")
def v2_about_page() -> FileResponse:
    page = V2_FRONTEND_DIR / "about.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="about page not built")
    return FileResponse(page, headers={"Cache-Control": "no-store"})


class CreateGameRequest(BaseModel):
    player_ids: list[str] = Field(min_length=2, max_length=4)
    seed: int | None = None
    debug_start_with_attack_desperation_card: bool = False


class SubmitOrdersRequest(BaseModel):
    player_id: str
    orders: dict


class DebugDrawDesperationRequest(BaseModel):
    player_id: str
    card_id: str


class DeviceInfoRequest(BaseModel):
    data_device: str = ""
    detected_phone_layout: bool = False
    user_agent: str = ""


class ClientEventRequest(BaseModel):
    app: str = Field(default="v2", max_length=20)
    event: str = Field(max_length=80)
    game_id: str | None = Field(default=None, max_length=80)
    player_id: str | None = Field(default=None, max_length=120)
    phase: str | None = Field(default=None, max_length=80)
    round_number: int | None = None
    details: dict = Field(default_factory=dict)
    platform: str = ""
    vendor: str = ""
    max_touch_points: int = 0
    device_pixel_ratio: float = 1
    inner_width: float | None = None
    inner_height: float | None = None
    outer_width: float | None = None
    outer_height: float | None = None
    screen_width: float | None = None
    screen_height: float | None = None
    avail_width: float | None = None
    avail_height: float | None = None
    visual_viewport_width: float | None = None
    visual_viewport_height: float | None = None
    orientation_type: str = ""
    pointer_coarse: bool = False
    pointer_fine: bool = False
    any_pointer_coarse: bool = False
    any_pointer_fine: bool = False
    hover_hover: bool = False
    any_hover_hover: bool = False
    max_width_760: bool = False
    max_width_900: bool = False
    max_width_1024: bool = False
    max_width_1180: bool = False
    max_width_1366: bool = False
    max_height_620: bool = False
    reason: str = ""


def get_store() -> SQLiteGameStore:
    return SQLiteGameStore(Path(os.environ.get("STARSHOT_DB", DEFAULT_DB_PATH)))


def _debug_draw_desperation_to_hand(state: GameState, player_id: str, representative_card_id: str) -> str:
    player = state.players.get(player_id)
    if player is None:
        raise RulesError(f"Unknown player: {player_id}")

    catalog = active_catalog()
    representative = catalog.desperation_card_map.get(representative_card_id)
    if representative is None:
        raise RulesError(f"Unknown desperation card: {representative_card_id}")

    draw_index = next(
        (
            index
            for index, card in enumerate(state.desperation_deck.cards)
            if card.name == representative.name
        ),
        None,
    )
    if draw_index is None:
        raise RulesError(f"No {representative.name} cards are available in the Desperation deck.")

    drawn = state.desperation_deck.cards.pop(draw_index)
    if not state.desperation_deck.cards:
        state.desperation_deck.shuffle_marker_on_top = True
    player.hand.append(drawn)
    state.event_log.append(
        {
            "type": "debug_desperation_drawn",
            "round": state.round_number,
            "phase": state.phase.value,
            "player_id": player.id,
            "card_id": drawn.id,
            "card_name": drawn.name,
            "hand_count": len(player.hand),
            "desperation_deck_count": len(state.desperation_deck.cards),
        }
    )
    return drawn.id


@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url="/v2", status_code=307)


@app.get("/api/health")
def health() -> dict[str, str]:
    catalog = active_catalog()
    return {"status": "ok", "deck_set_id": catalog.id, "deck_set_path": str(catalog.path)}


@app.post("/api/debug/device-info")
def debug_device_info(payload: DeviceInfoRequest, request: Request) -> dict[str, bool]:
    client_host = request.client.host if request.client else "unknown"
    device_logger.warning(
        "Device connect %s mode=%s phone=%s inner=%sx%s visual=%sx%s screen=%sx%s dpr=%s "
        "touch=%s pointer(coarse=%s fine=%s anyCoarse=%s anyFine=%s) "
        "widths(760=%s 900=%s 1024=%s 1180=%s 1366=%s) platform=%r ua=%r",
        client_host,
        payload.data_device,
        payload.detected_phone_layout,
        payload.inner_width,
        payload.inner_height,
        payload.visual_viewport_width,
        payload.visual_viewport_height,
        payload.screen_width,
        payload.screen_height,
        payload.device_pixel_ratio,
        payload.max_touch_points,
        payload.pointer_coarse,
        payload.pointer_fine,
        payload.any_pointer_coarse,
        payload.any_pointer_fine,
        payload.max_width_760,
        payload.max_width_900,
        payload.max_width_1024,
        payload.max_width_1180,
        payload.max_width_1366,
        payload.platform,
        payload.user_agent,
    )
    return {"ok": True}


@app.post("/api/debug/client-event")
def debug_client_event(payload: ClientEventRequest, request: Request) -> dict[str, bool]:
    client_host = request.client.host if request.client else "unknown"
    details = dict(payload.details or {})
    for key, value in list(details.items()):
        if isinstance(value, str) and len(value) > 240:
            details[key] = value[:240] + "..."
    if len(details) > 20:
        details = dict(list(details.items())[:20])
    device_logger.warning(
        "Client event %s app=%s event=%s game=%s player=%s phase=%s round=%s details=%r",
        client_host,
        payload.app,
        payload.event,
        payload.game_id,
        payload.player_id,
        payload.phase,
        payload.round_number,
        details,
    )
    return {"ok": True}


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


@app.post("/api/games/{game_id}/debug/desperation-draw")
def debug_draw_desperation_card(game_id: str, request: DebugDrawDesperationRequest) -> dict:
    try:
        store = get_store()
        state = store.load_game(game_id)
        drawn_card_id = _debug_draw_desperation_to_hand(state, request.player_id, request.card_id)
        store.save_game(game_id, state)
        return {"game_id": game_id, "drawn_card_id": drawn_card_id, "state": state_to_dict(state, reveal_orders=False)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RulesError as exc:
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
