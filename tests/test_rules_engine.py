import unittest

from starshot.rules import (
    ActionStack,
    GameConfig,
    GamePhase,
    OrderCardSelection,
    OrdersSubmission,
    RulesError,
    SealMode,
    create_initial_state,
    resolve_next_step,
    submit_orders,
)


class RulesEngineTests(unittest.TestCase):
    def test_initial_state_uses_base_rules(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=7))

        self.assertEqual(state.round_number, 1)
        self.assertEqual(state.phase, GamePhase.GIVE_ORDERS)
        self.assertIn(state.starting_player_id, {"red", "blue"})
        self.assertEqual(len(state.players["red"].deck), 8)
        self.assertEqual(state.players["red"].ship.shields, 2)
        self.assertEqual((state.players["red"].ship.q, state.players["red"].ship.r), (-9, 0))
        self.assertEqual(state.players["red"].ship.facing, 0)
        self.assertEqual((state.players["blue"].ship.q, state.players["blue"].ship.r), (9, 0))
        self.assertEqual(state.players["blue"].ship.facing, 3)

    def test_rejects_invalid_player_count(self):
        with self.assertRaises(RulesError):
            create_initial_state(GameConfig(player_ids=("red",)))

    def test_orders_cannot_mix_move_and_attack_cards_in_one_stack(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        orders = OrdersSubmission(
            stacks=(
                ActionStack(
                    action_number=1,
                    seal_mode=SealMode.SEALED,
                    cards=(
                        OrderCardSelection(card_id="move_1_a"),
                        OrderCardSelection(card_id="attack_1_a", target_player_id="blue"),
                    ),
                ),
                ActionStack(action_number=2, seal_mode=SealMode.SEALED),
                ActionStack(action_number=3, seal_mode=SealMode.SEALED),
            )
        )

        with self.assertRaises(RulesError):
            submit_orders(state, "red", orders)

    def test_orders_advance_to_cooldown_when_all_players_submit(self):
        state = self._state_with_submitted_orders()

        self.assertEqual(state.phase, GamePhase.COOLDOWN)
        self.assertEqual(len(state.players["red"].deck), 5)
        self.assertEqual(len(state.players["blue"].deck), 5)

    def test_resolve_advances_action_phases_and_moves_cards(self):
        state = self._state_with_submitted_orders()

        state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.ACTION_1)

        state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.ACTION_2)
        self.assertIn("move_1_a", {card.id for card in state.players["red"].deck})
        self.assertIn("attack_1_a", {card.id for card in state.players["blue"].deck})

        state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.ACTION_3)

        state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.AWARD_BAUBLES)
        self.assertIn("move_2_a", {card.id for card in state.players["red"].overheat})

        state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.CLEANUP)

        state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.GIVE_ORDERS)
        self.assertEqual(state.round_number, 2)
        self.assertIsNone(state.players["red"].prepared_orders)

    def test_movement_resolves_from_move_orientation(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        red_orders = OrdersSubmission(
            stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection("move_1_a", orientation="turn_right"),)),
                ActionStack(2, SealMode.SEALED, (OrderCardSelection("move_1_b", orientation="u_turn"),)),
                ActionStack(3, SealMode.OVERDRIVE, (OrderCardSelection("move_2_a", orientation="forward"),)),
            )
        )
        blue_orders = OrdersSubmission(
            stacks=(
                ActionStack(1, SealMode.SEALED),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )
        )
        state = submit_orders(state, "red", red_orders)
        state = submit_orders(state, "blue", blue_orders)

        state = resolve_next_step(state)
        state = resolve_next_step(state)
        self.assertEqual((state.players["red"].ship.q, state.players["red"].ship.r), (-8, 0))
        self.assertEqual(state.players["red"].ship.facing, 5)
        self.assertEqual(state.players["red"].ship.movement_this_action, 1)

        state = resolve_next_step(state)
        self.assertEqual((state.players["red"].ship.q, state.players["red"].ship.r), (-8, 0))
        self.assertEqual(state.players["red"].ship.facing, 2)
        self.assertEqual(state.players["red"].ship.movement_this_action, 0)

        state = resolve_next_step(state)
        self.assertEqual((state.players["red"].ship.q, state.players["red"].ship.r), (-8, -3))
        self.assertEqual(state.players["red"].ship.facing, 2)
        self.assertEqual(state.players["red"].ship.movement_this_action, 3)

    def test_attack_hit_spends_shield_and_awards_vp(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["blue"].ship.q = 1
        state.players["blue"].ship.r = 0
        state = submit_orders(
            state,
            "red",
            OrdersSubmission(
                stacks=(
                    ActionStack(1, SealMode.SEALED),
                    ActionStack(2, SealMode.SEALED),
                    ActionStack(3, SealMode.SEALED),
                )
            ),
        )
        state = submit_orders(
            state,
            "blue",
            OrdersSubmission(
                stacks=(
                    ActionStack(1, SealMode.SEALED, (OrderCardSelection("attack_1_a", target_player_id="red"),)),
                    ActionStack(2, SealMode.SEALED),
                    ActionStack(3, SealMode.SEALED),
                )
            ),
        )

        state = resolve_next_step(state)
        state = resolve_next_step(state)

        self.assertEqual(state.players["red"].ship.shields, 1)
        self.assertEqual(state.players["red"].ship.damage_taken, 0)
        self.assertEqual(state.players["blue"].victory_points, 1)
        self.assertTrue(
            any(event["type"] == "volley_resolved" and event["shielded"] for event in state.event_log)
        )

    def test_unshielded_attack_adds_damage_taken(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.shields = 0
        state.players["blue"].ship.q = 1
        state.players["blue"].ship.r = 0
        state = submit_orders(
            state,
            "red",
            OrdersSubmission(
                stacks=(
                    ActionStack(1, SealMode.SEALED),
                    ActionStack(2, SealMode.SEALED),
                    ActionStack(3, SealMode.SEALED),
                )
            ),
        )
        state = submit_orders(
            state,
            "blue",
            OrdersSubmission(
                stacks=(
                    ActionStack(1, SealMode.OVERDRIVE, (OrderCardSelection("attack_2_a", target_player_id="red"),)),
                    ActionStack(2, SealMode.SEALED),
                    ActionStack(3, SealMode.SEALED),
                )
            ),
        )

        state = resolve_next_step(state)
        state = resolve_next_step(state)

        self.assertEqual(state.players["red"].ship.damage_taken, 3)
        self.assertEqual(state.players["blue"].victory_points, 1)
        self.assertIn("attack_2_a", {card.id for card in state.players["blue"].overheat})

    def test_multiple_attack_cards_create_one_combined_volley(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.shields = 0
        state.players["blue"].ship.q = 1
        state.players["blue"].ship.r = 0
        state = submit_orders(
            state,
            "red",
            OrdersSubmission(
                stacks=(
                    ActionStack(1, SealMode.SEALED),
                    ActionStack(2, SealMode.SEALED),
                    ActionStack(3, SealMode.SEALED),
                )
            ),
        )
        state = submit_orders(
            state,
            "blue",
            OrdersSubmission(
                stacks=(
                    ActionStack(
                        1,
                        SealMode.SEALED,
                        (
                            OrderCardSelection("attack_1_a", target_player_id="red"),
                            OrderCardSelection("attack_2_a", target_player_id="red"),
                        ),
                    ),
                    ActionStack(2, SealMode.SEALED),
                    ActionStack(3, SealMode.SEALED),
                )
            ),
        )

        state = resolve_next_step(state)
        state = resolve_next_step(state)

        volleys = [event for event in state.event_log if event["type"] == "volley_resolved"]
        self.assertEqual(len(volleys), 1)
        self.assertEqual(volleys[0]["card_ids"], ["attack_1_a", "attack_2_a"])
        self.assertEqual(volleys[0]["damage"], 3)
        self.assertEqual(state.players["red"].ship.damage_taken, 3)
        self.assertEqual(state.rng_step, 2)

    def _state_with_submitted_orders(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
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
        return submit_orders(state, "blue", blue_orders)


if __name__ == "__main__":
    unittest.main()
