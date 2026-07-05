from __future__ import annotations

from random import Random

from starshot.rules.models import (
    Card,
    CardFamily,
    DesperateFace,
    DesperationDeck,
    OrderCardSelection,
    SealMode,
)


# Basic faces of all desperation cards that are in-scope for the first slice.
# 'value' here is the basic-face value; desperate_face holds the single-use
# face where that face fits the current action-stack engine.
# Hull Repair, Advanced Repair, and All She's Got are also deferred.
_DESPERATION_CARDS: list[Card] = [
    # Move-type basic faces
    Card(id="desp_thrust_ions_a",    name="Thrust Ions",      family=CardFamily.MOVE,   value=1, is_base=False, orientation_options=("forward",), desperate_face=DesperateFace(CardFamily.MOVE, value=5)),
    Card(id="desp_thrust_ions_b",    name="Thrust Ions",      family=CardFamily.MOVE,   value=1, is_base=False, orientation_options=("forward",), desperate_face=DesperateFace(CardFamily.MOVE, value=5)),
    Card(id="desp_turbo_ions",       name="Turbo Ions",       family=CardFamily.MOVE,   value=1, is_base=False, orientation_options=("forward",), desperate_face=DesperateFace(CardFamily.MOVE, value=10)),
    Card(id="desp_homeward_bound",   name="Homeward Bound",   family=CardFamily.MOVE,   value=1, is_base=False, orientation_options=("forward",), desperate_face=DesperateFace(CardFamily.MOVE, defense_bonus=5, warp_destination="home")),
    Card(id="desp_treasure_hound",   name="Treasure Hound",   family=CardFamily.MOVE,   value=1, is_base=False, orientation_options=("forward",), desperate_face=DesperateFace(CardFamily.MOVE, defense_bonus=5, warp_destination="bauble")),
    Card(id="desp_evasive_action",   name="Evasive Action",   family=CardFamily.MOVE,   value=1, is_base=False, orientation_options=("forward",), desperate_face=DesperateFace(CardFamily.MOVE, defense_bonus=10, movement_disabled=True)),
    # Attack-type basic faces (untargeted bonus; must pair with a targeted attack)
    Card(id="desp_ace_shot_a",       name="Ace Shot",         family=CardFamily.ATTACK, value=1, is_base=False, orientation_options=("forward",), requires_target=False, is_hybrid=True, desperate_face=DesperateFace(CardFamily.ATTACK, aim_bonus=5)),
    Card(id="desp_ace_shot_b",       name="Ace Shot",         family=CardFamily.ATTACK, value=1, is_base=False, orientation_options=("forward",), requires_target=False, is_hybrid=True, desperate_face=DesperateFace(CardFamily.ATTACK, aim_bonus=5)),
    Card(id="desp_deadeye",          name="Deadeye",          family=CardFamily.ATTACK, value=1, is_base=False, orientation_options=("forward",), requires_target=False, is_hybrid=True, desperate_face=DesperateFace(CardFamily.ATTACK, aim_bonus=999, always_hits=True)),
    Card(id="desp_nightjammer",      name="Nightjammer",      family=CardFamily.ATTACK, value=1, is_base=False, orientation_options=("forward",), requires_target=False, is_hybrid=True, desperate_face=DesperateFace(CardFamily.MOVE, defense_bonus=5, warp_destination="leader")),
    Card(id="desp_self_destruct",    name="Self Destruct",    family=CardFamily.ATTACK, value=1, is_base=False, orientation_options=("forward",), requires_target=False, is_hybrid=True, desperate_face=DesperateFace(CardFamily.ATTACK, value=4, requires_target=True, max_range=2)),
    Card(id="desp_death_blossom",    name="Death Blossom",    family=CardFamily.ATTACK, value=1, is_base=False, orientation_options=("forward",), requires_target=False, is_hybrid=True, desperate_face=DesperateFace(CardFamily.ATTACK, value=1, fixed_defense_threshold=10, attacks_all=True)),
    Card(id="desp_steady_shot_a",    name="Steady Shot",      family=CardFamily.ATTACK, value=1, is_base=False, orientation_options=("forward",), requires_target=False, is_hybrid=True, desperate_face=DesperateFace(CardFamily.ATTACK, aim_bonus=2, damage_bonus=1)),
    Card(id="desp_steady_shot_b",    name="Steady Shot",      family=CardFamily.ATTACK, value=1, is_base=False, orientation_options=("forward",), requires_target=False, is_hybrid=True, desperate_face=DesperateFace(CardFamily.ATTACK, aim_bonus=2, damage_bonus=1)),
    # Desperate Targeted Attack cards - proper targeted attacks, not overdriven
    Card(id="desp_targeted_attack_1_a", name="Desperation Attack 1", family=CardFamily.ATTACK, value=1, is_base=False),
    Card(id="desp_targeted_attack_1_b", name="Desperation Attack 1", family=CardFamily.ATTACK, value=1, is_base=False),
    Card(id="desp_targeted_attack_1_c", name="Desperation Attack 1", family=CardFamily.ATTACK, value=1, is_base=False),
    Card(id="desp_targeted_attack_1_d", name="Desperation Attack 1", family=CardFamily.ATTACK, value=1, is_base=False),
]

