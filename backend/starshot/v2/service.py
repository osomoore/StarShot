"""Match/game orchestration for StarShot v2.

All engine calls run under the core_0_3 deck-set override. The server drives
AI order submission and resolves entire rounds automatically the moment the
last human's orders arrive; clients replay the appended events at their own
pace.
"""

from __future__ import annotations

import os
from pathlib import Path

from starshot.rules import RulesError, create_initial_state, resolve_next_step, submit_orders
from starshot.rules.engine import is_game_over
from starshot.rules.deck_data import deck_set_override
from starshot.rules.models import GameConfig, GamePhase, GameState
from starshot.rules.serialization import orders_from_dict, state_from_dict, state_to_dict

from starshot.v2.ai import AI_DISPLAY_NAMES, AI_TYPES, build_ai_orders, fallback_orders
from starshot.v2.store import V2Store

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_V2_DECK_PATH = ROOT / "resources" / "decks" / "core_0_3"
DECKS_ROOT = ROOT / "resources" / "decks"


def custom_decks_root() -> Path:
    return Path(os.environ.get("STARSHOT_CUSTOM_DECKS", DECKS_ROOT / "custom"))


class _CustomDecksProxy:
    def __fspath__(self) -> str:
        return str(custom_decks_root())

    def __str__(self) -> str:
        return str(custom_decks_root())

    def __truediv__(self, other):
        return custom_decks_root() / other

    @property
    def parent(self):
        return custom_decks_root().parent

    def mkdir(self, **kwargs):
        return custom_decks_root().mkdir(**kwargs)

    def is_dir(self):
        return custom_decks_root().is_dir()

    def iterdir(self):
        return custom_decks_root().iterdir()


CUSTOM_DECKS_ROOT = _CustomDecksProxy()


def core_deck_path() -> Path:
    """Deck set for NEW v2 games: admin-selected setting, else env, else core_0_3."""
    from starshot.v2.settings import active_deck_setting

    configured = active_deck_setting()
    if configured and Path(configured).is_dir():
        return Path(configured)
    return Path(os.environ.get("STARSHOT_V2_DECK_SET", DEFAULT_V2_DECK_PATH))


def _manifest_id(path: Path) -> str | None:
    import tomllib

    try:
        return tomllib.loads((path / "manifest.toml").read_text()).get("id")
    except (OSError, ValueError):
        return None


def scan_deck_sets() -> list[dict]:
    """All installed deck sets (stock + custom saves)."""
    import tomllib

    sets: list[dict] = []
    custom_root = custom_decks_root()
    for root, is_custom in ((DECKS_ROOT, False), (custom_root, True)):
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            manifest = child / "manifest.toml"
            if not (child.is_dir() and manifest.exists()):
                continue
            try:
                data = tomllib.loads(manifest.read_text())
            except (OSError, ValueError):
                continue
            if data.get("id"):
                sets.append({
                    "id": data["id"],
                    "name": data.get("name", data["id"]),
                    "rules_version": data.get("rules_version", ""),
                    "path": str(child.resolve()),
                    "custom": is_custom,
                })
    return sets


def deck_path_for_game(raw_state: dict) -> Path:
    """Games are bound to the deck set they were created with, so switching
    the active set never breaks battles already in flight."""
    wanted = raw_state.get("deck_set_id")
    active = core_deck_path()
    if not wanted or _manifest_id(active) == wanted:
        return active
    for deck_set in scan_deck_sets():
        if deck_set["id"] == wanted:
            return Path(deck_set["path"])
    return active


# Backwards-compatible alias used as `with deck_set_override(CORE_0_3_PATH)`.
class _DeckPathProxy:
    def __fspath__(self) -> str:
        return str(core_deck_path())

    def __str__(self) -> str:
        return str(core_deck_path())

    def __truediv__(self, other):
        return core_deck_path() / other


CORE_0_3_PATH = _DeckPathProxy()

MAX_ADVANCE_STEPS = 400


def _load_state(store: V2Store, game_id: str) -> tuple[GameState, Path]:
    raw = store.load_game(game_id)
    deck_path = deck_path_for_game(raw)
    with deck_set_override(deck_path):
        return state_from_dict(raw), deck_path


def _save_state(store: V2Store, game_id: str, state: GameState, deck_path: Path) -> None:
    with deck_set_override(deck_path):
        store.save_game(game_id, state_to_dict(state, reveal_orders=True))


def serialized_state(store: V2Store, game_id: str) -> dict:
    raw = store.load_game(game_id)
    with deck_set_override(deck_path_for_game(raw)):
        return state_to_dict(state_from_dict(raw), reveal_orders=True)


def ai_seats(match: dict) -> list[dict]:
    return [seat for seat in match["seat_list"] if seat["ai_type"]]


def human_seats(match: dict) -> list[dict]:
    return [seat for seat in match["seat_list"] if not seat["ai_type"]]


