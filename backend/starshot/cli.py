from __future__ import annotations

import argparse
import json
from pathlib import Path

from starshot.persistence import SQLiteGameStore
from starshot.rules import GameConfig, RulesError, create_initial_state, resolve_next_step, submit_orders
from starshot.rules.serialization import orders_from_dict, state_to_dict


DEFAULT_DB_PATH = Path(".starshot") / "games.sqlite3"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starshot")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite game database path.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_game = subparsers.add_parser("new-game", help="Create and persist a new game.")
    new_game.add_argument("--players", nargs="+", required=True)
    new_game.add_argument("--seed", type=int)

    subparsers.add_parser("list-games", help="List saved games.")

    show = subparsers.add_parser("show", help="Show a saved game.")
    show.add_argument("game_id")
    show.add_argument("--reveal-orders", action="store_true", help="Show submitted hidden orders.")

    orders = subparsers.add_parser("orders", help="Submit hidden orders for a player.")
    orders.add_argument("game_id")
    orders.add_argument("player_id")
    orders.add_argument("orders_json", help="Inline orders JSON or a path to a JSON file.")

    resolve = subparsers.add_parser("resolve", help="Resolve the next game phase.")
    resolve.add_argument("game_id")

    args = parser.parse_args(argv)
    store = SQLiteGameStore(args.db)

    try:
        if args.command == "new-game":
            state = create_initial_state(GameConfig(player_ids=tuple(args.players), seed=args.seed))
            game_id = store.create_game(state)
            print(json.dumps({"game_id": game_id, **public_summary(state)}, indent=2))
            return 0

        if args.command == "list-games":
            print(json.dumps({"games": store.list_games()}, indent=2))
            return 0

        if args.command == "show":
            state = store.load_game(args.game_id)
            print(json.dumps(state_to_dict(state, reveal_orders=args.reveal_orders), indent=2))
            return 0

        if args.command == "orders":
            state = store.load_game(args.game_id)
            orders_payload = _read_json_argument(args.orders_json)
            next_state = submit_orders(state, args.player_id, orders_from_dict(orders_payload))
            store.save_game(args.game_id, next_state)
            print(json.dumps(public_summary(next_state), indent=2))
            return 0

        if args.command == "resolve":
            state = store.load_game(args.game_id)
            next_state = resolve_next_step(state)
            store.save_game(args.game_id, next_state)
            print(json.dumps(public_summary(next_state), indent=2))
            return 0
    except (KeyError, RulesError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"starshot: error: {exc}\n")

    parser.error(f"Unknown command: {args.command}")
    return 2


def public_summary(state) -> dict:
    return {
        "round": state.round_number,
        "phase": state.phase.value,
        "starting_player_id": state.starting_player_id,
        "players": list(state.players),
    }


def _read_json_argument(value: str) -> dict:
    possible_path = Path(value)
    if possible_path.exists():
        return json.loads(possible_path.read_text(encoding="utf-8"))
    return json.loads(value)


if __name__ == "__main__":
    raise SystemExit(main())
