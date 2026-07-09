"""Tests for the desperation deck: card definitions, draw logic, and game integration."""

import unittest
from random import Random

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
from starshot.rules.decks import (
    card_by_id,
)
from starshot.rules.desperation import (
    all_desperation_cards,
    card_aim_bonus,
    card_damage_bonus,
    card_orientation_options,
    card_requires_target,
    card_value,
    create_desperation_deck,
    desperation_card_by_id,
    draw_desperation_card,
    return_desperation_card,
    selected_card_family,
)
from starshot.rules.models import Card, CardFamily, DesperationDeck


class DesperationDeckDefinitionTests(unittest.TestCase):
    def test_desperation_deck_has_expected_card_count(self):
        cards = all_desperation_cards()
        # 6 move-type + 8 attack-type (untargeted) + 4 targeted attack = 18 cards
        self.assertEqual(len(cards), 18)

    def test_all_desperation_cards_are_not_base(self):
        for card in all_desperation_cards():
            self.assertFalse(card.is_base, f"{card.id} should have is_base=False")

    def test_card_by_id_finds_base_cards(self):
        card = card_by_id("move_1_a")
        self.assertTrue(card.is_base)
        self.assertEqual(card.family, CardFamily.MOVE)

    def test_card_by_id_finds_desperation_cards(self):
        card = card_by_id("desp_thrust_ions_a")
        self.assertFalse(card.is_base)
        self.assertEqual(card.family, CardFamily.MOVE)
        self.assertEqual(card.value, 1)

    def test_card_by_id_raises_on_unknown_id(self):
        with self.assertRaises(KeyError):
            card_by_id("nonexistent_card")


class DesperationDeckDrawTests(unittest.TestCase):
    def _fresh_rng(self) -> Random:
        return Random(42)

    def test_create_deck_has_all_cards_shuffled(self):
        rng = self._fresh_rng()
        deck = create_desperation_deck(rng)
        self.assertEqual(len(deck.cards), 18)
        self.assertFalse(deck.shuffle_marker_on_top)

    def test_draw_removes_from_bottom(self):
        rng = self._fresh_rng()
        deck = create_desperation_deck(rng)
        first_card_id = deck.cards[0].id
        drawn = draw_desperation_card(deck, Random(0))
        self.assertEqual(drawn.id, first_card_id)
        self.assertEqual(len(deck.cards), 17)

    def test_draw_all_cards_triggers_reshuffle(self):
        rng = self._fresh_rng()
        deck = create_desperation_deck(rng)
        draw_rng = Random(99)
        # Draw all 18 cards
        drawn_ids = [draw_desperation_card(deck, draw_rng).id for _ in range(18)]
        self.assertEqual(len(drawn_ids), 18)
        # Deck should be empty and marker should be set
        self.assertEqual(len(deck.cards), 0)
        self.assertTrue(deck.shuffle_marker_on_top)
        # Drawing once more should trigger reshuffle and return a card
        next_card = draw_desperation_card(deck, Random(7))
        self.assertIsNotNone(next_card)
        self.assertEqual(len(deck.cards), 17)
        self.assertFalse(deck.shuffle_marker_on_top)

    def test_desperation_deck_always_returns_a_valid_card(self):
        deck = DesperationDeck(cards=[], shuffle_marker_on_top=True)
        card = draw_desperation_card(deck, Random(5))
        self.assertIsNotNone(card)
        self.assertFalse(card.is_base)

    def test_return_desperation_card_places_card_on_top_and_clears_marker(self):
        card = desperation_card_by_id("desp_thrust_ions_a")
        deck = DesperationDeck(cards=[], shuffle_marker_on_top=True)
        return_desperation_card(deck, card)
        self.assertEqual(deck.cards, [card])
        self.assertFalse(deck.shuffle_marker_on_top)


