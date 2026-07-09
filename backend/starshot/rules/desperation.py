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
from starshot.rules.models import Card, CardFamily, DesperateFace, DesperationDeck

# ---------------------------------------------------------------------------
# Sentinel for deferred desperate faces.  Cards that carry this face will
# raise RulesError when the player attempts to play the desperate face.
# ---------------------------------------------------------------------------
_DEFERRED = None  # explicit alias for readability in the card list below

# ---------------------------------------------------------------------------
# 0.2 Desperation Deck — 41 cards total.
#
# Basic face structure:
#   - Most cards are hybrid Move N / Attack Aim +N.
#   - Afterburners and Crack Shot have no_basic_face=True; they always return
#     to the Desperation deck regardless of which face is played.
#
# Desperate face orientation_options default to ("forward",) via DesperateFace.
# ---------------------------------------------------------------------------

_DESPERATION_CARDS: list[Card] = [
    # ------------------------------------------------------------------
    # Afterburners x5  (no basic face — always returns to deck)
    # Basic: Move 3 (forward / turn-right / turn-left)
    # Desperate: same move options at Move 3 (the card IS the desperate face)
    # ------------------------------------------------------------------
    Card(
        id="desp_afterburners_a",
        name="Afterburners",
        family=CardFamily.MOVE,
        value=3,
        is_base=False,
        orientation_options=("forward", "turn_right", "turn_left"),
        requires_target=False,
        no_basic_face=True,
        desperate_face=DesperateFace(
            CardFamily.MOVE,
            value=3,
            orientation_options=("forward", "turn_right", "turn_left"),
        ),
    ),
    Card(
        id="desp_afterburners_b",
        name="Afterburners",
        family=CardFamily.MOVE,
        value=3,
        is_base=False,
        orientation_options=("forward", "turn_right", "turn_left"),
        requires_target=False,
        no_basic_face=True,
        desperate_face=DesperateFace(
            CardFamily.MOVE,
            value=3,
            orientation_options=("forward", "turn_right", "turn_left"),
        ),
    ),
    Card(
        id="desp_afterburners_c",
        name="Afterburners",
        family=CardFamily.MOVE,
        value=3,
        is_base=False,
        orientation_options=("forward", "turn_right", "turn_left"),
        requires_target=False,
        no_basic_face=True,
        desperate_face=DesperateFace(
            CardFamily.MOVE,
            value=3,
            orientation_options=("forward", "turn_right", "turn_left"),
        ),
    ),
    Card(
        id="desp_afterburners_d",
        name="Afterburners",
        family=CardFamily.MOVE,
        value=3,
        is_base=False,
        orientation_options=("forward", "turn_right", "turn_left"),
        requires_target=False,
        no_basic_face=True,
        desperate_face=DesperateFace(
            CardFamily.MOVE,
            value=3,
            orientation_options=("forward", "turn_right", "turn_left"),
        ),
    ),
    Card(
        id="desp_afterburners_e",
        name="Afterburners",
        family=CardFamily.MOVE,
        value=3,
        is_base=False,
        orientation_options=("forward", "turn_right", "turn_left"),
        requires_target=False,
        no_basic_face=True,
        desperate_face=DesperateFace(
            CardFamily.MOVE,
            value=3,
            orientation_options=("forward", "turn_right", "turn_left"),
        ),
    ),
    # ------------------------------------------------------------------
    # Crack Shot x5  (no basic face — always returns to deck)
    # Basic / Desperate: Targeted Attack Damage +1
    # ------------------------------------------------------------------
    Card(
        id="desp_crack_shot_a",
        name="Crack Shot",
        family=CardFamily.ATTACK,
        value=0,
        is_base=False,
        requires_target=True,
        no_basic_face=True,
        desperate_face=DesperateFace(
            CardFamily.ATTACK,
            base_damage=1,
            damage_bonus=1,
            requires_target=True,
        ),
    ),
    Card(
        id="desp_crack_shot_b",
        name="Crack Shot",
        family=CardFamily.ATTACK,
        value=0,
        is_base=False,
        requires_target=True,
        no_basic_face=True,
        desperate_face=DesperateFace(
            CardFamily.ATTACK,
            base_damage=1,
            damage_bonus=1,
            requires_target=True,
        ),
    ),
    Card(
        id="desp_crack_shot_c",
        name="Crack Shot",
        family=CardFamily.ATTACK,
        value=0,
        is_base=False,
        requires_target=True,
        no_basic_face=True,
        desperate_face=DesperateFace(
            CardFamily.ATTACK,
            base_damage=1,
            damage_bonus=1,
            requires_target=True,
        ),
    ),
    Card(
        id="desp_crack_shot_d",
        name="Crack Shot",
        family=CardFamily.ATTACK,
        value=0,
        is_base=False,
        requires_target=True,
        no_basic_face=True,
        desperate_face=DesperateFace(
            CardFamily.ATTACK,
            base_damage=1,
            damage_bonus=1,
            requires_target=True,
        ),
    ),
    Card(
        id="desp_crack_shot_e",
        name="Crack Shot",
        family=CardFamily.ATTACK,
        value=0,
        is_base=False,
        requires_target=True,
        no_basic_face=True,
        desperate_face=DesperateFace(
            CardFamily.ATTACK,
            base_damage=1,
            damage_bonus=1,
            requires_target=True,
        ),
    ),
    # ------------------------------------------------------------------
    # Reconfigure x3  (desperate face deferred)
    # Basic: Move 2 / Attack Aim +2
    # ------------------------------------------------------------------
    Card(id="desp_reconfigure_a", name="Reconfigure", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=_DEFERRED),
    Card(id="desp_reconfigure_b", name="Reconfigure", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=_DEFERRED),
    Card(id="desp_reconfigure_c", name="Reconfigure", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=_DEFERRED),
    # ------------------------------------------------------------------
    # Hull Repair x3  (desperate face deferred)
    # Basic: Move 2 / Attack Aim +2
    # ------------------------------------------------------------------
    Card(id="desp_hull_repair_a", name="Hull Repair", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=_DEFERRED),
    Card(id="desp_hull_repair_b", name="Hull Repair", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=_DEFERRED),
    Card(id="desp_hull_repair_c", name="Hull Repair", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=_DEFERRED),
    # ------------------------------------------------------------------
    # Steady Shot x3
    # Basic: Move 2 / Attack Aim +2
    # Desperate: Aim +2, Damage +1
    # ------------------------------------------------------------------
    Card(id="desp_steady_shot_a", name="Steady Shot", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.ATTACK, aim_bonus=2, damage_bonus=1)),
    Card(id="desp_steady_shot_b", name="Steady Shot", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.ATTACK, aim_bonus=2, damage_bonus=1)),
    Card(id="desp_steady_shot_c", name="Steady Shot", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.ATTACK, aim_bonus=2, damage_bonus=1)),
    # ------------------------------------------------------------------
    # Side Slip x3
    # Basic: Move 2 / Attack Aim +2
    # Desperate: Move 4 sideways (right or left)
    # ------------------------------------------------------------------
    Card(id="desp_side_slip_a", name="Side Slip", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, value=4, orientation_options=("slip_right", "slip_left"), side_slip_direction="right")),
    Card(id="desp_side_slip_b", name="Side Slip", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, value=4, orientation_options=("slip_right", "slip_left"), side_slip_direction="right")),
    Card(id="desp_side_slip_c", name="Side Slip", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, value=4, orientation_options=("slip_right", "slip_left"), side_slip_direction="right")),
    # ------------------------------------------------------------------
    # Drift King x3
    # Basic: Move 2 / Attack Aim +2
    # Desperate: Turn right twice then Move 4
    # ------------------------------------------------------------------
    Card(id="desp_drift_king_a", name="Drift King", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, value=4, double_turn_right=True)),
    Card(id="desp_drift_king_b", name="Drift King", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, value=4, double_turn_right=True)),
    Card(id="desp_drift_king_c", name="Drift King", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, value=4, double_turn_right=True)),
    # ------------------------------------------------------------------
    # Thrust Ions x3
    # Basic: Move 2 / Attack Aim +2
    # Desperate: Move 5 forward
    # ------------------------------------------------------------------
    Card(id="desp_thrust_ions_a", name="Thrust Ions", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, value=5)),
    Card(id="desp_thrust_ions_b", name="Thrust Ions", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, value=5)),
    Card(id="desp_thrust_ions_c", name="Thrust Ions", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, value=5)),
    # ------------------------------------------------------------------
    # Crazy Ivan x3
    # Basic: Move 2 / Attack Aim +2
    # Desperate face A (move): U-Turn then Move 3
    # Desperate face B (attack): U-Turn then Attack Aim +3
    # The card carries the move desperate face; the attack variant is
    # expressed via u_turn_attack on the same face when mode="attack".
    # We model this as two orientation options on the desperate face.
    # ------------------------------------------------------------------
    Card(id="desp_crazy_ivan_a", name="Crazy Ivan", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, value=3, orientation_options=("u_turn_move", "u_turn_attack"), u_turn_move=True)),
    Card(id="desp_crazy_ivan_b", name="Crazy Ivan", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, value=3, orientation_options=("u_turn_move", "u_turn_attack"), u_turn_move=True)),
    Card(id="desp_crazy_ivan_c", name="Crazy Ivan", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, value=3, orientation_options=("u_turn_move", "u_turn_attack"), u_turn_move=True)),
    # ------------------------------------------------------------------
    # Active Cooling x3
    # Basic: Move 2 / Attack Aim +2
    # Desperate: Move 1 forward, then move Overheat pile to Discard
    # ------------------------------------------------------------------
    Card(id="desp_active_cooling_a", name="Active Cooling", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, value=1, active_cooling=True)),
    Card(id="desp_active_cooling_b", name="Active Cooling", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, value=1, active_cooling=True)),
    Card(id="desp_active_cooling_c", name="Active Cooling", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, value=1, active_cooling=True)),
    # ------------------------------------------------------------------
    # Turbo Ions x1
    # Basic: Move 3 / Attack Aim +3
    # Desperate: Move 10 forward
    # ------------------------------------------------------------------
    Card(id="desp_turbo_ions", name="Turbo Ions", family=CardFamily.MOVE, value=3, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, value=10)),
    # ------------------------------------------------------------------
    # NightJammer x1
    # Basic: Move 4 / Attack Aim +4
    # Desperate: Warp behind VP leader, Defense +5
    # ------------------------------------------------------------------
    Card(id="desp_nightjammer", name="NightJammer", family=CardFamily.MOVE, value=4, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.MOVE, defense_bonus=5, warp_destination="leader")),
    # ------------------------------------------------------------------
    # Holdo Maneuver x1  (desperate face deferred)
    # Basic: Move 5 / Attack Aim +5
    # ------------------------------------------------------------------
    Card(id="desp_holdo_maneuver", name="Holdo Maneuver", family=CardFamily.MOVE, value=5, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=_DEFERRED),
    # ------------------------------------------------------------------
    # StarShot x1
    # Basic: Move 6 / Attack Aim +6
    # Desperate: Attack Aim +999 (always hits)
    # ------------------------------------------------------------------
    Card(id="desp_starshot", name="StarShot", family=CardFamily.MOVE, value=6, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.ATTACK, aim_bonus=999, always_hits=True)),
    # ------------------------------------------------------------------
    # ScatterShot x1  (desperate face deferred)
    # Basic: Move 7 / Attack Aim +7
    # ------------------------------------------------------------------
    Card(id="desp_scattershot", name="ScatterShot", family=CardFamily.MOVE, value=7, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=_DEFERRED),
    # ------------------------------------------------------------------
    # Lead the Target x1
    # Basic: Move 8 / Attack Aim +8
    # Desperate: Attack ignores target's movement bonus, Damage +1
    # ------------------------------------------------------------------
    Card(id="desp_lead_the_target", name="Lead the Target", family=CardFamily.MOVE, value=8, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=DesperateFace(CardFamily.ATTACK, damage_bonus=1, lead_the_target=True)),
    # ------------------------------------------------------------------
    # Overdrive 2x x1  (desperate face deferred)
    # Basic: Move 2 / Attack Aim +2
    # ------------------------------------------------------------------
    Card(id="desp_overdrive_2x", name="Overdrive 2x", family=CardFamily.MOVE, value=2, is_base=False, is_hybrid=True, orientation_options=("forward",), requires_target=False, desperate_face=_DEFERRED),
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
