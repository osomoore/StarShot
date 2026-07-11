import os
import tempfile
import unittest
from pathlib import Path

from starshot.rules import GameConfig, create_initial_state
from starshot.rules.deck_data import active_catalog, default_deck_set_path, load_deck_catalog


class DeckDataTests(unittest.TestCase):
    def test_default_catalog_matches_expected_core_counts(self):
        catalog = load_deck_catalog(default_deck_set_path())

        self.assertEqual(catalog.id, "core_0_2_sides")
        self.assertTrue(catalog.rules_config.overheat_pile)
        self.assertEqual(len(catalog.base_cards), 10)
        self.assertEqual(len(catalog.desperation_cards), 41)
        self.assertIn("controlled_move_1_a", catalog.base_card_map)
        self.assertIn("desp_afterburners_a", catalog.desperation_card_map)
        self.assertIn("desp_lead_the_target", catalog.card_map)

        self.assertEqual([card.id for card in catalog.base_cards[:3]], ["controlled_move_1_a", "controlled_move_1_b", "controlled_move_1_c"])
        self.assertIn("targeted_attack_aim_2_a", catalog.base_card_map)
        self.assertEqual(catalog.desperation_card_map["desp_turbo_ions"].id, "desp_turbo_ions")

    def test_english_card_text_supports_mixed_faces_and_orientations(self):
        catalog = load_deck_catalog(default_deck_set_path())

        steady_shot = catalog.desperation_card_map["desp_steady_shot_a"]
        self.assertTrue(steady_shot.is_hybrid)
        self.assertEqual(steady_shot.value, 2)
        self.assertEqual(steady_shot.desperate_face.aim_bonus, 2)
        self.assertEqual(steady_shot.desperate_face.damage_bonus, 1)

        side_slip = catalog.desperation_card_map["desp_side_slip_a"]
        self.assertEqual(side_slip.desperate_face.orientation_options, ("slip_right", "slip_left"))
        self.assertEqual(side_slip.desperate_face.side_slip_direction, "right")

        crazy_ivan = catalog.desperation_card_map["desp_crazy_ivan_a"]
        self.assertEqual(crazy_ivan.desperate_face.family.value, "hybrid")
        self.assertEqual(crazy_ivan.desperate_face.orientation_options, ("u_turn_move", "u_turn_attack"))

        afterburners = catalog.desperation_card_map["desp_afterburners_a"]
        self.assertTrue(afterburners.no_basic_face)

    def test_duplicate_card_ids_are_rejected_on_load(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            deck_path = Path(temp_dir)
            (deck_path / "manifest.toml").write_text(
                'id = "bad"\nname = "Bad"\nrules_version = "test"\n',
                encoding="utf-8",
            )
            (deck_path / "base_deck.toml").write_text(
                """
[[cards]]
id = "duplicate"
name = "Duplicate"
copies = ["same_id", "same_id"]
family = "move"
value = 1
requires_target = false
""".strip(),
                encoding="utf-8",
            )
            (deck_path / "desperation_deck.toml").write_text(
                """
[[cards]]
id = "desp_test"
name = "Desperation Test"
copies = ["desp_test"]
family = "move"
value = 1
requires_target = false
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Duplicate card id"):
                load_deck_catalog(deck_path)

    def test_unknown_orientation_is_rejected_on_load(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            deck_path = Path(temp_dir)
            (deck_path / "manifest.toml").write_text(
                'id = "bad"\nname = "Bad"\nrules_version = "test"\n',
                encoding="utf-8",
            )
            (deck_path / "base_deck.toml").write_text(
                """
[[cards]]
id = "bad_move"
name = "Bad Move"
copies = ["bad_move"]
family = "move"
value = 1
orientation_options = ["barrel_roll"]
requires_target = false
""".strip(),
                encoding="utf-8",
            )
            (deck_path / "desperation_deck.toml").write_text(
                """
[[cards]]
id = "desp_test"
name = "Desperation Test"
copies = ["desp_test"]
family = "move"
value = 1
requires_target = false
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "unknown: barrel_roll"):
                load_deck_catalog(deck_path)

    def test_active_catalog_can_be_swapped_with_environment_variable(self):
        original = os.environ.get("STARSHOT_DECK_SET")
        with tempfile.TemporaryDirectory() as temp_dir:
            deck_path = Path(temp_dir)
            (deck_path / "manifest.toml").write_text(
                'id = "tiny_test"\nname = "Tiny Test"\nrules_version = "test"\n',
                encoding="utf-8",
            )
            (deck_path / "base_deck.toml").write_text(
                """
[[cards]]
id = "tiny_move"
name = "Tiny Move"
copies = ["tiny_move_a", "tiny_move_b", "tiny_move_c", "tiny_move_d", "tiny_move_e"]
family = "move"
value = 1
requires_target = false
""".strip(),
                encoding="utf-8",
            )
            (deck_path / "desperation_deck.toml").write_text(
                """
[[cards]]
id = "tiny_desperation"
name = "Tiny Desperation"
copies = ["tiny_desperation"]
family = "move"
value = 1
requires_target = false
""".strip(),
                encoding="utf-8",
            )
            (deck_path / "config.toml").write_text('overheat_pile = "no"\n', encoding="utf-8")

            try:
                os.environ["STARSHOT_DECK_SET"] = str(deck_path)
                catalog = active_catalog()
                state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))

                self.assertEqual(catalog.id, "tiny_test")
                self.assertFalse(catalog.rules_config.overheat_pile)
                self.assertEqual(state.deck_set_id, "tiny_test")
                self.assertEqual(
                    [card.id for card in state.players["red"].hand],
                    ["tiny_move_a", "tiny_move_b", "tiny_move_c", "tiny_move_d", "tiny_move_e"],
                )
            finally:
                if original is None:
                    os.environ.pop("STARSHOT_DECK_SET", None)
                else:
                    os.environ["STARSHOT_DECK_SET"] = original


if __name__ == "__main__":
    unittest.main()
