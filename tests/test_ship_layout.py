import unittest

from starshot.rules.ship_layout import (
    BASE_SHIP_COMPONENTS,
    BASE_SHIP_DAMAGE_LANES,
    first_intact_component_for_lane,
    is_ship_destroyed,
)


class ShipLayoutTests(unittest.TestCase):
    def test_component_count(self):
        # We expect exactly 15 components
        self.assertEqual(len(BASE_SHIP_COMPONENTS), 15)

    def test_lane_5_enters_port_shields_then_bone_room_then_starboard_inner_engines(self):
        first_hit = first_intact_component_for_lane(5, set())
        second_hit = first_intact_component_for_lane(5, {"port_shields"})
        third_hit = first_intact_component_for_lane(5, {"port_shields", "bone_room"})
        fourth_hit = first_intact_component_for_lane(5, {"port_shields", "bone_room", "starboard_inner_engines"})

        self.assertEqual(first_hit.id, "port_shields")
        self.assertEqual(second_hit.id, "bone_room")
        self.assertEqual(third_hit.id, "starboard_inner_engines")
        self.assertIsNone(fourth_hit)

    def test_lane_9_mirrors_lane_5_through_starboard_shields(self):
        first_hit = first_intact_component_for_lane(9, set())
        second_hit = first_intact_component_for_lane(9, {"starboard_shields"})

        self.assertEqual(first_hit.id, "starboard_shields")
        self.assertEqual(second_hit.id, "bone_room")

    def test_lanes_mirroring(self):
        def mirror_id(comp_id: str) -> str:
            if comp_id.startswith("port_"):
                return comp_id.replace("port_", "starboard_")
            elif comp_id.startswith("starboard_"):
                return comp_id.replace("starboard_", "port_")
            return comp_id

        # Check mirroring of side lanes (2-6 mirrored by 12-8)
        for i in range(2, 7):
            mirror_lane_idx = 14 - i
            lane_components = BASE_SHIP_DAMAGE_LANES[i]
            mirrored_lane_components = BASE_SHIP_DAMAGE_LANES[mirror_lane_idx]

            self.assertEqual(len(lane_components), len(mirrored_lane_components))
            expected_mirrored = tuple(mirror_id(cid) for cid in lane_components)
            self.assertEqual(mirrored_lane_components, expected_mirrored)

        # Check self-mirroring of center lanes (1 and 7)
        for idx in (1, 7):
            lane_components = BASE_SHIP_DAMAGE_LANES[idx]
            expected_mirrored = tuple(mirror_id(cid) for cid in lane_components)
            self.assertEqual(lane_components, expected_mirrored)

    def test_ship_destruction_logic(self):
        # Bridge destroyed -> ship destroyed
        self.assertTrue(is_ship_destroyed({"command_bridge"}))

        # Both life supports destroyed -> ship destroyed
        self.assertTrue(is_ship_destroyed({"port_life_support", "starboard_life_support"}))
        self.assertFalse(is_ship_destroyed({"port_life_support"}))

        # All weapons and engines destroyed -> ship destroyed
        all_weapons = {"forward_ion_cannon", "port_ion_cannon", "starboard_ion_cannon"}
        all_engines = {"port_inner_engines", "starboard_inner_engines", "port_outer_engines", "starboard_outer_engines", "aft_engines"}
        
        self.assertFalse(is_ship_destroyed(all_weapons))
        self.assertFalse(is_ship_destroyed(all_engines))
        self.assertTrue(is_ship_destroyed(all_weapons.union(all_engines)))


if __name__ == "__main__":
    unittest.main()
