from __future__ import annotations

from starshot.rules.desperation import (
    all_desperation_cards,
    create_desperation_deck,
    desperation_card_by_id,
    draw_desperation_card,
    is_desperation_card_id,
)
from starshot.rules.models import Card, CardFamily


def create_base_deck() -> list[Card]:
    return [
        Card(id="move_1_a", name="Controlled Move 1", family=CardFamily.MOVE, value=1),
        Card(id="move_1_b", name="Controlled Move 1", family=CardFamily.MOVE, value=1),
        Card(id="move_1_c", name="Controlled Move 1", family=CardFamily.MOVE, value=1),
        Card(id="move_2_a", name="Controlled Move 2", family=CardFamily.MOVE, value=2),
        Card(id="move_2_b", name="Controlled Move 2", family=CardFamily.MOVE, value=2),
        Card(id="move_2_c", name="Controlled Move 2", family=CardFamily.MOVE, value=2),
        Card(id="move_2_d", name="Controlled Move 2", family=CardFamily.MOVE, value=2),
        Card(id="attack_1_a", name="Targeted Attack Aim +1", family=CardFamily.ATTACK, value=1),
        Card(id="attack_1_b", name="Targeted Attack Aim +1", family=CardFamily.ATTACK, value=1),
        Card(id="attack_2_a", name="Targeted Attack Aim +2", family=CardFamily.ATTACK, value=2),
    ]


_BASE_CARD_MAP: dict[str, Card] = {card.id: card for card in create_base_deck()}


def base_card_by_id(card_id: str) -> Card:
    return _BASE_CARD_MAP[card_id]


def card_by_id(card_id: str) -> Card:
    """Look up a card by id from either the base deck or the desperation deck."""
    if card_id in _BASE_CARD_MAP:
        return _BASE_CARD_MAP[card_id]
    if is_desperation_card_id(card_id):
        return desperation_card_by_id(card_id)
    raise KeyError(card_id)
