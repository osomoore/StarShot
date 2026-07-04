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
        self.assertEqual(restored.players["red"].ship.q, -11)
        self.assertEqual(restored.players["red"].ship.r, 0)
        self.assertEqual(restored.players["red"].ship.facing, 0)
        self.assertEqual(restored.players["red"].ship.damage_taken, 0)
        self.assertEqual(restored.rng_seed, state.rng_seed)
        self.assertEqual(restored.rng_step, state.rng_step)
        self.assertEqual(len(restored.baubles), 11)
        self.assertEqual(restored.baubles[0].id, state.baubles[0].id)
        self.assertEqual((restored.baubles[-1].q, restored.baubles[-1].r), (0, 0))
        self.assertTrue(restored.baubles[-1].is_fang)

        serialized_ship = state_to_dict(state)["players"]["red"]["ship"]
        self.assertEqual(serialized_ship["layout_id"], "base_ship_0")
        self.assertIn("component_layout", serialized_ship)
        self.assertEqual(serialized_ship["damage_lanes"]["1"][0], "aft_engines")

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

    def test_hybrid_desperation_cards_keep_metadata_across_serialization(self):
        state = create_initial_state(
            GameConfig(
                player_ids=("red", "blue"),
                seed=1,
                debug_start_with_attack_desperation_card=True,
            )
        )
        restored = state_from_dict(state_to_dict(state))

        ace_shot = next(card for card in restored.players["red"].deck if card.id == "desp_ace_shot_a")
        self.assertTrue(ace_shot.is_hybrid)
        self.assertFalse(ace_shot.requires_target)


if __name__ == "__main__":
    unittest.main()
