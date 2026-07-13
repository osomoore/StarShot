from __future__ import annotations

from dataclasses import dataclass

from starshot.rules.models import Card, CardFamily, DesperateFace, OrderCardSelection, SealMode


@dataclass(frozen=True, slots=True)
class MoveDirective:
    distance: int
    orientation_options: tuple[str, ...]
    defense_bonus: int = 0
    movement_disabled: bool = False
    warp_destination: str | None = None
    side_slip_direction: str | None = None
    double_turn_right: bool = False
    double_turn_after_move: bool = False
    u_turn_move: bool = False
    active_cooling: bool = False
    repair_components: int = 0
    reconfigure_components: int = 0


@dataclass(frozen=True, slots=True)
class AttackContribution:
    base_damage: int
    damage_bonus: int = 0
    aim_bonus: int = 0
    requires_target: bool = True
    always_hits: bool = False
    max_range: int | None = None
    fixed_defense_threshold: int | None = None
    attacks_all: bool = False
    u_turn_attack: bool = False
    lead_the_target: bool = False
    ramming_distance: int = 0
    ramming_damage: int = 0
    attacks_cone_120: bool = False

    @property
    def damage(self) -> int:
        return self.base_damage + self.damage_bonus


@dataclass(frozen=True, slots=True)
class CardEffect:
    family: CardFamily
    is_desperate_face: bool
    value: int
    requires_target: bool
    orientation_options: tuple[str, ...]
    move: MoveDirective | None = None
    attack: AttackContribution | None = None
    repair_components: int = 0
    reconfigure_components: int = 0


def is_desperate_face(selection: OrderCardSelection) -> bool:
    return selection.face == "desperate"


def desperate_face_for(card: Card, selection: OrderCardSelection) -> DesperateFace | None:
    if not is_desperate_face(selection) and not card.no_basic_face:
        return None
    if card.desperate_face is None:
        raise ValueError(f"Card {card.id} does not have an implemented desperate face.")
    return card.desperate_face


def selected_card_family(card: Card, selection: OrderCardSelection) -> CardFamily:
    desperate_face = desperate_face_for(card, selection)
    if desperate_face is not None:
        if desperate_face.repair_components or desperate_face.reconfigure_components:
            if selection.mode == "attack":
                return CardFamily.ATTACK
            if selection.mode in {None, "move"}:
                return CardFamily.MOVE
            raise ValueError(f"Engineering desperate face for card {card.id} requires a valid mode selection.")
        if desperate_face.family == CardFamily.HYBRID:
            if selection.mode == "attack" or selection.orientation.endswith("attack"):
                return CardFamily.ATTACK
            if selection.mode in {None, "move"}:
                return CardFamily.MOVE
            raise ValueError(f"Hybrid desperate face for card {card.id} requires a mode selection.")
        # Crazy Ivan: orientation u_turn_attack means the desperate face acts as an attack
        if selection.orientation == "u_turn_attack":
            return CardFamily.ATTACK
        return desperate_face.family
    if card.is_hybrid:
        if selection.mode == "attack":
            return CardFamily.ATTACK
        if selection.mode == "move":
            return CardFamily.MOVE
        raise ValueError(f"Hybrid card {card.id} requires a mode selection.")
    return card.family


def interpret_card(card: Card, selection: OrderCardSelection, seal_mode: SealMode) -> CardEffect:
    desperate_face = desperate_face_for(card, selection)
    family = selected_card_family(card, selection)
    value = card_value(card, selection, seal_mode)
    requires_target = card_requires_target(card, selection)
    orientation_options = card_orientation_options(card, selection)

    move = None
    attack = None
    repair_components = card_repair_components(card, selection)
    reconfigure_components = card_reconfigure_components(card, selection)
    if family == CardFamily.MOVE and not (repair_components or reconfigure_components):
        move = MoveDirective(
            distance=value,
            orientation_options=orientation_options,
            defense_bonus=card_defense_bonus(card, selection),
            movement_disabled=card_movement_disabled(card, selection),
            warp_destination=card_warp_destination(card, selection),
            side_slip_direction=card_side_slip_direction(card, selection),
            double_turn_right=card_double_turn_right(card, selection),
            double_turn_after_move=card_double_turn_after_move(card, selection),
            u_turn_move=card_u_turn_move(card, selection),
            active_cooling=card_active_cooling(card, selection),
            repair_components=card_repair_components(card, selection),
            reconfigure_components=card_reconfigure_components(card, selection),
        )
    elif family == CardFamily.ATTACK and not (repair_components or reconfigure_components):
        attack = AttackContribution(
            base_damage=card_attack_base_damage(card, selection, seal_mode),
            damage_bonus=card_damage_bonus(card, selection),
            aim_bonus=card_attack_aim_bonus(card, selection, seal_mode),
            requires_target=requires_target,
            always_hits=card_always_hits(card, selection),
            max_range=card_max_range(card, selection),
            fixed_defense_threshold=card_fixed_defense_threshold(card, selection),
            attacks_all=card_attacks_all(card, selection),
            u_turn_attack=card_u_turn_attack(card, selection),
            lead_the_target=card_lead_the_target(card, selection),
            ramming_distance=card_ramming_distance(card, selection),
            ramming_damage=card_ramming_damage(card, selection),
            attacks_cone_120=card_attacks_cone_120(card, selection),
        )

    return CardEffect(
        family=family,
        is_desperate_face=desperate_face is not None,
        value=value,
        requires_target=requires_target,
        orientation_options=orientation_options,
        move=move,
        attack=attack,
        repair_components=repair_components,
        reconfigure_components=reconfigure_components,
    )


