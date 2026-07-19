"""Match/game orchestration for StarShot v2.

All engine calls run under the core_0_3 deck-set override. The server drives
AI order submission and resolves entire rounds automatically the moment the
last human's orders arrive; clients replay the appended events at their own
pace.
"""

from __future__ import annotations

import os
import hashlib
import shutil
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from starshot.rules import RulesError, create_initial_state, resolve_next_step, submit_orders
from starshot.rules.engine import is_game_over
from starshot.rules.deck_data import deck_set_override
from starshot.rules.models import GameConfig, GamePhase, GameState
from starshot.rules.serialization import orders_from_dict, state_from_dict, state_to_dict
from starshot.rules.engine import choose_captain
from starshot.rules.star_command import CAPTAINS

from starshot.v2.ai import AI_DISPLAY_NAMES, AI_TYPES, build_ai_orders, fallback_orders
from starshot.v2.store import V2Store

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_V2_DECK_PATH = ROOT / "resources" / "decks" / "core_0_3"
DECKS_ROOT = ROOT / "resources" / "decks"
RUNTIME_DECKS_ROOT = ROOT / ".starshot" / "content" / "decks"
LEGACY_CUSTOM_DECKS_ROOT = DECKS_ROOT / "custom"
SOURCE_DEVELOPER = "developer"
SOURCE_SERVER = "server"


def custom_decks_root() -> Path:
    return Path(os.environ.get("STARSHOT_CUSTOM_DECKS", RUNTIME_DECKS_ROOT / "custom"))


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


