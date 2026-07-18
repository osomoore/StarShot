from __future__ import annotations

from dataclasses import replace

from starshot.rules.deck_data import active_catalog
from starshot.rules.models import Card, CardFamily


# Extra copies of a base card in a designed-ship deck get ids like
# "move_2_b__s3" so every card in a player's deck has a unique id while
# card_by_id can still resolve them against the active catalog.
_COPY_SEPARATOR = "__s"

# Used when the active deck set has no card matching a StarDock deck slot
# (custom deck sets). Shapes mirror the core 0.2 base deck.
_FALLBACK_CARDS = {
    "move_1": Card(id="stardock_move_1", name="Move 1", family=CardFamily.MOVE, value=1, requires_target=False),
    "move_2": Card(id="stardock_move_2", name="Move 2", family=CardFamily.MOVE, value=2, requires_target=False),
    "aim_1": Card(
        id="stardock_aim_1", name="Targeted Attack Aim +1", family=CardFamily.ATTACK,
        value=1, aim_bonus=1, requires_target=True, orientation_options=("forward",),
    ),
    "aim_2": Card(
        id="stardock_aim_2", name="Targeted Attack Aim +2", family=CardFamily.ATTACK,
        value=2, aim_bonus=2, requires_target=True, orientation_options=("forward",),
    ),
}


def create_base_deck() -> list[Card]:
    return list(active_catalog().base_cards)


def _lookup(card_id: str, card_map: dict[str, Card]) -> Card:
    card = card_map.get(card_id)
    if card is not None:
        return card
    # designed-deck copy: "<proto_id>__s<n>"
    prototype_id, separator, suffix = card_id.rpartition(_COPY_SEPARATOR)
    if separator and suffix.isdigit():
        prototype = card_map.get(prototype_id) or next(
            (card for card in _FALLBACK_CARDS.values() if card.id == prototype_id), None
        )
        if prototype is not None:
            return replace(prototype, id=card_id)
    raise KeyError(card_id)


def base_card_by_id(card_id: str) -> Card:
    return _lookup(card_id, active_catalog().base_card_map)


def card_by_id(card_id: str) -> Card:
    """Look up a card by id from either the base deck or the desperation deck."""
    return _lookup(card_id, active_catalog().card_map)


def _base_card_kind(card: Card) -> str | None:
    """Which StarDock deck slot a base card fills, if any."""
    if card.is_hybrid or card.desperate_face is not None or card.no_basic_face:
        return None
    if card.family == CardFamily.MOVE and card.value in (1, 2) and card.aim_bonus == 0:
        return f"move_{card.value}"
    if card.family == CardFamily.ATTACK and card.requires_target and card.aim_bonus in (1, 2):
        return f"aim_{card.aim_bonus}"
    return None


def create_designed_deck(counts: dict) -> list[Card]:
    """The starting deck for a StarDock-designed ship: `counts` maps
    "move_1"/"move_2"/"aim_1"/"aim_2" to how many copies the placed Engine /
    Double Engine / Cannon / Double Cannon components grant. Catalog copies
    are used first; extra copies clone the first prototype with a __s suffix."""
    pools: dict[str, list[Card]] = {"move_1": [], "move_2": [], "aim_1": [], "aim_2": []}
    for card in active_catalog().base_cards:
        kind = _base_card_kind(card)
        if kind in pools:
            pools[kind].append(card)

    deck: list[Card] = []
    for kind, pool in pools.items():
        needed = max(0, int(counts.get(kind, 0)))
        prototype = pool[0] if pool else _FALLBACK_CARDS[kind]
        for index in range(needed):
            if index < len(pool):
                deck.append(pool[index])
            else:
                deck.append(replace(prototype, id=f"{prototype.id}{_COPY_SEPARATOR}{index + 1}"))
    return deck
