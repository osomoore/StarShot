import unittest
from unittest.mock import patch

from starshot.rules import (
    ActionStack,
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
from starshot.rules import star_breach as sbd
from starshot.rules.decks import card_by_id
from starshot.rules.engine import (
    _fighting_ace_lane_choice,
    _first_star_breach_forward_target,
    _star_breach_overdrive_exempt,
    is_game_over,
)
from starshot.rules.serialization import state_to_dict, state_from_dict


def _coop_state(player_ids=("alice", "bob"), seed=11):
    return create_initial_state(
        GameConfig(player_ids=player_ids, seed=seed, active_expansions=("star_breach",))
    )


def _empty_stacks():
    return OrdersSubmission(
        stacks=(
            ActionStack(1, SealMode.SEALED),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )
    )


def _attack_orders(card_id, target, action=1, seal=SealMode.SEALED):
    stacks = []
    for number in (1, 2, 3):
        if number == action:
            stacks.append(
                ActionStack(number, seal, (OrderCardSelection(card_id, target_player_id=target),))
            )
        else:
            stacks.append(ActionStack(number, SealMode.SEALED))
    return OrdersSubmission(stacks=tuple(stacks))


def _set_hand(state, player_id, *card_ids):
    player = state.players[player_id]
    requested = set(card_ids)
    player.deck = [card for card in player.deck if card.id not in requested]
    player.hand = [card_by_id(card_id) for card_id in card_ids]


class StarBreachSetupTests(unittest.TestCase):
    def test_setup_assigns_prey_roles_fleet_and_tank_shield(self):
        state = _coop_state()
        sb = state.star_breach
        self.assertIsNotNone(sb)
        self.assertEqual(sb.scenario_id, "bauble_breacher")
        self.assertEqual(sb.prey_player_id, "alice")
        self.assertEqual(state.players["alice"].roles, ("treasure_hunter", "fighting_ace"))
        self.assertEqual(state.players["bob"].roles, ("tank", "engineer"))
        self.assertEqual(state.players["bob"].ship.shields, 3)
        self.assertEqual(len(state.players["bob"].hand), 7)  # engineer draws +2
        self.assertEqual(len(state.players["alice"].hand), 5)
        self.assertEqual([craft.id for craft in sb.fleet], ["hk_blue", "hk_green", "hk_yellow"])
        self.assertEqual(sb.shield_hp, {area: 3 for area in sbd.AREAS})

    def test_solo_play_is_allowed_and_gets_all_roles(self):
        state = _coop_state(player_ids=("solo",))
        self.assertEqual(set(state.players["solo"].roles), set(sbd.ROLE_ASSIGN_ORDER))
        self.assertEqual(state.star_breach.prey_player_id, "solo")

    def test_base_game_still_requires_two_players(self):
        with self.assertRaises(RulesError):
            create_initial_state(GameConfig(player_ids=("solo",)))

    def test_serialization_round_trip(self):
        state = _coop_state()
        state.star_breach.destroyed_hexes.add((0, -3))
        state.star_breach.progress = 5
        data = state_to_dict(state)
        self.assertEqual(data["star_breach"]["prey_player_id"], "alice")
        self.assertIn("boss_layout", data["star_breach"])
        self.assertEqual(data["players"]["bob"]["roles"], ["tank", "engineer"])
        restored = state_from_dict(data)
        self.assertEqual(restored.star_breach.destroyed_hexes, {(0, -3)})
        self.assertEqual(restored.star_breach.progress, 5)
        self.assertEqual(restored.players["bob"].roles, ("tank", "engineer"))

    def test_boss_layout_lanes_cover_each_area(self):
        for area in sbd.AREAS:
            for roll in sbd.DAMAGE_LANE_ROLLS:
                self.assertTrue(sbd.BOSS_DAMAGE_LANES[area][roll], (area, roll))
        for component in sbd.BOSS_COMPONENTS:
            self.assertIn((component.q, component.r), sbd.BOSS_FOOTPRINT_SET, component.id)


class StarBreachTargetValidationTests(unittest.TestCase):
    def test_valid_boss_and_craft_targets_accepted(self):
        state = _coop_state()
        _set_hand(state, "alice", "targeted_attack_aim_1_a")
        state = submit_orders(state, "alice", _attack_orders("targeted_attack_aim_1_a", "boss:forward"))
        self.assertTrue(state.players["alice"].has_submitted_orders if hasattr(state.players["alice"], "has_submitted_orders") else state.players["alice"].prepared_orders)

    def test_unknown_area_and_craft_rejected(self):
        state = _coop_state()
        _set_hand(state, "alice", "targeted_attack_aim_1_a")
        with self.assertRaisesRegex(RulesError, "target area"):
            submit_orders(state, "alice", _attack_orders("targeted_attack_aim_1_a", "boss:dorsal"))
        with self.assertRaisesRegex(RulesError, "fleet craft"):
            submit_orders(state, "alice", _attack_orders("targeted_attack_aim_1_a", "craft:hk_pink"))

    def test_only_engineer_may_target_allies(self):
        state = _coop_state()
        _set_hand(state, "alice", "targeted_attack_aim_1_a")
        with self.assertRaisesRegex(RulesError, "Engineer"):
            submit_orders(state, "alice", _attack_orders("targeted_attack_aim_1_a", "bob"))
        _set_hand(state, "bob", "targeted_attack_aim_1_a")
        state = submit_orders(state, "bob", _attack_orders("targeted_attack_aim_1_a", "alice"))
        self.assertIsNotNone(state.players["bob"].prepared_orders)


class StarBreachCombatTests(unittest.TestCase):
    def _quiet_enemies(self):
        # All boss/fleet shots roll 0 and miss (thresholds are always >= 1).
        return patch("starshot.rules.engine._roll_d6_sum", return_value=0)

    def _submit_both(self, state, alice_orders, bob_orders=None):
        state = submit_orders(state, "alice", alice_orders)
        return submit_orders(state, "bob", bob_orders or _empty_stacks())

    def test_boss_shield_arc_absorbs_hits(self):
        state = _coop_state()
        state.players["alice"].ship.q, state.players["alice"].ship.r = 0, -13
        _set_hand(state, "alice", "targeted_attack_aim_1_a")
        state = self._submit_both(state, _attack_orders("targeted_attack_aim_1_a", "boss:forward"))
        with self._quiet_enemies():
            state = resolve_next_step(state)
        sb = state.star_breach
        self.assertEqual(sb.shield_hp["forward"], 2)
        self.assertEqual(len(sb.destroyed_hexes), 0)
        event = next(e for e in state.event_log if e["type"] == "boss_volley_resolved")
        self.assertTrue(event["hit"])
        self.assertEqual(event["shields_absorbed"], 1)
        self.assertEqual(state.players["alice"].victory_points, 1)

    def test_boss_lane_strike_destroys_hull_then_component(self):
        state = _coop_state()
        state.players["alice"].ship.q, state.players["alice"].ship.r = 0, -13
        state.star_breach.shield_hp["forward"] = 0
        _set_hand(state, "alice", "targeted_attack_aim_1_a", "targeted_attack_aim_1_b")
        orders = OrdersSubmission(
            stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection("targeted_attack_aim_1_a", target_player_id="boss:forward"),)),
                ActionStack(2, SealMode.SEALED, (OrderCardSelection("targeted_attack_aim_1_b", target_player_id="boss:forward"),)),
                ActionStack(3, SealMode.SEALED),
            )
        )
        state = self._submit_both(state, orders)
        with self._quiet_enemies(), patch("starshot.rules.engine._roll_d8", return_value=5):
            state = resolve_next_step(state)  # action 1: strikes (0,-3)
            state = resolve_next_step(state)  # action 2: lane continues inward to (0,-2)
        sb = state.star_breach
        self.assertIn((0, -3), sb.destroyed_hexes)
        self.assertIn((0, -2), sb.destroyed_hexes)  # Shield Generator C hex
        self.assertIn("sg_center", sbd.destroyed_component_ids(sb.destroyed_hexes))
        # Destroying SG C drops the forward and rear shield arcs immediately.
        self.assertEqual(sb.shield_hp["rear"], 0)
        events = [e for e in state.event_log if e["type"] == "boss_volley_resolved"]
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["components_destroyed"], ["sg_center"])

    def test_glancing_blow_awards_desperation_card(self):
        state = _coop_state()
        state.players["alice"].ship.q, state.players["alice"].ship.r = 0, -13
        state.star_breach.shield_hp["forward"] = 0
        # Alice is the Fighting Ace: kill the ace shift by making lane 2 dead too.
        state.players["alice"].roles = ("treasure_hunter",)
        _set_hand(state, "alice", "targeted_attack_aim_1_a")
        deck_before = len(state.players["alice"].deck)
        state = self._submit_both(state, _attack_orders("targeted_attack_aim_1_a", "boss:forward"))
        with self._quiet_enemies(), patch("starshot.rules.engine._roll_d8", return_value=1):
            state = resolve_next_step(state)
        event = next(e for e in state.event_log if e["type"] == "boss_volley_resolved")
        self.assertEqual(event["desperation_cards_drawn"], 1)
        self.assertEqual(len(state.star_breach.destroyed_hexes), 0)
        self.assertEqual(len(state.players["alice"].deck), deck_before + 1)

    def test_craft_can_be_damaged_and_destroyed(self):
        state = _coop_state()
        craft = next(c for c in state.star_breach.fleet if c.id == "hk_green")
        craft.q, craft.r = 1, -13
        craft.hp = 1
        state.players["alice"].ship.q, state.players["alice"].ship.r = 0, -13
        _set_hand(state, "alice", "targeted_attack_aim_1_a")
        state = self._submit_both(state, _attack_orders("targeted_attack_aim_1_a", "craft:hk_green"))
        with self._quiet_enemies():
            state = resolve_next_step(state)
        craft = next(c for c in state.star_breach.fleet if c.id == "hk_green")
        self.assertTrue(craft.destroyed)
        self.assertEqual(state.players["alice"].victory_points, 3)
        event = next(e for e in state.event_log if e["type"] == "craft_volley_resolved")
        self.assertTrue(event["craft_destroyed"])

    def test_engineer_repair_restores_component_once_per_action(self):
        state = _coop_state()
        state.players["alice"].ship.q, state.players["alice"].ship.r = 0, 11
        state.players["bob"].ship.q, state.players["bob"].ship.r = 1, 11
        alice = state.players["alice"]
        alice.ship.destroyed_components = {"bone_room"}
        alice.ship.damage_taken = 1
        _set_hand(state, "bob", "targeted_attack_aim_1_a")
        state = submit_orders(state, "alice", _empty_stacks())
        state = submit_orders(state, "bob", _attack_orders("targeted_attack_aim_1_a", "alice"))
        with self._quiet_enemies():
            state = resolve_next_step(state)
        alice = state.players["alice"]
        self.assertEqual(alice.ship.destroyed_components, set())
        self.assertEqual(alice.ship.damage_taken, 0)
        event = next(e for e in state.event_log if e["type"] == "repair_volley_resolved")
        self.assertTrue(event["hit"])
        self.assertEqual(event["restored_component_id"], "bone_room")
        self.assertIn("alice", state.star_breach.repaired_ship_ids_this_action)

    def test_engineer_repair_restores_shield_when_hull_is_intact(self):
        state = _coop_state()
        state.players["alice"].ship.q, state.players["alice"].ship.r = 0, 11
        state.players["alice"].ship.shields = 0
        state.players["bob"].ship.q, state.players["bob"].ship.r = 1, 11
        _set_hand(state, "bob", "targeted_attack_aim_1_a")
        state = submit_orders(state, "alice", _empty_stacks())
        state = submit_orders(state, "bob", _attack_orders("targeted_attack_aim_1_a", "alice"))
        with self._quiet_enemies():
            state = resolve_next_step(state)
        self.assertEqual(state.players["alice"].ship.shields, 1)
        event = next(e for e in state.event_log if e["type"] == "repair_volley_resolved")
        self.assertTrue(event["shield_restored"])


