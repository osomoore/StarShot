"""Tests for desperation deck definitions, draw logic, and card counts."""

import unittest
from random import Random

from starshot.rules import GameConfig, create_initial_state
from starshot.rules.decks import card_by_id
from starshot.rules.desperation import (
    all_desperation_cards,
    create_desperation_deck,
    desperation_card_by_id,
    draw_desperation_card,
    return_desperation_card,
)
from starshot.rules.models import Card, CardFamily, DesperationDeck


class DesperationDeckDefinitionTests(unittest.TestCase):
    def test_desperation_deck_has_expected_card_count(self):
        self.assertEqual(len(all_desperation_cards()), 41)

    def test_all_desperation_cards_are_not_base(self):
        for card in all_desperation_cards():
            self.assertFalse(card.is_base, f"{card.id} should have is_base=False")

    def test_card_by_id_finds_base_cards(self):
        card = card_by_id("controlled_move_1_a")
        self.assertTrue(card.is_base)
        self.assertEqual(card.family, CardFamily.MOVE)

    def test_card_by_id_finds_desperation_cards(self):
        card = card_by_id("desp_thrust_ions_a")
        self.assertFalse(card.is_base)
        self.assertEqual(card.family, CardFamily.MOVE)
        self.assertEqual(card.value, 2)

    def test_card_by_id_raises_on_unknown_id(self):
        with self.assertRaises(KeyError):
            card_by_id("nonexistent_card")

    def test_afterburners_are_no_basic_face(self):
        for suffix in ("a", "b", "c", "d", "e"):
            card = desperation_card_by_id(f"desp_afterburners_{suffix}")
            self.assertTrue(card.no_basic_face)
            self.assertEqual(card.value, 3)
            self.assertEqual(card.family, CardFamily.MOVE)

    def test_crack_shot_are_no_basic_face(self):
        for suffix in ("a", "b", "c", "d", "e"):
            card = desperation_card_by_id(f"desp_crack_shot_{suffix}")
            self.assertTrue(card.no_basic_face)
            self.assertEqual(card.family, CardFamily.ATTACK)
            self.assertTrue(card.requires_target)

    def test_hybrid_cards_have_controlled_move_2_basic_value(self):
        hybrid_ids = [
            "desp_steady_shot_a", "desp_side_slip_a", "desp_drift_king_a",
            "desp_thrust_ions_a", "desp_crazy_ivan_a", "desp_active_cooling_a",
            "desp_reconfigure_a", "desp_hull_repair_a",
        ]
        for card_id in hybrid_ids:
            card = desperation_card_by_id(card_id)
            self.assertTrue(card.is_hybrid, card_id)
            self.assertEqual(card.value, 2, card_id)

    def test_singleton_cards_have_correct_values(self):
        self.assertEqual(desperation_card_by_id("desp_turbo_ions").value, 3)
        self.assertEqual(desperation_card_by_id("desp_nightjammer").value, 4)
        self.assertEqual(desperation_card_by_id("desp_holdo_maneuver").value, 5)
        self.assertEqual(desperation_card_by_id("desp_starshot").value, 6)
        self.assertEqual(desperation_card_by_id("desp_scattershot").value, 7)
        self.assertEqual(desperation_card_by_id("desp_lead_the_target").value, 8)
        self.assertEqual(desperation_card_by_id("desp_overdrive_2x").value, 2)


class DesperationDeckDrawTests(unittest.TestCase):
    def test_create_deck_has_all_cards_shuffled(self):
        deck = create_desperation_deck(Random(42))
        self.assertEqual(len(deck.cards), 41)
        self.assertFalse(deck.shuffle_marker_on_top)

    def test_draw_removes_from_bottom(self):
        deck = create_desperation_deck(Random(42))
        first_id = deck.cards[0].id
        drawn = draw_desperation_card(deck, Random(0))
        self.assertEqual(drawn.id, first_id)
        self.assertEqual(len(deck.cards), 40)

    def test_draw_all_cards_triggers_reshuffle(self):
        deck = create_desperation_deck(Random(42))
        rng = Random(99)
        for _ in range(41):
            draw_desperation_card(deck, rng)
        self.assertEqual(len(deck.cards), 0)
        self.assertTrue(deck.shuffle_marker_on_top)
        next_card = draw_desperation_card(deck, Random(7))
        self.assertIsNotNone(next_card)
        self.assertEqual(len(deck.cards), 40)
        self.assertFalse(deck.shuffle_marker_on_top)

    def test_draw_from_empty_deck_reshuffles(self):
        deck = DesperationDeck(cards=[], shuffle_marker_on_top=True)
        card = draw_desperation_card(deck, Random(5))
        self.assertIsNotNone(card)
        self.assertFalse(card.is_base)

    def test_return_card_appends_and_clears_marker(self):
        card = desperation_card_by_id("desp_thrust_ions_a")
        deck = DesperationDeck(cards=[], shuffle_marker_on_top=True)
        return_desperation_card(deck, card)
        self.assertEqual(deck.cards, [card])
        self.assertFalse(deck.shuffle_marker_on_top)

    def test_initial_state_has_desperation_deck_with_cards(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self.assertEqual(len(state.desperation_deck.cards), 41)
        self.assertFalse(state.desperation_deck.shuffle_marker_on_top)


if __name__ == "__main__":
    unittest.main()
