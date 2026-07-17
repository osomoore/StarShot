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


ENGINEER_BONUS_HAND_SIZE = 2


def hand_size_for_player(player: PlayerState) -> int:
    # Designed ships bring their own base draw (3-6); the base ship draws 5.
    # Exhausted shields grant +1 either way (base: 5 -> 6).
    base = DEFAULT_HAND_SIZE
    if player.ship.layout:
        base = int(player.ship.layout.get("base_draw", DEFAULT_HAND_SIZE))
    size = base + (SHIELDS_EXHAUSTED_HAND_SIZE - DEFAULT_HAND_SIZE) if player.ship.shields <= 0 else base
    if "engineer" in player.roles:
        size += ENGINEER_BONUS_HAND_SIZE
    return size


def draw_hand(
    player: PlayerState,
    *,
    shuffle_cards: Callable[[list[Card]], None] | None = None,
) -> DrawHandResult:
    drawn: list[Card] = []
    reshuffled_discard: list[Card] = []
    moved_overheat_to_discard: list[Card] = []
    target = max(0, hand_size_for_player(player) + player.bonus_draws_pending - player.overdrive_seals_pending)
    player.overdrive_seals_pending = 0
    player.bonus_draws_pending = 0
    while len(drawn) < target and player.deck:
        drawn.append(player.deck.pop(0))
    while len(drawn) < target:
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
