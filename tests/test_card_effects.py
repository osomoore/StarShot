import unittest

from starshot.rules.card_effects import interpret_card
from starshot.rules.decks import card_by_id
from starshot.rules.desperation import desperation_card_by_id
from starshot.rules.models import CardFamily, OrderCardSelection, SealMode


class CardEffectsTests(unittest.TestCase):
    def test_base_move_ignores_overdrive_for_card_value(self):
        card = card_by_id("controlled_move_2_a")
        effect = interpret_card(card, OrderCardSelection(card.id), SealMode.OVERDRIVE)

        self.assertEqual(effect.family, CardFamily.MOVE)
        self.assertIsNotNone(effect.move)
        self.assertEqual(effect.move.distance, 2)
        self.assertEqual(effect.move.orientation_options, ("forward", "turn_left", "turn_right"))

    def test_base_attack_ignores_overdrive_for_aim_value(self):
        card = card_by_id("targeted_attack_aim_2_a")
        effect = interpret_card(
            card,
            OrderCardSelection(card.id, target_player_id="blue"),
            SealMode.OVERDRIVE,
        )

        self.assertEqual(effect.family, CardFamily.ATTACK)
        self.assertIsNotNone(effect.attack)
        self.assertEqual(effect.attack.base_damage, 1)
        self.assertEqual(effect.attack.aim_bonus, 2)
        self.assertEqual(effect.attack.damage, 1)
        self.assertTrue(effect.attack.requires_target)

    def test_hybrid_basic_face_uses_selected_mode(self):
        card = desperation_card_by_id("desp_steady_shot_a")
        move_effect = interpret_card(card, OrderCardSelection(card.id, mode="move"), SealMode.SEALED)
        attack_effect = interpret_card(card, OrderCardSelection(card.id, mode="attack"), SealMode.SEALED)

        self.assertEqual(move_effect.family, CardFamily.MOVE)
        self.assertIsNotNone(move_effect.move)
        self.assertEqual(attack_effect.family, CardFamily.ATTACK)
        self.assertIsNotNone(attack_effect.attack)
        self.assertFalse(attack_effect.attack.requires_target)

    def test_desperate_face_returns_structured_attack_contribution(self):
        card = desperation_card_by_id("desp_steady_shot_a")
        effect = interpret_card(card, OrderCardSelection(card.id, face="desperate"), SealMode.OVERDRIVE)

        self.assertTrue(effect.is_desperate_face)
        self.assertEqual(effect.family, CardFamily.ATTACK)
        self.assertIsNotNone(effect.attack)
        self.assertEqual(effect.attack.base_damage, 1)
        self.assertEqual(effect.attack.damage_bonus, 1)
        self.assertEqual(effect.attack.damage, 2)
        self.assertEqual(effect.attack.aim_bonus, 2)


if __name__ == "__main__":
    unittest.main()
