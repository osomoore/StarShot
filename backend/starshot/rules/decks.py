from __future__ import annotations

from random import Random

from starshot.rules.models import Card, CardFamily, DesperationDeck


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


def base_card_by_id(card_id: str) -> Card:
    cards = {card.id: card for card in create_base_deck()}
    return cards[card_id]


# ---------------------------------------------------------------------------
# Desperation deck
# ---------------------------------------------------------------------------

# Basic faces of all desperation cards that are in-scope for the first slice.
# Desperate faces are deferred; 'value' here is the basic-face value.
# Hull Repair, Advanced Repair, and All She's Got are also deferred.
_DESPERATION_CARDS: list[Card] = [
    # Move-type basic faces
    Card(id="desp_thrust_ions_a",    name="Thrust Ions",      family=CardFamily.MOVE,   value=1, is_base=False, orientation_options=("forward",)),
    Card(id="desp_thrust_ions_b",    name="Thrust Ions",      family=CardFamily.MOVE,   value=1, is_base=False, orientation_options=("forward",)),
    Card(id="desp_turbo_ions",       name="Turbo Ions",       family=CardFamily.MOVE,   value=1, is_base=False, orientation_options=("forward",)),
    Card(id="desp_homeward_bound",   name="Homeward Bound",   family=CardFamily.MOVE,   value=1, is_base=False, orientation_options=("forward",)),
    Card(id="desp_treasure_hound",   name="Treasure Hound",   family=CardFamily.MOVE,   value=1, is_base=False, orientation_options=("forward",)),
    Card(id="desp_evasive_action",   name="Evasive Action",   family=CardFamily.MOVE,   value=1, is_base=False, orientation_options=("forward",)),
    # Attack-type basic faces (untargeted bonus; must pair with a targeted attack)
    Card(id="desp_ace_shot_a",       name="Ace Shot",         family=CardFamily.ATTACK, value=1, is_base=False, requires_target=False, is_hybrid=True),
    Card(id="desp_ace_shot_b",       name="Ace Shot",         family=CardFamily.ATTACK, value=1, is_base=False, requires_target=False, is_hybrid=True),
    Card(id="desp_deadeye",          name="Deadeye",          family=CardFamily.ATTACK, value=1, is_base=False, requires_target=False, is_hybrid=True),
    Card(id="desp_nightjammer",      name="Nightjammer",      family=CardFamily.ATTACK, value=1, is_base=False, requires_target=False, is_hybrid=True),
    Card(id="desp_self_destruct",    name="Self Destruct",    family=CardFamily.ATTACK, value=1, is_base=False, requires_target=False, is_hybrid=True),
    Card(id="desp_death_blossom",    name="Death Blossom",    family=CardFamily.ATTACK, value=1, is_base=False, requires_target=False, is_hybrid=True),
    Card(id="desp_steady_shot_a",    name="Steady Shot",      family=CardFamily.ATTACK, value=1, is_base=False, requires_target=False, is_hybrid=True),
    Card(id="desp_steady_shot_b",    name="Steady Shot",      family=CardFamily.ATTACK, value=1, is_base=False, requires_target=False, is_hybrid=True),
    # Desperate Targeted Attack cards – proper targeted attacks, not overdriven
    Card(id="desp_targeted_attack_1_a", name="Desperation Attack 1", family=CardFamily.ATTACK, value=1, is_base=False),
    Card(id="desp_targeted_attack_1_b", name="Desperation Attack 1", family=CardFamily.ATTACK, value=1, is_base=False),
    Card(id="desp_targeted_attack_1_c", name="Desperation Attack 1", family=CardFamily.ATTACK, value=1, is_base=False),
    Card(id="desp_targeted_attack_1_d", name="Desperation Attack 1", family=CardFamily.ATTACK, value=1, is_base=False),
]

_DESPERATION_CARD_MAP: dict[str, Card] = {card.id: card for card in _DESPERATION_CARDS}
_BASE_CARD_MAP: dict[str, Card] = {card.id: card for card in create_base_deck()}


def all_desperation_cards() -> list[Card]:
    """Return a fresh copy of the full desperation card list."""
    return list(_DESPERATION_CARDS)


def desperation_card_by_id(card_id: str) -> Card:
    return _DESPERATION_CARD_MAP[card_id]


def card_by_id(card_id: str) -> Card:
    """Look up a card by id from either the base deck or the desperation deck."""
    if card_id in _BASE_CARD_MAP:
        return _BASE_CARD_MAP[card_id]
    return _DESPERATION_CARD_MAP[card_id]


def create_desperation_deck(rng: Random) -> DesperationDeck:
    """Create and shuffle the shared desperation deck.

    The rules say cards are drawn from the bottom; we model this as pop(0).
    The 'Shuffle Desperately' sentinel is a flag – when the deck would be
    drawn empty we set shuffle_marker_on_top=True; the next draw triggers
    a reshuffle and places the marker back at the top.
    """
    cards = all_desperation_cards()
    rng.shuffle(cards)
    return DesperationDeck(cards=cards, shuffle_marker_on_top=False)


def draw_desperation_card(deck: DesperationDeck, rng: Random) -> Card:
    """Draw one card from the bottom (index 0) of the desperation deck.

    If the deck is empty (shuffle marker just reached the top), reshuffle all
    cards, reset the marker to False, and draw the first card.
    """
    if not deck.cards:
        # Reshuffle – happens when the sentinel was reached during a prior draw.
        cards = all_desperation_cards()
        rng.shuffle(cards)
        deck.cards = cards
        deck.shuffle_marker_on_top = False

    card = deck.cards.pop(0)

    # If the deck is now empty, mark the sentinel for next time.
    if not deck.cards:
        deck.shuffle_marker_on_top = True

    return card
