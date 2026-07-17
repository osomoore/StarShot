"""Player ship designer: lane generation, points, validation, storage, and
custom ships in play."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from starshot.rules.engine import _apply_unshielded_damage, create_initial_state, resolve_next_step, submit_orders
from starshot.rules.models import ActionStack, GameConfig, OrderCardSelection, OrdersSubmission, SealMode
from starshot.rules.player_ships import (
    PLAYER_SHIP_POINT_BUDGET,
    compile_layout_spec,
    component_entries,
    core_armor_tile_count,
    generate_damage_lanes,
    points_breakdown,
)
from starshot.rules.ship_layout import (
    BASE_SHIP_COMPONENTS,
    BASE_SHIP_DAMAGE_LANES,
    layout_for_ship,
    layout_from_spec,
)
from starshot.rules.serialization import state_from_dict, state_to_dict
from starshot.v2 import ship_designs


def base_clone_design() -> dict:
    """A design that recreates the stock base ship exactly (costs 19)."""
    tiles = []
    for component in BASE_SHIP_COMPONENTS:
        tile_type = {"bridge": "core"}.get(component.component_type, component.component_type)
        tiles.append({"q": component.q, "r": component.r, "type": tile_type})
    return {
        "id": "base_clone",
        "name": "Base Clone",
        "description": "",
        "shields": 2,
        "draw": 5,
        "tiles": tiles,
    }


def skirmisher_design() -> dict:
    """A legal 15-tile custom ship: 0 shields, draw 3, light core armor,
    2 Signal Jammers and 2 Targeting Sensors (15 points total)."""
    tiles = [
        {"q": 0, "r": 0, "type": "core"},
        # eight tiles on the core's axes (the core armor)
        {"q": 0, "r": -1, "type": "life_support"},
        {"q": 0, "r": 1, "type": "life_support"},
        {"q": 0, "r": -2, "type": "weapon"},
        {"q": 0, "r": 2, "type": "engine"},
        {"q": -1, "r": 0, "type": "engine"},
        {"q": 1, "r": 0, "type": "engine"},
        {"q": -2, "r": 0, "type": "weapon"},
        {"q": 2, "r": 0, "type": "weapon"},
        # six off-axis tiles
        {"q": 1, "r": -2, "type": "signal_jammer"},
        {"q": 2, "r": -1, "type": "signal_jammer"},
        {"q": -1, "r": -1, "type": "targeting_sensors"},
        {"q": 1, "r": 1, "type": "targeting_sensors"},
        {"q": -2, "r": 1, "type": "crew"},
        {"q": -1, "r": 2, "type": "bay"},
    ]
    return {
        "id": "skirmisher",
        "name": "Skirmisher",
        "description": "",
        "shields": 0,
        "draw": 3,
        "tiles": tiles,
    }


def _idle_orders() -> OrdersSubmission:
    return OrdersSubmission(
        stacks=(
            ActionStack(1, SealMode.SEALED),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )
    )


class LaneGenerationTests(unittest.TestCase):
    def test_base_clone_reproduces_printed_lane_table(self):
        design = ship_designs.normalize_design(base_clone_design())
        entries = component_entries(design)
        id_by_coord = {(entry["q"], entry["r"]): entry["id"] for entry in entries}
        coord_by_id = {v: k for k, v in id_by_coord.items()}
        generated = generate_damage_lanes(design, id_by_coord)

        base_by_id = {component.id: component for component in BASE_SHIP_COMPONENTS}
        for roll, base_ids in BASE_SHIP_DAMAGE_LANES.items():
            expected = tuple((base_by_id[cid].q, base_by_id[cid].r) for cid in base_ids)
            actual = tuple(coord_by_id[cid] for cid in generated[roll])
            self.assertEqual(actual, expected, f"lane {roll} mismatch")

    def test_missing_core_yields_empty_lanes(self):
        design = ship_designs.normalize_design(base_clone_design())
        design["tiles"] = [tile for tile in design["tiles"] if tile["type"] != "core"]
        lanes = generate_damage_lanes(design, {})
        self.assertEqual(set(lanes), set(range(1, 13)))
        self.assertTrue(all(lane == () for lane in lanes.values()))

    def test_lanes_off_ship_lines_are_empty_and_miss(self):
        design = ship_designs.normalize_design(skirmisher_design())
        spec = compile_layout_spec(design)
        layout = layout_from_spec(spec)
        # every roll must resolve without KeyError even when a lane is empty
        for roll in range(1, 13):
            layout.first_intact_component_for_lane(roll, set())


class PointsTests(unittest.TestCase):
    def test_base_clone_costs_exactly_the_budget(self):
        breakdown = points_breakdown(ship_designs.normalize_design(base_clone_design()))
        self.assertEqual(breakdown["shields"], 2)
        self.assertEqual(breakdown["draw"], 5)
        self.assertEqual(breakdown["core_armor"], 12)
        self.assertEqual(breakdown["total"], PLAYER_SHIP_POINT_BUDGET)

    def test_skirmisher_costs_fifteen(self):
        breakdown = points_breakdown(ship_designs.normalize_design(skirmisher_design()))
        self.assertEqual(breakdown["core_armor"], 8)
        self.assertEqual(breakdown["signal_jammers"], 2)
        self.assertEqual(breakdown["targeting_sensors"], 2)
        self.assertEqual(breakdown["total"], 15)

    def test_core_armor_counts_only_axis_tiles(self):
        design = ship_designs.normalize_design(skirmisher_design())
        self.assertEqual(core_armor_tile_count(design), 8)


class ValidationTests(unittest.TestCase):
    def test_valid_designs_have_no_problems(self):
        for design in (base_clone_design(), skirmisher_design()):
            problems = ship_designs.validate_design(ship_designs.normalize_design(design))
            self.assertEqual(problems, [], design["id"])

    def _problems(self, mutate) -> list[str]:
        raw = skirmisher_design()
        mutate(raw)
        return ship_designs.validate_design(ship_designs.normalize_design(raw))

    def test_missing_core_flagged(self):
        problems = self._problems(
            lambda raw: raw["tiles"].__setitem__(0, {"q": 0, "r": 0, "type": "engine"})
        )
        self.assertTrue(any("Core" in problem for problem in problems))

    def test_wrong_life_support_count_flagged(self):
        problems = self._problems(
            lambda raw: raw["tiles"].__setitem__(1, {"q": 0, "r": -1, "type": "engine"})
        )
        self.assertTrue(any("Life Support" in problem for problem in problems))

    def test_wrong_tile_count_flagged(self):
        problems = self._problems(lambda raw: raw["tiles"].pop())
        self.assertTrue(any("exactly 15 tiles" in problem for problem in problems))

    def test_disconnected_hull_flagged(self):
        def mutate(raw):
            # empty the jammer hexes so the (2,-2) corner has no neighbors
            raw["tiles"] = [
                tile for tile in raw["tiles"] if tile["type"] != "signal_jammer"
            ]
            raw["tiles"][-1] = {"q": 2, "r": -2, "type": "bay"}  # isolated corner
        problems = self._problems(mutate)
        self.assertTrue(any("connected" in problem for problem in problems))

    def test_over_budget_flagged(self):
        def mutate(raw):
            raw["shields"] = 3
            raw["draw"] = 6
        problems = self._problems(mutate)  # 8 armor + 3 + 6 + 4 = 21
        self.assertTrue(any("budget" in problem for problem in problems))

    def test_too_many_jammers_rejected_at_validation(self):
        def mutate(raw):
            raw["tiles"][-1] = {"q": -1, "r": 2, "type": "signal_jammer"}
        problems = self._problems(mutate)
        self.assertTrue(any("Signal Jammer" in problem for problem in problems))

    def test_normalize_rejects_bad_tile_type_and_off_grid(self):
        raw = skirmisher_design()
        raw["tiles"][0] = {"q": 0, "r": 0, "type": "laser"}
        with self.assertRaises(ship_designs.ShipDesignError):
            ship_designs.normalize_design(raw)
        raw = skirmisher_design()
        raw["tiles"][0] = {"q": 3, "r": 0, "type": "core"}
        with self.assertRaises(ship_designs.ShipDesignError):
            ship_designs.normalize_design(raw)
        raw = skirmisher_design()
        raw["shields"] = 4
        with self.assertRaises(ship_designs.ShipDesignError):
            ship_designs.normalize_design(raw)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self._original_dir = ship_designs.DESIGNS_DIR
        self._original_runtime_dir = ship_designs.RUNTIME_DESIGNS_DIR
        root = Path(self._tempdir.name)
        ship_designs.DESIGNS_DIR = root / "bundled"
        ship_designs.RUNTIME_DESIGNS_DIR = root / "runtime"

    def tearDown(self):
        ship_designs.DESIGNS_DIR = self._original_dir
        ship_designs.RUNTIME_DESIGNS_DIR = self._original_runtime_dir
        self._tempdir.cleanup()

    def test_save_load_list_delete_round_trip(self):
        design, problems = ship_designs.save_design(skirmisher_design(), owner_id=7)
        self.assertEqual(problems, [])
        listed = ship_designs.list_designs(7)
        self.assertEqual([entry["id"] for entry in listed], ["skirmisher"])
        self.assertTrue(listed[0]["valid"])
        self.assertEqual(listed[0]["points"], 15)
        loaded = ship_designs.load_design("skirmisher", 7)
        self.assertEqual(loaded, design)
        self.assertEqual(ship_designs.list_designs(), [])  # global library untouched
        self.assertTrue(ship_designs.delete_design("skirmisher", 7))
        self.assertEqual(ship_designs.list_designs(7), [])

    def test_player_design_limit(self):
        for index in range(ship_designs.PLAYER_DESIGN_LIMIT):
            raw = skirmisher_design()
            raw["id"] = f"ship_{index}"
            ship_designs.save_design(raw, owner_id=3)
        raw = skirmisher_design()
        raw["id"] = "one_too_many"
        with self.assertRaises(ship_designs.ShipDesignError):
            ship_designs.save_design(raw, owner_id=3)
        # overwriting an existing design is still allowed
        raw["id"] = "ship_0"
        ship_designs.save_design(raw, owner_id=3)

    def test_clone_to_global(self):
        ship_designs.save_design(skirmisher_design(), owner_id=7)
        design, problems = ship_designs.clone_design_to_global(7, "skirmisher")
        self.assertEqual(problems, [])
        self.assertEqual([entry["id"] for entry in ship_designs.list_designs()], ["skirmisher"])
        # cloning again gets a fresh id instead of overwriting
        design2, _ = ship_designs.clone_design_to_global(7, "skirmisher")
        self.assertEqual(design2["id"], "skirmisher_2")

    def test_incomplete_design_saves_with_problems(self):
        raw = skirmisher_design()
        raw["tiles"] = raw["tiles"][:5]
        design, problems = ship_designs.save_design(raw, owner_id=7)
        self.assertTrue(problems)
        self.assertFalse(ship_designs.list_designs(7)[0]["valid"])


class CustomShipInPlayTests(unittest.TestCase):
    def _state_with_designs(self, red_design=None, blue_design=None, seed=1):
        designs = {}
        if red_design is not None:
            designs["red"] = ship_designs.normalize_design(red_design)
        if blue_design is not None:
            designs["blue"] = ship_designs.normalize_design(blue_design)
        return create_initial_state(
            GameConfig(player_ids=("red", "blue"), seed=seed, player_ship_designs=designs or None)
        )

    def test_designed_stats_apply_at_setup(self):
        state = self._state_with_designs(red_design=skirmisher_design())
        red = state.players["red"]
        blue = state.players["blue"]
        self.assertEqual(red.ship.shields, 0)
        # 0 shields = exhausted from the start: draw 3 + 1
        self.assertEqual(len(red.hand), 4)
        self.assertIsNotNone(red.ship.layout)
        self.assertIsNone(blue.ship.layout)
        self.assertEqual(blue.ship.shields, 2)
        self.assertEqual(len(blue.hand), 5)

    def test_damage_lanes_follow_custom_layout(self):
        state = self._state_with_designs(red_design=skirmisher_design())
        red = state.players["red"]
        layout = layout_for_ship(red.ship)
        # lane 1 on the skirmisher: the core column entered from aft
        lane_1 = layout.damage_lanes[1]
        self.assertEqual(layout.component_by_id[lane_1[0]].component_type, "engine")
        result = _apply_unshielded_damage(state, red, 1, fixed_lane_roll=1)
        self.assertEqual(result["damage_applied"], 1)
        self.assertIn(lane_1[0], red.ship.destroyed_components)

    def test_ship_death_uses_custom_layout(self):
        state = self._state_with_designs(red_design=skirmisher_design())
        red = state.players["red"]
        layout = layout_for_ship(red.ship)
        life_ids = [c.id for c in layout.components if c.component_type == "life_support"]
        self.assertEqual(len(life_ids), 2)
        red.ship.destroyed_components.update(life_ids)
        self.assertTrue(layout.is_ship_destroyed(red.ship.destroyed_components))

    def test_sensors_and_jammers_shape_the_volley(self):
        state = self._state_with_designs(
            red_design=skirmisher_design(), blue_design=skirmisher_design()
        )
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["blue"].ship.q = 2
        state.players["blue"].ship.r = 0
        from starshot.rules.decks import card_by_id

        state.players["red"].hand = [card_by_id("targeted_attack_aim_1_a")]
        red_orders = OrdersSubmission(
            stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection("targeted_attack_aim_1_a", target_player_id="blue"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )
        )
        state = submit_orders(state, "red", red_orders)
        state = submit_orders(state, "blue", _idle_orders())
        state = resolve_next_step(state)
        volley = [event for event in state.event_log if event["type"] == "volley_resolved"][-1]
        # attacker: 2 intact Targeting Sensors -> +4 aim on top of the card's +1
        self.assertEqual(volley["sensor_aim_bonus"], 4)
        self.assertEqual(volley["aim_bonus"], 5)
        # target: 2 intact Signal Jammers -> +4 defense
        self.assertEqual(volley["jammer_defense_bonus"], 4)
        self.assertEqual(volley["defense_threshold"], 2 + 0 + 0 + 4)

    def test_serialization_round_trips_custom_layout(self):
        state = self._state_with_designs(red_design=skirmisher_design())
        data = state_to_dict(state)
        red_ship = data["players"]["red"]["ship"]
        self.assertEqual(red_ship["max_shields"], 0)
        self.assertEqual(red_ship["layout_id"], "design_skirmisher")
        self.assertEqual(len(red_ship["component_layout"]), 15)
        self.assertEqual(len(red_ship["damage_lanes"]), 12)
        restored = state_from_dict(data)
        layout = layout_for_ship(restored.players["red"].ship)
        self.assertEqual(layout.base_draw, 3)
        self.assertEqual(layout.max_shields, 0)
        self.assertEqual(
            layout.damage_lanes, layout_for_ship(state.players["red"].ship).damage_lanes
        )

    def test_compile_spec_matches_layout_contract(self):
        spec = compile_layout_spec(ship_designs.normalize_design(base_clone_design()))
        layout = layout_from_spec(spec)
        self.assertEqual(len(layout.components), 15)
        self.assertEqual(layout.max_shields, 2)
        self.assertEqual(layout.base_draw, 5)
        self.assertEqual(layout.intact_count_of_type("life_support", set()), 2)
        self.assertIsNotNone(layout.bridge_id)


if __name__ == "__main__":
    unittest.main()
