from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from starshot.persistence import SQLiteGameStore
from starshot.rules import (  # noqa: E402
    ActionStack,
    GameConfig,
    OrderCardSelection,
    OrdersSubmission,
    SealMode,
    create_initial_state,
    submit_orders,
)
from starshot.rules.serialization import state_to_dict


def main() -> int:
    db_path = ROOT / ".starshot" / "demo.sqlite3"
    store = SQLiteGameStore(db_path)

    state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=3))
    game_id = store.create_game(state)
    print(f"Created demo game: {game_id}")
    print(f"Database: {db_path}")
    print()

    red_orders = OrdersSubmission(
        stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("move_1_a"),)),
            ActionStack(2, SealMode.SEALED, (OrderCardSelection("move_1_b"),)),
            ActionStack(3, SealMode.OVERDRIVE, (OrderCardSelection("move_2_a"),)),
        )
    )
    blue_orders = OrdersSubmission(
        stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("attack_1_a", target_player_id="red"),)),
            ActionStack(2, SealMode.SEALED, (OrderCardSelection("attack_1_b", target_player_id="red"),)),
            ActionStack(3, SealMode.SEALED, (OrderCardSelection("attack_2_a", target_player_id="red"),)),
        )
    )

    state = submit_orders(state, "red", red_orders)
    store.save_game(game_id, state)
    print("Submitted red orders.")
    print(f"Phase after red submits: {state.phase.value}")

    state = submit_orders(state, "blue", blue_orders)
    store.save_game(game_id, state)
    print("Submitted blue orders.")
    print(f"Phase after blue submits: {state.phase.value}")
    print()

    public_state = state_to_dict(store.load_game(game_id), reveal_orders=False)
    print("Current public game state:")
    print(json.dumps(public_state, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
