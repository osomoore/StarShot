"""Regression: random bauble placement must never fail game creation.

The original greedy placement (baubles 1..5 in order, no retry) could strand
bauble 5 — its ring is the tightest — and crash create_initial_state with
BaublePlacementError roughly once in a few hundred games.
"""

from __future__ import annotations

import unittest
from random import Random

from starshot.rules import create_initial_state
from starshot.rules.baubles import BAUBLE_MAX_CENTER_DISTANCE, create_baubles
from starshot.rules.hex import hex_distance
from starshot.rules.models import GameConfig, PlayerState, ShipState


def four_players() -> dict[str, PlayerState]:
    from starshot.rules.hex import corner_start

    players = {}
    for index, name in enumerate(("a", "b", "c", "d")):
        q, r, facing = corner_start(index)
        players[name] = PlayerState(id=name, deck=[], ship=ShipState(q=q, r=r, facing=facing))
    return players


class BaublePlacementTests(unittest.TestCase):
    def test_many_random_layouts_place_all_baubles(self) -> None:
        players = four_players()
        for seed in range(400):
            baubles = create_baubles(Random(seed), players)
            numbered = [bauble for bauble in baubles if not bauble.is_fang]
            self.assertEqual(len(numbered), 10, f"seed {seed}")
            for bauble in numbered:
                self.assertLessEqual(
                    hex_distance(0, 0, bauble.q, bauble.r),
                    BAUBLE_MAX_CENTER_DISTANCE[bauble.number],
                    f"seed {seed}: bauble {bauble.id} outside its ring",
                )

    def test_many_unseeded_game_creations_succeed(self) -> None:
        for _ in range(150):
            state = create_initial_state(GameConfig(player_ids=("red", "blue", "green", "gold")))
            self.assertEqual(len(state.baubles), 11)


if __name__ == "__main__":
    unittest.main()