def _safe_deck_alias(value: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return slug or "deck_set"


def _deck_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for name in ("manifest.toml", "config.toml", "base_deck.toml", "desperation_deck.toml"):
        file_path = path / name
        if file_path.exists():
            digest.update(name.encode("utf-8"))
            digest.update(file_path.read_bytes())
    return digest.hexdigest()


def _deck_scan_roots() -> tuple[tuple[str, Path], ...]:
    roots = [(SOURCE_DEVELOPER, DECKS_ROOT)]
    if LEGACY_CUSTOM_DECKS_ROOT != custom_decks_root():
        roots.append((SOURCE_DEVELOPER, LEGACY_CUSTOM_DECKS_ROOT))
    roots.append((SOURCE_SERVER, custom_decks_root()))
    return tuple(roots)


def _unique_deck_alias(base_id: str, source: str, used: set[str]) -> str:
    stem = _safe_deck_alias(f"{base_id}_{source}")
    candidate = stem
    suffix = 2
    while candidate in used:
        candidate = _safe_deck_alias(f"{stem}_{suffix}")
        suffix += 1
    used.add(candidate)
    return candidate


def _toml_escape(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _serialize_manifest(data: dict) -> str:
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (int, float)):
            rendered = str(value)
        else:
            rendered = _toml_escape(str(value))
        lines.append(f"{key} = {rendered}")
    return "\n".join(lines) + "\n"


def materialize_runtime_deck_set(deck_set: dict, *, force: bool = False) -> dict:
    """Copy a scanned deck set into runtime storage when its visible id is an
    alias. This makes conflict aliases safe to activate/use because the
    manifest id then matches the id games store."""
    source_id = deck_set.get("source_id") or deck_set["id"]
    if not force and deck_set["id"] == source_id:
        return deck_set
    if force and deck_set.get("source") == SOURCE_SERVER and deck_set["id"] == source_id:
        return deck_set
    source = Path(deck_set["path"])
    target = custom_decks_root() / _safe_deck_alias(deck_set["id"])
    if not target.exists():
        target.mkdir(parents=True, exist_ok=True)
        for filename in ("manifest.toml", "config.toml", "base_deck.toml", "desperation_deck.toml"):
            shutil.copy(source / filename, target / filename)
        keyword_file = source / "custom_keywords.json"
        if keyword_file.exists():
            shutil.copy(keyword_file, target / "custom_keywords.json")
        manifest = tomllib.loads((target / "manifest.toml").read_text(encoding="utf-8"))
        manifest["id"] = deck_set["id"]
        manifest["name"] = deck_set.get("name") or deck_set["id"]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        manifest["uploaded_at"] = manifest.get("uploaded_at") or now
        manifest["modified_at"] = now
        (target / "manifest.toml").write_text(_serialize_manifest(manifest), encoding="utf-8")
    updated = dict(deck_set)
    updated["path"] = str(target.resolve())
    updated["source"] = SOURCE_SERVER
    updated["custom"] = True
    updated["source_id"] = deck_set["id"]
    return updated


def scan_deck_sets() -> list[dict]:
    """All installed deck sets, merging bundled developer and runtime server content."""
    import tomllib

    records_by_id: dict[str, list[dict]] = {}
    for source, root in _deck_scan_roots():
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if root == DECKS_ROOT and child == LEGACY_CUSTOM_DECKS_ROOT:
                continue
            manifest = child / "manifest.toml"
            if not (child.is_dir() and manifest.exists()):
                continue
            try:
                data = tomllib.loads(manifest.read_text())
            except (OSError, ValueError):
                continue
            if data.get("id"):
                try:
                    latest_mtime = max(
                        (child / name).stat().st_mtime
                        for name in ("manifest.toml", "config.toml", "base_deck.toml", "desperation_deck.toml")
                        if (child / name).exists()
                    )
                except ValueError:
                    latest_mtime = manifest.stat().st_mtime
                latest_file_modified_at = datetime.fromtimestamp(latest_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
                modified_at = data.get("modified_at") or data.get("uploaded_at") or latest_file_modified_at
                deck_id = str(data["id"])
                records_by_id.setdefault(deck_id, []).append({
                    "id": data["id"],
                    "source_id": data["id"],
                    "name": data.get("name", data["id"]),
                    "rules_version": data.get("rules_version", ""),
                    "deprecated": bool(data.get("deprecated", False)),
                    "uploaded_at": data.get("uploaded_at"),
                    "modified_at": modified_at,
                    "last_changed_at": modified_at,
                    "path": str(child.resolve()),
                    "custom": source == SOURCE_SERVER or root == LEGACY_CUSTOM_DECKS_ROOT,
                    "source": source,
                    "conflict_of": None,
                    "_hash": _deck_hash(child),
                    "_mtime": latest_mtime,
                })
    sets: list[dict] = []
    used: set[str] = set()
    for deck_id in sorted(records_by_id):
        records = records_by_id[deck_id]
        hashes = {record["_hash"] for record in records}
        if len(hashes) <= 1:
            chosen = sorted(records, key=lambda item: (item["source"] == SOURCE_SERVER, item["_mtime"]))[-1]
            chosen = dict(chosen)
            chosen["id"] = deck_id
            used.add(deck_id)
            sets.append(chosen)
            continue
        ordered = sorted(records, key=lambda item: (item["_mtime"], item["source"] == SOURCE_SERVER), reverse=True)
        newest = dict(ordered[0])
        newest["id"] = deck_id
        used.add(deck_id)
        sets.append(newest)
        for record in ordered[1:]:
            alternate = dict(record)
            alternate["id"] = _unique_deck_alias(deck_id, alternate["source"], used)
            alternate["conflict_of"] = deck_id
            alternate["name"] = f"{alternate['name']} ({alternate['source']})"
            sets.append(alternate)
    for deck_set in sets:
        deck_set.pop("_hash", None)
        deck_set.pop("_mtime", None)
    return sorted(sets, key=lambda item: (bool(item.get("deprecated")), item["id"]))


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


def _submit_ai_orders(state: GameState, seat: dict, ai_level: str = "pirate_king") -> GameState:
    orders = build_ai_orders(state, seat["player_id"], seat["ai_type"], ai_level=ai_level)
    try:
        return submit_orders(state, seat["player_id"], orders)
    except RulesError:
        return submit_orders(state, seat["player_id"], fallback_orders())


# Captains whose powers alter ship movement (Drifter's cleanup drift, Turbo's
# +1 move). The AI planners mirror the engine's plain movement rules and have
# no model of these powers, so AI seats never pick them.
AI_EXCLUDED_CAPTAIN_IDS = frozenset({"danny_davos", "riley_rounder"})


def _choose_ai_captain(state: GameState, seat: dict) -> GameState:
    player = state.players.get(seat["player_id"])
    if player is None or player.captain_id or not player.captain_options:
        return state
    rng = state.rng_seed or 0
    captain_ids = tuple(captain.id for captain in CAPTAINS if captain.id not in AI_EXCLUDED_CAPTAIN_IDS)
    index = (state.rng_step + len(seat["player_id"]) + rng) % len(captain_ids)
    player.captain_options = captain_ids
    return choose_captain(state, player.id, captain_ids[index])


def advance_game(state: GameState, match: dict, deck_path: Path | None = None) -> GameState:
    """Push the game forward as far as it can go without human input:
    AI players submit orders, and any fully-ordered phase chain resolves."""
    with deck_set_override(deck_path or core_deck_path()):
        for _ in range(MAX_ADVANCE_STEPS):
            if state.phase == GamePhase.COMPLETE:
                break
            if state.phase == GamePhase.GIVE_ORDERS:
                pending_captain_ai = [
                    seat
                    for seat in ai_seats(match)
                    if (player := state.players.get(seat["player_id"])) is not None
                    and not player.eliminated
                    and player.captain_options
                    and not player.captain_id
                ]
                if pending_captain_ai:
                    for seat in pending_captain_ai:
                        state = _choose_ai_captain(state, seat)
                    continue
                if any(
                    player.captain_options and not player.captain_id and not player.eliminated
                    for player in state.players.values()
                ):
                    break
                # One (or zero) captains left while everyone else waits for
                # orders? The battle is decided right now — don't make the
                # survivor play out an empty round. (Mid-round eliminations
                # still resolve the full round, per the rules.)
                result = is_game_over(state)
                if (
                    result is not None
                    and state.result is None
                    and result.reason not in {"round_six_victory_points", "star_breach_victory", "star_breach_objective_failed"}
                ):
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
                    state = _submit_ai_orders(state, seat, match.get("ai_level") or "pirate_king")
                continue
            state = resolve_next_step(state)
    return state


def parse_boss_design_ref(design_id: str) -> tuple[int | None, str]:
    """Split a boss design reference into (owner_id, design_id). Global
    library ids have no prefix; player-owned ones look like `user:<uid>:<id>`."""
    if design_id.startswith("user:"):
        parts = design_id.split(":", 2)
        if len(parts) != 3 or not parts[1].isdigit():
            raise ValueError(f"Malformed boss design reference: {design_id}")
        return int(parts[1]), parts[2]
    return None, design_id


def _load_playable_boss_design(design_id: str | None) -> dict | None:
    """Resolve a boss design id chosen at match creation. Only validated
    (problem-free) designs may enter a game."""
    if not design_id:
        return None
    from starshot.v2 import boss_designs

    owner_id, bare_id = parse_boss_design_ref(design_id)
    design = boss_designs.load_design(bare_id, owner_id)
    if design is None:
        raise ValueError(f"Boss design '{design_id}' no longer exists.")
    problems = boss_designs.validate_design(design)
    if problems:
        raise ValueError(
            f"Boss design '{design['name']}' is not battle-ready: {problems[0]}"
        )
    return design


def parse_ship_design_ref(design_id: str) -> tuple[int | None, str]:
    """Split a ship design reference into (owner_id, design_id). Global
    library ids have no prefix; player-owned ones look like `user:<uid>:<id>`."""
    if design_id.startswith("user:"):
        parts = design_id.split(":", 2)
        if len(parts) != 3 or not parts[1].isdigit():
            raise ValueError(f"Malformed ship design reference: {design_id}")
        return int(parts[1]), parts[2]
    return None, design_id


def _load_playable_ship_design(design_id: str | None) -> dict | None:
    """Resolve a ship design id chosen at a match seat. Only battle-ready
    (problem-free) designs may enter a game; empty = the standard base ship."""
    if not design_id:
        return None
    from starshot.v2 import ship_designs

    owner_id, bare_id = parse_ship_design_ref(design_id)
    design = ship_designs.load_design(bare_id, owner_id)
    if design is None:
        raise ValueError(f"Ship design '{design_id}' no longer exists.")
    problems = ship_designs.validate_design(design)
    if problems:
        raise ValueError(
            f"Ship design '{design['name']}' is not battle-ready: {problems[0]}"
        )
    return design


def _player_ship_designs_for_match(match: dict) -> dict | None:
    from starshot.v2 import ship_designs

    designs = {}
    for seat in match["seat_list"]:
        design = _load_playable_ship_design(seat.get("ship_design_id"))
        if design is not None:
            # bake the current admin StarDock config into the compiled spec
            designs[seat["player_id"]] = ship_designs.with_active_config(design)
    return designs or None


def start_match_game(store: V2Store, match: dict, deck_path: Path | None = None, seed: int | None = None) -> str:
    player_ids = tuple(seat["player_id"] for seat in match["seat_list"])
    deck_path = deck_path or core_deck_path()
    active_expansions = tuple(match.get("active_expansions") or ())
    boss_design = (
        _load_playable_boss_design(match.get("star_breach_boss_design_id"))
        if "star_breach" in active_expansions
        else None
    )
    with deck_set_override(deck_path):
        state = create_initial_state(
            GameConfig(
                player_ids=player_ids,
                seed=seed,
                active_expansions=active_expansions,
                star_breach_prey_player_id=match.get("star_breach_prey_player_id"),
                star_breach_role_preferences={
                    seat["player_id"]: seat["star_breach_role"]
                    for seat in match["seat_list"]
                    if seat.get("star_breach_role")
                } or None,
                star_breach_boss_design=boss_design,
                player_ship_designs=_player_ship_designs_for_match(match),
            )
        )
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
    category = leaderboard_category_for_match(match)
    for seat in human_seats(match):
        if seat["user_id"] is None or seat.get("stats_exempt"):
            continue
        # Guests never accrue persistent stats or leaderboard entries.
        seat_user = store.get_user(seat["user_id"])
        if seat_user is None or seat_user.get("is_guest"):
            continue
        if is_tie and seat["player_id"] in winner_ids:
            outcome = "draw"
        elif seat["player_id"] in winner_ids:
            outcome = "win"
        else:
            outcome = "loss"
        score = ai_score_for_match(match) if category == "ai" and outcome == "win" else 0
        player = state.players.get(seat["player_id"])
        store.record_result(
            seat["user_id"],
            outcome,
            category=category,
            score=score,
            ship_loss=bool(player and player.ship.destroyed),
        )


def leaderboard_category_for_match(match: dict) -> str:
    return "humans" if len(human_seats(match)) >= 2 else "ai"


def ai_score_for_match(match: dict) -> int:
    return {"deck_hand": 1, "buccaneer": 2, "pirate_king": 3}.get(match.get("ai_level"), 1)


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


def _deck_set_for_id(deck_set_id: str | None) -> dict:
    active = core_deck_path()
    for deck_set in scan_deck_sets():
        if deck_set_id is None and Path(deck_set["path"]) == active:
            return deck_set
        if deck_set["id"] == deck_set_id:
            if deck_set.get("deprecated"):
                raise ValueError(f"Deck set {deck_set_id!r} is deprecated.")
            return materialize_runtime_deck_set(deck_set)
    if deck_set_id is None:
        fallback_id = _manifest_id(active) or "active"
        return {"id": fallback_id, "name": fallback_id, "path": str(active), "custom": False, "rules_version": ""}
    raise ValueError(f"No deck set with id {deck_set_id!r}.")


def _ai_match_definition(host_user_id: int, ai_types: list[str], name: str) -> dict:
    counts: dict[str, int] = {}
    seats = []
    for index, ai_type in enumerate(ai_types):
        counts[ai_type] = counts.get(ai_type, 0) + 1
        seats.append({
            "match_id": "",
            "seat_index": index,
            "player_id": f"ai:{ai_type}:{counts[ai_type]}",
            "user_id": None,
            "ai_type": ai_type,
            "display_name": ai_display_name(ai_type, counts[ai_type]),
            "abandoned": 0,
            "stats_exempt": 0,
        })
    return {
        "id": "",
        "name": name,
        "status": "open",
        "host_user_id": host_user_id,
        "seats": len(ai_types),
        "ai_level": "pirate_king",
        "active_expansions": [],
        "game_id": None,
        "seat_list": seats,
    }


def _analysis_for_state(state: GameState, match: dict) -> dict:
    by_player = {
        seat["player_id"]: {
            "player_id": seat["player_id"],
            "display_name": seat["display_name"],
            "ai_type": seat["ai_type"],
            "ai_label": AI_TYPES.get(seat["ai_type"], seat["ai_type"]),
            "victory_points": state.players[seat["player_id"]].victory_points,
            "destroyed": state.players[seat["player_id"]].ship.destroyed,
            "damage_dealt": 0,
            "ships_killed": 0,
            "vaults_collected": 0,
            "vault_vp": 0,
            "volleys": 0,
            "hits": 0,
            "shielded_hits": 0,
        }
        for seat in match["seat_list"]
    }
    environmental_damage = 0
    for event in state.event_log:
        if event.get("type") == "volley_resolved":
            stats = by_player.get(event.get("attacker_id"))
            if not stats:
                continue
            stats["volleys"] += 1
            if event.get("hit"):
                stats["hits"] += 1
            if event.get("shielded"):
                stats["shielded_hits"] += 1
            stats["damage_dealt"] += int(event.get("damage_applied") or 0)
            if event.get("target_destroyed"):
                stats["ships_killed"] += 1
        elif event.get("type") == "vault_awarded":
            for award in event.get("awards") or []:
                stats = by_player.get(award.get("player_id"))
                if not stats:
                    continue
                stats["vaults_collected"] += 1
                stats["vault_vp"] += int(award.get("vp_awarded") or 0)
                environmental_damage += int(award.get("damage_applied") or 0)
    players = sorted(by_player.values(), key=lambda player: (-player["victory_points"], player["display_name"]))
    total_volleys = sum(player["volleys"] for player in players)
    total_hits = sum(player["hits"] for player in players)
    return {
        "complete": state.phase == GamePhase.COMPLETE,
        "rounds_played": state.round_number,
        "winners": list(state.result.winner_ids) if state.result else [],
        "winner_names": [
            by_player[player_id]["display_name"]
            for player_id in (state.result.winner_ids if state.result else ())
            if player_id in by_player
        ],
        "reason": state.result.reason if state.result else None,
        "is_tie": state.result.is_tie if state.result else False,
        "players": players,
        "total_damage_dealt": sum(player["damage_dealt"] for player in players),
        "environmental_damage": environmental_damage,
        "ships_killed": sum(player["ships_killed"] for player in players),
        "vaults_collected": sum(player["vaults_collected"] for player in players),
        "total_vp": sum(player["victory_points"] for player in players),
        "volley_count": total_volleys,
        "hit_rate": (total_hits / total_volleys) if total_volleys else 0,
        "event_count": len(state.event_log),
    }


def run_ai_battle(store: V2Store, host_user: dict, ai_types: list[str], deck_set_id: str | None = None) -> dict:
    """Create and fully resolve a replayable AI-only game in one call."""
    deck_set = _deck_set_for_id(deck_set_id)
    deck_path = Path(deck_set["path"])
    name = "AI Battle: " + " vs ".join(AI_TYPES.get(t, t) for t in ai_types)
    match_id = store.create_match(name=name, host_user_id=host_user["id"], seats=len(ai_types), status="open")
    definition = _ai_match_definition(host_user["id"], ai_types, name)
    for seat in definition["seat_list"]:
        store.add_seat(match_id, seat["seat_index"], seat["player_id"], seat["display_name"], ai_type=seat["ai_type"])
    match = store.get_match(match_id)
    game_id = start_match_game(store, match, deck_path=deck_path)
    state, _deck_path = _load_state(store, game_id)
    match = store.get_match(match_id)
    summary = _analysis_for_state(state, match)
    summary.update({"match_id": match_id, "game_id": game_id, "deck_set_id": deck_set["id"], "deck_set_name": deck_set["name"]})
    entry = store.create_ai_battle_run(
        kind="single",
        name=name,
        deck_set_id=deck_set["id"],
        deck_set_name=deck_set["name"],
        ai_types=ai_types,
        run_count=1,
        game_id=game_id,
        summary=summary,
        detail={"match_id": match_id, "game_id": game_id, "summary": summary},
    )
    return {**summary, "history_entry": entry}


def _batch_summary(analyses: list[dict], ai_types: list[str]) -> tuple[dict, dict]:
    run_count = len(analyses)
    totals = {key: 0 for key in ("rounds_played", "total_damage_dealt", "environmental_damage", "ships_killed", "vaults_collected", "total_vp", "volley_count")}
    weighted_hits = 0.0
    reason_counts: dict[str, int] = {}
    rankings: dict[str, dict] = {}
    for analysis in analyses:
        for key in totals:
            totals[key] += analysis[key]
        weighted_hits += analysis["hit_rate"] * analysis["volley_count"]
        reason = analysis.get("reason") or "unknown"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        winners = set(analysis.get("winners") or [])
        for player in analysis["players"]:
            bucket = rankings.setdefault(
                player["ai_type"],
                {
                    "ai_type": player["ai_type"],
                    "ai_label": player["ai_label"],
                    "appearances": 0,
                    "wins": 0,
                    "survivals": 0,
                    "vp_total": 0,
                    "damage_total": 0,
                    "kills_total": 0,
                    "vaults_total": 0,
                },
            )
            bucket["appearances"] += 1
            bucket["wins"] += 1 if player["player_id"] in winners else 0
            bucket["survivals"] += 0 if player["destroyed"] else 1
            bucket["vp_total"] += player["victory_points"]
            bucket["damage_total"] += player["damage_dealt"]
            bucket["kills_total"] += player["ships_killed"]
            bucket["vaults_total"] += player["vaults_collected"]
    ai_rankings = []
    for bucket in rankings.values():
        appearances = bucket["appearances"] or 1
        ai_rankings.append({
            **bucket,
            "average_vp": bucket["vp_total"] / appearances,
            "average_damage": bucket["damage_total"] / appearances,
            "average_kills": bucket["kills_total"] / appearances,
            "average_vaults": bucket["vaults_total"] / appearances,
            "win_rate": bucket["wins"] / appearances,
            "survival_rate": bucket["survivals"] / appearances,
        })
    ai_rankings.sort(key=lambda item: (-item["wins"], -item["average_vp"], item["ai_label"]))
    avg = lambda key: totals[key] / run_count if run_count else 0
    summary = {
        "complete": all(analysis["complete"] for analysis in analyses),
        "run_count": run_count,
        "ai_types": list(ai_types),
        "average_rounds": avg("rounds_played"),
        "average_damage_dealt": avg("total_damage_dealt"),
        "average_environmental_damage": avg("environmental_damage"),
        "average_ships_killed": avg("ships_killed"),
        "average_vaults_collected": avg("vaults_collected"),
        "average_total_vp": avg("total_vp"),
        "average_volleys": avg("volley_count"),
        "hit_rate": (weighted_hits / totals["volley_count"]) if totals["volley_count"] else 0,
        "reason_counts": reason_counts,
        "ai_rankings": ai_rankings,
    }
    detail = {
        "summary": summary,
        "runs": analyses,
        "notes": [
            "Damage is volley damage dealt by ships; Fang/vault damage is tracked separately as environmental damage.",
            "AI rankings aggregate by AI style, so duplicate copies of the same style share one bucket.",
        ],
    }
    return summary, detail


def run_ai_battle_batch(
    store: V2Store,
    host_user: dict,
    ai_types: list[str],
    run_count: int,
    deck_set_id: str | None = None,
    progress_callback=None,
) -> dict:
    deck_set = _deck_set_for_id(deck_set_id)
    deck_path = Path(deck_set["path"])
    name = f"Batch: {' vs '.join(AI_TYPES.get(t, t) for t in ai_types)} x{run_count}"
    definition = _ai_match_definition(host_user["id"], ai_types, name)
    analyses: list[dict] = []
    for index in range(run_count):
        seed = (index + 1) * 7919 + len(ai_types) * 101
        with deck_set_override(deck_path):
            state = create_initial_state(
                GameConfig(player_ids=tuple(seat["player_id"] for seat in definition["seat_list"]), seed=seed)
            )
        state = advance_game(state, definition, deck_path)
        analyses.append(_analysis_for_state(state, definition))
        if progress_callback:
            progress_callback(index + 1, run_count)
    summary, detail = _batch_summary(analyses, ai_types)
    summary.update({"deck_set_id": deck_set["id"], "deck_set_name": deck_set["name"]})
    entry = store.create_ai_battle_run(
        kind="batch",
        name=name,
        deck_set_id=deck_set["id"],
        deck_set_name=deck_set["name"],
        ai_types=ai_types,
        run_count=run_count,
        game_id=None,
        summary=summary,
        detail=detail,
    )
    return {**summary, "history_entry": entry}


def build_match_meta(match: dict, state: GameState | None) -> dict:
    title_by_user = {entry["user_id"]: entry["title"] for entry in state_title_holders()}
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
                "title": title_by_user.get(seat["user_id"]) if seat["user_id"] is not None else None,
                "star_breach_role": seat.get("star_breach_role"),
            }
        )
    return {
        "id": match["id"],
        "name": match["name"],
        "status": match["status"],
        "seats": match["seats"],
        "game_id": match["game_id"],
        "host_user_id": match["host_user_id"],
        "ai_level": match.get("ai_level") or "deck_hand",
        "active_expansions": list(match.get("active_expansions") or []),
        "seat_list": seats,
    }


