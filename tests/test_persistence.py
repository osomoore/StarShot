import tempfile
import unittest
from pathlib import Path

from starshot.persistence import SQLiteGameStore
from starshot.rules import GameConfig, create_initial_state


class SQLiteGameStoreTests(unittest.TestCase):
    def test_saves_and_loads_game_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteGameStore(Path(directory) / "games.sqlite3")
            state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=3))

            game_id = store.create_game(state)
            loaded = store.load_game(game_id)

            self.assertEqual(loaded.round_number, 1)
            self.assertEqual(loaded.phase, state.phase)
            self.assertEqual(loaded.deck_set_id, "core_0_2_sides")
            self.assertEqual(set(loaded.players), {"red", "blue"})
            self.assertEqual(loaded.starting_player_id, state.starting_player_id)

    def test_lists_games(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteGameStore(Path(directory) / "games.sqlite3")
            state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=3))

            game_id = store.create_game(state)
            games = store.list_games()

            self.assertEqual(games[0]["id"], game_id)
            self.assertEqual(games[0]["phase"], "give_orders")
            self.assertEqual(games[0]["deck_set_id"], "core_0_2_sides")


if __name__ == "__main__":
    unittest.main()
