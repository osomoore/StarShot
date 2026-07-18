import unittest
from types import SimpleNamespace
from unittest.mock import patch

from starshot.rules import GameConfig, OverdriveStyle, RulesConfig, SealMode, create_initial_state, submit_orders
from starshot.rules.decks import card_by_id
from starshot.rules.engine import resolve_next_step
from starshot.rules.hex import hex_distance, is_within_board
from starshot.rules.models import GamePhase
from starshot.rules.vaults import VAULT_RADIUS
from starshot.v2.ai import build_ai_orders, fallback_orders

MODERN_RULES = RulesConfig(
    overheat_pile=False,
    allow_mixed_card_type_stacks=True,
    overdrive_style=OverdriveStyle.COMBINE_CARDS,
    allow_overdrive_desperation=True,
)


class V2AiPlannerTests(unittest.TestCase):
    def _catalog(self, state, config):
        return SimpleNamespace(id=state.deck_set_id, rules_config=config)

    def _set_hand(self, state, player_id, *card_ids):
        player = state.players[player_id]
        player.hand = [card_by_id(card_id) for card_id in card_ids]
        player.deck = []
        player.discard = []
        player.overheat = []

    def _patched(self, state, config):
        return (
            patch("starshot.v2.ai.active_catalog", return_value=self._catalog(state, config)),
            patch("starshot.rules.engine.active_catalog", return_value=self._catalog(state, config)),
        )

    def _resolve_round(self, state):
        while state.phase not in (GamePhase.GIVE_ORDERS, GamePhase.COMPLETE):
            state = resolve_next_step(state)
        return state

    def _place_before_vault(self, state, player_id, vault, gap):
        """Put the ship `gap` hexes from the vault on the q axis, facing it."""
        ship = state.players[player_id].ship
        if is_within_board(vault.q - gap, vault.r):
            ship.q, ship.r, ship.facing = vault.q - gap, vault.r, 0
        else:
            self.assertTrue(is_within_board(vault.q + gap, vault.r))
            ship.q, ship.r, ship.facing = vault.q + gap, vault.r, 3

    def test_blaster_uses_mixed_move_attack_stack_when_enabled(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        red = state.players["red"]
        blue = state.players["blue"]
        red.ship.q, red.ship.r, red.ship.facing = -11, 0, 0
        blue.ship.q, blue.ship.r, blue.ship.facing = -4, 0, 3
        blue.ship.shields = 0
        self._set_hand(state, "red", "controlled_move_2_a", "targeted_attack_aim_1_a")
        config = RulesConfig(
            allow_mixed_card_type_stacks=True,
            overdrive_style=OverdriveStyle.COMBINE_CARDS,
        )

        with (
            patch("starshot.v2.ai.active_catalog", return_value=self._catalog(state, config)),
            patch("starshot.rules.engine.active_catalog", return_value=self._catalog(state, config)),
        ):
            orders = build_ai_orders(state, "red", "blaster")
            submit_orders(state, "red", orders)

        mixed_stacks = [
            stack
            for stack in orders.stacks
            if {selection.card_id for selection in stack.cards}
            == {"controlled_move_2_a", "targeted_attack_aim_1_a"}
        ]
        self.assertEqual(len(mixed_stacks), 1)

    def test_overdrive_desperation_setting_controls_ai_seal_choice(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        red = state.players["red"]
        blue = state.players["blue"]
        red.ship.q, red.ship.r, red.ship.facing = -3, 0, 0
        blue.ship.q, blue.ship.r, blue.ship.facing = -2, 0, 3
        blue.ship.shields = 0
        blue.ship.damage_taken = 6
        self._set_hand(state, "red", "targeted_attack_aim_2_a", "desp_crack_shot_a")

        disabled = RulesConfig(allow_overdrive_desperation=False)
        with (
            patch("starshot.v2.ai.active_catalog", return_value=self._catalog(state, disabled)),
            patch("starshot.rules.engine.active_catalog", return_value=self._catalog(state, disabled)),
        ):
            disabled_orders = build_ai_orders(state, "red", "blaster")
            submit_orders(state, "red", disabled_orders)

        desperate_stack = next(
            stack
            for stack in disabled_orders.stacks
            if any(selection.card_id == "desp_crack_shot_a" for selection in stack.cards)
        )
        self.assertEqual(desperate_stack.seal_mode, SealMode.SEALED)

        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        red = state.players["red"]
        blue = state.players["blue"]
        red.ship.q, red.ship.r, red.ship.facing = -3, 0, 0
        blue.ship.q, blue.ship.r, blue.ship.facing = -2, 0, 3
        blue.ship.shields = 0
        blue.ship.damage_taken = 6
        self._set_hand(state, "red", "targeted_attack_aim_2_a", "desp_crack_shot_a")
        enabled = RulesConfig(allow_overdrive_desperation=True)
        with (
            patch("starshot.v2.ai.active_catalog", return_value=self._catalog(state, enabled)),
            patch("starshot.rules.engine.active_catalog", return_value=self._catalog(state, enabled)),
        ):
            enabled_orders = build_ai_orders(state, "red", "blaster")
            submit_orders(state, "red", enabled_orders)

        desperate_stack = next(
            stack
            for stack in enabled_orders.stacks
            if any(selection.card_id == "desp_crack_shot_a" for selection in stack.cards)
        )
        self.assertEqual(desperate_stack.seal_mode, SealMode.OVERDRIVE)

    def test_deck_hand_level_strips_overdrive_without_changing_type(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        red = state.players["red"]
        blue = state.players["blue"]
        red.ship.q, red.ship.r, red.ship.facing = -3, 0, 0
        blue.ship.q, blue.ship.r, blue.ship.facing = -2, 0, 3
        blue.ship.shields = 0
        self._set_hand(state, "red", "targeted_attack_aim_2_a")
        config = RulesConfig()

        with (
            patch("starshot.v2.ai.active_catalog", return_value=self._catalog(state, config)),
            patch("starshot.rules.engine.active_catalog", return_value=self._catalog(state, config)),
        ):
            king_orders = build_ai_orders(state, "red", "blaster", ai_level="pirate_king")
            deck_hand_orders = build_ai_orders(state, "red", "blaster", ai_level="deck_hand")

        self.assertTrue(any(stack.seal_mode == SealMode.OVERDRIVE for stack in king_orders.stacks))
        self.assertTrue(all(stack.seal_mode == SealMode.SEALED for stack in deck_hand_orders.stacks))

    def test_vault_runner_reaches_and_holds_current_round_vault(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=7))
        vault = next(v for v in state.vaults if v.number == state.round_number)
        self._place_before_vault(state, "red", vault, gap=4)
        blue = state.players["blue"].ship
        blue.q, blue.r, blue.facing = -vault.q, -vault.r, 0
        self._set_hand(state, "red", "controlled_move_2_a", "controlled_move_2_b", "controlled_move_1_a")

        with self._patched(state, MODERN_RULES)[0], self._patched(state, MODERN_RULES)[1]:
            orders = build_ai_orders(state, "red", "vault_runner")
            state = submit_orders(state, "red", orders)
            state = submit_orders(state, "blue", fallback_orders())
            state = self._resolve_round(state)

        red = state.players["red"]
        final_vault = next(v for v in state.vaults if v.id == vault.id)
        self.assertLessEqual(hex_distance(red.ship.q, red.ship.r, vault.q, vault.r), VAULT_RADIUS)
        self.assertIn("red", final_vault.claimed_by)
        self.assertGreaterEqual(red.victory_points, vault.victory_points)

    def test_vault_runner_makes_progress_toward_distant_vault(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=7))
        red = state.players["red"]
        red.ship.q, red.ship.r, red.ship.facing = -11, 0, 0
        blue = state.players["blue"].ship
        blue.q, blue.r = 11, 0
        # Vaults the runner may reasonably chase: this round's, next round's, and the Fang.
        candidates = [
            v for v in state.vaults if v.is_fang or v.number in (state.round_number, state.round_number + 1)
        ]
        start_distances = {
            v.id: hex_distance(red.ship.q, red.ship.r, v.q, v.r) for v in candidates
        }
        self._set_hand(state, "red", "controlled_move_2_a", "controlled_move_1_a")

        with self._patched(state, MODERN_RULES)[0], self._patched(state, MODERN_RULES)[1]:
            orders = build_ai_orders(state, "red", "vault_runner")
            state = submit_orders(state, "red", orders)
            state = submit_orders(state, "blue", fallback_orders())
            state = self._resolve_round(state)

        played_cards = [selection.card_id for stack in orders.stacks for selection in stack.cards]
        self.assertTrue(played_cards, "vault_runner passed the whole round instead of closing on a vault")
        red = state.players["red"]
        progressed = any(
            hex_distance(red.ship.q, red.ship.r, v.q, v.r) <= start_distances[v.id] - 2
            for v in candidates
        )
        self.assertTrue(progressed, "vault_runner's moves closed no ground on any chasable vault")

    def test_vault_runner_shoots_but_stays_parked_on_its_vault(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=7))
        vault = next(v for v in state.vaults if v.number == state.round_number)
        red = state.players["red"]
        red.ship.q, red.ship.r, red.ship.facing = vault.q, vault.r, 0
        blue = state.players["blue"].ship
        blue.q, blue.r = vault.q + 3, vault.r
        self.assertTrue(is_within_board(blue.q, blue.r))
        self._set_hand(state, "red", "targeted_attack_aim_1_a", "controlled_move_2_a")

        with self._patched(state, MODERN_RULES)[0], self._patched(state, MODERN_RULES)[1]:
            orders = build_ai_orders(state, "red", "vault_runner")
            state = submit_orders(state, "red", orders)
            state = submit_orders(state, "blue", fallback_orders())
            state = self._resolve_round(state)

        targeted = [
            selection
            for stack in orders.stacks
            for selection in stack.cards
            if selection.target_player_id == "blue"
        ]
        self.assertTrue(targeted, "vault_runner sat on its vault without spending its attack card")
        red = state.players["red"]
        final_vault = next(v for v in state.vaults if v.id == vault.id)
        self.assertLessEqual(hex_distance(red.ship.q, red.ship.r, vault.q, vault.r), VAULT_RADIUS)
        self.assertIn("red", final_vault.claimed_by)

    def test_hunter_killer_closes_on_distant_prey(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        red = state.players["red"]
        blue = state.players["blue"]
        red.ship.q, red.ship.r, red.ship.facing = -11, 0, 0
        blue.ship.q, blue.ship.r, blue.ship.facing = 11, 0, 3
        start_distance = hex_distance(red.ship.q, red.ship.r, blue.ship.q, blue.ship.r)
        self._set_hand(state, "red", "controlled_move_2_a", "controlled_move_2_b", "controlled_move_1_a")

        with self._patched(state, MODERN_RULES)[0], self._patched(state, MODERN_RULES)[1]:
            orders = build_ai_orders(state, "red", "hunter_killer")
            state = submit_orders(state, "red", orders)
            state = submit_orders(state, "blue", fallback_orders())
            state = self._resolve_round(state)

        red = state.players["red"]
        blue = state.players["blue"]
        end_distance = hex_distance(red.ship.q, red.ship.r, blue.ship.q, blue.ship.r)
        self.assertLessEqual(end_distance, start_distance - 4, "hunter_killer failed to chase its prey")

    def test_blaster_takes_low_odds_shot_instead_of_passing(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        red = state.players["red"]
        blue = state.players["blue"]
        red.ship.q, red.ship.r, red.ship.facing = -5, 0, 0
        blue.ship.q, blue.ship.r, blue.ship.facing = 4, 0, 3
        self._set_hand(state, "red", "targeted_attack_aim_1_a", "targeted_attack_aim_1_b")

        with self._patched(state, MODERN_RULES)[0], self._patched(state, MODERN_RULES)[1]:
            orders = build_ai_orders(state, "red", "blaster")

        targeted = [
            selection
            for stack in orders.stacks
            for selection in stack.cards
            if selection.target_player_id == "blue"
        ]
        self.assertTrue(targeted, "blaster passed with attack cards in hand; unplayed cards are discarded at cleanup")

    def test_ai_rations_overdrive_to_one_stack_before_final_round(self):
        for ai_type in ("vault_runner", "hunter_killer", "blaster"):
            state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=2))
            red = state.players["red"]
            blue = state.players["blue"]
            red.ship.q, red.ship.r, red.ship.facing = -11, 0, 0
            blue.ship.q, blue.ship.r, blue.ship.facing = 11, 0, 3
            self._set_hand(
                state, "red", "controlled_move_2_a", "controlled_move_2_b", "controlled_move_2_c", "controlled_move_1_a"
            )

            with self._patched(state, MODERN_RULES)[0], self._patched(state, MODERN_RULES)[1]:
                orders = build_ai_orders(state, "red", ai_type)
                submit_orders(state, "red", orders)

            overdriven = sum(1 for stack in orders.stacks if stack.seal_mode == SealMode.OVERDRIVE)
            self.assertLessEqual(
                overdriven,
                1,
                f"{ai_type} overdrove {overdriven} stacks in round 1; each one costs a card off next round's draw",
            )

    def test_final_round_overdrive_is_unrationed(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=2))
        state.round_number = 6
        red = state.players["red"]
        blue = state.players["blue"]
        red.ship.q, red.ship.r, red.ship.facing = -13, 0, 0
        blue.ship.q, blue.ship.r, blue.ship.facing = 13, 0, 3
        self._set_hand(
            state, "red", "controlled_move_2_a", "controlled_move_2_b", "controlled_move_2_c", "controlled_move_2_d"
        )

        with self._patched(state, MODERN_RULES)[0], self._patched(state, MODERN_RULES)[1]:
            orders = build_ai_orders(state, "red", "hunter_killer")
            submit_orders(state, "red", orders)

        overdriven = sum(1 for stack in orders.stacks if stack.seal_mode == SealMode.OVERDRIVE)
        self.assertGreaterEqual(
            overdriven, 2, "round six has no next draw, so overdrive is free tempo for the chase"
        )


class V2AiCaptainTests(unittest.TestCase):
    def test_ai_seats_never_pick_movement_altering_captains(self):
        from starshot.v2.service import AI_EXCLUDED_CAPTAIN_IDS, _choose_ai_captain

        for seed in range(1, 8):
            for rng_step in range(0, 12, 3):
                state = create_initial_state(GameConfig(player_ids=("ai:blaster:1", "blue"), seed=seed))
                state.active_expansions = ("star_command",)
                state.rng_step = rng_step
                player = state.players["ai:blaster:1"]
                player.captain_options = ("danny_davos", "riley_rounder", "malcolm_manderly")
                chosen = _choose_ai_captain(state, {"player_id": "ai:blaster:1"})
                captain_id = chosen.players["ai:blaster:1"].captain_id
                self.assertIsNotNone(captain_id)
                self.assertNotIn(captain_id, AI_EXCLUDED_CAPTAIN_IDS)


if __name__ == "__main__":
    unittest.main()
