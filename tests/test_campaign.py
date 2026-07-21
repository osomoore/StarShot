from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from starshot.rules.decks import card_for_player, create_designed_deck
from starshot.rules.models import GameResult
from starshot.v2.campaign import (
    _active_v2_catalog,
    _default_catalog,
    award_for_completed_match,
    component_catalog,
    normalize_catalog,
)
from starshot.v2.store import V2Store


class CampaignRewardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = V2Store(Path(self.temp.name) / "campaign.sqlite3")
        self.user = self.store.create_user("winner", "unused")
        self.match = {
            "id": "campaign_match_1",
            "seat_list": [
                {"player_id": "winner", "user_id": self.user["id"], "ai_type": None},
                {"player_id": "bot", "user_id": None, "ai_type": "salvage"},
            ],
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_winning_player_gains_new_component_once(self) -> None:
        state = SimpleNamespace(
            result=GameResult(winner_ids=("winner",), reason="round_six_victory_points"),
            event_log=[],
            players={"winner": object(), "bot": object()},
        )

        award_for_completed_match(self.store, self.match, state)
        inventory = self.store.campaign_component_ids(self.user["id"])
        self.assertEqual(len(inventory), 1)
        self.assertIn(inventory[0], {entry["id"] for entry in component_catalog(self.store)})
        self.assertEqual(
            self.store.campaign_award_for_match(self.user["id"], self.match["id"])["source_kind"],
            "dominance",
        )

        award_for_completed_match(self.store, self.match, state)
        self.assertEqual(self.store.campaign_component_ids(self.user["id"]), inventory)

    def test_destroying_opposing_ship_earns_wreckage_reward_even_without_vp_win(self) -> None:
        state = SimpleNamespace(
            result=GameResult(winner_ids=("bot",), reason="round_six_victory_points"),
            event_log=[{
                "type": "volley_resolved", "attacker_id": "winner", "target_id": "bot",
                "target_destroyed": True,
            }],
            players={"winner": object(), "bot": object()},
        )

        award_for_completed_match(self.store, self.match, state)
        self.assertEqual(len(self.store.campaign_component_ids(self.user["id"])), 1)
        self.assertEqual(
            self.store.campaign_award_for_match(self.user["id"], self.match["id"])["source_kind"],
            "wreckage",
        )

    def test_initial_catalog_clones_every_physical_active_base_card(self) -> None:
        catalog = _default_catalog()
        self.assertEqual(len(catalog), len(_active_v2_catalog().base_cards))
        self.assertTrue(all(entry["card"]["copies"] == 1 for entry in catalog))
        self.assertTrue(all(entry["starting_cards"] for entry in catalog))

    def test_reward_card_uses_deck_editor_faces_and_orientations(self) -> None:
        component = normalize_catalog([{
            "id": "hook_thruster",
            "name": "Hook Thruster",
            "description": "Turns hard before moving.",
            "cost": 2,
            "component_type": "engine",
            "card": {
                "name": "Hook Turn",
                "copies": 1,
                "side_a_type": "Basic",
                "side_a_1": "Turn Left, Move 3",
                "side_a_2": "Turn Right, Move 3",
            },
        }])[0]

        starting_card = component["starting_cards"][0]
        self.assertEqual(starting_card["orientation_options"], ["turn_left", "turn_right"])
        deck = create_designed_deck({}, component["starting_cards"])
        self.assertEqual([card.id for card in deck], [starting_card["id"]])
        player = SimpleNamespace(ship=SimpleNamespace(layout={"bonus_cards": component["starting_cards"]}))
        self.assertEqual(card_for_player(player, starting_card["id"]).name, "Hook Turn")

    def test_legacy_dropdown_entry_migrates_to_owned_card_definition(self) -> None:
        default = _default_catalog()[0]
        migrated = normalize_catalog([{
            "id": "legacy_reward",
            "name": "Legacy Reward",
            "description": "Old dropdown entry.",
            "cost": 1,
            "component_type": "engine",
            "card_id": default["legacy_card_id"],
        }])[0]
        self.assertIn("side_a_type", migrated["card"])
        self.assertEqual(migrated["card_id"], "campaign_legacy_reward_card")


if __name__ == "__main__":
    unittest.main()