class StarBreachBossBehaviorTests(unittest.TestCase):
    def test_boss_moves_toward_prey_during_move_phase(self):
        state = _coop_state()
        state = submit_orders(state, "alice", _empty_stacks())
        state = submit_orders(state, "bob", _empty_stacks())
        anchor_before = (state.star_breach.anchor_q, state.star_breach.anchor_r)
        with patch("starshot.rules.engine._roll_d6_sum", return_value=0), patch(
            "starshot.rules.engine._roll_d3_plus_1", return_value=2
        ):
            state = resolve_next_step(state)  # action 1 (boss 0.5 attack phase)
            self.assertEqual((state.star_breach.anchor_q, state.star_breach.anchor_r), anchor_before)
            state = resolve_next_step(state)  # action 2 (boss 1.5 move phase)
        sb = state.star_breach
        self.assertNotEqual((sb.anchor_q, sb.anchor_r), anchor_before)
        # Base + two intact fuel tanks = 3 slots x 2 hexes.
        self.assertEqual(sb.boss_movement_this_action, 6)

    def test_enemy_attacks_target_prey_and_advance_progress(self):
        state = _coop_state()
        # Keep the tank far away so the jammer stays out of the picture.
        state.players["bob"].ship.q, state.players["bob"].ship.r = 0, 13
        state = submit_orders(state, "alice", _empty_stacks())
        state = submit_orders(state, "bob", _empty_stacks())
        with patch("starshot.rules.engine._roll_d6_sum", return_value=30), patch(
            "starshot.rules.engine._roll_d3_plus_1", return_value=1
        ):
            state = resolve_next_step(state)  # boss 0.5: base + fc_a + fc_b, plus 3 craft
        shots = [e for e in state.event_log if e["type"] == "enemy_volley_resolved"]
        self.assertTrue(shots)
        self.assertTrue(all(shot["target_id"] == "alice" for shot in shots))
        self.assertTrue(all(shot["hit"] for shot in shots))
        self.assertEqual(state.star_breach.progress, len(shots))

    def test_tank_proximity_jammer_redirects_and_reduces_dice(self):
        state = _coop_state()
        craft = next(c for c in state.star_breach.fleet if c.id == "hk_green")
        # Tank (bob) sits within jammer range of the craft; prey is far away.
        state.players["bob"].ship.q, state.players["bob"].ship.r = craft.q + 2, craft.r
        state.players["alice"].ship.q, state.players["alice"].ship.r = 0, 13
        state = submit_orders(state, "alice", _empty_stacks())
        state = submit_orders(state, "bob", _empty_stacks())
        with patch("starshot.rules.engine._roll_d6_sum", return_value=30), patch(
            "starshot.rules.engine._roll_d3_plus_1", return_value=1
        ):
            state = resolve_next_step(state)
        craft_shot = next(
            e for e in state.event_log
            if e["type"] == "enemy_volley_resolved" and e.get("craft_id") == "hk_green"
        )
        self.assertEqual(craft_shot["target_id"], "bob")
        self.assertEqual(craft_shot["dice"], 1)

    def test_firing_computer_destruction_disables_attack_slot(self):
        state = _coop_state()
        sb = state.star_breach
        sb.destroyed_hexes.update({(-5, 1), (-5, 2)})  # fc_a and fc_b
        state = submit_orders(state, "alice", _empty_stacks())
        state = submit_orders(state, "bob", _empty_stacks())
        with patch("starshot.rules.engine._roll_d6_sum", return_value=0), patch(
            "starshot.rules.engine._roll_d3_plus_1", return_value=1
        ):
            state = resolve_next_step(state)
        event = next(e for e in state.event_log if e["type"] == "boss_phase_resolved" and e["boss_phase"] == "0.5")
        self.assertEqual([slot["slot"] for slot in event["slots"]], ["base"])

    def test_progress_tiers_unlock_extra_slots(self):
        state = _coop_state()
        state.star_breach.progress = sbd.TIER_PROGRESS[1]
        state = submit_orders(state, "alice", _empty_stacks())
        state = submit_orders(state, "bob", _empty_stacks())
        with patch("starshot.rules.engine._roll_d6_sum", return_value=0), patch(
            "starshot.rules.engine._roll_d3_plus_1", return_value=1
        ):
            state = resolve_next_step(state)
        event = next(e for e in state.event_log if e["type"] == "boss_phase_resolved" and e["boss_phase"] == "0.5")
        self.assertIn({"slot": "tier", "tier": 1, "amount": 1, "attacks": event["slots"][-1]["attacks"]}, [event["slots"][-1]])


