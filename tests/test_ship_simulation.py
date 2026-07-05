import unittest

from starshot.rules.ship_simulation import simulate_ship_kills


class ShipSimulationTests(unittest.TestCase):
    def test_simulation_uses_ship_destruction_rules(self):
        result = simulate_ship_kills(runs=25, seed=3, damage_per_volley=1)

        self.assertEqual(result["config"]["runs"], 25)
        self.assertGreater(result["summary"]["average_steps_to_kill"], 0)
        self.assertEqual(sum(result["summary"]["elimination_reasons"].values()), 25)
        self.assertEqual(len(result["components"]), 15)
        self.assertTrue(
            any(component["id"] == "command_bridge" and component["average_first_hit_step"] is not None for component in result["components"])
        )

    def test_starting_shields_delay_damage_steps(self):
        unshielded = simulate_ship_kills(runs=10, seed=9, initial_shields=0, defense_threshold=0)
        shielded = simulate_ship_kills(runs=10, seed=9, initial_shields=2, defense_threshold=0)

        self.assertGreater(
            shielded["summary"]["average_steps_to_kill"],
            unshielded["summary"]["average_steps_to_kill"],
        )

    def test_defense_creates_misses_before_damage(self):
        result = simulate_ship_kills(runs=5, seed=4, defense_threshold=24, aim_bonus=0, max_steps=25)

        self.assertGreater(result["summary"]["total_misses"], 0)
        self.assertLess(result["summary"]["hit_rate"], 1)
        self.assertEqual(
            result["summary"]["total_shots"],
            result["summary"]["total_hits"] + result["summary"]["total_misses"],
        )

    def test_zero_defense_hits_every_shot(self):
        result = simulate_ship_kills(runs=5, seed=4, defense_threshold=0)

        self.assertEqual(result["summary"]["total_misses"], 0)
        self.assertEqual(result["summary"]["hit_rate"], 1)

    def test_configurable_attack_dice_are_reported(self):
        result = simulate_ship_kills(
            runs=5,
            seed=4,
            defense_threshold=14,
            aim_bonus=4,
            attack_dice_count=3,
            attack_die_sides=6,
        )

        self.assertEqual(result["config"]["attack_dice_count"], 3)
        self.assertEqual(result["config"]["attack_die_sides"], 6)
        self.assertEqual(result["config"]["aim_bonus"], 4)
        self.assertEqual(min(int(roll) for roll in result["summary"]["attack_rolls"]), 3)
        self.assertEqual(max(int(roll) for roll in result["summary"]["attack_rolls"]), 18)

    def test_double_max_roll_can_auto_hit(self):
        without_auto_hit = simulate_ship_kills(
            runs=20,
            seed=8,
            defense_threshold=999,
            attack_dice_count=2,
            attack_die_sides=2,
            double_max_auto_hit=False,
            max_steps=20,
        )
        with_auto_hit = simulate_ship_kills(
            runs=20,
            seed=8,
            defense_threshold=999,
            attack_dice_count=2,
            attack_die_sides=2,
            double_max_auto_hit=True,
            max_steps=20,
        )

        self.assertEqual(without_auto_hit["summary"]["total_hits"], 0)
        self.assertGreater(with_auto_hit["summary"]["total_auto_hits"], 0)
        self.assertEqual(with_auto_hit["summary"]["total_hits"], with_auto_hit["summary"]["total_auto_hits"])

    def test_rejects_invalid_run_count(self):
        with self.assertRaises(ValueError):
            simulate_ship_kills(runs=0)


if __name__ == "__main__":
    unittest.main()
