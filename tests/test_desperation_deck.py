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
    all_desperation_cards,
    card_by_id,
    create_desperation_deck,
    draw_desperation_card,
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
        # The drawn card should be non-base
        drawn_card = state.players["red"].deck[-1]
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
        from starshot.rules.decks import desperation_card_by_id
        state.players["red"].deck = [
            desperation_card_by_id("desp_thrust_ions_a"),
            desperation_card_by_id("desp_thrust_ions_b"),
            desperation_card_by_id("desp_turbo_ions"),
        ]
        state.players["red"].overheat = []  # no base cards in overheat either

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
        from starshot.rules.decks import desperation_card_by_id
        state.players["red"].deck.append(desperation_card_by_id("desp_ace_shot_a"))

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
        from starshot.rules.decks import desperation_card_by_id
        state.players["red"].deck.append(desperation_card_by_id("desp_ace_shot_a"))

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

    def test_desperation_move_card_requires_forward_orientation(self):
        """Desperation move cards should be forward-only and reject other move orientations."""
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        from starshot.rules.decks import desperation_card_by_id
        desp_card = desperation_card_by_id("desp_thrust_ions_a")
        state.players["red"].deck.append(desp_card)

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
        # Give red a desperation move card
        from starshot.rules.decks import desperation_card_by_id
        desp_card = desperation_card_by_id("desp_thrust_ions_a")
        state.players["red"].deck.append(desp_card)

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


if __name__ == "__main__":
    unittest.main()