def card_attack_base_damage(card: Card, selection: OrderCardSelection, seal_mode: SealMode) -> int:
    desperate_face = desperate_face_for(card, selection)
    if desperate_face is not None:
        return desperate_face.base_damage
    return 1


def card_attack_aim_bonus(card: Card, selection: OrderCardSelection, seal_mode: SealMode) -> int:
    desperate_face = desperate_face_for(card, selection)
    if desperate_face is not None:
        return desperate_face.aim_bonus
    return card_value(card, selection, seal_mode)


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
    return card.value


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


def card_side_slip_direction(card: Card, selection: OrderCardSelection) -> str | None:
    desperate_face = desperate_face_for(card, selection)
    return desperate_face.side_slip_direction if desperate_face is not None else None


def card_double_turn_right(card: Card, selection: OrderCardSelection) -> bool:
    desperate_face = desperate_face_for(card, selection)
    return bool(desperate_face is not None and desperate_face.double_turn_right)


def card_double_turn_after_move(card: Card, selection: OrderCardSelection) -> bool:
    desperate_face = desperate_face_for(card, selection)
    return bool(desperate_face is not None and desperate_face.double_turn_after_move)


def card_u_turn_move(card: Card, selection: OrderCardSelection) -> bool:
    desperate_face = desperate_face_for(card, selection)
    return bool(desperate_face is not None and desperate_face.u_turn_move)


def card_u_turn_attack(card: Card, selection: OrderCardSelection) -> bool:
    desperate_face = desperate_face_for(card, selection)
    if desperate_face is None:
        return False
    return bool(desperate_face.u_turn_attack or selection.orientation == "u_turn_attack")


def card_active_cooling(card: Card, selection: OrderCardSelection) -> bool:
    desperate_face = desperate_face_for(card, selection)
    return bool(desperate_face is not None and desperate_face.active_cooling)


def card_lead_the_target(card: Card, selection: OrderCardSelection) -> bool:
    desperate_face = desperate_face_for(card, selection)
    return bool(desperate_face is not None and desperate_face.lead_the_target)


def card_ramming_distance(card: Card, selection: OrderCardSelection) -> int:
    desperate_face = desperate_face_for(card, selection)
    return desperate_face.ramming_distance if desperate_face is not None else 0


def card_ramming_damage(card: Card, selection: OrderCardSelection) -> int:
    desperate_face = desperate_face_for(card, selection)
    return desperate_face.ramming_damage if desperate_face is not None else 0


def card_attacks_cone_120(card: Card, selection: OrderCardSelection) -> bool:
    desperate_face = desperate_face_for(card, selection)
    return bool(desperate_face is not None and desperate_face.attacks_cone_120)


def card_repair_components(card: Card, selection: OrderCardSelection) -> int:
    desperate_face = desperate_face_for(card, selection)
    return desperate_face.repair_components if desperate_face is not None else 0


def card_reconfigure_components(card: Card, selection: OrderCardSelection) -> int:
    desperate_face = desperate_face_for(card, selection)
    return desperate_face.reconfigure_components if desperate_face is not None else 0


def static_card_effect_summary(card: Card) -> dict:
    return {
        "family": card.family.value,
        "value": card.value,
        "requires_target": card.requires_target,
        "orientation_options": list(card.orientation_options),
        "is_hybrid": card.is_hybrid,
    }
