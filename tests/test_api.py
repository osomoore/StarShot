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
        created = self.client.post("/api/games", json={"player_ids": ["red", "blue"], "seed": 3})
        self.assertEqual(created.status_code, 200)
        game_id = created.json()["game_id"]

        listed = self.client.get("/api/games")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["games"][0]["id"], game_id)

        red_orders = {
            "player_id": "red",
            "orders": {
                "stacks": [
                    {"action_number": 1, "seal_mode": "sealed", "cards": [{"card_id": "move_1_a"}]},
                    {"action_number": 2, "seal_mode": "sealed", "cards": [{"card_id": "move_1_b"}]},
                    {"action_number": 3, "seal_mode": "overdrive", "cards": [{"card_id": "move_2_a"}]},
                ]
            },
        }
        blue_orders = {
            "player_id": "blue",
            "orders": {
                "stacks": [
                    {
                        "action_number": 1,
                        "seal_mode": "sealed",
                        "cards": [{"card_id": "attack_1_a", "target_player_id": "red"}],
                    },
                    {
                        "action_number": 2,
                        "seal_mode": "sealed",
                        "cards": [{"card_id": "attack_1_b", "target_player_id": "red"}],
                    },
                    {
                        "action_number": 3,
                        "seal_mode": "sealed",
                        "cards": [{"card_id": "attack_2_a", "target_player_id": "red"}],
                    },
                ]
            },
        }

        first_submit = self.client.post(f"/api/games/{game_id}/orders", json=red_orders)
        self.assertEqual(first_submit.status_code, 200)
        self.assertEqual(first_submit.json()["state"]["phase"], "give_orders")

        second_submit = self.client.post(f"/api/games/{game_id}/orders", json=blue_orders)
        self.assertEqual(second_submit.status_code, 200)
        self.assertEqual(second_submit.json()["state"]["phase"], "cooldown")

        resolved = self.client.post(f"/api/games/{game_id}/resolve")
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json()["state"]["phase"], "action_1")

        shown = self.client.get(f"/api/games/{game_id}")
        self.assertEqual(shown.status_code, 200)
        self.assertTrue(shown.json()["state"]["players"]["red"]["has_submitted_orders"])
        self.assertIsNone(shown.json()["state"]["players"]["red"]["prepared_orders"])


if __name__ == "__main__":
    unittest.main()