class StarBreachOutcomeTests(unittest.TestCase):
    def test_prey_destruction_ends_the_game_immediately(self):
        state = _coop_state()
        state.players["alice"].ship.destroyed = True
        state = submit_orders(state, "alice", _empty_stacks())
        state = submit_orders(state, "bob", _empty_stacks())
        state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.COMPLETE)
        self.assertEqual(state.result.reason, "star_breach_prey_destroyed")
        self.assertEqual(state.result.winner_ids, ())

    def test_prey_in_fang_at_end_of_round_six_wins(self):
        state = _coop_state()
        state.round_number = 6
        state.phase = GamePhase.CLEANUP
        state.players["alice"].ship.q, state.players["alice"].ship.r = 0, 0
        state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.COMPLETE)
        self.assertEqual(state.result.reason, "star_breach_victory")
        self.assertEqual(set(state.result.winner_ids), {"alice", "bob"})

    def test_prey_outside_fang_at_end_of_round_six_loses(self):
        state = _coop_state()
        state.round_number = 6
        state.phase = GamePhase.CLEANUP
        state.players["alice"].ship.q, state.players["alice"].ship.r = 5, 5
        state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.COMPLETE)
        self.assertEqual(state.result.reason, "star_breach_objective_failed")

    def test_is_game_over_uses_coop_rules(self):
        state = _coop_state()
        # A lone surviving ship is normal in co-op, not a win condition.
        state.players["bob"].ship.destroyed = True
        self.assertIsNone(is_game_over(state))


