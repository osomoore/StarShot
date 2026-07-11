import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from starshot.api.app import app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["STARSHOT_DB"] = str(Path(self.temp_dir.name) / "games.sqlite3")
        self.client = TestClient(app)

    def tearDown(self):
        os.environ.pop("STARSHOT_DB", None)
        self.temp_dir.cleanup()

    def test_create_list_get_and_submit_orders(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["deck_set_id"], "core_0_2_sides")

        created = self.client.post("/api/games", json={"player_ids": ["red", "blue"], "seed": 3})
        self.assertEqual(created.status_code, 200)
        game_id = created.json()["game_id"]
        self.assertEqual(created.json()["state"]["deck_set_id"], "core_0_2_sides")

        listed = self.client.get("/api/games")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["games"][0]["id"], game_id)
        self.assertEqual(listed.json()["games"][0]["deck_set_id"], "core_0_2_sides")

        state = created.json()["state"]
        red_cards = [card["id"] for card in state["players"]["red"]["hand"]]
        blue_cards = [card["id"] for card in state["players"]["blue"]["hand"]]
        red_orders = {
            "player_id": "red",
            "orders": {
                "stacks": [
                    {"action_number": 1, "seal_mode": "sealed", "cards": [{"card_id": red_cards[0]}]},
                    {"action_number": 2, "seal_mode": "sealed", "cards": [{"card_id": red_cards[1]}]},
                    {"action_number": 3, "seal_mode": "overdrive", "cards": [{"card_id": red_cards[2]}]},
                ]
            },
        }
        blue_orders = {
            "player_id": "blue",
            "orders": {
                "stacks": [
                    {"action_number": 1, "seal_mode": "sealed", "cards": [{"card_id": blue_cards[0]}]},
                    {"action_number": 2, "seal_mode": "sealed", "cards": [{"card_id": blue_cards[1]}]},
                    {"action_number": 3, "seal_mode": "sealed", "cards": [{"card_id": blue_cards[2]}]},
                ]
            },
        }

        first_submit = self.client.post(f"/api/games/{game_id}/orders", json=red_orders)
        self.assertEqual(first_submit.status_code, 200)
        self.assertEqual(first_submit.json()["state"]["phase"], "give_orders")

        second_submit = self.client.post(f"/api/games/{game_id}/orders", json=blue_orders)
        self.assertEqual(second_submit.status_code, 200)
        self.assertEqual(second_submit.json()["state"]["phase"], "action_1")

        resolved = self.client.post(f"/api/games/{game_id}/resolve")
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json()["state"]["phase"], "action_2")

        shown = self.client.get(f"/api/games/{game_id}")
        self.assertEqual(shown.status_code, 200)
        self.assertTrue(shown.json()["state"]["players"]["red"]["has_submitted_orders"])
        self.assertIsNone(shown.json()["state"]["players"]["red"]["prepared_orders"])

    def test_debug_draw_desperation_card_type_to_hand(self):
        created = self.client.post("/api/games", json={"player_ids": ["red", "blue"], "seed": 3})
        self.assertEqual(created.status_code, 200)
        game_id = created.json()["game_id"]
        state = created.json()["state"]
        hand_before = len(state["players"]["red"]["hand"])
        deck_before = len(state["desperation_deck"]["cards"])

        drawn = self.client.post(
            f"/api/games/{game_id}/debug/desperation-draw",
            json={"player_id": "red", "card_id": "desp_afterburners_a"},
        )

        self.assertEqual(drawn.status_code, 200)
        next_state = drawn.json()["state"]
        self.assertEqual(len(next_state["players"]["red"]["hand"]), hand_before + 1)
        self.assertEqual(len(next_state["desperation_deck"]["cards"]), deck_before - 1)
        self.assertEqual(next_state["players"]["red"]["hand"][-1]["name"], "Afterburners")
        self.assertEqual(next_state["event_log"][-1]["type"], "debug_desperation_drawn")
        self.assertEqual(next_state["event_log"][-1]["card_name"], "Afterburners")


if __name__ == "__main__":
    unittest.main()
