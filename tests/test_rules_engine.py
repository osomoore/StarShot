import unittest

from starshot.rules import (
    ActionStack,
    BaubleState,
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
from starshot.rules.baubles import BAUBLE_MAX_CENTER_DISTANCE, bauble_hexes
from starshot.rules.decks import card_by_id
from starshot.rules.hex import BOARD_RADIUS, hex_distance


class RulesEngineTests(unittest.TestCase):
    def test_initial_state_uses_base_rules(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=7))

        self.assertEqual(state.round_number, 1)
        self.assertEqual(state.phase, GamePhase.GIVE_ORDERS)
        self.assertIn(state.starting_player_id, {"red", "blue"})
        self.assertEqual(len(state.players["red"].deck), 5)
        self.assertEqual(len(state.players["red"].hand), 5)
        self.assertEqual(len(state.players["red"].discard), 0)
        self.assertEqual(state.players["red"].ship.shields, 2)
        self.assertEqual((state.players["red"].ship.q, state.players["red"].ship.r), (-11, 0))
        self.assertEqual(state.players["red"].ship.facing, 0)
        self.assertEqual((state.players["blue"].ship.q, state.players["blue"].ship.r), (11, 0))
        self.assertEqual(state.players["blue"].ship.facing, 3)
        self.assertEqual(len(state.baubles), 11)
        self.assertEqual([bauble.number for bauble in state.baubles].count(1), 2)
        self.assertEqual([bauble.number for bauble in state.baubles].count(5), 2)
        self.assertEqual([bauble.number for bauble in state.baubles].count(6), 1)
        self.assertEqual(len({(bauble.q, bauble.r) for bauble in state.baubles}), 11)
        fang = [bauble for bauble in state.baubles if bauble.is_fang][0]
        self.assertEqual((fang.q, fang.r), (0, 0))

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

    def test_orders_advance_to_action_one_when_all_players_submit(self):
        state = self._state_with_submitted_orders()

        self.assertEqual(state.phase, GamePhase.ACTION_1)
        self.assertEqual(len(state.players["red"].hand), 0)
        self.assertEqual(len(state.players["red"].discard), 2)
        self.assertEqual(len(state.players["blue"].hand), 0)

    def test_resolve_advances_action_phases_and_moves_cards_at_cleanup(self):
        state = self._state_with_submitted_orders()

        state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.ACTION_2)
        self.assertNotIn("move_1_a", {card.id for card in state.players["red"].discard})
        self.assertNotIn("attack_1_a", {card.id for card in state.players["blue"].discard})

        state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.ACTION_3)

        state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.AWARD_BAUBLES)
        self.assertNotIn("move_2_a", {card.id for card in state.players["red"].overheat})

        state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.CLEANUP)

        state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.GIVE_ORDERS)
        self.assertEqual(state.round_number, 2)
        self.assertIsNone(state.players["red"].prepared_orders)
        red_moves = [
            event for event in state.event_log
            if event["type"] == "action_cards_moved" and event["player_id"] == "red"
        ]
        blue_moves = [
            event for event in state.event_log
            if event["type"] == "action_cards_moved" and event["player_id"] == "blue"
        ]
        self.assertIn("move_1_a", red_moves[0]["moved_to_discard"])
        self.assertIn("attack_1_a", blue_moves[0]["moved_to_discard"])
        self.assertIn("move_2_a", red_moves[2]["moved_to_overheat"])

    def test_overheated_cards_wait_until_deck_exhausts(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.phase = GamePhase.CLEANUP
        red = state.players["red"]
        red.deck = [
            card_by_id("move_1_a"),
            card_by_id("move_1_b"),
            card_by_id("move_2_b"),
            card_by_id("move_2_c"),
            card_by_id("attack_1_a"),
        ]
        red.hand = []
        red.discard = [card_by_id("attack_1_b")]
        red.overheat = [card_by_id("move_2_a")]

        state = resolve_next_step(state)
        red = state.players["red"]

        self.assertEqual({card.id for card in red.hand}, {"move_1_a", "move_1_b", "move_2_b", "move_2_c", "attack_1_a"})
        self.assertEqual([card.id for card in red.overheat], ["move_2_a"])
        self.assertEqual([card.id for card in red.discard], ["attack_1_b"])

    def test_deck_exhaustion_shuffles_discard_then_moves_overheat_to_discard(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.phase = GamePhase.CLEANUP
        red = state.players["red"]
        red.deck = []
        red.hand = []
        red.discard = [card_by_id("move_1_a")]
        red.overheat = [card_by_id("move_2_a")]

        state = resolve_next_step(state)
        red = state.players["red"]

        self.assertEqual({card.id for card in red.hand}, {"move_1_a", "move_2_a"})
        self.assertEqual(red.overheat, [])
        self.assertEqual(red.discard, [])
        refresh = [event for event in state.event_log if event["type"] == "deck_refreshed" and event["player_id"] == "red"][0]
        self.assertEqual(refresh["reshuffled_discard"], ["move_1_a", "move_2_a"])
        self.assertEqual(refresh["moved_overheat_to_discard"], ["move_2_a"])

    def test_movement_resolves_from_move_orientation(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        # Red starts at (-11, 0) facing 0 (east)
        red_orders = OrdersSubmission(
            stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection("move_1_a", orientation="turn_right"),)),
                ActionStack(2, SealMode.SEALED, (OrderCardSelection("move_1_b", orientation="turn_left"),)),
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

        # Action 1: turn_right (0->5), move 1 in facing 5
        state = resolve_next_step(state)
        self.assertEqual(state.players["red"].ship.facing, 5)
        self.assertEqual(state.players["red"].ship.movement_this_action, 1)

        # Action 2: turn_left (5->0), move 1 in facing 0
        state = resolve_next_step(state)
        self.assertEqual(state.players["red"].ship.facing, 0)
        self.assertEqual(state.players["red"].ship.movement_this_action, 1)

        # Action 3: forward Move 2, overdrive duplicates it (2+2=4)
        state = resolve_next_step(state)
        self.assertEqual(state.players["red"].ship.facing, 0)
        self.assertEqual(state.players["red"].ship.movement_this_action, 4)
        movement_events = [event for event in state.event_log if event["type"] == "movement_resolved"]
        self.assertFalse(movement_events[-2]["overdrive_copy"])
        self.assertTrue(movement_events[-1]["overdrive_copy"])

    def test_move_clamps_to_board_after_attempt_but_keeps_full_defense(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.players["red"].ship.q = 13
        state.players["red"].ship.r = 0
        state.players["red"].ship.facing = 0
        red_orders = OrdersSubmission(
            stacks=(
                ActionStack(1, SealMode.OVERDRIVE, (OrderCardSelection("move_2_a"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
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

        self.assertEqual((state.players["red"].ship.q, state.players["red"].ship.r), (14, 0))
        self.assertEqual(state.players["red"].ship.movement_this_action, 4)
        movements = [event for event in state.event_log if event["type"] == "movement_resolved"]
        self.assertEqual(movements[0]["steps"][0]["attempted"], {"q": 15, "r": 0, "facing": 0})
        self.assertEqual(movements[1]["steps"][0]["attempted"], {"q": 16, "r": 0, "facing": 0})
        self.assertTrue(movements[0]["steps"][0]["clamped"])
        self.assertTrue(movements[1]["steps"][0]["clamped"])

    def test_overdriven_move_counts_both_moves_for_attack_defense(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.facing = 0
        state.players["blue"].ship.q = 3
        state.players["blue"].ship.r = 0
        state.players["blue"].ship.facing = 0
        state.players["red"].hand = [card_by_id("attack_2_a")]
        state.players["blue"].hand = [card_by_id("move_2_a")]

        red_orders = OrdersSubmission(
            stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection("attack_2_a", target_player_id="blue"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )
        )
        blue_orders = OrdersSubmission(
            stacks=(
                ActionStack(1, SealMode.OVERDRIVE, (OrderCardSelection("move_2_a"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )
        )
        state = submit_orders(state, "red", red_orders)
        state = submit_orders(state, "blue", blue_orders)

        state = resolve_next_step(state)

        volley = [event for event in state.event_log if event["type"] == "volley_resolved"][0]
        self.assertEqual(state.players["blue"].ship.movement_this_action, 4)
        self.assertEqual(volley["target_movement"], 4)
        self.assertEqual(volley["defense_threshold"], volley["distance"] + 4 + volley["target_defense_bonus"])

    def test_baubles_are_placed_without_overlap_and_later_rounds_are_nearer_center(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue", "green", "yellow"), seed=11))
        positions = {(bauble.q, bauble.r) for bauble in state.baubles}
        occupied_bauble_hexes = set()

        self.assertEqual(len(state.baubles), 11)
        self.assertEqual(len(positions), len(state.baubles))
        for bauble in state.baubles:
            footprint = set(bauble_hexes(bauble.q, bauble.r))
            self.assertTrue(all(hex_distance(0, 0, q, r) <= BOARD_RADIUS for q, r in footprint))
            self.assertTrue(occupied_bauble_hexes.isdisjoint(footprint))
            occupied_bauble_hexes.update(footprint)

        for number in range(1, 6):
            numbered = [bauble for bauble in state.baubles if bauble.number == number]
            self.assertEqual(len(numbered), 2)
            max_distance = BAUBLE_MAX_CENTER_DISTANCE[number]
            self.assertTrue(all(hex_distance(0, 0, bauble.q, bauble.r) <= max_distance for bauble in numbered))

        for index, bauble in enumerate(state.baubles):
            for other in state.baubles[index + 1 :]:
                self.assertGreaterEqual(hex_distance(bauble.q, bauble.r, other.q, other.r), 4)

        early_baubles = [bauble for bauble in state.baubles if bauble.number in {1, 2}]
        for bauble in early_baubles:
            for player in state.players.values():
                self.assertGreater(hex_distance(bauble.q, bauble.r, player.ship.q, player.ship.r), 3)

    def test_award_baubles_scores_matching_round_baubles_in_range(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.phase = GamePhase.AWARD_BAUBLES
        state.round_number = 1
        state.baubles = [BaubleState(id="bauble_1_test", number=1, q=0, r=0, victory_points=2)]
        state.players["red"].ship.q = 1
        state.players["red"].ship.r = 0
        state.players["blue"].ship.q = 2
        state.players["blue"].ship.r = 0

        state = resolve_next_step(state)

        self.assertEqual(state.phase, GamePhase.CLEANUP)
        self.assertEqual(state.players["red"].victory_points, 2)
        self.assertEqual(state.players["blue"].victory_points, 0)
        self.assertEqual(state.baubles[0].claimed_by, ["red"])
        award = [event for event in state.event_log if event["type"] == "bauble_awarded"][0]
        self.assertEqual(award["awards"][0]["player_id"], "red")
        self.assertTrue(award["awards"][0]["desperation_card_drawn"])

    def test_fang_scores_every_round_and_shields_block_damage(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.phase = GamePhase.AWARD_BAUBLES
        state.round_number = 2
        state.baubles = [BaubleState(id="fang", number=6, q=0, r=0, victory_points=1, is_fang=True)]
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 1
        state.players["red"].ship.shields = 1
        state.players["blue"].ship.q = 4
        state.players["blue"].ship.r = 0

        state = resolve_next_step(state)

        self.assertEqual(state.players["red"].victory_points, 1)
        self.assertEqual(state.players["red"].ship.shields, 0)
        self.assertEqual(state.players["red"].ship.damage_taken, 0)
        award = [event for event in state.event_log if event["type"] == "bauble_awarded"][0]["awards"][0]
        self.assertFalse(award["desperation_card_drawn"])
        self.assertEqual(award["fang_damage"], 1)
        self.assertTrue(award["shielded"])
        self.assertEqual(award["damage_applied"], 0)
        self.assertEqual(award["damage_shots"], [])

    def test_fang_unshielded_damage_rolls_one_lane(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.phase = GamePhase.AWARD_BAUBLES
        state.round_number = 3
        state.baubles = [BaubleState(id="fang", number=6, q=0, r=0, victory_points=1, is_fang=True)]
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 1
        state.players["red"].ship.shields = 0
        state.players["blue"].ship.q = 4
        state.players["blue"].ship.r = 0

        state = resolve_next_step(state)

        self.assertEqual(state.players["red"].victory_points, 1)
        self.assertEqual(state.players["red"].ship.damage_taken, 1)
        award = [event for event in state.event_log if event["type"] == "bauble_awarded"][0]["awards"][0]
        self.assertFalse(award["shielded"])
        self.assertEqual(award["damage_applied"], 1)
        self.assertEqual(len(award["damage_shots"]), 1)

    def test_fang_awards_six_vp_on_round_six(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.phase = GamePhase.AWARD_BAUBLES
        state.round_number = 6
        state.baubles = [BaubleState(id="fang", number=6, q=0, r=0, victory_points=1, is_fang=True)]
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 1
        state.players["red"].ship.shields = 1
        state.players["blue"].ship.q = 4
        state.players["blue"].ship.r = 0

        state = resolve_next_step(state)

        self.assertEqual(state.players["red"].victory_points, 6)
        award = [event for event in state.event_log if event["type"] == "bauble_awarded"][0]["awards"][0]
        self.assertEqual(award["vp_awarded"], 6)
        self.assertTrue(award["shielded"])

    def test_attack_hit_spends_shield_and_awards_vp(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["blue"].ship.q = 1
        state.players["blue"].ship.r = 0
        self._set_hand(state, "blue", "attack_1_a")
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

        self.assertEqual(state.players["red"].ship.shields, 1)
        self.assertEqual(state.players["red"].ship.damage_taken, 0)
        self.assertEqual(state.players["blue"].victory_points, 1)
        self.assertTrue(
            any(event["type"] == "volley_resolved" and event["shielded"] for event in state.event_log)
        )

    def test_unshielded_attack_rolls_damage_lanes_and_destroys_components(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.shields = 0
        state.players["blue"].ship.q = 1
        state.players["blue"].ship.r = 0
        self._set_hand(state, "blue", "attack_2_a")
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

        self.assertEqual(state.players["red"].ship.damage_taken, 2)
        self.assertEqual(state.players["blue"].victory_points, 2)
        self.assertNotIn("attack_2_a", {card.id for card in state.players["blue"].overheat})
        volleys = [event for event in state.event_log if event["type"] == "volley_resolved"]
        self.assertEqual(len(volleys), 2)
        self.assertFalse(volleys[0]["overdrive_copy"])
        self.assertTrue(volleys[1]["overdrive_copy"])
        self.assertEqual(volleys[0]["damage_applied"], 1)
        self.assertEqual(volleys[1]["damage_applied"], 1)
        self.assertEqual(len(volleys[0]["damage_rolls"]), 1)
        self.assertEqual(len(volleys[1]["damage_shots"]), 1)

    def test_multiple_attack_cards_create_one_combined_volley(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.shields = 0
        state.players["blue"].ship.q = 1
        state.players["blue"].ship.r = 0
        self._set_hand(state, "blue", "attack_1_a", "attack_2_a")
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

        volleys = [event for event in state.event_log if event["type"] == "volley_resolved"]
        self.assertEqual(len(volleys), 1)
        self.assertEqual(volleys[0]["card_ids"], ["attack_1_a", "attack_2_a"])
        self.assertEqual(volleys[0]["damage"], 1)
        self.assertEqual(state.players["red"].ship.damage_taken, 1)
        self.assertEqual(state.rng_step, 3)

    def test_bridge_damage_destroys_ship_and_awards_destroyed_ship_vp(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=2))
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.shields = 0
        state.players["blue"].ship.q = 1
        state.players["blue"].ship.r = 0
        state.players["red"].ship.destroyed_components.update(
            {"port_outer_engines", "port_life_support"}
        )
        state.players["red"].ship.damage_taken = 2
        self._set_hand(state, "blue", "attack_1_a")
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

        self.assertTrue(state.players["red"].ship.destroyed)
        self.assertIn("command_bridge", state.players["red"].ship.destroyed_components)
        self.assertEqual(state.players["blue"].victory_points, 3)

    def test_overdrive_seal_card_placed_on_deck_and_drawn_next_round(self):
        """One overdrive stack with 2 cards: both go to overheat, draw reduced by 1 next round.
        Round 2 hand should have 4 playable cards (5 - 1 overdrive seal)."""
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "move_1_a", "move_2_a")
        red_orders = OrdersSubmission(
            stacks=(
                ActionStack(1, SealMode.OVERDRIVE, (
                    OrderCardSelection("move_1_a"),
                    OrderCardSelection("move_2_a"),
                )),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
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
        while state.phase != GamePhase.GIVE_ORDERS or state.round_number != 2:
            state = resolve_next_step(state)

        red = state.players["red"]
        self.assertEqual(len(red.hand), 4)
        hand_ids = {card.id for card in red.hand}
        self.assertNotIn("move_1_a", hand_ids)
        self.assertNotIn("move_2_a", hand_ids)
        self.assertEqual(len(red.overheat), 2)

    def test_two_overdrive_stacks_place_two_seal_cards_on_deck(self):
        """Two overdrive stacks: draw reduced by 2 next round, hand has 3 playable cards."""
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "move_1_a", "move_2_a", "move_1_b", "move_2_b")
        red_orders = OrdersSubmission(
            stacks=(
                ActionStack(1, SealMode.OVERDRIVE, (
                    OrderCardSelection("move_1_a"),
                    OrderCardSelection("move_2_a"),
                )),
                ActionStack(2, SealMode.OVERDRIVE, (
                    OrderCardSelection("move_1_b"),
                    OrderCardSelection("move_2_b"),
                )),
                ActionStack(3, SealMode.SEALED),
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
        while state.phase != GamePhase.GIVE_ORDERS or state.round_number != 2:
            state = resolve_next_step(state)

        red = state.players["red"]
        self.assertEqual(len(red.hand), 3)
        self.assertEqual(len(red.overheat), 4)

    def _state_with_submitted_orders(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "blue", "attack_1_a", "attack_1_b", "attack_2_a")
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

    def _set_hand(self, state, player_id, *card_ids):
        player = state.players[player_id]
        requested = set(card_ids)
        player.deck = [card for card in player.deck if card.id not in requested]
        player.discard = [card for card in player.discard if card.id not in requested]
        player.overheat = [card for card in player.overheat if card.id not in requested]
        player.hand = [card_by_id(card_id) for card_id in card_ids]


if __name__ == "__main__":
    unittest.main()