class DesperationCardSemanticsTests(unittest.TestCase):
    def test_hybrid_basic_face_uses_selected_mode(self):
        card = desperation_card_by_id("desp_ace_shot_a")
        self.assertEqual(
            selected_card_family(card, OrderCardSelection(card.id, mode="move")),
            CardFamily.MOVE,
        )
        self.assertEqual(
            selected_card_family(card, OrderCardSelection(card.id, mode="attack")),
            CardFamily.ATTACK,
        )

    def test_hybrid_basic_face_requires_mode(self):
        card = desperation_card_by_id("desp_ace_shot_a")
        with self.assertRaises(ValueError):
            selected_card_family(card, OrderCardSelection(card.id))

    def test_desperate_face_overrides_basic_card_semantics(self):
        card = desperation_card_by_id("desp_steady_shot_a")
        selection = OrderCardSelection(card.id, face="desperate")
        self.assertEqual(selected_card_family(card, selection), CardFamily.ATTACK)
        self.assertFalse(card_requires_target(card, selection))
        self.assertEqual(card_value(card, selection, SealMode.OVERDRIVE), 0)
        self.assertEqual(card_aim_bonus(card, selection), 2)
        self.assertEqual(card_damage_bonus(card, selection), 1)

    def test_desperation_basic_face_ignores_overdrive_boost(self):
        card = desperation_card_by_id("desp_targeted_attack_1_a")
        selection = OrderCardSelection(card.id)
        self.assertEqual(card_value(card, selection, SealMode.OVERDRIVE), 1)

    def test_desperation_move_options_are_forward_only(self):
        card = desperation_card_by_id("desp_thrust_ions_a")
        selection = OrderCardSelection(card.id, mode="move")
        self.assertEqual(card_orientation_options(card, selection), ("forward",))

    def test_warp_desperate_faces_have_destinations_and_defense(self):
        self.assertEqual(desperation_card_by_id("desp_homeward_bound").desperate_face.warp_destination, "home")
        self.assertEqual(desperation_card_by_id("desp_treasure_hound").desperate_face.warp_destination, "bauble")
        self.assertEqual(desperation_card_by_id("desp_nightjammer").desperate_face.warp_destination, "leader")
        self.assertEqual(desperation_card_by_id("desp_homeward_bound").desperate_face.defense_bonus, 5)

    def test_deadeye_desperate_face_uses_large_to_hit_bonus(self):
        face = desperation_card_by_id("desp_deadeye").desperate_face
        self.assertEqual(face.aim_bonus, 999)
        self.assertTrue(face.always_hits)

    def test_self_destruct_and_death_blossom_desperate_faces_have_special_attack_metadata(self):
        self_destruct = desperation_card_by_id("desp_self_destruct").desperate_face
        self.assertEqual(self_destruct.value, 4)
        self.assertTrue(self_destruct.requires_target)
        self.assertEqual(self_destruct.max_range, 2)

        death_blossom = desperation_card_by_id("desp_death_blossom").desperate_face
        self.assertEqual(death_blossom.value, 1)
        self.assertTrue(death_blossom.attacks_all)
        self.assertEqual(death_blossom.fixed_defense_threshold, 10)


