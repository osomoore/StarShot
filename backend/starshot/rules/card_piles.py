from __future__ import annotations

from starshot.rules.models import Card, PlayerState


DEFAULT_HAND_SIZE = 5
SHIELDS_EXHAUSTED_HAND_SIZE = 6


def hand_size_for_player(player: PlayerState) -> int:
    return SHIELDS_EXHAUSTED_HAND_SIZE if player.ship.shields <= 0 else DEFAULT_HAND_SIZE


def draw_hand(player: PlayerState) -> list[Card]:
    drawn: list[Card] = []
    while len(drawn) < hand_size_for_player(player) and player.deck:
        drawn.append(player.deck.pop(0))
    player.hand.extend(drawn)
    return drawn


def discard_hand(player: PlayerState) -> list[Card]:
    discarded = list(player.hand)
    player.discard.extend(discarded)
    player.hand = []
    return discarded


def remove_ordered_cards_from_hand(player: PlayerState, ordered_card_ids: set[str]) -> list[Card]:
    removed: list[Card] = []
    remaining: list[Card] = []
    for card in player.hand:
        if card.id in ordered_card_ids:
            removed.append(card)
        else:
            remaining.append(card)
    player.hand = remaining
    return removed


def available_order_cards(player: PlayerState) -> dict[str, Card]:
    return {card.id: card for card in player.hand}
