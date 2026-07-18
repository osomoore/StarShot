"""StarBreach features: enemy AI programs, boss Supers, and player goals."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from starshot.rules import (
    ActionStack,
    GameConfig,
    GamePhase,
    OrderCardSelection,
    OrdersSubmission,
    SealMode,
    create_initial_state,
    resolve_next_step,
    submit_orders,
)
from starshot.rules import star_breach_spec as sb_spec
from starshot.rules.decks import card_by_id
from starshot.rules.hex import hex_distance
from starshot.rules.serialization import state_from_dict, state_to_dict
from starshot.rules.star_breach_engine import (
    _drag_player,
    _resolve_super_effect,
    adjust_player_action_landing,
)
from starshot.v2.boss_designs import BossDesignError, normalize_design, validate_design

from tests.test_boss_designer import make_design


def _coop_state(player_ids=("alice", "bob"), seed=11, boss_ai=None, fleet_ai=None, supers=None, goal=None):
    state = create_initial_state(
        GameConfig(player_ids=player_ids, seed=seed, active_expansions=("star_breach",))
    )
    if boss_ai or fleet_ai or supers or goal:
        spec = sb_spec.default_spec()
        if boss_ai:
            spec["boss_ai"] = boss_ai
        if fleet_ai:
            spec["fleet_ai"] = fleet_ai
        if supers:
            spec["supers"] = supers
        if goal:
            spec["goal"] = goal
        state.star_breach.boss_spec = spec
    return state


def _empty_stacks():
    return OrdersSubmission(
        stacks=(
            ActionStack(1, SealMode.SEALED),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )
    )


def _attack_orders(card_id, target, action=1):
    stacks = []
    for number in (1, 2, 3):
        if number == action:
            stacks.append(
                ActionStack(number, SealMode.SEALED, (OrderCardSelection(card_id, target_player_id=target),))
            )
        else:
            stacks.append(ActionStack(number, SealMode.SEALED))
    return OrdersSubmission(stacks=tuple(stacks))


def _set_hand(state, player_id, *card_ids):
    player = state.players[player_id]
    requested = set(card_ids)
    player.deck = [card for card in player.deck if card.id not in requested]
    player.hand = [card_by_id(card_id) for card_id in card_ids]


def _submit_all_empty(state):
    for player_id in state.players:
        state = submit_orders(state, player_id, _empty_stacks())
    return state


def _quiet_enemies():
    return patch("starshot.rules.engine._roll_d6_sum", return_value=0)


class DesignSchemaTests(unittest.TestCase):
    def test_normalize_supers_goal_and_ais(self):
        raw = make_design()
        raw["behavior"] = {
            "boss_ai": "vault_runner",
            "fleet": {"count": 2, "kind": "hunter_killer", "hp": 3, "ai": "dynamic", "actions": [
                {"stack": "0.5", "action": "shoot"},
            ]},
        }
        raw["supers"] = [
            {"effect": "chain_shot", "core": 1, "stack": "0.5", "trigger": {"kind": "round", "value": 3}},
            {"effect": "mine_dropper", "core": 1, "stack": "starbreach", "trigger": {"kind": "progress", "value": 2}},
        ]
        raw["goal"] = {"kind": "capture_vaults", "count": 8}
        design = normalize_design(raw)
        self.assertEqual(design["behavior"]["boss_ai"], "vault_runner")
        self.assertEqual(design["behavior"]["fleet"]["ai"], "dynamic")
        self.assertEqual(
            design["supers"][0],
            {"effect": "chain_shot", "core": 1, "stack": "0.5", "trigger": {"kind": "round", "value": 3}},
        )
        self.assertEqual(design["goal"], {"kind": "capture_vaults", "count": 8})
        self.assertEqual(validate_design(design), [])

    def test_missing_supers_and_goal_default(self):
        design = normalize_design(make_design())
        self.assertEqual(design["supers"], [])
        self.assertEqual(design["goal"], {"kind": "escape_fang"})

    def test_bad_super_and_goal_rejected(self):
        raw = make_design()
        raw["supers"] = [{"effect": "death_ray", "core": 1, "trigger": {"kind": "round", "value": 1}}]
        with self.assertRaises(BossDesignError):
            normalize_design(raw)
        raw = make_design()
        # core_destroyed is no longer a trigger kind: cores gate Supers instead.
        raw["supers"] = [{"effect": "infuser", "core": 1, "trigger": {"kind": "core_destroyed", "value": 1}}]
        with self.assertRaises(BossDesignError):
            normalize_design(raw)
        raw = make_design()
        raw["goal"] = {"kind": "world_domination"}
        with self.assertRaises(BossDesignError):
            normalize_design(raw)

    def test_validation_flags_missing_core_and_fleetless_goal(self):
        raw = make_design()
        raw["supers"] = [{"effect": "infuser", "core": 7, "trigger": {"kind": "round", "value": 1}}]
        problems = validate_design(normalize_design(raw))
        self.assertTrue(any("core 7" in problem for problem in problems))
        raw = make_design()
        raw["goal"] = {"kind": "destroy_fleet"}
        problems = validate_design(normalize_design(raw))
        self.assertTrue(any("no fleet craft" in problem for problem in problems))

    def test_spec_carries_ai_supers_and_goal(self):
        raw = make_design()
        raw["behavior"] = {
            "boss_ai": "blaster",
            "fleet": {"count": 1, "kind": "hunter_killer", "hp": 3, "ai": "vault_runner", "actions": [
                {"stack": "1.5", "action": "move"},
            ]},
        }
        raw["supers"] = [{"effect": "scattershot", "core": 1, "stack": "3.5", "trigger": {"kind": "progress", "value": 2}}]
        raw["goal"] = {"kind": "destroy_fleet"}
        spec = sb_spec.spec_from_design(normalize_design(raw))
        self.assertEqual(sb_spec.boss_ai(spec), "blaster")
        self.assertEqual(sb_spec.fleet_ai(spec), "vault_runner")
        self.assertEqual(sb_spec.boss_supers(spec), [
            {"id": "super_1", "effect": "scattershot", "core": 1, "stack": "3.5",
             "trigger": {"kind": "progress", "value": 2}}
        ])
        # The Super occupies a slot in its stack, gated on its Core and tier.
        super_slots = [slot for slot in sb_spec.phase_slots(spec, "3.5") if slot["slot"] == "super"]
        self.assertEqual(len(super_slots), 1)
        slot = super_slots[0]
        self.assertEqual(slot["core_hex"], [0, 0])
        self.assertEqual(slot["tier"], 2)
        self.assertFalse(sb_spec.slot_is_active(spec, slot, set(), set(), round_number=6))
        self.assertTrue(sb_spec.slot_is_active(spec, slot, set(), {2}, round_number=1))
        self.assertFalse(sb_spec.slot_is_active(spec, slot, {(0, 0)}, {2}, round_number=1))
        self.assertEqual(sb_spec.boss_goal(spec), {"kind": "destroy_fleet"})
        # Old specs (no fields) default cleanly.
        self.assertEqual(sb_spec.boss_ai({}), "hunter_killer")
        self.assertEqual(sb_spec.boss_goal({}), {"kind": "escape_fang"})
        self.assertEqual(sb_spec.boss_supers({}), [])


class EnemyAiTests(unittest.TestCase):
    def test_blaster_targets_nearest_player_not_prey(self):
        state = _coop_state(boss_ai="blaster", fleet_ai="blaster")
        # Prey (alice) stays far away; bob parks next to the boss nose.
        state.players["bob"].ship.q, state.players["bob"].ship.r = 0, -11
        state = _submit_all_empty(state)
        with patch("starshot.rules.engine._roll_d6_sum", return_value=30):
            state = resolve_next_step(state)
        shots = [e for e in state.event_log if e["type"] == "enemy_volley_resolved"]
        self.assertTrue(shots)
        self.assertTrue(all(shot["target_id"] == "bob" for shot in shots))

    def test_dynamic_switches_to_attacker_once_per_round(self):
        state = _coop_state(boss_ai="dynamic")
        sb = state.star_breach
        # Bob (tank/engineer) shoots the boss in action 1.
        state.players["bob"].ship.q, state.players["bob"].ship.r = 0, -11
        _set_hand(state, "bob", "targeted_attack_aim_1_a")
        state = submit_orders(state, "alice", _empty_stacks())
        state = submit_orders(state, "bob", _attack_orders("targeted_attack_aim_1_a", "boss:forward"))
        with _quiet_enemies():
            state = resolve_next_step(state)
        sb = state.star_breach
        self.assertEqual(sb.boss_ai_target_id, "bob")
        self.assertEqual(sb.boss_ai_switch_round, 1)
        switch = next(e for e in state.event_log if e["type"] == "boss_directive_changed")
        self.assertEqual(switch["scope"], "boss")
        self.assertEqual(switch["reason"], "boss_hit")
        # A second trigger in the same round does not move the directive.
        from starshot.rules.star_breach_engine import _dynamic_directive_switch

        _dynamic_directive_switch(state, state.players["alice"], "bauble_pickup")
        self.assertEqual(state.star_breach.boss_ai_target_id, "bob")
        # Next round the directive may switch again.
        state.round_number = 2
        _dynamic_directive_switch(state, state.players["alice"], "bauble_pickup")
        self.assertEqual(state.star_breach.boss_ai_target_id, "alice")

    def test_vault_runner_boss_heads_for_and_harvests_the_vault(self):
        state = _coop_state(boss_ai="vault_runner")
        sb = state.star_breach
        vault = next(v for v in state.vaults if not v.is_fang and v.number == 1)
        # Park the boss three hexes from the vault; keep players far away.
        sb.anchor_q, sb.anchor_r = vault.q + 3, vault.r
        state.players["alice"].ship.q, state.players["alice"].ship.r = -12, 0
        state.players["bob"].ship.q, state.players["bob"].ship.r = 12, -12
        state = _submit_all_empty(state)
        with _quiet_enemies():
            state = resolve_next_step(state)  # action 1 (boss 0.5 attack)
            state = resolve_next_step(state)  # action 2 (boss 1.5 move x3)
        sb = state.star_breach
        vault = next(v for v in state.vaults if not v.is_fang and v.number == 1)
        self.assertLessEqual(hex_distance(sb.anchor_q, sb.anchor_r, vault.q, vault.r), 1)
        self.assertIn("starbreacher", vault.claimed_by)
        self.assertTrue(any(e["type"] == "boss_vault_pickup" for e in state.event_log))
        # No vault-pickup progress trigger is set, so the track holds still.
        self.assertEqual(sb.progress, 0)


def _stock_super(effect, *, stack="0.5", kind="round", value=1):
    """A Super synced to the stock Breacher Core (Core 1 at boss-local 0,0)."""
    return {"id": "super_1", "effect": effect, "core": 1, "stack": stack, "trigger": {"kind": kind, "value": value}}


class BossSuperTests(unittest.TestCase):
    def test_immobilizer_cancels_movement_and_recurs_each_round(self):
        state = _coop_state(supers=[_stock_super("immobilizer_shot")])
        alice = state.players["alice"]
        alice.ship.q, alice.ship.r, alice.ship.facing = 0, 0, 0
        _set_hand(state, "alice", "controlled_move_2_a")
        orders = OrdersSubmission(
            stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection("controlled_move_2_a", orientation="forward"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )
        )
        state = submit_orders(state, "alice", orders)
        state = submit_orders(state, "bob", _empty_stacks())
        with _quiet_enemies():
            state = resolve_next_step(state)
        self.assertIn("alice", state.star_breach.immobilized_player_ids)
        activations = [e for e in state.event_log if e["type"] == "boss_super_activated"]
        self.assertEqual(len(activations), 1)
        # The move card resolved for zero distance: the ship did not budge.
        self.assertEqual((state.players["alice"].ship.q, state.players["alice"].ship.r), (0, 0))
        # The effect wears off when the next round activates...
        with _quiet_enemies():
            for _ in range(40):
                if state.phase == GamePhase.GIVE_ORDERS and state.round_number > 1:
                    break
                state = resolve_next_step(state)
        self.assertEqual(state.star_breach.immobilized_player_ids, [])
        # ...and the Super fires again next round: it keeps its stack slot.
        state = _submit_all_empty(state)
        with _quiet_enemies():
            state = resolve_next_step(state)
        activations = [e for e in state.event_log if e["type"] == "boss_super_activated"]
        self.assertEqual(len(activations), 2)
        self.assertTrue(state.star_breach.immobilized_player_ids)

    def test_super_falls_silent_when_its_core_is_destroyed(self):
        state = _coop_state(supers=[_stock_super("mark_the_prey")])
        state.star_breach.destroyed_hexes.add((0, 0))  # the Breacher Core hex
        state = _submit_all_empty(state)
        with _quiet_enemies():
            state = resolve_next_step(state)
        self.assertFalse(any(e["type"] == "boss_super_activated" for e in state.event_log))
        self.assertEqual(state.star_breach.marked_player_ids, [])

    def test_mark_the_prey_lowers_defense_threshold(self):
        state = _coop_state(supers=[_stock_super("mark_the_prey")])
        state = _submit_all_empty(state)
        with _quiet_enemies():
            state = resolve_next_step(state)
        self.assertIn("alice", state.star_breach.marked_player_ids)
        # The Super holds the last slot of stack 0.5, so the fleet's shots
        # (which resolve after the boss's slots) fire at the marked Prey.
        craft_shots = [
            e for e in state.event_log
            if e["type"] == "enemy_volley_resolved" and e.get("craft_id") and e["target_id"] == "alice"
        ]
        self.assertTrue(craft_shots)
        self.assertTrue(all(shot["marked_penalty"] == 5 for shot in craft_shots))

    def test_mine_drops_and_detonates_on_passersby(self):
        state = _coop_state(supers=[_stock_super("mine_dropper")])
        state = _submit_all_empty(state)
        with _quiet_enemies():
            state = resolve_next_step(state)
        sb = state.star_breach
        self.assertEqual(len(sb.mines), 1)
        mine = sb.mines[0]
        alice = state.players["alice"]
        # Sailing within 2 hexes of the mine sets it off for 3 damage.
        path = [(mine["q"], mine["r"] + 2)]
        shields_before = alice.ship.shields
        adjust_player_action_landing(state, alice, path)
        self.assertEqual(sb.mines, [])
        event = next(e for e in state.event_log if e["type"] == "mine_detonated")
        self.assertEqual(event["player_id"], "alice")
        self.assertEqual(event["damage"], 3)
        self.assertEqual(event["shields_absorbed"], shields_before)
        self.assertEqual(alice.ship.shields, 0)

    def test_tractor_beam_and_knockback_drag_two_hexes(self):
        state = _coop_state()
        sb = state.star_breach
        alice = state.players["alice"]
        alice.ship.q, alice.ship.r = sb.anchor_q, sb.anchor_r + 6
        detail = _drag_player(state, alice, 2, inward=True)
        self.assertEqual(detail["moved"], 2)
        self.assertEqual(hex_distance(alice.ship.q, alice.ship.r, sb.anchor_q, sb.anchor_r), 4)
        detail = _drag_player(state, alice, 2, inward=False)
        self.assertEqual(detail["moved"], 2)
        self.assertEqual(hex_distance(alice.ship.q, alice.ship.r, sb.anchor_q, sb.anchor_r), 6)

    def test_chain_shot_arcs_between_nearby_ships(self):
        state = _coop_state()
        sb = state.star_breach
        state.players["alice"].ship.q, state.players["alice"].ship.r = sb.anchor_q, sb.anchor_r - 2
        state.players["bob"].ship.q, state.players["bob"].ship.r = sb.anchor_q + 3, sb.anchor_r - 2
        with patch("starshot.rules.engine._roll_d6_sum", return_value=30):
            detail = _resolve_super_effect(state, "chain_shot")
        self.assertEqual(len(detail["links"]), 2)
        self.assertEqual({link["target_id"] for link in detail["links"]}, {"alice", "bob"})
        chain_shots = [
            e for e in state.event_log
            if e["type"] == "enemy_volley_resolved" and e["attacker"] == "starbreacher_chain"
        ]
        self.assertEqual(len(chain_shots), 2)

    def test_infuser_grants_three_fleet_move_actions(self):
        state = _coop_state()
        sb = state.star_breach
        craft = sb.fleet[0]
        before = (craft.q, craft.r)
        prey = state.players["alice"]
        distance_before = hex_distance(before[0], before[1], prey.ship.q, prey.ship.r)
        detail = _resolve_super_effect(state, "infuser")
        living = [c for c in sb.fleet if not c.destroyed]
        self.assertEqual(len(detail["fleet_moves"]), 3 * len(living))
        distance_after = hex_distance(craft.q, craft.r, prey.ship.q, prey.ship.r)
        self.assertLess(distance_after, distance_before)

    def test_super_slots_count_toward_expected_phase_actions(self):
        state = _coop_state(supers=[_stock_super("inferno_zone", stack="3.5", kind="round", value=2)])
        sb = state.star_breach
        spec = sb_spec.spec_for(sb)
        # Round 1: gate closed — the stock 3.5 stack has its usual 3 slots.
        self.assertEqual(sb_spec.expected_phase_actions(spec, set(), (), 1)["3.5"], 3)
        # Round 2: the Super adds a fourth action to its stack.
        self.assertEqual(sb_spec.expected_phase_actions(spec, set(), (), 2)["3.5"], 4)
        # Its Core destroyed: back to 3, whatever the round.
        self.assertEqual(sb_spec.expected_phase_actions(spec, {(0, 0)}, (), 6)["3.5"], 3)


class PlayerGoalTests(unittest.TestCase):
    def test_destroy_fleet_goal_wins_when_last_craft_dies(self):
        state = _coop_state(goal={"kind": "destroy_fleet"})
        sb = state.star_breach
        for craft in sb.fleet[:-1]:
            craft.destroyed = True
        last = sb.fleet[-1]
        last.q, last.r = 1, 12
        last.hp = 1
        state.players["alice"].ship.q, state.players["alice"].ship.r = 0, 12
        _set_hand(state, "alice", "targeted_attack_aim_1_a")
        state = submit_orders(state, "alice", _attack_orders("targeted_attack_aim_1_a", f"craft:{last.id}"))
        state = submit_orders(state, "bob", _empty_stacks())
        with _quiet_enemies():
            state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.COMPLETE)
        self.assertEqual(state.result.reason, "star_breach_victory")
        self.assertEqual(set(state.result.winner_ids), {"alice", "bob"})

    def test_capture_vaults_goal_wins_at_award_time(self):
        state = _coop_state(goal={"kind": "capture_vaults", "count": 1})
        vault = next(v for v in state.vaults if v.number == 1 and not v.is_fang)
        state.players["alice"].ship.q, state.players["alice"].ship.r = vault.q, vault.r
        state.phase = GamePhase.AWARD_VAULTS
        with _quiet_enemies():
            state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.COMPLETE)
        self.assertEqual(state.result.reason, "star_breach_victory")

    def test_non_fang_goal_fails_at_round_six_without_completion(self):
        state = _coop_state(goal={"kind": "capture_vaults", "count": 9})
        state.round_number = 6
        state.phase = GamePhase.CLEANUP
        # The prey sits in The Fang, but the goal is the vault haul, not escape.
        state.players["alice"].ship.q, state.players["alice"].ship.r = 0, 0
        state = resolve_next_step(state)
        self.assertEqual(state.phase, GamePhase.COMPLETE)
        self.assertEqual(state.result.reason, "star_breach_objective_failed")


class FeatureSerializationTests(unittest.TestCase):
    def test_new_state_fields_round_trip(self):
        state = _coop_state(
            boss_ai="dynamic",
            fleet_ai="blaster",
            supers=[_stock_super("mine_dropper", stack="1.5", kind="round", value=1)],
            goal={"kind": "capture_vaults", "count": 8},
        )
        sb = state.star_breach
        sb.boss_ai_target_id = "bob"
        sb.boss_ai_switch_round = 2
        sb.mines = [{"id": "mine_1", "q": 3, "r": -4}]
        sb.immobilized_player_ids = ["alice"]
        sb.marked_player_ids = ["alice"]
        data = state_to_dict(state)
        self.assertEqual(data["star_breach"]["boss_ai"], "dynamic")
        self.assertEqual(data["star_breach"]["fleet_ai"], "blaster")
        self.assertEqual(data["star_breach"]["goal"], {"kind": "capture_vaults", "count": 8})
        self.assertTrue(data["star_breach"]["supers"][0]["active"])
        restored = state_from_dict(data)
        rsb = restored.star_breach
        self.assertEqual(rsb.boss_ai_target_id, "bob")
        self.assertEqual(rsb.boss_ai_switch_round, 2)
        self.assertEqual(rsb.mines, [{"id": "mine_1", "q": 3, "r": -4}])
        self.assertEqual(rsb.immobilized_player_ids, ["alice"])
        self.assertEqual(rsb.marked_player_ids, ["alice"])


if __name__ == "__main__":
    unittest.main()
