from __future__ import annotations

import argparse
import json

from starshot.rules import GameConfig, create_initial_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starshot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_game = subparsers.add_parser("new-game", help="Create a new in-memory game state.")
    new_game.add_argument("--players", nargs="+", required=True)
    new_game.add_argument("--seed", type=int)

    args = parser.parse_args(argv)

    if args.command == "new-game":
        state = create_initial_state(GameConfig(player_ids=tuple(args.players), seed=args.seed))
        print(
            json.dumps(
                {
                    "round": state.round_number,
                    "phase": state.phase,
                    "starting_player_id": state.starting_player_id,
                    "players": list(state.players),
                },
                indent=2,
            )
        )
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
