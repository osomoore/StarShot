from __future__ import annotations

from random import Random

from starshot.rules.card_effects import (
    card_aim_bonus,
    card_always_hits,
    card_attacks_all,
    card_damage_bonus,
    card_defense_bonus,
    card_fixed_defense_threshold,
    card_max_range,
    card_movement_disabled,
    card_orientation_options,
    card_requires_target,
    card_value,
    card_warp_destination,
    desperate_face_for,
    is_desperate_face,
    selected_card_family,
)
from starshot.rules.deck_data import active_catalog
from starshot.rules.models import Card, DesperationDeck


def all_desperation_cards() -> list[Card]:
    """Return a fresh copy of the full desperation card list."""
    return list(active_catalog().desperation_cards)


def desperation_card_by_id(card_id: str) -> Card:
    return active_catalog().desperation_card_map[card_id]


def is_desperation_card_id(card_id: str) -> bool:
    return card_id in active_catalog().desperation_card_map


def create_desperation_deck(rng: Random) -> DesperationDeck:
    """Create and shuffle the shared desperation deck."""
    cards = all_desperation_cards()
    rng.shuffle(cards)
    return DesperationDeck(cards=cards, shuffle_marker_on_top=False)


def draw_desperation_card(deck: DesperationDeck, rng: Random) -> Card:
    """Draw one card from the bottom (index 0) of the desperation deck."""
    if not deck.cards:
        cards = all_desperation_cards()
        rng.shuffle(cards)
        deck.cards = cards
        deck.shuffle_marker_on_top = False

    card = deck.cards.pop(0)

    if not deck.cards:
        deck.shuffle_marker_on_top = True

    return card


def return_desperation_card(deck: DesperationDeck, card: Card) -> None:
    deck.cards.append(card)
    deck.shuffle_marker_on_top = False
