"""Regression: random vault placement must never fail game creation.

The original greedy placement (vaults 1..5 in order, no retry) could strand
vault 5 — its ring is the tightest — and crash create_initial_state with
VaultPlacementError roughly once in a few hundred games.
"""

from __future__ import annotations

import unittest
from random import Random

from starshot.rules import create_initial_state
from starshot.rules.vaults import VAULT_MAX_CENTER_DISTANCE, create_vaults
from starshot.rules.hex import hex_distance
from starshot.rules.models import GameConfig, PlayerState, ShipState


def four_players() -> dict[str, PlayerState]:
    from starshot.rules.hex import corner_start

    players = {}
    for index, name in enumerate(("a", "b", "c", "d")):
        q, r, facing = corner_start(index)
        players[name] = PlayerState(id=name, deck=[], ship=ShipState(q=q, r=r, facing=facing))
    return players


class VaultPlacementTests(unittest.TestCase):
    def test_many_random_layouts_place_all_vaults(self) -> None:
        players = four_players()
        for seed in range(400):
            vaults = create_vaults(Random(seed), players)
            numbered = [vault for vault in vaults if not vault.is_fang]
            self.assertEqual(len(numbered), 10, f"seed {seed}")
            for vault in numbered:
                self.assertLessEqual(
                    hex_distance(0, 0, vault.q, vault.r),
                    VAULT_MAX_CENTER_DISTANCE[vault.number],
                    f"seed {seed}: vault {vault.id} outside its ring",
                )

    def test_many_unseeded_game_creations_succeed(self) -> None:
        for _ in range(150):
            state = create_initial_state(GameConfig(player_ids=("red", "blue", "green", "gold")))
            self.assertEqual(len(state.vaults), 11)


if __name__ == "__main__":
    unittest.main()
