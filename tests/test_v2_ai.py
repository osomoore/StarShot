import unittest
from types import SimpleNamespace
from unittest.mock import patch

from starshot.rules import GameConfig, OverdriveStyle, RulesConfig, SealMode, create_initial_state, submit_orders
from starshot.rules.decks import card_by_id
from starshot.v2.ai import build_ai_orders


class V2AiPlannerTests(unittest.TestCase):
    def _catalog(self, state, config):
        return SimpleNamespace(id=state.deck_set_id, rules_config=config)

    def _set_hand(self, state, player_id, *card_ids):
        player = state.players[player_id]
        player.hand = [card_by_id(card_id) for card_id in card_ids]
        player.deck = []
        player.discard = []
        player.overheat = []

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


if __name__ == "__main__":
    unittest.main()
