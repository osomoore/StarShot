"""Boss ship designer: normalization, validation warnings, and file storage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from starshot.v2 import boss_designs


def make_design(**overrides) -> dict:
    """A small valid boss: a 7-hex flower with one shielded edge region.

    Layout (axial): center core at (0,0) surrounded by its six neighbors.
    Region 1 protects three edge hexes on the +q side, powered by the
    shield gen at (1,0).
    """
    design = {
        "id": "test_boss",
        "name": "Test Boss",
        "tiles": [
            {"q": 0, "r": 0, "type": "core", "number": 1},
            {"q": 1, "r": 0, "type": "shield_gen", "number": 1},
            {"q": 1, "r": -1, "type": "firing_computer", "stack": "0.5"},
            {"q": 0, "r": -1, "type": "generic"},
            {"q": -1, "r": 0, "type": "generic"},
            {"q": -1, "r": 1, "type": "fuel_tank", "stack": "1.5"},
            {"q": 0, "r": 1, "type": "generic"},
        ],
        "shield_regions": [
            {
                "number": 1,
                "hexes": [[1, -1], [1, 0], [0, 1]],
                "generator": [1, 0],
                "lanes": [
                    {"roll": 2, "q": 1, "r": -1, "facing": 0},
                    {"roll": 3, "q": 1, "r": 0, "facing": 0},
                    {"roll": 4, "q": 0, "r": 1, "facing": 5},
                    {"roll": 5, "q": 1, "r": -1, "facing": 1},
                    {"roll": 6, "q": 1, "r": 0, "facing": 1},
                    {"roll": 7, "q": 0, "r": 1, "facing": 0},
                    {"roll": 8, "q": 1, "r": -1, "facing": 2},
                ],
            }
        ],
        "progression": {
            "triggers": ["bauble_pickup_boss", "player_kill"],
            "steps": [
                {"kind": "filler"},
                {"kind": "action_link", "stack": "0.5", "action": "shoot"},
                {"kind": "breacher_link", "core": 1, "round": 3},
                {"kind": "ability_trigger", "name": "Ion Wave", "notes": ""},
            ],
        },
    }
    design.update(overrides)
    return design


class NormalizeTests(unittest.TestCase):
    def test_valid_design_round_trips(self):
        design = boss_designs.normalize_design(make_design())
        self.assertEqual(design["id"], "test_boss")
        self.assertEqual(len(design["tiles"]), 7)
        self.assertEqual(design["shield_regions"][0]["generator"], [1, 0])
        self.assertEqual(len(design["shield_regions"][0]["lanes"]), 7)
        self.assertEqual(design["progression"]["steps"][2], {"kind": "breacher_link", "core": 1, "round": 3})

    def test_rejects_duplicate_tile_hex(self):
        raw = make_design()
        raw["tiles"].append({"q": 0, "r": 0, "type": "generic"})
        with self.assertRaises(boss_designs.BossDesignError):
            boss_designs.normalize_design(raw)

    def test_rejects_bad_stack_and_lane_roll(self):
        raw = make_design()
        raw["tiles"][2]["stack"] = "9.5"
        with self.assertRaises(boss_designs.BossDesignError):
            boss_designs.normalize_design(raw)
        raw = make_design()
        raw["shield_regions"][0]["lanes"][0]["roll"] = 1  # 1 is a miss, not a lane
        with self.assertRaises(boss_designs.BossDesignError):
            boss_designs.normalize_design(raw)

    def test_rejects_breacher_link_without_core_or_round(self):
        raw = make_design()
        raw["progression"]["steps"] = [{"kind": "breacher_link"}]
        with self.assertRaises(boss_designs.BossDesignError):
            boss_designs.normalize_design(raw)

    def test_rejects_duplicate_region_numbers(self):
        raw = make_design()
        raw["shield_regions"].append({"number": 1, "hexes": [], "generator": None, "lanes": []})
        with self.assertRaises(boss_designs.BossDesignError):
            boss_designs.normalize_design(raw)

    def test_rejects_out_of_grid_hex(self):
        raw = make_design()
        raw["tiles"][0]["q"] = 20
        with self.assertRaises(boss_designs.BossDesignError):
            boss_designs.normalize_design(raw)


class ValidateTests(unittest.TestCase):
    def _problems(self, raw) -> list[str]:
        return boss_designs.validate_design(boss_designs.normalize_design(raw))

    def test_complete_design_has_no_problems(self):
        self.assertEqual(self._problems(make_design()), [])

    def test_disconnected_hull_flagged(self):
        raw = make_design()
        raw["tiles"].append({"q": 4, "r": 0, "type": "generic"})
        problems = self._problems(raw)
        self.assertTrue(any("not fully connected" in p for p in problems))

    def test_fewer_lanes_allowed_but_zero_lanes_flagged(self):
        # Unassigned rolls reroll in play, so a partial lane set is fine...
        raw = make_design()
        raw["shield_regions"][0]["lanes"] = raw["shield_regions"][0]["lanes"][:3]
        self.assertEqual(self._problems(raw), [])
        # ...but a region with no lanes at all could never be damaged.
        raw["shield_regions"][0]["lanes"] = []
        problems = self._problems(raw)
        self.assertTrue(any("has no damage lanes" in p for p in problems))

    def test_two_lanes_may_share_a_hex(self):
        raw = make_design()
        raw["shield_regions"][0]["lanes"] = [
            {"roll": 2, "q": 1, "r": -1, "facing": 0},
            {"roll": 3, "q": 1, "r": -1, "facing": 1},
        ]
        self.assertEqual(self._problems(raw), [])

    def test_duplicate_lane_roll_flagged(self):
        raw = make_design()
        raw["shield_regions"][0]["lanes"][1]["roll"] = 2
        problems = self._problems(raw)
        self.assertTrue(any("assigns lane 2 more than once" in p for p in problems))

    def test_non_continuous_region_flagged(self):
        raw = make_design()
        # (1,-1) and (-1,1) are on opposite sides of the flower.
        raw["shield_regions"][0]["hexes"] = [[1, -1], [-1, 1]]
        raw["shield_regions"][0]["lanes"] = []
        problems = self._problems(raw)
        self.assertTrue(any("not continuous" in p for p in problems))

    def test_interior_region_hex_flagged(self):
        raw = make_design()
        raw["shield_regions"][0]["hexes"].append([0, 0])  # core: fully surrounded
        problems = self._problems(raw)
        self.assertTrue(any("not on the ship edge" in p for p in problems))

    def test_lane_facing_must_be_edge_face(self):
        raw = make_design()
        raw["shield_regions"][0]["lanes"][0]["facing"] = 3  # points at the core
        problems = self._problems(raw)
        self.assertTrue(any("does not enter from the ship edge" in p for p in problems))

    def test_wrong_generator_number_flagged(self):
        raw = make_design()
        raw["tiles"][1]["number"] = 2
        problems = self._problems(raw)
        self.assertTrue(any("numbered 2 (expected 1)" in p for p in problems))

    def test_steps_without_triggers_flagged(self):
        raw = make_design()
        raw["progression"]["triggers"] = []
        problems = self._problems(raw)
        self.assertTrue(any("no way to progress" in p for p in problems))

    def test_breacher_link_to_missing_core_flagged(self):
        raw = make_design()
        raw["progression"]["steps"] = [{"kind": "breacher_link", "core": 5}]
        problems = self._problems(raw)
        self.assertTrue(any("links to core 5" in p for p in problems))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self._original_dir = boss_designs.DESIGNS_DIR
        boss_designs.DESIGNS_DIR = Path(self._tempdir.name)

    def tearDown(self):
        boss_designs.DESIGNS_DIR = self._original_dir
        self._tempdir.cleanup()

    def test_save_load_list_delete(self):
        saved, problems = boss_designs.save_design(make_design())
        self.assertEqual(problems, [])
        loaded = boss_designs.load_design("test_boss")
        self.assertEqual(loaded, saved)
        entries = boss_designs.list_designs()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], "test_boss")
        self.assertEqual(entries[0]["tile_count"], 7)
        self.assertTrue(boss_designs.delete_design("test_boss"))
        self.assertIsNone(boss_designs.load_design("test_boss"))
        self.assertFalse(boss_designs.delete_design("test_boss"))

    def test_save_keeps_design_with_warnings(self):
        raw = make_design()
        raw["shield_regions"][0]["lanes"] = []
        _, problems = boss_designs.save_design(raw)
        self.assertTrue(problems)
        self.assertIsNotNone(boss_designs.load_design("test_boss"))

    def test_design_id_is_slugged(self):
        raw = make_design(id="Test Boss II!")
        saved, _ = boss_designs.save_design(raw)
        self.assertEqual(saved["id"], "test_boss_ii")
        self.assertIsNotNone(boss_designs.load_design("test_boss_ii"))


class SpawnStepTests(unittest.TestCase):
    def test_spawn_fleet_step_normalizes(self):
        raw = make_design()
        raw["progression"]["steps"].append({"kind": "spawn_fleet", "count": 2, "location": "bauble"})
        design = boss_designs.normalize_design(raw)
        self.assertEqual(design["progression"]["steps"][-1], {"kind": "spawn_fleet", "count": 2, "location": "bauble"})
        self.assertEqual(boss_designs.validate_design(design), [])

    def test_spawn_fleet_rejects_bad_count_and_location(self):
        raw = make_design()
        raw["progression"]["steps"] = [{"kind": "spawn_fleet", "count": 0, "location": "fang"}]
        with self.assertRaises(boss_designs.BossDesignError):
            boss_designs.normalize_design(raw)
        raw["progression"]["steps"] = [{"kind": "spawn_fleet", "count": 1, "location": "nowhere"}]
        with self.assertRaises(boss_designs.BossDesignError):
            boss_designs.normalize_design(raw)


class PlayerStorageTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self._original_dir = boss_designs.DESIGNS_DIR
        boss_designs.DESIGNS_DIR = Path(self._tempdir.name)

    def tearDown(self):
        boss_designs.DESIGNS_DIR = self._original_dir
        self._tempdir.cleanup()

    def test_player_designs_are_separate_from_global(self):
        boss_designs.save_design(make_design(), owner_id=7)
        self.assertIsNone(boss_designs.load_design("test_boss"))
        self.assertIsNotNone(boss_designs.load_design("test_boss", owner_id=7))
        self.assertEqual(boss_designs.list_designs(), [])
        self.assertEqual(len(boss_designs.list_designs(7)), 1)
        self.assertEqual(boss_designs.list_player_owner_ids(), [7])

    def test_player_design_limit(self):
        for index in range(boss_designs.PLAYER_DESIGN_LIMIT):
            boss_designs.save_design(make_design(id=f"boss_{index}"), owner_id=7)
        with self.assertRaises(boss_designs.BossDesignError):
            boss_designs.save_design(make_design(id="one_more"), owner_id=7)
        # Updating an existing design is still allowed at the cap.
        updated, _ = boss_designs.save_design(make_design(id="boss_0", name="Renamed"), owner_id=7)
        self.assertEqual(updated["name"], "Renamed")

    def test_clone_player_design_to_global(self):
        boss_designs.save_design(make_design(), owner_id=7)
        cloned, problems = boss_designs.clone_design_to_global(7, "test_boss")
        self.assertEqual(problems, [])
        self.assertIsNotNone(boss_designs.load_design(cloned["id"]))
        again, _ = boss_designs.clone_design_to_global(7, "test_boss")
        self.assertNotEqual(again["id"], cloned["id"])


if __name__ == "__main__":
    unittest.main()
