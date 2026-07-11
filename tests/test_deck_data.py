import tempfile
import unittest
from pathlib import Path

from starshot.rules.deck_data import default_deck_set_path, load_deck_catalog


class DeckDataTests(unittest.TestCase):
    def test_default_catalog_matches_expected_core_counts(self):
        catalog = load_deck_catalog(default_deck_set_path())

        self.assertEqual(catalog.id, "core_0_2")
        self.assertEqual(len(catalog.base_cards), 10)
        self.assertEqual(len(catalog.desperation_cards), 41)
        self.assertIn("move_1_a", catalog.base_card_map)
        self.assertIn("desp_afterburners_a", catalog.desperation_card_map)
        self.assertIn("desp_lead_the_target", catalog.card_map)

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


if __name__ == "__main__":
    unittest.main()