_DESPERATION_CARD_MAP: dict[str, Card] = {card.id: card for card in _DESPERATION_CARDS}


def all_desperation_cards() -> list[Card]:
    """Return a fresh copy of the full desperation card list."""
    return list(_DESPERATION_CARDS)


def desperation_card_by_id(card_id: str) -> Card:
    return _DESPERATION_CARD_MAP[card_id]


def is_desperation_card_id(card_id: str) -> bool:
    return card_id in _DESPERATION_CARD_MAP


def create_desperation_deck(rng: Random) -> DesperationDeck:
    """Create and shuffle the shared desperation deck.

    The rules say cards are drawn from the bottom; we model this as pop(0).
    The 'Shuffle Desperately' sentinel is a flag - when the deck would be
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
        # Reshuffle - happens when the sentinel was reached during a prior draw.
        cards = all_desperation_cards()
        rng.shuffle(cards)
        deck.cards = cards
        deck.shuffle_marker_on_top = False

    card = deck.cards.pop(0)

    # If the deck is now empty, mark the sentinel for next time.
    if not deck.cards:
        deck.shuffle_marker_on_top = True

    return card


def return_desperation_card(deck: DesperationDeck, card: Card) -> None:
    deck.cards.append(card)
    deck.shuffle_marker_on_top = False


def is_desperate_face(selection: OrderCardSelection) -> bool:
    return selection.face == "desperate"


def desperate_face_for(card: Card, selection: OrderCardSelection) -> DesperateFace | None:
    if not is_desperate_face(selection):
        return None
    if card.desperate_face is None:
        raise ValueError(f"Card {card.id} does not have an implemented desperate face.")
    return card.desperate_face


def selected_card_family(card: Card, selection: OrderCardSelection) -> CardFamily:
    desperate_face = desperate_face_for(card, selection)
    if desperate_face is not None:
        return desperate_face.family
    if card.is_hybrid:
        if selection.mode == "attack":
            return CardFamily.ATTACK
        if selection.mode == "move":
            return CardFamily.MOVE
        raise ValueError(f"Hybrid card {card.id} requires a mode selection.")
    return card.family


def card_requires_target(card: Card, selection: OrderCardSelection) -> bool:
    desperate_face = desperate_face_for(card, selection)
    if desperate_face is not None:
        return desperate_face.requires_target
    return card.requires_target


def card_orientation_options(card: Card, selection: OrderCardSelection) -> tuple[str, ...]:
    desperate_face = desperate_face_for(card, selection)
    if desperate_face is not None:
        return desperate_face.orientation_options
    return card.orientation_options


def card_value(card: Card, selection: OrderCardSelection, seal_mode: SealMode) -> int:
    desperate_face = desperate_face_for(card, selection)
    if desperate_face is not None:
        return desperate_face.value
    return card.value + (1 if seal_mode == SealMode.OVERDRIVE and card.is_base else 0)


def card_aim_bonus(card: Card, selection: OrderCardSelection) -> int:
    desperate_face = desperate_face_for(card, selection)
    return desperate_face.aim_bonus if desperate_face is not None else 0


def card_damage_bonus(card: Card, selection: OrderCardSelection) -> int:
    desperate_face = desperate_face_for(card, selection)
    return desperate_face.damage_bonus if desperate_face is not None else 0


def card_defense_bonus(card: Card, selection: OrderCardSelection) -> int:
    desperate_face = desperate_face_for(card, selection)
    return desperate_face.defense_bonus if desperate_face is not None else 0


def card_always_hits(card: Card, selection: OrderCardSelection) -> bool:
    desperate_face = desperate_face_for(card, selection)
    return bool(desperate_face is not None and desperate_face.always_hits)


def card_movement_disabled(card: Card, selection: OrderCardSelection) -> bool:
    desperate_face = desperate_face_for(card, selection)
    return bool(desperate_face is not None and desperate_face.movement_disabled)


def card_warp_destination(card: Card, selection: OrderCardSelection) -> str | None:
    desperate_face = desperate_face_for(card, selection)
    return desperate_face.warp_destination if desperate_face is not None else None


def card_max_range(card: Card, selection: OrderCardSelection) -> int | None:
    desperate_face = desperate_face_for(card, selection)
    return desperate_face.max_range if desperate_face is not None else None


def card_fixed_defense_threshold(card: Card, selection: OrderCardSelection) -> int | None:
    desperate_face = desperate_face_for(card, selection)
    return desperate_face.fixed_defense_threshold if desperate_face is not None else None


def card_attacks_all(card: Card, selection: OrderCardSelection) -> bool:
    desperate_face = desperate_face_for(card, selection)
    return bool(desperate_face is not None and desperate_face.attacks_all)
