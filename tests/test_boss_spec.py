"""Boss specs: default equivalence, design compilation, and playable games."""

from __future__ import annotations

import unittest

from starshot.rules import (
    ActionStack,
    GameConfig,
    OrdersSubmission,
    SealMode,
    create_initial_state,
    resolve_next_step,
    submit_orders,
)
from starshot.rules import star_breach as sb_data
from starshot.rules import star_breach_spec as sb_spec
from starshot.rules.serialization import state_from_dict, state_to_dict
from starshot.v2.boss_designs import normalize_design, validate_design

from tests.test_boss_designer import make_design


def playable_design(**overrides) -> dict:
    """The designer-test fixture, upgraded with a fleet, and normalized."""
    raw = make_design()
    raw["behavior"] = {
        "boss_ai": "hunter_killer",
        "fleet": {
            "count": 2,
            "kind": "hunter_killer",
            "hp": 2,
            "ai": "hunter_killer",
            "actions": [
                {"stack": "0.5", "action": "shoot"},
                {"stack": "1.5", "action": "move"},
            ],
        },
    }
    raw.update(overrides)
    return normalize_design(raw)


def _empty_orders():
    return OrdersSubmission(
        stacks=(
            ActionStack(1, SealMode.SEALED),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )
    )


class DefaultSpecTests(unittest.TestCase):
    def test_default_spec_matches_stock_scenario_data(self):
        spec = sb_spec.default_spec()
        self.assertEqual(sb_spec.footprint_set(spec), set(sb_data.BOSS_FOOTPRINT))
        self.assertEqual(spec["areas"], list(sb_data.AREAS))
        self.assertEqual(spec["initial_shield_hp"], dict(sb_data.INITIAL_SHIELD_HP))
        self.assertEqual(sb_spec.board_hex_areas(spec), sb_data.BOARD_HEX_AREAS)
        self.assertEqual(
            sb_spec.unlocked_tiers(spec, 7), sb_data.unlocked_tiers(7)
        )
        # Expected actions agree with the stock computation for a fresh boss.
        self.assertEqual(
            sb_spec.expected_phase_actions(spec, set(), (), 1),
            sb_data.expected_phase_actions(set(), ()),
        )

    def test_default_lanes_agree_with_stock(self):
        spec = sb_spec.default_spec()
        for area in sb_data.AREAS:
            for roll in sb_data.DAMAGE_LANE_ROLLS:
                self.assertEqual(
                    sb_spec.first_intact_lane_hex(spec, area, roll, set()),
                    sb_data.first_intact_lane_hex(area, roll, set()),
                )