class DesperationDeckGameIntegrationTests(unittest.TestCase):
    def test_initial_state_has_desperation_deck_with_cards(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self.assertEqual(len(state.desperation_deck.cards), 18)
        self.assertFalse(state.desperation_deck.shuffle_marker_on_top)

    def test_debug_startup_can_seed_attack_desperation_cards(self):
        state = create_initial_state(
            GameConfig(
                player_ids=("red", "blue"),
                seed=1,
                debug_start_with_attack_desperation_card=True,
            )
        )
        for player in state.players.values():
            self.assertTrue(any(card.id == "desp_ace_shot_a" for card in player.deck))

    def test_bauble_award_draws_desperation_card_into_player_deck(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.phase = GamePhase.AWARD_BAUBLES
        state.round_number = 1
        state.baubles = [BaubleState(id="bauble_1_test", number=1, q=0, r=0, victory_points=4)]
        state.players["red"].ship.q = 1
        state.players["red"].ship.r = 0
        state.players["blue"].ship.q = 5
        state.players["blue"].ship.r = 0

        deck_before = len(state.players["red"].deck)
        desp_deck_before = len(state.desperation_deck.cards)

        state = resolve_next_step(state)

        # Red's deck should gain one desperation card
        self.assertEqual(len(state.players["red"].deck), deck_before + 1)
        # Desperation deck should shrink by one
        self.assertEqual(len(state.desperation_deck.cards), desp_deck_before - 1)
        # The drawn card should be non-base and placed on top of the deck.
        drawn_card = state.players["red"].deck[0]
        self.assertFalse(drawn_card.is_base)
        # The award event should record the card id
        award = [e for e in state.event_log if e["type"] == "bauble_awarded"][0]
        self.assertIsNotNone(award["awards"][0]["desperation_card_id"])

    def test_fang_bauble_does_not_draw_desperation_card(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.phase = GamePhase.AWARD_BAUBLES
        state.round_number = 2
        state.baubles = [BaubleState(id="fang", number=6, q=0, r=0, victory_points=1, is_fang=True)]
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 1
        state.players["red"].ship.shields = 2
        state.players["blue"].ship.q = 5
        state.players["blue"].ship.r = 0

        desp_deck_before = len(state.desperation_deck.cards)
        state = resolve_next_step(state)

        # Fang should not draw a desperation card
        self.assertEqual(len(state.desperation_deck.cards), desp_deck_before)

    def test_unshielded_damage_triggers_desperation_consequence_swap_deck(self):
        """When first component is destroyed, a base card in deck is swapped for a desperation card."""
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.shields = 0
        state.players["blue"].ship.q = 1
        state.players["blue"].ship.r = 0
        self._set_hand(state, "blue", "attack_1_a")

        red_base_count_before = sum(1 for c in state.players["red"].deck if c.is_base)
        desp_count_before = sum(1 for c in state.players["red"].deck if not c.is_base)
        desp_deck_size_before = len(state.desperation_deck.cards)

        state = submit_orders(
            state, "red",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )
        state = submit_orders(
            state, "blue",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection("attack_1_a", target_player_id="red"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )

        state = resolve_next_step(state)  # cooldown
        state = resolve_next_step(state)  # action_1

        consequence_events = [e for e in state.event_log if e["type"] == "desperation_consequence"]
        # Check whether a consequence was triggered (only fires if the attack hit unshielded)
        volley = [e for e in state.event_log if e["type"] == "volley_resolved"][0]
        if volley["hit"] and volley["damage_applied"] > 0:
            self.assertEqual(len(consequence_events), 1)
            evt = consequence_events[0]
            self.assertEqual(evt["player_id"], "red")
            self.assertIn(evt["choice"], ("swap_deck", "swap_overheat", "vp_penalty"))
            if evt["choice"] in ("swap_deck", "swap_overheat"):
                # Desperation deck should have one fewer card
                self.assertEqual(len(state.desperation_deck.cards), desp_deck_size_before - 1)
                # Red's base card count should decrease by 1
                new_base_count = sum(1 for c in state.players["red"].deck if c.is_base)
                self.assertEqual(new_base_count, red_base_count_before - 1)

    def test_desperation_consequence_loses_vp_when_no_base_cards_available(self):
        """When no base cards remain in deck or overheat, player loses 1 VP."""
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.shields = 0
        state.players["blue"].ship.q = 1
        state.players["blue"].ship.r = 0
        state.players["red"].victory_points = 5

        # Replace all base cards in red's deck with desperation cards
        state.players["red"].deck = [
            desperation_card_by_id("desp_thrust_ions_a"),
            desperation_card_by_id("desp_thrust_ions_b"),
            desperation_card_by_id("desp_turbo_ions"),
        ]
        state.players["red"].overheat = []  # no base cards in overheat either
        self._set_hand(state, "blue", "attack_1_a")

        state = submit_orders(
            state, "red",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )
        state = submit_orders(
            state, "blue",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection("attack_1_a", target_player_id="red"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )

        state = resolve_next_step(state)  # cooldown
        state = resolve_next_step(state)  # action_1

        consequence_events = [e for e in state.event_log if e["type"] == "desperation_consequence"]
        volley = [e for e in state.event_log if e["type"] == "volley_resolved"][0]
        if volley["hit"] and volley["damage_applied"] > 0:
            self.assertEqual(len(consequence_events), 1)
            self.assertEqual(consequence_events[0]["choice"], "vp_penalty")
            self.assertEqual(state.players["red"].victory_points, 4)

    def test_untargeted_desperation_attack_requires_targeted_partner(self):
        """Untargeted desperation attacks must be paired with a targeted attack in the same stack."""
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_ace_shot_a")

        with self.assertRaises(RulesError):
            submit_orders(
                state,
                "red",
                OrdersSubmission(
                    stacks=(
                        ActionStack(
                            1,
                            SealMode.SEALED,
                            (OrderCardSelection("desp_ace_shot_a"),),
                        ),
                        ActionStack(2, SealMode.SEALED),
                        ActionStack(3, SealMode.SEALED),
                    ),
                ),
            )

    def test_hybrid_desperation_attack_allows_move_mode(self):
        """Hybrid desperation attacks can be selected as a move mode for the builder UI."""
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_ace_shot_a")

        submit_orders(
            state,
            "red",
            OrdersSubmission(
                stacks=(
                    ActionStack(
                        1,
                        SealMode.SEALED,
                        (OrderCardSelection("desp_ace_shot_a", orientation="forward", mode="move"),),
                    ),
                    ActionStack(2, SealMode.SEALED),
                    ActionStack(3, SealMode.SEALED),
                ),
            ),
        )

    def test_hybrid_desperation_move_mode_is_forward_only(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_ace_shot_a")

        with self.assertRaises(RulesError):
            submit_orders(
                state,
                "red",
                OrdersSubmission(
                    stacks=(
                        ActionStack(
                            1,
                            SealMode.SEALED,
                            (OrderCardSelection("desp_ace_shot_a", orientation="turn_left", mode="move"),),
                        ),
                        ActionStack(2, SealMode.SEALED),
                        ActionStack(3, SealMode.SEALED),
                    ),
                ),
            )

    def test_hybrid_desperation_attack_allows_attack_mode_with_targeted_partner(self):
        """Hybrid attack mode is legal when paired with a targeted attack."""
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "attack_1_a", "desp_ace_shot_a")

        submit_orders(
            state,
            "red",
            OrdersSubmission(
                stacks=(
                    ActionStack(
                        1,
                        SealMode.SEALED,
                        (
                            OrderCardSelection("attack_1_a", target_player_id="blue"),
                            OrderCardSelection("desp_ace_shot_a", mode="attack"),
                        ),
                    ),
                    ActionStack(2, SealMode.SEALED),
                    ActionStack(3, SealMode.SEALED),
                ),
            ),
        )

    def test_hybrid_desperation_move_mode_rejects_targeted_attack_partner(self):
        """A hybrid card cannot use move mode in a targeted attack stack."""
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "attack_1_a", "desp_ace_shot_a")

        with self.assertRaises(RulesError):
            submit_orders(
                state,
                "red",
                OrdersSubmission(
                    stacks=(
                        ActionStack(
                            1,
                            SealMode.SEALED,
                            (
                                OrderCardSelection("attack_1_a", target_player_id="blue"),
                                OrderCardSelection("desp_ace_shot_a", orientation="forward", mode="move"),
                            ),
                        ),
                        ActionStack(2, SealMode.SEALED),
                        ActionStack(3, SealMode.SEALED),
                    ),
                ),
            )

    def test_desperation_move_card_requires_forward_orientation(self):
        """Desperation move cards should be forward-only and reject other move orientations."""
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_thrust_ions_a")

        with self.assertRaises(RulesError):
            submit_orders(
                state,
                "red",
                OrdersSubmission(
                    stacks=(
                        ActionStack(
                            1,
                            SealMode.SEALED,
                            (OrderCardSelection("desp_thrust_ions_a", orientation="turn_right"),),
                        ),
                        ActionStack(2, SealMode.SEALED),
                        ActionStack(3, SealMode.SEALED),
                    ),
                ),
            )

    def test_desperation_card_not_boosted_by_overdrive(self):
        """Desperation move card played with overdrive keeps value=1 and returns to deck (not overheat)."""
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_thrust_ions_a")

        state = submit_orders(
            state, "red",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.OVERDRIVE, (OrderCardSelection("desp_thrust_ions_a"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )
        state = submit_orders(
            state, "blue",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )

        state = resolve_next_step(state)  # cooldown
        state = resolve_next_step(state)  # action_1

        # Desperation card should return to deck, NOT go to overheat
        self.assertIn("desp_thrust_ions_a", {c.id for c in state.players["red"].deck})
        self.assertNotIn("desp_thrust_ions_a", {c.id for c in state.players["red"].overheat})

        # Check movement distance was 1 (not boosted to 2)
        movement_events = [e for e in state.event_log if e["type"] == "movement_resolved"
                           and e["player_id"] == "red"]
        if movement_events:
            self.assertEqual(movement_events[0]["steps"][0]["distance"], 1)

    def test_desperate_move_uses_single_use_face_and_returns_to_desperation_deck(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_thrust_ions_a")
        desperation_deck_size_before = len(state.desperation_deck.cards)

        state = submit_orders(
            state,
            "red",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.OVERDRIVE, (OrderCardSelection("desp_thrust_ions_a", face="desperate"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )
        state = submit_orders(
            state,
            "blue",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )

        state = resolve_next_step(state)
        state = resolve_next_step(state)

        movement_events = [e for e in state.event_log if e["type"] == "movement_resolved"
                           and e["player_id"] == "red"]
        self.assertEqual(movement_events[0]["steps"][0]["distance"], 5)
        self.assertNotIn("desp_thrust_ions_a", {c.id for c in state.players["red"].deck})
        self.assertIn("desp_thrust_ions_a", {c.id for c in state.desperation_deck.cards})
        self.assertEqual(len(state.desperation_deck.cards), desperation_deck_size_before + 1)

    def test_desperate_evasive_action_adds_defense_without_movement(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_evasive_action")

        state = submit_orders(
            state,
            "red",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_evasive_action", face="desperate"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )
        state = submit_orders(
            state,
            "blue",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )

        state = resolve_next_step(state)
        state = resolve_next_step(state)

        self.assertEqual(state.players["red"].ship.movement_this_action, 0)
        self.assertEqual(state.players["red"].ship.defense_bonus_this_action, 10)
        movement_events = [e for e in state.event_log if e["type"] == "movement_resolved"
                           and e["player_id"] == "red"]
        self.assertEqual(movement_events[0]["steps"][0]["distance"], 0)
        self.assertEqual(movement_events[0]["steps"][0]["defense_bonus"], 10)

    def test_homeward_bound_warps_home_without_counting_as_movement(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_homeward_bound")
        state.players["red"].ship.q = 4
        state.players["red"].ship.r = -2
        state.players["red"].ship.facing = 2

        state = submit_orders(
            state,
            "red",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_homeward_bound", face="desperate"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )
        state = submit_orders(
            state,
            "blue",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )

        state = resolve_next_step(state)
        state = resolve_next_step(state)

        self.assertEqual((state.players["red"].ship.q, state.players["red"].ship.r), (-11, 0))
        self.assertEqual(state.players["red"].ship.facing, 2)
        self.assertEqual(state.players["red"].ship.movement_this_action, 0)
        self.assertEqual(state.players["red"].ship.defense_bonus_this_action, 5)
        movement = [e for e in state.event_log if e["type"] == "movement_resolved" and e["player_id"] == "red"][0]
        self.assertEqual(movement["steps"][0]["warp_destination"], "home")
        self.assertEqual(movement["steps"][0]["distance"], 0)

    def test_treasure_hound_warps_to_nearest_active_numbered_bauble(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_treasure_hound")
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.baubles = [
            BaubleState(id="far_active", number=1, q=6, r=0, victory_points=4),
            BaubleState(id="near_inactive", number=2, q=1, r=0, victory_points=3),
            BaubleState(id="near_active", number=1, q=2, r=0, victory_points=4),
        ]

        state = submit_orders(
            state,
            "red",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_treasure_hound", face="desperate"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )
        state = submit_orders(
            state,
            "blue",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )

        state = resolve_next_step(state)
        state = resolve_next_step(state)

        self.assertEqual((state.players["red"].ship.q, state.players["red"].ship.r), (2, 0))
        self.assertEqual(state.players["red"].ship.movement_this_action, 0)
        self.assertEqual(state.players["red"].ship.defense_bonus_this_action, 5)

    def test_nightjammer_warps_to_vp_leader_without_targeted_attack_partner(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_nightjammer")
        state.players["blue"].victory_points = 8
        state.players["blue"].ship.q = 5
        state.players["blue"].ship.r = -2
        state.players["blue"].ship.facing = 1
        state.players["red"].ship.facing = 4
        desperation_deck_size_before = len(state.desperation_deck.cards)

        state = submit_orders(
            state,
            "red",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_nightjammer", face="desperate"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )
        state = submit_orders(
            state,
            "blue",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )

        state = resolve_next_step(state)
        state = resolve_next_step(state)

        self.assertEqual((state.players["red"].ship.q, state.players["red"].ship.r), (4, -1))
        self.assertEqual(state.players["red"].ship.facing, 1)
        self.assertEqual(state.players["red"].ship.movement_this_action, 0)
        self.assertEqual(state.players["red"].ship.defense_bonus_this_action, 5)
        self.assertNotIn("desp_nightjammer", {c.id for c in state.players["red"].deck})
        self.assertIn("desp_nightjammer", {c.id for c in state.desperation_deck.cards})
        self.assertEqual(len(state.desperation_deck.cards), desperation_deck_size_before + 1)

    def test_desperate_steady_shot_adds_aim_and_damage(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "attack_1_a", "desp_steady_shot_a")
        state.players["blue"].ship.shields = 0
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["blue"].ship.q = 1
        state.players["blue"].ship.r = 0

        state = submit_orders(
            state,
            "red",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED, (
                    OrderCardSelection("attack_1_a", target_player_id="blue"),
                    OrderCardSelection("desp_steady_shot_a", face="desperate"),
                )),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )
        state = submit_orders(
            state,
            "blue",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )

        state = resolve_next_step(state)
        state = resolve_next_step(state)

        volley = [e for e in state.event_log if e["type"] == "volley_resolved"][0]
        self.assertEqual(volley["aim_bonus"], 2)
        self.assertEqual(volley["damage"], 2)
        self.assertEqual(volley["roll_total"], volley["roll"] + 2)
        moved = [e for e in state.event_log if e["type"] == "action_cards_moved"
                 and e["player_id"] == "red"][0]
        self.assertIn("desp_steady_shot_a", moved["returned_to_desperation_deck"])

    def test_desperate_deadeye_always_hits(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "attack_1_a", "desp_deadeye")
        state.players["blue"].ship.shields = 0
        state.players["red"].ship.q = -14
        state.players["red"].ship.r = 0
        state.players["blue"].ship.q = 14
        state.players["blue"].ship.r = 0

        state = submit_orders(
            state,
            "red",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED, (
                    OrderCardSelection("attack_1_a", target_player_id="blue"),
                    OrderCardSelection("desp_deadeye", face="desperate"),
                )),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )
        state = submit_orders(
            state,
            "blue",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )

        state = resolve_next_step(state)
        state = resolve_next_step(state)

        volley = [e for e in state.event_log if e["type"] == "volley_resolved"][0]
        self.assertTrue(volley["always_hits"])
        self.assertTrue(volley["hit"])
        self.assertEqual(volley["aim_bonus"], 999)
        self.assertEqual(volley["roll_total"], volley["roll"] + 999)
        self.assertGreaterEqual(volley["roll_total"], volley["defense_threshold"])

    def test_desperate_self_destruct_is_targeted_range_two_damage_four(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_self_destruct")
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["blue"].ship.q = 2
        state.players["blue"].ship.r = 0
        state.players["blue"].ship.shields = 0

        state = submit_orders(
            state,
            "red",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_self_destruct", face="desperate", target_player_id="blue"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )
        state = submit_orders(
            state,
            "blue",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )

        state = resolve_next_step(state)
        state = resolve_next_step(state)

        volley = [e for e in state.event_log if e["type"] == "volley_resolved"][0]
        self.assertEqual(volley["damage"], 4)
        self.assertEqual(volley["max_range"], 2)
        self.assertTrue(volley["in_range"])
        moved = [e for e in state.event_log if e["type"] == "action_cards_moved" and e["player_id"] == "red"][0]
        self.assertIn("desp_self_destruct", moved["returned_to_desperation_deck"])

    def test_desperate_self_destruct_misses_outside_range_two(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_self_destruct")
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["blue"].ship.q = 3
        state.players["blue"].ship.r = 0
        state.players["blue"].ship.shields = 0

        state = submit_orders(
            state,
            "red",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_self_destruct", face="desperate", target_player_id="blue"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )
        state = submit_orders(
            state,
            "blue",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )

        state = resolve_next_step(state)
        state = resolve_next_step(state)

        volley = [e for e in state.event_log if e["type"] == "volley_resolved"][0]
        self.assertFalse(volley["in_range"])
        self.assertFalse(volley["hit"])
        self.assertEqual(volley["damage_applied"], 0)

    def test_desperate_death_blossom_attacks_all_opponents_at_fixed_defense_ten(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue", "green"), seed=1))
        self._set_hand(state, "red", "desp_death_blossom")
        state.players["blue"].ship.q = 1
        state.players["blue"].ship.r = 0
        state.players["green"].ship.q = 5
        state.players["green"].ship.r = 0

        state = submit_orders(
            state,
            "red",
            OrdersSubmission(stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_death_blossom", face="desperate"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )),
        )
        for player_id in ("blue", "green"):
            state = submit_orders(
                state,
                player_id,
                OrdersSubmission(stacks=(
                    ActionStack(1, SealMode.SEALED),
                    ActionStack(2, SealMode.SEALED),
                    ActionStack(3, SealMode.SEALED),
                )),
            )

        state = resolve_next_step(state)
        state = resolve_next_step(state)

        volleys = [e for e in state.event_log if e["type"] == "volley_resolved"]
        self.assertEqual({volley["target_id"] for volley in volleys}, {"blue", "green"})
        for volley in volleys:
            self.assertEqual(volley["card_ids"], ["desp_death_blossom"])
            self.assertEqual(volley["damage"], 1)
            self.assertEqual(volley["fixed_defense_threshold"], 10)
            self.assertEqual(volley["defense_threshold"], 10)
        moved = [e for e in state.event_log if e["type"] == "action_cards_moved" and e["player_id"] == "red"][0]
        self.assertIn("desp_death_blossom", moved["returned_to_desperation_deck"])

    def _set_hand(self, state, player_id, *card_ids):
        player = state.players[player_id]
        requested = set(card_ids)
        player.deck = [card for card in player.deck if card.id not in requested]
        player.discard = [card for card in player.discard if card.id not in requested]
        player.overheat = [card for card in player.overheat if card.id not in requested]
        player.hand = [card_by_id(card_id) for card_id in card_ids]


if __name__ == "__main__":
    unittest.main()