class StarBreachRoleHelperTests(unittest.TestCase):
    def test_treasure_hunter_move_only_overdrive_is_exempt(self):
        state = _coop_state()
        alice = state.players["alice"]  # treasure hunter + fighting ace
        move_stack = ActionStack(1, SealMode.OVERDRIVE, (OrderCardSelection("controlled_move_1_a"),))
        attack_stack = ActionStack(
            2, SealMode.OVERDRIVE, (OrderCardSelection("targeted_attack_aim_1_a", target_player_id="boss:forward"),)
        )
        self.assertTrue(_star_breach_overdrive_exempt(state, alice, move_stack))
        self.assertTrue(_star_breach_overdrive_exempt(state, alice, attack_stack))  # fighting ace
        bob = state.players["bob"]  # tank + engineer: no exemptions
        self.assertFalse(_star_breach_overdrive_exempt(state, bob, move_stack))
        self.assertFalse(_star_breach_overdrive_exempt(state, bob, attack_stack))

    def test_treasure_hunter_bauble_grants_bonus_draws(self):
        state = _coop_state()
        bauble = next(b for b in state.baubles if b.number == 1 and not b.is_fang)
        state.players["alice"].ship.q, state.players["alice"].ship.r = bauble.q, bauble.r
        state.phase = GamePhase.AWARD_BAUBLES
        with patch("starshot.rules.engine._roll_d6_sum", return_value=0), patch(
            "starshot.rules.engine._roll_d3_plus_1", return_value=1
        ):
            state = resolve_next_step(state)
        self.assertGreaterEqual(state.players["alice"].bonus_draws_pending, 1)
        self.assertGreaterEqual(state.players["bob"].bonus_draws_pending, 1)

    def test_fighting_ace_lane_choice_avoids_glancing_and_finds_components(self):
        state = _coop_state()
        sb = state.star_breach
        roll, shift = _fighting_ace_lane_choice(sb, "forward", 1)
        self.assertEqual(roll, 2)
        self.assertEqual(shift, 1)
        # Forward lane 3 leads with Shield Generator L's hex; a roll of 4 shifts down.
        lane_3_first = sbd.first_intact_lane_hex("forward", 3, sb.destroyed_hexes)
        if lane_3_first in sbd.BOSS_COMPONENT_BY_HEX:
            roll, shift = _fighting_ace_lane_choice(sb, "forward", 4)
            self.assertEqual(roll, 3)

    def test_untargeted_forward_attack_finds_craft_then_boss(self):
        state = _coop_state()
        alice = state.players["alice"]
        alice.ship.q, alice.ship.r, alice.ship.facing = 0, 5, 2  # facing -r, toward the boss
        craft = next(c for c in state.star_breach.fleet if c.id == "hk_green")
        craft.q, craft.r = 0, 2
        self.assertEqual(_first_star_breach_forward_target(state, alice), "craft:hk_green")
        craft.destroyed = True
        target = _first_star_breach_forward_target(state, alice)
        self.assertTrue(target.startswith("boss:"), target)


if __name__ == "__main__":
    unittest.main()
