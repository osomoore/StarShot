from __future__ import annotations

import random
import unittest

from starshot.v2 import names


class DisplayNameValidationTests(unittest.TestCase):
    def test_valid_names(self) -> None:
        for name in ("Salty Bones", "Captain Obvious", "Peg-Leg Pete", "O'Malley", "Dr. Plunder", "abc"):
            self.assertTrue(names.valid_display_name(name), name)

    def test_invalid_names(self) -> None:
        for name in ("", "ab", " padded", "padded ", "way too long a pirate name here", "bad<tag>", "☠☠☠"):
            self.assertFalse(names.valid_display_name(name), name)


class ObjectionableNameTests(unittest.TestCase):
    def test_clean_names_pass(self) -> None:
        for name in ("Scunthorpe", "Class Act", "Salty Bones", "Grass Assassin", "Cocktail Hour", "Matt Titmuss"):
            self.assertFalse(names.name_is_objectionable(name), name)

    def test_profane_names_flagged(self) -> None:
        for name in ("ShitLord", "F U C K e r", "Sh1t Happens", "a$$hole ass", "Capt Bitch", "PornKing"):
            self.assertTrue(names.name_is_objectionable(name), name)

    def test_leetspeak_is_normalized(self) -> None:
        self.assertTrue(names.name_is_objectionable("5h1t 5t0rm"))
        self.assertTrue(names.name_is_objectionable("b!tch queen"))


class RandomNameTests(unittest.TestCase):
    def test_generated_names_are_always_legal(self) -> None:
        rng = random.Random(42)
        for _ in range(200):
            name = names.random_pirate_name(rng)
            self.assertTrue(names.valid_display_name(name), name)
            self.assertFalse(names.name_is_objectionable(name), name)


if __name__ == "__main__":
    unittest.main()
