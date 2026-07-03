import unittest

from starshot.rules import (
    ActionStack,
    GameConfig,
    OrderCardSelection,
    OrdersSubmission,
    SealMode,
    create_initial_state,
    submit_orders,
)
from starshot.rules.serialization import orders_from_dict, state_from_dict, state_to_dict


class SerializationTests(unittest.TestCase):
    def test_state_round_trips(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=5))
        restored = state_from_dict(state_to_dict(state))

        self.assertEqual(restored.round_number, state.round_number)
        self.assertEqual(restored.phase, state.phase)
        self.assertEqual(restored.players["red"].deck[0].id, "move_1_a")

    def test_hidden_orders_can_be_suppressed(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=5))
        orders = OrdersSubmission(
            stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection("move_1_a"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )
        )
        state = submit_orders(state, "red", orders)

        hidden = state_to_dict(state, reveal_orders=False)
        revealed = state_to_dict(state, reveal_orders=True)

        self.assertTrue(hidden["players"]["red"]["has_submitted_orders"])
        self.assertIsNone(hidden["players"]["red"]["prepared_orders"])
        self.assertIsNotNone(revealed["players"]["red"]["prepared_orders"])

    def test_orders_parse_from_json_shape(self):
        orders = orders_from_dict(
            {
                "stacks": [
                    {
                        "action_number": 1,
                        "seal_mode": "sealed",
                        "cards": [{"card_id": "move_1_a"}],
                    },
                    {"action_number": 2, "seal_mode": "sealed", "cards": []},
                    {"action_number": 3, "seal_mode": "overdrive", "cards": []},
                ]
            }
        )

        self.assertEqual(orders.stacks[0].cards[0].card_id, "move_1_a")
        self.assertEqual(orders.stacks[2].seal_mode, SealMode.OVERDRIVE)


if __name__ == "__main__":
    unittest.main()
