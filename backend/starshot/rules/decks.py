from __future__ import annotations

from starshot.rules.deck_data import active_catalog
from starshot.rules.models import Card


def create_base_deck() -> list[Card]:
    return list(active_catalog().base_cards)


def base_card_by_id(card_id: str) -> Card:
    return active_catalog().base_card_map[card_id]


def card_by_id(card_id: str) -> Card:
    """Look up a card by id from either the base deck or the desperation deck."""
    return active_catalog().card_map[card_id]
