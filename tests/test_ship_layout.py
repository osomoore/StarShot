import unittest

from starshot.rules.ship_layout import first_intact_component_for_lane


class ShipLayoutTests(unittest.TestCase):
    def test_lane_5_enters_port_shields_then_bone_room(self):
        first_hit = first_intact_component_for_lane(5, set())
        second_hit = first_intact_component_for_lane(5, {"port_shields"})

        self.assertEqual(first_hit.id, "port_shields")
        self.assertEqual(second_hit.id, "bone_room")

    def test_lane_9_mirrors_lane_5_through_starboard_shields(self):
        first_hit = first_intact_component_for_lane(9, set())
        second_hit = first_intact_component_for_lane(9, {"starboard_shields"})

        self.assertEqual(first_hit.id, "starboard_shields")
        self.assertEqual(second_hit.id, "bone_room")


if __name__ == "__main__":
    unittest.main()
