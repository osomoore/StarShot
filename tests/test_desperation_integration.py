"""Integration tests for desperate face resolution in the game engine."""

import os
import unittest

from starshot.rules import (
    ActionStack,
    BaubleState,
    GameConfig,
    GamePhase,
    OrderCardSelection,
    OrdersSubmission,
    RulesError,
    SealMode,
    create_initial_state,
    resolve_next_step,
    submit_orders,
)
from starshot.rules.decks import card_by_id
from starshot.rules.desperation import desperation_card_by_id


class DesperationIntegrationTests(unittest.TestCase):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_hand(self, state, player_id, *card_ids):
        player = state.players[player_id]
        requested = set(card_ids)
        player.deck = [c for c in player.deck if c.id not in requested]
        player.discard = [c for c in player.discard if c.id not in requested]
        player.overheat = [c for c in player.overheat if c.id not in requested]
        player.hand = [card_by_id(cid) for cid in card_ids]

    def _resolve_through_cleanup(self, state):
        while state.phase != GamePhase.CLEANUP:
            state = resolve_next_step(state)
        return resolve_next_step(state)

    def _empty_orders(self):
        return OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        ))

    # ------------------------------------------------------------------
    # Bauble / deck draw
    # ------------------------------------------------------------------

    def test_bauble_award_draws_desperation_card_into_player_deck(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.phase = GamePhase.AWARD_BAUBLES
        state.round_number = 1
        state.baubles = [BaubleState(id="b1", number=1, q=0, r=0, victory_points=2)]
        state.players["red"].ship.q = 1
        state.players["red"].ship.r = 0
        state.players["blue"].ship.q = 5
        state.players["blue"].ship.r = 0

        deck_before = len(state.players["red"].deck)
        desp_before = len(state.desperation_deck.cards)
        state = resolve_next_step(state)

        self.assertEqual(len(state.players["red"].deck), deck_before + 1)
        self.assertEqual(len(state.desperation_deck.cards), desp_before - 1)
        self.assertFalse(state.players["red"].deck[0].is_base)
        award = [e for e in state.event_log if e["type"] == "bauble_awarded"][0]
        self.assertIsNotNone(award["awards"][0]["desperation_card_id"])

    def test_fang_bauble_does_not_draw_desperation_card(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.phase = GamePhase.AWARD_BAUBLES
        state.round_number = 2
        state.baubles = [BaubleState(id="fang", number=6, q=0, r=0, victory_points=1, is_fang=True)]
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 1
        state.players["blue"].ship.q = 5
        state.players["blue"].ship.r = 0
        desp_before = len(state.desperation_deck.cards)
        state = resolve_next_step(state)
        self.assertEqual(len(state.desperation_deck.cards), desp_before)

    # ------------------------------------------------------------------
    # Desperation consequence
    # ------------------------------------------------------------------

    def test_unshielded_damage_triggers_desperation_consequence(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.shields = 0
        state.players["blue"].ship.q = 1
        state.players["blue"].ship.r = 0
        self._set_hand(state, "blue", "targeted_attack_aim_1_a")
        desp_before = len(state.desperation_deck.cards)

        state = submit_orders(state, "red", self._empty_orders())
        state = submit_orders(state, "blue", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("targeted_attack_aim_1_a", target_player_id="red"),)),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = resolve_next_step(state)

        volley = [e for e in state.event_log if e["type"] == "volley_resolved"][0]
        if volley["hit"] and volley["damage_applied"] > 0:
            events = [e for e in state.event_log if e["type"] == "desperation_consequence"]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["choice"], "automatic")
            self.assertEqual(len(state.desperation_deck.cards), desp_before - 1)
            self.assertFalse(state.players["red"].deck[0].is_base)

    # ------------------------------------------------------------------
    # No-basic-face cards always return to desperation deck
    # ------------------------------------------------------------------

    def test_afterburners_basic_face_returns_to_desperation_deck(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_afterburners_a")
        desp_before = len(state.desperation_deck.cards)

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_afterburners_a", orientation="forward"),)),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)
        state = self._resolve_through_cleanup(state)

        moved = [e for e in state.event_log if e["type"] == "action_cards_moved" and e["player_id"] == "red"][0]
        self.assertIn("desp_afterburners_a", moved["returned_to_desperation_deck"])
        self.assertEqual(len(state.desperation_deck.cards), desp_before + 1)

    def test_crack_shot_basic_face_returns_to_desperation_deck(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        state.players["blue"].ship.shields = 0
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["blue"].ship.q = 1
        state.players["blue"].ship.r = 0
        self._set_hand(state, "red", "desp_crack_shot_a")
        desp_before = len(state.desperation_deck.cards)

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_crack_shot_a", target_player_id="blue"),)),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)
        state = self._resolve_through_cleanup(state)

        moved = [e for e in state.event_log if e["type"] == "action_cards_moved" and e["player_id"] == "red"][0]
        self.assertIn("desp_crack_shot_a", moved["returned_to_desperation_deck"])
        # Deck may shrink by 1 if a desperation consequence fired (hit unshielded), then
        # grows by 1 when crack_shot returns. Net is 0 or -1+1=0 vs just +1.
        desp_after = len(state.desperation_deck.cards)
        consequence_events = [e for e in state.event_log if e["type"] == "desperation_consequence"]
        expected = desp_before - len(consequence_events) + 1
        self.assertEqual(desp_after, expected)

    # ------------------------------------------------------------------
    # Thrust Ions desperate face
    # ------------------------------------------------------------------

    def test_desperate_thrust_ions_moves_5(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_thrust_ions_a")
        desp_before = len(state.desperation_deck.cards)

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_thrust_ions_a", face="desperate"),)),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)

        moves = [e for e in state.event_log if e["type"] == "movement_resolved" and e["player_id"] == "red"]
        self.assertEqual(moves[0]["steps"][0]["distance"], 5)

        state = self._resolve_through_cleanup(state)
        moved = [e for e in state.event_log if e["type"] == "action_cards_moved" and e["player_id"] == "red"][0]
        self.assertIn("desp_thrust_ions_a", moved["returned_to_desperation_deck"])
        self.assertEqual(len(state.desperation_deck.cards), desp_before + 1)

    # ------------------------------------------------------------------
    # Turbo Ions desperate face
    # ------------------------------------------------------------------

    def test_desperate_turbo_ions_moves_10(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_turbo_ions")

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_turbo_ions", face="desperate"),)),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)

        moves = [e for e in state.event_log if e["type"] == "movement_resolved" and e["player_id"] == "red"]
        self.assertEqual(moves[0]["steps"][0]["distance"], 10)

    # ------------------------------------------------------------------
    # Steady Shot desperate face
    # ------------------------------------------------------------------

    def test_desperate_steady_shot_adds_aim_and_damage(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "targeted_attack_aim_1_a", "desp_steady_shot_a")
        state.players["blue"].ship.shields = 0
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["blue"].ship.q = 1
        state.players["blue"].ship.r = 0

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (
                OrderCardSelection("targeted_attack_aim_1_a", target_player_id="blue"),
                OrderCardSelection("desp_steady_shot_a", face="desperate"),
            )),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)

        volley = [e for e in state.event_log if e["type"] == "volley_resolved"][0]
        self.assertEqual(volley["aim_bonus"], 3)
        self.assertEqual(volley["damage"], 2)

        state = self._resolve_through_cleanup(state)
        moved = [e for e in state.event_log if e["type"] == "action_cards_moved" and e["player_id"] == "red"][0]
        self.assertIn("desp_steady_shot_a", moved["returned_to_desperation_deck"])

    def test_untargeted_desperate_attack_shoots_straight_when_unpaired(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_steady_shot_a")
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.facing = 0
        state.players["blue"].ship.q = 2
        state.players["blue"].ship.r = 0
        state.players["blue"].ship.shields = 0

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (
                OrderCardSelection("desp_steady_shot_a", face="desperate"),
            )),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)

        volley = [e for e in state.event_log if e["type"] == "volley_resolved"][0]
        self.assertEqual(volley["target_id"], "blue")
        self.assertEqual(volley["aim_bonus"], 2)
        self.assertEqual(volley["damage"], 2)

    def test_untargeted_basic_attack_shoots_straight_when_unpaired(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_steady_shot_a")
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.facing = 0
        state.players["blue"].ship.q = 2
        state.players["blue"].ship.r = 0
        state.players["blue"].ship.shields = 0

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (
                OrderCardSelection("desp_steady_shot_a", mode="attack"),
            )),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)

        volley = [e for e in state.event_log if e["type"] == "volley_resolved"][0]
        self.assertEqual(volley["target_id"], "blue")
        self.assertEqual(volley["aim_bonus"], 2)
        self.assertEqual(volley["damage"], 1)

    def test_untargeted_attack_joins_targeted_card_target(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue", "green"), seed=1))
        self._set_hand(state, "red", "targeted_attack_aim_1_a", "desp_steady_shot_a")
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.facing = 0
        state.players["blue"].ship.q = 5
        state.players["blue"].ship.r = 0
        state.players["green"].ship.q = 1
        state.players["green"].ship.r = 0

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (
                OrderCardSelection("targeted_attack_aim_1_a", target_player_id="blue"),
                OrderCardSelection("desp_steady_shot_a", face="desperate"),
            )),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = submit_orders(state, "green", self._empty_orders())
        state = resolve_next_step(state)

        volley = [e for e in state.event_log if e["type"] == "volley_resolved"][0]
        self.assertEqual(volley["target_id"], "blue")
        self.assertEqual(volley["aim_bonus"], 3)
        self.assertEqual(volley["damage"], 2)

    # ------------------------------------------------------------------
    # NightJammer desperate face
    # ------------------------------------------------------------------

    def test_desperate_nightjammer_warps_behind_vp_leader(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_nightjammer")
        state.players["blue"].victory_points = 8
        state.players["blue"].ship.q = 5
        state.players["blue"].ship.r = -2
        state.players["blue"].ship.facing = 1
        state.players["red"].ship.facing = 4
        desp_before = len(state.desperation_deck.cards)

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_nightjammer", face="desperate"),)),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)

        self.assertEqual((state.players["red"].ship.q, state.players["red"].ship.r), (4, -1))
        self.assertEqual(state.players["red"].ship.facing, 1)
        self.assertEqual(state.players["red"].ship.movement_this_action, 0)
        self.assertEqual(state.players["red"].ship.defense_bonus_this_action, 5)

        state = self._resolve_through_cleanup(state)
        moved = [e for e in state.event_log if e["type"] == "action_cards_moved" and e["player_id"] == "red"][0]
        self.assertIn("desp_nightjammer", moved["returned_to_desperation_deck"])
        self.assertEqual(len(state.desperation_deck.cards), desp_before + 1)

    # ------------------------------------------------------------------
    # StarShot desperate face
    # ------------------------------------------------------------------

    def test_desperate_starshot_always_hits(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "targeted_attack_aim_1_a", "desp_starshot")
        state.players["blue"].ship.shields = 0
        state.players["red"].ship.q = -14
        state.players["red"].ship.r = 0
        state.players["blue"].ship.q = 14
        state.players["blue"].ship.r = 0

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (
                OrderCardSelection("targeted_attack_aim_1_a", target_player_id="blue"),
                OrderCardSelection("desp_starshot", face="desperate"),
            )),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)

        volley = [e for e in state.event_log if e["type"] == "volley_resolved"][0]
        self.assertTrue(volley["always_hits"])
        self.assertTrue(volley["hit"])
        self.assertGreaterEqual(volley["roll_total"], volley["defense_threshold"])

    # ------------------------------------------------------------------
    # Side Slip desperate face
    # ------------------------------------------------------------------

    def test_desperate_side_slip_right_moves_laterally(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_side_slip_a")
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.facing = 0  # facing direction 0: dq=1, dr=0

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_side_slip_a", face="desperate", orientation="slip_right"),)),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)

        # slip_right from facing 0 uses facing -1 mod 6 = 5: dq=0, dr=1 => r+=4
        self.assertEqual(state.players["red"].ship.q, 0)
        self.assertEqual(state.players["red"].ship.r, 4)
        self.assertEqual(state.players["red"].ship.facing, 0)  # facing unchanged

    def test_desperate_side_slip_left_moves_laterally(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_side_slip_a")
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.facing = 0  # facing 0: dq=1, dr=0

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_side_slip_a", face="desperate", orientation="slip_left"),)),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)

        # slip_left from facing 0 uses facing +1 mod 6 = 1: dq=1, dr=-1 => q+=4, r-=4
        self.assertEqual(state.players["red"].ship.q, 4)
        self.assertEqual(state.players["red"].ship.r, -4)
        self.assertEqual(state.players["red"].ship.facing, 0)  # facing unchanged

    # ------------------------------------------------------------------
    # Drift King desperate face
    # ------------------------------------------------------------------

    def test_desperate_drift_king_turns_right_twice_then_moves(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_drift_king_a")
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.facing = 0  # facing 0: dq=1, dr=0

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_drift_king_a", face="desperate"),)),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)

        # turn_right twice from facing 0 => facing (0-2) mod 6 = 4: dq=-1, dr=1 => q-=4, r+=4
        self.assertEqual(state.players["red"].ship.facing, 4)
        self.assertEqual(state.players["red"].ship.q, -4)
        self.assertEqual(state.players["red"].ship.r, 4)

    def test_core_0_3_desperate_drift_king_moves_then_turns_twice(self):
        original = os.environ.get("STARSHOT_DECK_SET")
        try:
            os.environ["STARSHOT_DECK_SET"] = "resources/decks/core_0_3"
            state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
            self._set_hand(state, "red", "desp_drift_king_a")
            state.players["red"].ship.q = 0
            state.players["red"].ship.r = 0
            state.players["red"].ship.facing = 0

            state = submit_orders(state, "red", OrdersSubmission(stacks=(
                ActionStack(
                    1,
                    SealMode.SEALED,
                    (OrderCardSelection("desp_drift_king_a", face="desperate", orientation="turn_left"),),
                ),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )))
            state = submit_orders(state, "blue", self._empty_orders())
            state = resolve_next_step(state)

            self.assertEqual(state.players["red"].ship.q, 4)
            self.assertEqual(state.players["red"].ship.r, 0)
            self.assertEqual(state.players["red"].ship.facing, 2)
        finally:
            if original is None:
                os.environ.pop("STARSHOT_DECK_SET", None)
            else:
                os.environ["STARSHOT_DECK_SET"] = original

    # ------------------------------------------------------------------
    # Crazy Ivan desperate face — move variant
    # ------------------------------------------------------------------

    def test_desperate_crazy_ivan_u_turn_move(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_crazy_ivan_a")
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.facing = 0  # facing 0: dq=1, dr=0

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_crazy_ivan_a", face="desperate", orientation="u_turn_move"),)),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)

        # u_turn from facing 0 => facing 3: dq=-1, dr=0 => q-=3
        self.assertEqual(state.players["red"].ship.facing, 3)
        self.assertEqual(state.players["red"].ship.q, -3)
        self.assertEqual(state.players["red"].ship.r, 0)

    def test_overdrive_does_not_copy_desperate_movement(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_crazy_ivan_a")
        with self.assertRaisesRegex(RulesError, "Desperation cards cannot be overdriven"):
            submit_orders(state, "red", OrdersSubmission(stacks=(
                ActionStack(
                    1,
                    SealMode.OVERDRIVE,
                    (OrderCardSelection("desp_crazy_ivan_a", face="desperate", orientation="u_turn_move"),),
                ),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )))

    # ------------------------------------------------------------------
    # Crazy Ivan desperate face — attack variant
    # ------------------------------------------------------------------

    def test_desperate_crazy_ivan_u_turn_attack(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_crazy_ivan_a")
        state.players["red"].ship.q = 2
        state.players["red"].ship.r = 0
        state.players["red"].ship.facing = 0   # facing away from blue
        state.players["blue"].ship.q = 0
        state.players["blue"].ship.r = 0
        state.players["blue"].ship.shields = 0

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_crazy_ivan_a", face="desperate", orientation="u_turn_attack"),)),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)

        # After u_turn, facing = 3, forward line hits blue at (0,0)
        self.assertEqual(state.players["red"].ship.facing, 3)
        volleys = [e for e in state.event_log if e["type"] == "volley_resolved"]
        self.assertEqual(len(volleys), 1)
        self.assertEqual(volleys[0]["target_id"], "blue")
        self.assertEqual(volleys[0]["aim_bonus"], 3)
        self.assertTrue(volleys[0]["u_turn_attack"])

    def test_overdrive_does_not_copy_desperate_attack(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_crack_shot_a")
        with self.assertRaisesRegex(RulesError, "Desperation cards cannot be overdriven"):
            submit_orders(state, "red", OrdersSubmission(stacks=(
                ActionStack(
                    1,
                    SealMode.OVERDRIVE,
                    (OrderCardSelection("desp_crack_shot_a", face="desperate", target_player_id="blue"),),
                ),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )))

    def test_overdrive_copy_excludes_desperate_attack_from_mixed_volley(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "targeted_attack_aim_2_a", "desp_crack_shot_a")
        with self.assertRaisesRegex(RulesError, "Desperation cards cannot be overdriven"):
            submit_orders(state, "red", OrdersSubmission(stacks=(
                ActionStack(
                    1,
                    SealMode.OVERDRIVE,
                    (
                        OrderCardSelection("targeted_attack_aim_2_a", target_player_id="blue"),
                        OrderCardSelection("desp_crack_shot_a", face="desperate", target_player_id="blue"),
                    ),
                ),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )))

    # ------------------------------------------------------------------
    # Active Cooling desperate face
    # ------------------------------------------------------------------

    def test_desperate_active_cooling_moves_overheat_to_discard(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_active_cooling_a")
        overheat_card = desperation_card_by_id("desp_thrust_ions_b")
        state.players["red"].overheat = [overheat_card]

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_active_cooling_a", face="desperate"),)),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)

        self.assertEqual(state.players["red"].overheat, [])
        self.assertIn(overheat_card, state.players["red"].discard)
        moves = [e for e in state.event_log if e["type"] == "movement_resolved" and e["player_id"] == "red"]
        self.assertEqual(moves[0]["steps"][0]["distance"], 1)
        self.assertTrue(moves[0]["steps"][0]["active_cooling"])

    # ------------------------------------------------------------------
    # Lead the Target desperate face
    # ------------------------------------------------------------------

    def test_desperate_lead_the_target_ignores_target_movement(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "targeted_attack_aim_1_a", "desp_lead_the_target")
        self._set_hand(state, "blue", "controlled_move_2_a")
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["blue"].ship.q = 1
        state.players["blue"].ship.r = 0
        state.players["blue"].ship.shields = 0

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (
                OrderCardSelection("targeted_attack_aim_1_a", target_player_id="blue"),
                OrderCardSelection("desp_lead_the_target", face="desperate"),
            )),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("controlled_move_2_a", orientation="forward"),)),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = resolve_next_step(state)

        volley = [e for e in state.event_log if e["type"] == "volley_resolved"][0]
        self.assertTrue(volley["lead_the_target"])
        self.assertEqual(volley["target_movement"], 0)
        # defense_threshold should not include blue's movement
        self.assertEqual(volley["defense_threshold"], volley["distance"] + volley["target_defense_bonus"])

    # ------------------------------------------------------------------
    # Engineering and special attack desperate faces
    # ------------------------------------------------------------------

    def test_hull_repair_restores_selected_component(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_hull_repair_a")
        state.players["red"].ship.destroyed_components.add("forward_ion_cannon")
        state.players["red"].ship.damage_taken = 1

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (
                OrderCardSelection("desp_hull_repair_a", face="desperate", repair_component_ids=("forward_ion_cannon",)),
            )),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)

        self.assertNotIn("forward_ion_cannon", state.players["red"].ship.destroyed_components)
        self.assertEqual(state.players["red"].ship.damage_taken, 0)
        self.assertTrue(any(e["type"] == "engineering_resolved" for e in state.event_log))

    def test_reconfigure_moves_two_damage_markers(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_reconfigure_a")
        state.players["red"].ship.destroyed_components.update({"port_shields", "bone_room"})
        state.players["red"].ship.damage_taken = 2

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (
                OrderCardSelection(
                    "desp_reconfigure_a",
                    face="desperate",
                    reconfigure_from_component_ids=("port_shields", "bone_room"),
                    reconfigure_to_component_ids=("forward_ion_cannon", "aft_engines"),
                ),
            )),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)

        destroyed = state.players["red"].ship.destroyed_components
        self.assertNotIn("port_shields", destroyed)
        self.assertNotIn("bone_room", destroyed)
        self.assertIn("forward_ion_cannon", destroyed)
        self.assertIn("aft_engines", destroyed)

    def test_holdo_maneuver_rams_without_shields(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue"), seed=1))
        self._set_hand(state, "red", "desp_holdo_maneuver")
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.facing = 0
        state.players["blue"].ship.q = 2
        state.players["blue"].ship.r = 0
        state.players["blue"].ship.shields = 2

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_holdo_maneuver", face="desperate"),)),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        state = submit_orders(state, "blue", self._empty_orders())
        state = resolve_next_step(state)

        event = [e for e in state.event_log if e["type"] == "ramming_resolved"][0]
        self.assertEqual(event["target_id"], "blue")
        self.assertEqual(state.players["red"].ship.q, 2)
        self.assertEqual(state.players["blue"].ship.shields, 2)
        self.assertGreaterEqual(event["target_damage"]["damage_applied"], 1)
        self.assertGreaterEqual(event["attacker_damage"]["damage_applied"], 1)

    def test_scattershot_targets_only_ships_in_facing_cone(self):
        state = create_initial_state(GameConfig(player_ids=("red", "blue", "green", "yellow"), seed=1))
        self._set_hand(state, "red", "desp_scattershot")
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["red"].ship.facing = 0
        state.players["blue"].ship.q = 2
        state.players["blue"].ship.r = 0
        state.players["green"].ship.q = 1
        state.players["green"].ship.r = -1
        state.players["yellow"].ship.q = -1
        state.players["yellow"].ship.r = 0

        state = submit_orders(state, "red", OrdersSubmission(stacks=(
            ActionStack(1, SealMode.SEALED, (OrderCardSelection("desp_scattershot", face="desperate"),)),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )))
        for player_id in ("blue", "green", "yellow"):
            state = submit_orders(state, player_id, self._empty_orders())
        state = resolve_next_step(state)

        target_ids = {event["target_id"] for event in state.event_log if event["type"] == "volley_resolved"}
        self.assertEqual(target_ids, {"blue", "green"})

    # ------------------------------------------------------------------
    # debug_start_with_attack_desperation_card
    # ------------------------------------------------------------------

    def test_debug_startup_seeds_desperation_card(self):
        state = create_initial_state(GameConfig(
            player_ids=("red", "blue"), seed=1,
            debug_start_with_attack_desperation_card=True,
        ))
        for player in state.players.values():
            self.assertTrue(any(not c.is_base for c in player.deck))


if __name__ == "__main__":
    unittest.main()
