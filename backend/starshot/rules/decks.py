from __future__ import annotations

from starshot.rules.models import Card, CardFamily


def create_base_deck() -> list[Card]:
    return [
        Card(id="move_1_a", name="Controlled Move 1", family=CardFamily.MOVE, value=1),
        Card(id="move_1_b", name="Controlled Move 1", family=CardFamily.MOVE, value=1),
        Card(id="move_2_a", name="Controlled Move 2", family=CardFamily.MOVE, value=2),
        Card(id="move_2_b", name="Controlled Move 2", family=CardFamily.MOVE, value=2),
        Card(id="move_2_c", name="Controlled Move 2", family=CardFamily.MOVE, value=2),
        Card(id="attack_1_a", name="Targeted Attack 1", family=CardFamily.ATTACK, value=1),
        Card(id="attack_1_b", name="Targeted Attack 1", family=CardFamily.ATTACK, value=1),
        Card(id="attack_2_a", name="Targeted Attack 2", family=CardFamily.ATTACK, value=2),
    ]