def seat_for_user(match: dict, user_id: int) -> dict | None:
    for seat in match["seat_list"]:
        if seat["user_id"] == user_id:
            return seat
    return None


def _submit_ai_orders(state: GameState, seat: dict) -> GameState:
    orders = build_ai_orders(state, seat["player_id"], seat["ai_type"])
    try:
        return submit_orders(state, seat["player_id"], orders)
    except RulesError:
        return submit_orders(state, seat["player_id"], fallback_orders())


def advance_game(state: GameState, match: dict, deck_path: Path | None = None) -> GameState:
    """Push the game forward as far as it can go without human input:
    AI players submit orders, and any fully-ordered phase chain resolves."""
    with deck_set_override(deck_path or core_deck_path()):
        for _ in range(MAX_ADVANCE_STEPS):
            if state.phase == GamePhase.COMPLETE:
                break
            if state.phase == GamePhase.GIVE_ORDERS:
                # One (or zero) captains left while everyone else waits for
                # orders? The battle is decided right now — don't make the
                # survivor play out an empty round. (Mid-round eliminations
                # still resolve the full round, per the rules.)
                result = is_game_over(state)
                if result is not None and state.result is None:
                    state.result = result
                    state.phase = GamePhase.COMPLETE
                    state.event_log.append({"type": "phase_changed", "phase": state.phase})
                    break
                # The engine only flips give_orders -> action_1 inside
                # submit_orders. If the last holdout was eliminated (forfeit)
                # after everyone else submitted, flip it here the same way.
                if all(
                    player.prepared_orders is not None or player.eliminated
                    for player in state.players.values()
                ):
                    state.phase = GamePhase.ACTION_1
                    state.event_log.append({"type": "phase_changed", "phase": state.phase})
                    continue
                # Destroyed ships can't act, but the engine still expects an
                # order set from every non-eliminated player before it will
                # advance; file empty orders on their behalf.
                dead_pending = [
                    player
                    for player in state.players.values()
                    if not player.eliminated and player.ship.destroyed and player.prepared_orders is None
                ]
                for player in dead_pending:
                    state = submit_orders(state, player.id, fallback_orders())
                if dead_pending:
                    continue
                pending_ai = [
                    seat
                    for seat in ai_seats(match)
                    if (player := state.players.get(seat["player_id"])) is not None
                    and not player.eliminated
                    and not player.ship.destroyed
                    and player.prepared_orders is None
                ]
                if not pending_ai:
                    break  # waiting on humans (or the engine already advanced)
                for seat in pending_ai:
                    state = _submit_ai_orders(state, seat)
                continue
            state = resolve_next_step(state)
    return state


def start_match_game(store: V2Store, match: dict) -> str:
    player_ids = tuple(seat["player_id"] for seat in match["seat_list"])
    deck_path = core_deck_path()
    with deck_set_override(deck_path):
        state = create_initial_state(GameConfig(player_ids=player_ids))
    state = advance_game(state, match, deck_path)
    with deck_set_override(deck_path):
        game_id = store.create_game(state_to_dict(state, reveal_orders=True))
    store.set_match_started(match["id"], game_id)
    _record_completion(store, {**match, "game_id": game_id, "status": "active"}, state)
    return game_id


def submit_player_orders(store: V2Store, match: dict, player_id: str, orders_payload: dict) -> GameState:
    state, deck_path = _load_state(store, match["game_id"])
    with deck_set_override(deck_path):
        orders = orders_from_dict(orders_payload)
        state = submit_orders(state, player_id, orders)
    state = advance_game(state, match, deck_path)
    _save_state(store, match["game_id"], state, deck_path)
    _record_completion(store, match, state)
    return state


def refresh_game(store: V2Store, match: dict) -> GameState:
    """Give AIs a chance to act (e.g. first round) and persist any progress."""
    state, deck_path = _load_state(store, match["game_id"])
    before = len(state.event_log)
    state = advance_game(state, match, deck_path)
    if len(state.event_log) != before:
        _save_state(store, match["game_id"], state, deck_path)
        _record_completion(store, match, state)
    return state


def _record_completion(store: V2Store, match: dict, state: GameState) -> None:
    if state.phase != GamePhase.COMPLETE or state.result is None:
        return
    store.set_match_status(match["id"], "complete")
    if not store.mark_stats_recorded(match["id"]):
        return
    winner_ids = set(state.result.winner_ids)
    is_tie = state.result.is_tie
    for seat in human_seats(match):
        if seat["user_id"] is None or seat.get("stats_exempt"):
            continue
        if is_tie and seat["player_id"] in winner_ids:
            outcome = "draw"
        elif seat["player_id"] in winner_ids:
            outcome = "win"
        else:
            outcome = "loss"
        store.record_result(seat["user_id"], outcome)


