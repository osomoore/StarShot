"""StarDock player ship designer: lane placement, core points/deck building,
upgrades, validation, storage, and custom ships in play."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from starshot.rules.decks import card_by_id, create_designed_deck
from starshot.rules.engine import _apply_unshielded_damage, create_initial_state, resolve_next_step, submit_orders
from starshot.rules.models import ActionStack, GameConfig, OrderCardSelection, OrdersSubmission, SealMode
from starshot.rules.player_ships import (
    SECONDARY_LANE_ROLLS,
    compile_layout_spec,
    core_points_budget,
    core_points_spent,
    deck_counts,
    generate_damage_lanes,
    lane_cells,
    lane_severed_count,
    points_breakdown,
    primary_lane_tile_count,
)
from starshot.rules.serialization import state_from_dict, state_to_dict
from starshot.rules.ship_layout import layout_for_ship, layout_from_spec
from starshot.v2 import ship_designs


def vanguard_design() -> dict:
    """A battle-ready 15-tile ship: the classic 10-card deck (3 Move 1,
    4 Move 2, 2 Aim +1, 1 Aim +2 = 15 core points) plus a shield upgrade."""
    return {
        "id": "vanguard",
        "name": "Vanguard",
        "description": "",
        "tiles": [
            {"q": 0, "r": 0, "type": "core"},
            {"q": 0, "r": -1, "type": "bone_room"},
            {"q": 0, "r": 1, "type": "docking_bay"},
            {"q": 1, "r": -1, "type": "life_support"},
            {"q": -1, "r": 1, "type": "life_support"},
            {"q": 0, "r": -2, "type": "double_cannon"},
            {"q": 0, "r": 2, "type": "engine"},
            {"q": -1, "r": 0, "type": "engine"},
            {"q": 1, "r": 0, "type": "engine"},
            {"q": 1, "r": -2, "type": "cannon"},
            {"q": 2, "r": -1, "type": "cannon"},
            {"q": -1, "r": -1, "type": "double_engine"},
            {"q": -2, "r": 1, "type": "double_engine"},
            {"q": -1, "r": 2, "type": "double_engine"},
            {"q": 1, "r": 1, "type": "double_engine"},
        ],
        "lanes": {
            "3": {"q": 0, "r": 1, "dir": 1},
            "9": {"q": 0, "r": 1, "dir": 4},
            "5": {"q": 0, "r": -1, "dir": 0},
            "11": {"q": 0, "r": -1, "dir": 3},
            "6": {"q": 0, "r": 1, "dir": 0},
            "8": {"q": 0, "r": 1, "dir": 3},
        },
        "upgrade": "shield",
    }


def _with_upgrade(upgrade: str | None) -> dict:
    raw = vanguard_design()
    raw["upgrade"] = upgrade
    return raw


def _idle_orders() -> OrdersSubmission:
    return OrdersSubmission(
        stacks=(
            ActionStack(1, SealMode.SEALED),
            ActionStack(2, SealMode.SEALED),
            ActionStack(3, SealMode.SEALED),
        )
    )


class LaneMathTests(unittest.TestCase):
    def test_lane_cells_walks_the_full_grid_line(self):
        cells = lane_cells(0, -1, 0)  # row r=-1, port -> starboard
        self.assertEqual(cells[0], (-4, -1))
        self.assertEqual(cells[-1], (5, -1))
        self.assertTrue(all(r == -1 for _, r in cells))
        # opposite direction reverses travel order
        self.assertEqual(lane_cells(0, -1, 3), list(reversed(cells)))

    def test_primary_lanes_follow_the_core(self):
        design = ship_designs.normalize_design(vanguard_design())
        entries_by_coord = {
            (tile["q"], tile["r"]): f'{tile["type"]}_x' for tile in design["tiles"]
        }
        lanes = generate_damage_lanes(design, entries_by_coord)
        for roll in (1, 2, 4, 7, 10, 12):
            self.assertIn("core_x", lanes[roll], f"primary lane {roll} must contain the core")
        for roll in SECONDARY_LANE_ROLLS:
            self.assertNotIn("core_x", lanes[roll], f"secondary lane {roll} must avoid the core")
        # lane 1 and 7 are the same line in opposite orders
        self.assertEqual(tuple(reversed(lanes[1])), lanes[7])

    def test_missing_core_yields_empty_primary_lanes(self):
        design = ship_designs.normalize_design(vanguard_design())
        design["tiles"] = [tile for tile in design["tiles"] if tile["type"] != "core"]
        design["lanes"] = {}
        lanes = generate_damage_lanes(design, {})
        self.assertEqual(set(lanes), set(range(1, 13)))
        self.assertTrue(all(lane == () for lane in lanes.values()))

    def test_severed_count(self):
        design = ship_designs.normalize_design(vanguard_design())
        # row r=-1 severs the (0,-2)/(1,-2) nose pair
        self.assertEqual(lane_severed_count(design, lane_cells(0, -1, 0)), 2)
        # the q=1 column only severs the lone (2,-1) cannon
        self.assertEqual(lane_severed_count(design, lane_cells(1, 0, 5)), 1)
        # a lane through the core severs nothing (it is not a legal secondary lane)
        self.assertEqual(lane_severed_count(design, lane_cells(0, 0, 0)), 0)


class PointsAndDeckTests(unittest.TestCase):
    def test_vanguard_spends_exactly_fifteen(self):
        design = ship_designs.normalize_design(vanguard_design())
        self.assertEqual(core_points_spent(design), 15)
        self.assertEqual(core_points_budget(design), 15)
        self.assertEqual(
            deck_counts(design), {"move_1": 3, "move_2": 4, "aim_1": 2, "aim_2": 1}
        )
        breakdown = points_breakdown(design)
        self.assertEqual(breakdown["deck_components"], 10)
        self.assertEqual(breakdown["primary_lane_tiles"], 8)

    def test_points_upgrade_raises_the_budget(self):
        design = ship_designs.normalize_design(_with_upgrade("points"))
        self.assertEqual(core_points_budget(design), 17)

    def test_primary_lane_tiles_counted_against_limit(self):
        design = ship_designs.normalize_design(vanguard_design())
        self.assertEqual(primary_lane_tile_count(design), 8)

    def test_designed_deck_reuses_catalog_cards_then_clones(self):
        deck = create_designed_deck({"move_1": 5, "move_2": 0, "aim_1": 0, "aim_2": 3})
        self.assertEqual(len(deck), 8)
        self.assertEqual(len({card.id for card in deck}), 8, "card ids must be unique")
        for card in deck:
            resolved = card_by_id(card.id)  # clones must resolve by id too
            self.assertEqual(resolved.name, card.name)
        move_ones = [card for card in deck if card.value == 1 and card.aim_bonus == 0]
        self.assertEqual(len(move_ones), 5)


class ValidationTests(unittest.TestCase):
    def test_valid_design_has_no_problems(self):
        problems = ship_designs.validate_design(ship_designs.normalize_design(vanguard_design()))
        self.assertEqual(problems, [])

    def _problems(self, mutate) -> list[str]:
        raw = vanguard_design()
        mutate(raw)
        return ship_designs.validate_design(ship_designs.normalize_design(raw))

    def test_missing_core_flagged(self):
        problems = self._problems(
            lambda raw: raw["tiles"].__setitem__(0, {"q": 0, "r": 0, "type": "engine"})
        )
        self.assertTrue(any("1 Core" in problem for problem in problems))

    def test_wrong_life_support_count_flagged(self):
        problems = self._problems(
            lambda raw: raw["tiles"].__setitem__(3, {"q": 1, "r": -1, "type": "structure"})
        )
        self.assertTrue(any("Life Support" in problem for problem in problems))

    def test_bone_room_and_docking_bay_required(self):
        problems = self._problems(
            lambda raw: raw["tiles"].__setitem__(1, {"q": 0, "r": -1, "type": "engine"})
        )
        self.assertTrue(any("Bone Room" in problem for problem in problems))
        problems = self._problems(
            lambda raw: raw["tiles"].__setitem__(2, {"q": 0, "r": 1, "type": "engine"})
        )
        self.assertTrue(any("Docking Bay" in problem for problem in problems))

    def test_wrong_tile_count_flagged(self):
        problems = self._problems(lambda raw: raw["tiles"].pop())
        self.assertTrue(any("exactly 15 tiles" in problem for problem in problems))

    def test_deck_component_count_enforced(self):
        problems = self._problems(
            lambda raw: raw["tiles"].__setitem__(14, {"q": 1, "r": 1, "type": "structure"})
        )
        self.assertTrue(any("10 Engine/Cannon" in problem for problem in problems))

    def test_structure_only_when_admin_raises_total(self):
        problems = self._problems(
            lambda raw: raw["tiles"].append({"q": 2, "r": 0, "type": "structure"})
        )
        self.assertTrue(any("Structure" in problem for problem in problems))

    def test_over_core_points_budget_flagged(self):
        def mutate(raw):
            for tile in raw["tiles"]:
                if tile["type"] == "engine":
                    tile["type"] = "double_engine"
        problems = self._problems(mutate)  # 18 points > 15
        self.assertTrue(any("Core Component points" in problem for problem in problems))

    def test_points_upgrade_absorbs_two_extra(self):
        raw = vanguard_design()
        for tile in raw["tiles"]:
            if tile["type"] == "cannon":
                tile["type"] = "double_cannon"
                break  # 16 points
        raw["upgrade"] = "points"
        problems = ship_designs.validate_design(ship_designs.normalize_design(raw))
        self.assertEqual(problems, [])

    def test_disconnected_hull_flagged(self):
        problems = self._problems(
            lambda raw: raw["tiles"].__setitem__(10, {"q": 4, "r": -1, "type": "cannon"})
        )
        self.assertTrue(any("contiguous" in problem for problem in problems))

    def test_primary_lane_limit_enforced(self):
        # the vanguard has 8 tiles on the core's axes; a lower admin limit trips it
        design = ship_designs.normalize_design(vanguard_design())
        problems = ship_designs.validate_design(design, {"primary_lane_limit": 7})
        self.assertTrue(any("primary damage lanes" in problem for problem in problems))
        self.assertEqual(ship_designs.validate_design(design, {"primary_lane_limit": 8}), [])

    def test_missing_lanes_flagged(self):
        problems = self._problems(lambda raw: raw["lanes"].pop("6"))
        self.assertTrue(any("secondary damage lanes" in problem and "6" in problem for problem in problems))

    def test_lane_through_core_flagged(self):
        problems = self._problems(
            lambda raw: raw["lanes"].__setitem__("6", {"q": 0, "r": 0, "dir": 0})
        )
        self.assertTrue(any("passes through the Core" in problem for problem in problems))

    def test_duplicate_lane_flagged(self):
        problems = self._problems(
            lambda raw: raw["lanes"].__setitem__("6", dict(raw["lanes"]["5"]))
        )
        self.assertTrue(any("same line" in problem for problem in problems))

    def test_lane_that_severs_too_little_flagged(self):
        problems = self._problems(
            lambda raw: raw["lanes"].__setitem__("6", {"q": 1, "r": 0, "dir": 5})
        )
        self.assertTrue(any("severs at least" in problem for problem in problems))

    def test_min_severed_config_lowers_the_bar(self):
        raw = vanguard_design()
        raw["lanes"]["6"] = {"q": 1, "r": 0, "dir": 5}  # severs only 1
        design = ship_designs.normalize_design(raw)
        design["config"] = {"secondary_lane_min_severed": 1}
        self.assertEqual(ship_designs.validate_design(design), [])

    def test_missing_upgrade_flagged(self):
        problems = self._problems(lambda raw: raw.__setitem__("upgrade", None))
        self.assertTrue(any("special upgrade" in problem for problem in problems))

    def test_higher_max_tiles_requires_structure_fill(self):
        design = ship_designs.normalize_design(vanguard_design())
        design["config"] = {"max_tiles": 17}
        problems = ship_designs.validate_design(design)
        self.assertTrue(any("exactly 17 tiles" in problem for problem in problems))
        self.assertTrue(any("2 Structure tiles" in problem for problem in problems))
        design["tiles"].append({"q": 2, "r": 0, "type": "structure"})
        design["tiles"].append({"q": 2, "r": -2, "type": "structure"})
        self.assertEqual(ship_designs.validate_design(design, design["config"]), [])

    def test_legacy_tiles_flagged_but_normalizable(self):
        raw = vanguard_design()
        raw["tiles"][5]["type"] = "signal_jammer"
        design = ship_designs.normalize_design(raw)
        problems = ship_designs.validate_design(design)
        self.assertTrue(any("retired tile types" in problem for problem in problems))

    def test_normalize_rejects_bad_input(self):
        raw = vanguard_design()
        raw["tiles"][0] = {"q": 0, "r": 0, "type": "laser"}
        with self.assertRaises(ship_designs.ShipDesignError):
            ship_designs.normalize_design(raw)
        raw = vanguard_design()
        raw["tiles"][0] = {"q": 6, "r": 0, "type": "core"}
        with self.assertRaises(ship_designs.ShipDesignError):
            ship_designs.normalize_design(raw)
        raw = vanguard_design()
        raw["lanes"]["4"] = {"q": 0, "r": 1, "dir": 0}  # 4 is a primary roll
        with self.assertRaises(ship_designs.ShipDesignError):
            ship_designs.normalize_design(raw)
        raw = vanguard_design()
        raw["upgrade"] = "megalaser"
        with self.assertRaises(ship_designs.ShipDesignError):
            ship_designs.normalize_design(raw)

    def test_normalize_canonicalizes_lane_anchor(self):
        design = ship_designs.normalize_design(vanguard_design())
        self.assertEqual(design["lanes"]["5"], {"q": -4, "r": -1, "dir": 0})
        self.assertEqual(design["lanes"]["11"], {"q": 5, "r": -1, "dir": 3})


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
        design, problems = ship_designs.save_design(vanguard_design(), owner_id=7)
        self.assertEqual(problems, [])
        listed = ship_designs.list_designs(7)
        self.assertEqual([entry["id"] for entry in listed], ["vanguard"])
        self.assertTrue(listed[0]["valid"])
        self.assertEqual(listed[0]["points"], 15)
        self.assertEqual(listed[0]["upgrade"], "shield")
        loaded = ship_designs.load_design("vanguard", 7)
        self.assertEqual(loaded, design)
        self.assertEqual(ship_designs.list_designs(), [])  # global library untouched
        self.assertTrue(ship_designs.delete_design("vanguard", 7))
        self.assertEqual(ship_designs.list_designs(7), [])

    def test_player_design_limit(self):
        for index in range(ship_designs.PLAYER_DESIGN_LIMIT):
            raw = vanguard_design()
            raw["id"] = f"ship_{index}"
            ship_designs.save_design(raw, owner_id=3)
        raw = vanguard_design()
        raw["id"] = "one_too_many"
        with self.assertRaises(ship_designs.ShipDesignError):
            ship_designs.save_design(raw, owner_id=3)
        # overwriting an existing design is still allowed
        raw["id"] = "ship_0"
        ship_designs.save_design(raw, owner_id=3)

    def test_clone_to_global(self):
        ship_designs.save_design(vanguard_design(), owner_id=7)
        design, problems = ship_designs.clone_design_to_global(7, "vanguard")
        self.assertEqual(problems, [])
        self.assertEqual([entry["id"] for entry in ship_designs.list_designs()], ["vanguard"])
        design2, _ = ship_designs.clone_design_to_global(7, "vanguard")
        self.assertEqual(design2["id"], "vanguard_2")

    def test_incomplete_design_saves_with_problems(self):
        raw = vanguard_design()
        raw["tiles"] = raw["tiles"][:5]
        design, problems = ship_designs.save_design(raw, owner_id=7)
        self.assertTrue(problems)
        self.assertFalse(ship_designs.list_designs(7)[0]["valid"])

    def test_config_never_persists_with_the_design(self):
        raw = vanguard_design()
        raw["config"] = {"primary_lane_limit": 99}
        design, _ = ship_designs.save_design(raw, owner_id=7)
        self.assertNotIn("config", design)
        self.assertNotIn("config", ship_designs.load_design("vanguard", 7))


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

    def test_designed_ship_setup(self):
        state = self._state_with_designs(red_design=vanguard_design())
        red = state.players["red"]
        blue = state.players["blue"]
        self.assertEqual(red.ship.shields, 3)  # shield upgrade
        self.assertEqual(len(red.hand) + len(red.deck), 10)  # designed 10-card deck
        self.assertEqual(len(red.hand), 5)
        self.assertIsNotNone(red.ship.layout)
        self.assertIsNone(blue.ship.layout)
        self.assertEqual(blue.ship.shields, 2)

    def test_draw_upgrade_grants_sixth_card(self):
        state = self._state_with_designs(red_design=_with_upgrade("draw"))
        self.assertEqual(len(state.players["red"].hand), 6)
        self.assertEqual(state.players["red"].ship.shields, 2)

    def test_designed_deck_composition(self):
        state = self._state_with_designs(red_design=vanguard_design())
        red = state.players["red"]
        cards = red.hand + red.deck
        moves = [card for card in cards if card.family.value == "move"]
        attacks = [card for card in cards if card.family.value == "attack"]
        self.assertEqual(len(moves), 7)  # 3 Move 1 + 4 Move 2
        self.assertEqual(len(attacks), 3)  # 2 Aim +1 + 1 Aim +2
        self.assertEqual(sorted(card.value for card in moves), [1, 1, 1, 2, 2, 2, 2])
        self.assertEqual(sorted(card.value for card in attacks), [1, 1, 2])

    def test_damage_lanes_follow_custom_layout(self):
        state = self._state_with_designs(red_design=vanguard_design())
        red = state.players["red"]
        layout = layout_for_ship(red.ship)
        lane_1 = layout.damage_lanes[1]
        # lane 1 (aft -> fore, core column): engine, docking bay, core, ...
        self.assertEqual(layout.component_by_id[lane_1[0]].component_type, "engine")
        result = _apply_unshielded_damage(state, red, 1, fixed_lane_roll=1)
        self.assertEqual(result["damage_applied"], 1)
        self.assertIn(lane_1[0], red.ship.destroyed_components)

    def test_aim_and_defense_upgrades_shape_the_volley(self):
        state = self._state_with_designs(
            red_design=_with_upgrade("aim"), blue_design=_with_upgrade("defense")
        )
        state.players["red"].ship.q = 0
        state.players["red"].ship.r = 0
        state.players["blue"].ship.q = 2
        state.players["blue"].ship.r = 0
        aim_card = next(card for card in state.players["red"].hand + state.players["red"].deck if card.family.value == "attack")
        state.players["red"].hand = [aim_card]
        red_orders = OrdersSubmission(
            stacks=(
                ActionStack(1, SealMode.SEALED, (OrderCardSelection(aim_card.id, target_player_id="blue"),)),
                ActionStack(2, SealMode.SEALED),
                ActionStack(3, SealMode.SEALED),
            )
        )
        state = submit_orders(state, "red", red_orders)
        state = submit_orders(state, "blue", _idle_orders())
        state = resolve_next_step(state)
        volley = [event for event in state.event_log if event["type"] == "volley_resolved"][-1]
        self.assertEqual(volley["ship_aim_bonus"], 1)
        self.assertEqual(volley["ship_defense_bonus"], 1)
        self.assertEqual(volley["aim_bonus"], aim_card.aim_bonus + 1)
        self.assertEqual(volley["defense_threshold"], 2 + 0 + 0 + 0 + 1)

    def test_serialization_round_trips_custom_layout(self):
        state = self._state_with_designs(red_design=vanguard_design())
        data = state_to_dict(state)
        red_ship = data["players"]["red"]["ship"]
        self.assertEqual(red_ship["max_shields"], 3)
        self.assertEqual(red_ship["layout_id"], "design_vanguard")
        self.assertEqual(len(red_ship["component_layout"]), 15)
        self.assertEqual(len(red_ship["damage_lanes"]), 12)
        restored = state_from_dict(data)
        layout = layout_for_ship(restored.players["red"].ship)
        self.assertEqual(layout.max_shields, 3)
        self.assertEqual(
            layout.damage_lanes, layout_for_ship(state.players["red"].ship).damage_lanes
        )
        # decks survive the round trip, including any cloned card copies
        self.assertEqual(
            [card.id for card in restored.players["red"].deck],
            [card.id for card in state.players["red"].deck],
        )

    def test_compile_spec_matches_layout_contract(self):
        design = ship_designs.normalize_design(_with_upgrade("aim"))
        spec = compile_layout_spec(design)
        layout = layout_from_spec(spec)
        self.assertEqual(len(layout.components), 15)
        self.assertEqual(layout.max_shields, 2)
        self.assertEqual(layout.base_draw, 5)
        self.assertEqual(layout.aim_bonus, 1)
        self.assertEqual(layout.defense_bonus, 0)
        self.assertEqual(layout.intact_count_of_type("life_support", set()), 2)
        self.assertIsNotNone(layout.bridge_id)
        self.assertEqual(spec["deck"], {"move_1": 3, "move_2": 4, "aim_1": 2, "aim_2": 1})

    def test_configured_upgrade_bonus_bakes_into_spec(self):
        design = ship_designs.normalize_design(_with_upgrade("defense"))
        design["config"] = {"upgrade_defense_bonus": 3}
        spec = compile_layout_spec(design)
        self.assertEqual(spec["defense_bonus"], 3)


if __name__ == "__main__":
    unittest.main()
