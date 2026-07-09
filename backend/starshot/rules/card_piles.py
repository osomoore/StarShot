from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from starshot.rules.models import Card, PlayerState


DEFAULT_HAND_SIZE = 5
SHIELDS_EXHAUSTED_HAND_SIZE = 6


@dataclass(frozen=True, slots=True)
class DrawHandResult:
    drawn: list[Card]
    reshuffled_discard: list[Card]
    moved_overheat_to_discard: list[Card]


def hand_size_for_player(player: PlayerState) -> int:
    return SHIELDS_EXHAUSTED_HAND_SIZE if player.ship.shields <= 0 else DEFAULT_HAND_SIZE


def draw_hand(
    player: PlayerState,
    *,
    shuffle_cards: Callable[[list[Card]], None] | None = None,
) -> DrawHandResult:
    drawn: list[Card] = []
    reshuffled_discard: list[Card] = []
    moved_overheat_to_discard: list[Card] = []
    while len(drawn) < hand_size_for_player(player) and player.deck:
        drawn.append(player.deck.pop(0))
    while len(drawn) < hand_size_for_player(player):
        if not player.deck:
            if not player.discard and not player.overheat:
                break
            if player.discard:
                reshuffled = list(player.discard)
                if shuffle_cards is not None:
                    shuffle_cards(player.discard)
                player.deck = list(player.discard)
                player.discard = []
                reshuffled_discard.extend(reshuffled)
            if player.overheat:
                moved = list(player.overheat)
                player.discard.extend(moved)
                player.overheat = []
                moved_overheat_to_discard.extend(moved)
            if not player.deck:
                continue
        drawn.append(player.deck.pop(0))
    player.hand.extend(drawn)
    return DrawHandResult(
        drawn=drawn,
        reshuffled_discard=reshuffled_discard,
        moved_overheat_to_discard=moved_overheat_to_discard,
    )


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