def match_turn_info(store: V2Store, match: dict, player_id: str | None) -> dict | None:
    """Cheap 'is it my turn' summary straight from the stored state JSON."""
    if not match.get("game_id"):
        return None
    try:
        raw = store.load_game(match["game_id"])
    except KeyError:
        return None
    players = raw.get("players") or {}
    player = players.get(player_id or "", {})
    dead = bool(player.get("eliminated") or (player.get("ship") or {}).get("destroyed"))
    your_turn = (
        raw.get("phase") == "give_orders"
        and player_id is not None
        and not dead
        and not player.get("has_submitted_orders", False)
    )
    # Eliminated with an intact ship = struck their colors (forfeited).
    forfeited = [
        pid
        for pid, p in players.items()
        if p.get("eliminated") and not (p.get("ship") or {}).get("destroyed")
    ]
    return {
        "phase": raw.get("phase"),
        "round_number": raw.get("round_number"),
        "your_turn": your_turn,
        "you_dead": dead,
        "forfeited": forfeited,
    }


def forfeit_player(store: V2Store, match: dict, player_id: str) -> bool:
    """Strike the colors: eliminate the player so the battle sails on without
    them. Returns True when this was an EARLY abandon (round 1, before the
    player ever sealed orders) — which shouldn't cost them a loss."""
    state, deck_path = _load_state(store, match["game_id"])
    player = state.players.get(player_id)
    if player is None or state.phase == GamePhase.COMPLETE:
        return False
    early = (
        state.round_number == 1
        and state.phase == GamePhase.GIVE_ORDERS
        and player.prepared_orders is None
    )
    player.eliminated = True
    state.event_log.append(
        {"type": "player_forfeited", "round": state.round_number, "player_id": player_id}
    )
    state = advance_game(state, match, deck_path)
    _save_state(store, match["game_id"], state, deck_path)
    _record_completion(store, match, state)
    return early


def run_ai_battle(store: V2Store, host_user: dict, ai_types: list[str]) -> dict:
    """Create and fully resolve an AI-only game in one call (admin tool)."""
    counts: dict[str, int] = {}
    match_id = store.create_match(
        name="AI Battle: " + " vs ".join(AI_TYPES.get(t, t) for t in ai_types),
        host_user_id=host_user["id"],
        seats=len(ai_types),
        status="open",
    )
    for index, ai_type in enumerate(ai_types):
        counts[ai_type] = counts.get(ai_type, 0) + 1
        store.add_seat(
            match_id,
            index,
            f"ai:{ai_type}:{counts[ai_type]}",
            ai_display_name(ai_type, counts[ai_type]),
            ai_type=ai_type,
        )
    match = store.get_match(match_id)
    game_id = start_match_game(store, match)  # no humans → resolves to completion
    state, _deck_path = _load_state(store, game_id)
    match = store.get_match(match_id)
    summary = {
        "match_id": match_id,
        "game_id": game_id,
        "complete": state.phase == GamePhase.COMPLETE,
        "rounds_played": state.round_number,
        "winners": list(state.result.winner_ids) if state.result else [],
        "reason": state.result.reason if state.result else None,
        "players": [
            {
                "player_id": seat["player_id"],
                "display_name": seat["display_name"],
                "ai_type": seat["ai_type"],
                "victory_points": state.players[seat["player_id"]].victory_points,
                "destroyed": state.players[seat["player_id"]].ship.destroyed,
            }
            for seat in match["seat_list"]
        ],
    }
    return summary


def build_match_meta(match: dict, state: GameState | None) -> dict:
    seats = []
    for seat in match["seat_list"]:
        seats.append(
            {
                "seat_index": seat["seat_index"],
                "player_id": seat["player_id"],
                "display_name": seat["display_name"],
                "is_ai": bool(seat["ai_type"]),
                "ai_type": seat["ai_type"],
                "ai_label": AI_TYPES.get(seat["ai_type"] or "", None),
            }
        )
    return {
        "id": match["id"],
        "name": match["name"],
        "status": match["status"],
        "seats": match["seats"],
        "game_id": match["game_id"],
        "host_user_id": match["host_user_id"],
        "seat_list": seats,
    }


AI_NAME_POOLS = {
    "bauble_runner": ("Salvage Capt. Morrigan", "Salvage Capt. Vex", "Salvage Capt. Flint"),
    "hunter_killer": ("Corsair Blackvane", "Corsair Ironjaw", "Corsair Grimtide"),
    "blaster": ("Gunner Redbeard", "Gunner Sparks", "Gunner Maddock"),
}


def ai_display_name(ai_type: str, ordinal: int) -> str:
    pool = AI_NAME_POOLS.get(ai_type)
    if not pool:
        return AI_DISPLAY_NAMES.get(ai_type, "Rogue Drone")
    name = pool[(ordinal - 1) % len(pool)]
    # More than three of the same profile can't happen today (max 3 AI seats),
    # but stay unique if that ever changes.
    return name if ordinal <= len(pool) else f"{name} {ordinal}"