class DesignSpecTests(unittest.TestCase):
    def test_compiles_components_phases_and_shields(self):
        spec = sb_spec.spec_from_design(playable_design())
        self.assertEqual(spec["areas"], ["1"])
        self.assertEqual(spec["initial_shield_hp"], {"1": 3})
        # 0.5 holds the firing computer plus the step-2 action link; 1.5 the
        # fuel tank. Designed bosses have no free base slots.
        slots_05 = sb_spec.phase_slots(spec, "0.5")
        self.assertEqual([slot["slot"] for slot in slots_05], ["component", "tier"])
        self.assertEqual([slot["kind"] for slot in slots_05], ["attack", "attack"])
        slots_15 = sb_spec.phase_slots(spec, "1.5")
        self.assertEqual([slot["kind"] for slot in slots_15], ["move"])
        self.assertFalse(any(slot["slot"] == "base" for phase in spec["phases"] for slot in phase["slots"]))
        # Progression: 4 steps, each a tier unlocked at its own position.
        self.assertEqual(sb_spec.tier_progress_map(spec), {1: 1, 2: 2, 3: 3, 4: 4})
        # The tier-2 action link only fires once tier 2 is active.
        active_fresh = sb_spec.active_phase_slots(spec, "0.5", set(), set(), 1)
        self.assertEqual(len(active_fresh), 1)
        active_tier2 = sb_spec.active_phase_slots(spec, "0.5", set(), {2}, 1)
        self.assertEqual(len(active_tier2), 2)

    def test_action_link_and_breacher_link_slots(self):
        spec = sb_spec.spec_from_design(playable_design())
        # step 2: action_link 0.5 shoot -> tier slot in 0.5? No: fixture has
        # action_link at index 1 (tier 2).
        tier_slots = [
            slot for slot in sb_spec.phase_slots(spec, "0.5") + sb_spec.phase_slots(spec, "starbreach")
            if slot["slot"] == "tier"
        ]
        self.assertTrue(any(slot["tier"] == 2 for slot in tier_slots))
        breacher = [slot for slot in sb_spec.phase_slots(spec, "starbreach") if slot["slot"] == "tier"]
        self.assertEqual(len(breacher), 1)
        self.assertEqual(breacher[0]["core_hex"], [0, 0])
        self.assertEqual(breacher[0]["min_round"], 3)
        # Not active before its round even with the tier unlocked.
        self.assertFalse(
            sb_spec.slot_is_active(spec, breacher[0], set(), {1, 2, 3, 4}, round_number=2)
        )
        self.assertTrue(
            sb_spec.slot_is_active(spec, breacher[0], set(), {1, 2, 3, 4}, round_number=3)
        )
        # A destroyed core kills the breacher action.
        self.assertFalse(
            sb_spec.slot_is_active(spec, breacher[0], {(0, 0)}, {1, 2, 3, 4}, round_number=3)
        )

    def test_lane_rays_run_inward(self):
        spec = sb_spec.spec_from_design(playable_design())
        # Region 1, roll 3 enters at (1,0) from facing 0 -> inward toward (0,0), (-1,0).
        lane = spec["damage_lanes"]["1"]["3"]
        self.assertEqual(lane, [[1, 0], [0, 0], [-1, 0]])

    def test_partial_lane_set_is_valid_and_compiles(self):
        raw = make_design()
        raw["shield_regions"][0]["lanes"] = raw["shield_regions"][0]["lanes"][:2]
        design = normalize_design(raw)
        self.assertEqual(validate_design(design), [])
        spec = sb_spec.spec_from_design(design)
        self.assertEqual(sorted(spec["damage_lanes"]["1"].keys()), ["2", "3"])

    def test_fleet_and_actions(self):
        spec = sb_spec.spec_from_design(playable_design())
        self.assertEqual(len(spec["fleet"]), 2)
        self.assertTrue(all(craft["hp"] == 2 for craft in spec["fleet"]))
        self.assertEqual(sb_spec.fleet_action_kinds(spec, "0.5"), ["attack"])
        self.assertEqual(sb_spec.fleet_action_kinds(spec, "1.5"), ["move"])
        self.assertEqual(sb_spec.fleet_action_kinds(spec, "2.5"), [])

    def test_components_are_auto_numbered(self):
        spec = sb_spec.spec_from_design(playable_design())
        names = [component["name"] for component in spec["components"]]
        self.assertIn("Cannon 1", names)
        self.assertIn("Engine 1", names)

    def test_spawn_fleet_step_compiles_and_spawns_on_tier_activation(self):
        raw = make_design()
        raw["behavior"] = {
            "boss_ai": "hunter_killer",
            "fleet": {"count": 0, "kind": "hunter_killer", "hp": 4, "ai": "hunter_killer", "actions": []},
        }
        raw["progression"]["steps"].append({"kind": "spawn_fleet", "count": 2, "location": "fang"})
        design = normalize_design(raw)
        spec = sb_spec.spec_from_design(design)
        spawn_tier = str(len(design["progression"]["steps"]))
        self.assertEqual(
            spec["tier_spawns"][spawn_tier],
            {"count": 2, "location": "fang", "kind": "hunter_killer", "hp": 4},
        )
        self.assertEqual(spec["tier_labels"][spawn_tier], {"kind": "spawn", "stack": None})
        state = create_initial_state(
            GameConfig(
                player_ids=("alice", "bob"),
                seed=3,
                active_expansions=("star_breach",),
                star_breach_boss_design=design,
            )
        )
        from starshot.rules.star_breach_engine import _activate_star_breach_tiers

        sb = state.star_breach
        before = len(sb.fleet)
        sb.progress = int(spawn_tier)
        _activate_star_breach_tiers(state)
        self.assertEqual(len(sb.fleet), before + 2)
        events = [event for event in state.event_log if event["type"] == "boss_fleet_spawned"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["location"], "fang")


class DesignedBossGameTests(unittest.TestCase):
    def _designed_state(self, seed=11):
        design = playable_design()
        self.assertEqual(validate_design(design), [])
        return create_initial_state(
            GameConfig(
                player_ids=("alice", "bob"),
                seed=seed,
                active_expansions=("star_breach",),
                star_breach_boss_design=design,
            )
        )

    def test_designed_game_initializes_from_design(self):
        state = self._designed_state()
        sb = state.star_breach
        self.assertIsNotNone(sb.boss_spec)
        self.assertEqual(sb.scenario_id, "design:test_boss")
        self.assertEqual(sb.shield_hp, {"1": 3})
        self.assertEqual(len(sb.fleet), 2)
        self.assertEqual(sb.fleet[0].hp, 2)

    def test_designed_game_resolves_a_full_round(self):
        state = self._designed_state()
        for player_id in ("alice", "bob"):
            state = submit_orders(state, player_id, _empty_orders())
        for _ in range(40):
            if state.phase.value == "give_orders" and state.round_number > 1:
                break
            state = resolve_next_step(state)
        self.assertGreater(state.round_number, 1)
        # The designed boss announced phases with its own slots.
        phase_events = [e for e in state.event_log if e["type"] == "boss_phase_resolved"]
        self.assertTrue(phase_events)

    def test_designed_state_serialization_round_trip(self):
        state = self._designed_state()
        data = state_to_dict(state, reveal_orders=True)
        self.assertEqual(data["star_breach"]["boss_name"], "Test Boss")
        self.assertEqual(data["star_breach"]["boss_layout"]["areas"], ["1"])
        restored = state_from_dict(data)
        self.assertEqual(restored.star_breach.boss_spec, state.star_breach.boss_spec)
        # Round trip again through JSON-ish structures stays stable.
        again = state_to_dict(restored, reveal_orders=True)
        self.assertEqual(again["star_breach"]["boss_spec"], data["star_breach"]["boss_spec"])


if __name__ == "__main__":
    unittest.main()
