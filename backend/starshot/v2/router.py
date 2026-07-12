"""HTTP API for StarShot v2: accounts, lobby, matchmaking, and secure play."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from starshot.rules import RulesError
from starshot.v2 import security
from starshot.v2.ai import AI_TYPES
from starshot.v2.service import (
    advance_game,
    ai_display_name,
    build_match_meta,
    forfeit_player,
    match_turn_info,
    refresh_game,
    seat_for_user,
    serialized_state,
    start_match_game,
    submit_player_orders,
)
from starshot.v2.store import get_v2_store
from starshot.v2.views import game_view

router = APIRouter(prefix="/api/v2", tags=["v2"])

SESSION_COOKIE = "starshot_v2_session"
SESSION_MAX_AGE = 30 * 24 * 3600


# --------------------------------------------------------------------------
# Auth plumbing
# --------------------------------------------------------------------------


def _current_user(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not signed in.")
    user = get_v2_store().get_session_user(security.session_token_hash(token))
    if user is None:
        raise HTTPException(status_code=401, detail="Session expired. Sign in again.")
    return user


def _set_session(response: Response, user_id: int) -> None:
    token = security.new_session_token()
    get_v2_store().create_session(security.session_token_hash(token), user_id)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _check_maintenance(user: dict) -> None:
    """Block game-affecting actions while the site is under construction
    (admins keep full access to test their changes)."""
    from starshot.v2.admin import admin_usernames
    from starshot.v2.settings import maintenance_message

    message = maintenance_message()
    if message and user["username"].lower() not in admin_usernames():
        raise HTTPException(status_code=503, detail=f"⚓ Under construction: {message}")


def _public_profile(user: dict) -> dict:
    return {
        "username": user["username"],
        "wins": user["wins"],
        "losses": user["losses"],
        "draws": user["draws"],
        "games_played": user["games_played"],
        "created_at": user["created_at"],
    }


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=20)
    password: str = Field(min_length=security.MIN_PASSWORD_LENGTH, max_length=128)


@router.post("/auth/register")
def register(credentials: Credentials, response: Response) -> dict:
    if not security.valid_username(credentials.username):
        raise HTTPException(
            status_code=400,
            detail="Usernames are 3-20 characters: letters, digits, _ or -.",
        )
    store = get_v2_store()
    try:
        user = store.create_user(credentials.username, security.hash_password(credentials.password))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="That pirate name is already taken.")
    _set_session(response, user["id"])
    return {"user": _public_profile(store.get_user(user["id"]))}


@router.post("/auth/login")
def login(credentials: Credentials, response: Response) -> dict:
    store = get_v2_store()
    user = store.get_user_by_name(credentials.username)
    if user is None or not security.verify_password(credentials.password, user["pass_hash"]):
        raise HTTPException(status_code=401, detail="Wrong name or password, matey.")
    _set_session(response, user["id"])
    return {"user": _public_profile(user)}


@router.post("/auth/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        get_v2_store().delete_session(security.session_token_hash(token))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    from starshot.v2.admin import admin_usernames

    user = _current_user(request)
    store = get_v2_store()
    matches = [build_match_meta(match, None) for match in store.matches_for_user(user["id"])]
    return {
        "user": _public_profile(user),
        "matches": matches,
        "is_admin": user["username"].lower() in admin_usernames(),
    }


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=security.MIN_PASSWORD_LENGTH, max_length=128)


@router.post("/auth/password")
def change_password(body: PasswordChange, request: Request) -> dict:
    user = _current_user(request)
    if not security.verify_password(body.current_password, user["pass_hash"]):
        raise HTTPException(status_code=401, detail="Current password is wrong.")
    get_v2_store().update_password(user["id"], security.hash_password(body.new_password))
    return {"ok": True}


@router.get("/players/{username}")
def player_profile(username: str) -> dict:
    user = get_v2_store().get_user_by_name(username)
    if user is None:
        raise HTTPException(status_code=404, detail="No such pirate.")
    return {"user": _public_profile(user)}


@router.get("/leaderboard")
def leaderboard() -> dict:
    return {"leaderboard": get_v2_store().leaderboard()}


# --------------------------------------------------------------------------
# Lobby & matchmaking
# --------------------------------------------------------------------------


@router.get("/lobby")
def lobby(request: Request) -> dict:
    user = _current_user(request)
    store = get_v2_store()
    store.touch_presence(user["id"])
    my_matches = []
    for match in store.matches_for_user(user["id"]):
        meta = build_match_meta(match, None)
        seat = seat_for_user(match, user["id"])
        if match["status"] in ("active", "complete") and seat:
            meta["turn"] = match_turn_info(store, match, seat["player_id"])
        my_matches.append(meta)
    from starshot.v2.settings import maintenance_message

    return {
        "queue": store.queue_status(user["id"]),
        "open_matches": [build_match_meta(match, None) for match in store.open_matches()],
        "my_matches": my_matches,
        "ai_types": AI_TYPES,
        "active_players": [
            player for player in store.active_players() if player["id"] != user["id"]
        ],
        "challenges": store.challenges_for_user(user["id"]),
        "maintenance": maintenance_message(),
    }


class ChallengeRequest(BaseModel):
    username: str = Field(min_length=3, max_length=20)


@router.post("/lobby/challenge")
def send_challenge(body: ChallengeRequest, request: Request) -> dict:
    user = _current_user(request)
    _check_maintenance(user)
    store = get_v2_store()
    target = store.get_user_by_name(body.username)
    if target is None:
        raise HTTPException(status_code=404, detail="No such captain.")
    if target["id"] == user["id"]:
        raise HTTPException(status_code=400, detail="Duelling yerself is a court-martial offense.")
    challenge_id = store.create_challenge(user["id"], target["id"])
    return {"challenge_id": challenge_id}


class ChallengeResponse(BaseModel):
    accept: bool


@router.post("/lobby/challenge/{challenge_id}/respond")
def respond_challenge(challenge_id: str, body: ChallengeResponse, request: Request) -> dict:
    user = _current_user(request)
    store = get_v2_store()
    challenge = store.get_challenge(challenge_id)
    if challenge is None or challenge["to_user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Challenge not found.")
    if challenge["status"] != "pending":
        raise HTTPException(status_code=400, detail="Challenge already settled.")
    if not body.accept:
        store.set_challenge_status(challenge_id, "declined")
        return {"accepted": False}
    _check_maintenance(user)
    challenger = store.get_user(challenge["from_user_id"])
    store.leave_queue(user["id"])
    store.leave_queue(challenger["id"])
    match_id = store.create_match(
        name=f"{challenger['username']} vs {user['username']} (duel)",
        host_user_id=challenger["id"],
        seats=2,
        status="open",
    )
    store.add_seat(match_id, 0, challenger["username"], challenger["username"], user_id=challenger["id"])
    store.add_seat(match_id, 1, user["username"], user["username"], user_id=user["id"])
    game_id = start_match_game(store, store.get_match(match_id))
    store.set_challenge_status(challenge_id, "accepted", game_id=game_id)
    return {"accepted": True, "match_id": match_id, "game_id": game_id}


@router.post("/lobby/challenge/{challenge_id}/cancel")
def cancel_challenge(challenge_id: str, request: Request) -> dict:
    user = _current_user(request)
    store = get_v2_store()
    challenge = store.get_challenge(challenge_id)
    if challenge is None or user["id"] not in (challenge["from_user_id"], challenge["to_user_id"]):
        raise HTTPException(status_code=404, detail="Challenge not found.")
    store.set_challenge_status(challenge_id, "cancelled")
    return {"ok": True}


class QueueRequest(BaseModel):
    action: str = Field(pattern="^(join|leave)$")


@router.post("/lobby/queue")
def quick_match(body: QueueRequest, request: Request) -> dict:
    user = _current_user(request)
    if body.action == "join":
        _check_maintenance(user)
    store = get_v2_store()
    if body.action == "leave":
        store.leave_queue(user["id"])
        return {"queued": False, "matched": False}
    opponent_id = store.join_queue_and_pair(user["id"])
    if opponent_id is None:
        return {"queued": True, "matched": False}
    opponent = store.get_user(opponent_id)
    match_id = store.create_match(
        name=f"{opponent['username']} vs {user['username']}",
        host_user_id=opponent_id,
        seats=2,
        status="open",
    )
    store.add_seat(match_id, 0, opponent["username"], opponent["username"], user_id=opponent_id)
    store.add_seat(match_id, 1, user["username"], user["username"], user_id=user["id"])
    match = store.get_match(match_id)
    game_id = start_match_game(store, match)
    return {"queued": False, "matched": True, "match_id": match_id, "game_id": game_id}


class CreateMatchRequest(BaseModel):
    name: str = Field(default="", max_length=40)
    ai_types: list[str] = Field(default_factory=list, max_length=3)
    open_seats: int = Field(default=0, ge=0, le=3)


@router.post("/matches")
def create_match(body: CreateMatchRequest, request: Request) -> dict:
    user = _current_user(request)
    _check_maintenance(user)
    for ai_type in body.ai_types:
        if ai_type not in AI_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown AI type: {ai_type}")
    total = 1 + len(body.ai_types) + body.open_seats
    if total < 2 or total > 4:
        raise HTTPException(status_code=400, detail="Matches need 2 to 4 combatants.")
    store = get_v2_store()
    store.leave_queue(user["id"])  # starting your own battle cancels quick-match
    name = body.name.strip() or f"{user['username']}'s raid"
    match_id = store.create_match(name, user["id"], seats=total, status="open")
    store.add_seat(match_id, 0, user["username"], user["username"], user_id=user["id"])
    counts: dict[str, int] = {}
    for index, ai_type in enumerate(body.ai_types):
        counts[ai_type] = counts.get(ai_type, 0) + 1
        store.add_seat(
            match_id,
            index + 1,
            f"ai:{ai_type}:{counts[ai_type]}",
            ai_display_name(ai_type, counts[ai_type]),
            ai_type=ai_type,
        )
    match = store.get_match(match_id)
    game_id = None
    if body.open_seats == 0:
        game_id = start_match_game(store, match)
        match = store.get_match(match_id)
    return {"match": build_match_meta(match, None), "game_id": game_id}


@router.post("/matches/{match_id}/join")
def join_match(match_id: str, request: Request) -> dict:
    user = _current_user(request)
    _check_maintenance(user)
    store = get_v2_store()
    store.leave_queue(user["id"])
    try:
        result = store.try_join_match(match_id, user["id"], user["username"], user["username"])
    except KeyError:
        raise HTTPException(status_code=404, detail="Match not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    match = store.get_match(match_id)
    game_id = None
    if result["full"]:
        game_id = start_match_game(store, match)
        match = store.get_match(match_id)
    return {"match": build_match_meta(match, None), "game_id": game_id}


@router.post("/matches/{match_id}/leave")
def leave_match(match_id: str, request: Request) -> dict:
    user = _current_user(request)
    try:
        get_v2_store().leave_match(match_id, user["id"])
    except KeyError:
        raise HTTPException(status_code=404, detail="Match not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.post("/matches/{match_id}/start")
def start_match(match_id: str, request: Request) -> dict:
    user = _current_user(request)
    _check_maintenance(user)
    store = get_v2_store()
    match = store.get_match(match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found.")
    if match["host_user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only the host can give the launch order.")
    if match["status"] != "open":
        raise HTTPException(status_code=400, detail="Match already started.")
    if len(match["seat_list"]) < 2:
        raise HTTPException(status_code=400, detail="Need at least two combatants.")
    game_id = start_match_game(store, match)
    match = store.get_match(match_id)
    return {"match": build_match_meta(match, None), "game_id": game_id}


@router.post("/matches/{match_id}/abandon")
def abandon_match(match_id: str, request: Request) -> dict:
    """Strike the colors: forfeit an active game (or dismiss an open/finished
    one) and drop it from your battles list."""
    user = _current_user(request)
    store = get_v2_store()
    match = store.get_match(match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found.")
    seat = seat_for_user(match, user["id"])
    if seat is None:
        raise HTTPException(status_code=403, detail="You are not in this match.")
    if match["status"] == "open":
        try:
            store.leave_match(match_id, user["id"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "forfeited": False}
    if match["status"] == "active":
        # Bailing before sealing round-1 orders costs no loss — mark the seat
        # exempt BEFORE the forfeit possibly completes the game and records stats.
        turn = match_turn_info(store, match, seat["player_id"]) or {}
        early = turn.get("phase") == "give_orders" and turn.get("round_number") == 1 and turn.get("your_turn")
        store.mark_seat_abandoned(match_id, user["id"], stats_exempt=bool(early))
        forfeit_player(store, store.get_match(match_id), seat["player_id"])
        return {"ok": True, "forfeited": True, "counted_as_loss": not early}
    store.mark_seat_abandoned(match_id, user["id"])
    return {"ok": True, "forfeited": False}


@router.get("/matches/{match_id}")
def match_detail(match_id: str, request: Request) -> dict:
    _current_user(request)
    match = get_v2_store().get_match(match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found.")
    return {"match": build_match_meta(match, None)}


# --------------------------------------------------------------------------
# Game play
# --------------------------------------------------------------------------


def _match_and_seat(request: Request, game_id: str) -> tuple[dict, dict, dict | None]:
    """Returns (user, match, seat). Seat is None for a spectating host — e.g.
    the admin watching an AI-only battle they launched."""
    user = _current_user(request)
    store = get_v2_store()
    match = store.get_match_by_game(game_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Game not found.")
    seat = seat_for_user(match, user["id"])
    if seat is None:
        human_seats = [s for s in match["seat_list"] if not s["ai_type"]]
        if match["host_user_id"] == user["id"] and not human_seats:
            return user, match, None  # spectator on an AI-only battle
        raise HTTPException(status_code=403, detail="You are not aboard this battle.")
    return user, match, seat


@router.get("/games/{game_id}/view")
def view_game(game_id: str, request: Request, since: int = -1) -> dict:
    _, match, seat = _match_and_seat(request, game_id)
    store = get_v2_store()
    try:
        state_dict = serialized_state(store, game_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Game not found.")
    version = len(state_dict.get("event_log") or [])
    if since >= 0 and version == since and match["status"] != "open":
        return {"unchanged": True, "version": version}
    # Push AI/resolution forward in case the game is waiting only on bots.
    state = refresh_game(store, match)
    state_dict = serialized_state(store, game_id)
    viewer_player_id = seat["player_id"] if seat else None
    view = game_view(state_dict, viewer_player_id)
    return {
        "unchanged": False,
        "version": view["version"],
        "match": build_match_meta(get_v2_store().get_match(match["id"]), state),
        "you": viewer_player_id,
        "state": view,
    }


class OrdersRequest(BaseModel):
    orders: dict


@router.post("/games/{game_id}/orders")
def submit_orders_endpoint(game_id: str, body: OrdersRequest, request: Request) -> dict:
    _, match, seat = _match_and_seat(request, game_id)
    if seat is None:
        raise HTTPException(status_code=403, detail="Spectators don't give orders.")
    _check_maintenance(_)
    store = get_v2_store()
    try:
        state = submit_player_orders(store, match, seat["player_id"], body.orders)
    except KeyError:
        raise HTTPException(status_code=404, detail="Game not found.")
    except (RulesError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    state_dict = serialized_state(store, game_id)
    view = game_view(state_dict, seat["player_id"])
    return {
        "version": view["version"],
        "match": build_match_meta(store.get_match(match["id"]), state),
        "you": seat["player_id"],
        "state": view,
    }
