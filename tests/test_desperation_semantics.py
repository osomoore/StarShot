"""Tests for desperate face card semantics and effect metadata."""

import unittest

from starshot.rules.card_effects import (
    card_aim_bonus,
    card_damage_bonus,
    card_orientation_options,
    card_requires_target,
    card_value,
    selected_card_family,
)
from starshot.rules.desperation import desperation_card_by_id
from starshot.rules.models import CardFamily, OrderCardSelection, SealMode


class DesperationCardSemanticsTests(unittest.TestCase):
    def test_hybrid_basic_move_mode(self):
        card = desperation_card_by_id("desp_steady_shot_a")
        self.assertEqual(selected_card_family(card, OrderCardSelection(card.id, mode="move")), CardFamily.MOVE)

    def test_hybrid_basic_attack_mode(self):
        card = desperation_card_by_id("desp_steady_shot_a")
        self.assertEqual(selected_card_family(card, OrderCardSelection(card.id, mode="attack")), CardFamily.ATTACK)

    def test_hybrid_basic_face_requires_mode(self):
        card = desperation_card_by_id("desp_steady_shot_a")
        with self.assertRaises(ValueError):
            selected_card_family(card, OrderCardSelection(card.id))

    def test_desperate_steady_shot_face_semantics(self):
        card = desperation_card_by_id("desp_steady_shot_a")
        sel = OrderCardSelection(card.id, face="desperate")
        self.assertEqual(selected_card_family(card, sel), CardFamily.ATTACK)
        self.assertFalse(card_requires_target(card, sel))
        self.assertEqual(card_value(card, sel, SealMode.OVERDRIVE), 0)
        self.assertEqual(card_aim_bonus(card, sel), 2)
        self.assertEqual(card_damage_bonus(card, sel), 1)

    def test_afterburners_orientation_options(self):
        card = desperation_card_by_id("desp_afterburners_a")
        sel = OrderCardSelection(card.id)
        self.assertIn("forward", card_orientation_options(card, sel))
        self.assertIn("turn_right", card_orientation_options(card, sel))
        self.assertIn("turn_left", card_orientation_options(card, sel))

    def test_crack_shot_requires_target(self):
        card = desperation_card_by_id("desp_crack_shot_a")
        sel = OrderCardSelection(card.id, face="desperate", target_player_id="blue")
        self.assertTrue(card_requires_target(card, sel))
        self.assertEqual(card_damage_bonus(card, sel), 1)

    def test_thrust_ions_desperate_face_move_5(self):
        card = desperation_card_by_id("desp_thrust_ions_a")
        sel = OrderCardSelection(card.id, face="desperate")
        self.assertEqual(selected_card_family(card, sel), CardFamily.MOVE)
        self.assertEqual(card_value(card, sel, SealMode.SEALED), 5)

    def test_turbo_ions_desperate_face_move_10(self):
        card = desperation_card_by_id("desp_turbo_ions")
        sel = OrderCardSelection(card.id, face="desperate")
        self.assertEqual(card_value(card, sel, SealMode.SEALED), 10)

    def test_nightjammer_desperate_face_warp_and_defense(self):
        card = desperation_card_by_id("desp_nightjammer")
        self.assertEqual(card.desperate_face.warp_destination, "leader")
        self.assertEqual(card.desperate_face.defense_bonus, 5)

    def test_starshot_desperate_face_always_hits(self):
        card = desperation_card_by_id("desp_starshot")
        self.assertEqual(card.desperate_face.aim_bonus, 999)
        self.assertTrue(card.desperate_face.always_hits)

    def test_side_slip_desperate_face_orientation_options(self):
        card = desperation_card_by_id("desp_side_slip_a")
        self.assertIn("slip_right", card.desperate_face.orientation_options)
        self.assertIn("slip_left", card.desperate_face.orientation_options)
        self.assertEqual(card.desperate_face.value, 4)

    def test_drift_king_desperate_face_double_turn_right(self):
        card = desperation_card_by_id("desp_drift_king_a")
        self.assertTrue(card.desperate_face.double_turn_right)
        self.assertEqual(card.desperate_face.value, 4)

    def test_crazy_ivan_desperate_face_u_turn_options(self):
        card = desperation_card_by_id("desp_crazy_ivan_a")
        self.assertIn("u_turn_move", card.desperate_face.orientation_options)
        self.assertIn("u_turn_attack", card.desperate_face.orientation_options)

    def test_active_cooling_desperate_face_flag(self):
        card = desperation_card_by_id("desp_active_cooling_a")
        self.assertTrue(card.desperate_face.active_cooling)
        self.assertEqual(card.desperate_face.value, 1)

    def test_lead_the_target_desperate_face_flags(self):
        card = desperation_card_by_id("desp_lead_the_target")
        self.assertTrue(card.desperate_face.lead_the_target)
        self.assertEqual(card.desperate_face.damage_bonus, 1)

    def test_deferred_desperate_faces_are_none(self):
        for card_id in ("desp_reconfigure_a", "desp_hull_repair_a",
                        "desp_holdo_maneuver", "desp_scattershot", "desp_overdrive_2x"):
            card = desperation_card_by_id(card_id)
            self.assertIsNone(card.desperate_face, f"{card_id} should have no desperate face yet")


if __name__ == "__main__":
    unittest.main()