AI_NAME_POOLS = {
    "vault_runner": (
        "Freebooter Ben Gunn",
        "Freebooter Billy Bones",
        "Freebooter Long John Silver",
        "Freebooter Captain Flint",
        "Freebooter Squire Trelawney",
        "Freebooter Job Anderson",
        "Freebooter George Merry",
        "Freebooter Tom Redruth",
        "Freebooter Dick Johnson",
        "Freebooter Black Dog",
    ),
    "hunter_killer": (
        "Bloodthirsty Blackbeard",
        "Bloodthirsty Calico Jack",
        "Bloodthirsty Captain Kidd",
        "Bloodthirsty Anne Bonny",
        "Bloodthirsty Mary Read",
        "Bloodthirsty Bartholomew Roberts",
        "Bloodthirsty Charles Vane",
        "Bloodthirsty Stede Bonnet",
        "Bloodthirsty Ching Shih",
        "Bloodthirsty Edward Low",
    ),
    "blaster": (
        "Cannoneer Israel Hands",
        "Cannoneer Smee",
        "Cannoneer Bill Jukes",
        "Cannoneer Cecco",
        "Cannoneer Noodler",
        "Cannoneer Gentleman Starkey",
        "Cannoneer Skylights",
        "Cannoneer Alf Mason",
        "Cannoneer Robt. Mullins",
        "Cannoneer Cookson",
    ),
}


def ai_display_name(ai_type: str, ordinal: int) -> str:
    pool = AI_NAME_POOLS.get(ai_type)
    if not pool:
        return AI_DISPLAY_NAMES.get(ai_type, "Rogue Drone")
    name = pool[(ordinal - 1) % len(pool)]
    # More than three of the same profile can't happen today (max 3 AI seats),
    # but stay unique if that ever changes.
    return name if ordinal <= len(pool) else f"{name} {ordinal}"


def state_title_holders() -> list[dict]:
    from starshot.v2.store import get_v2_store

    return get_v2_store().title_holders()
