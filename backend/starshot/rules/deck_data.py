from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starshot.rules.card_effects import interpret_card
from starshot.rules.models import Card, CardFamily, DesperateFace, OrderCardSelection, SealMode

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DECK_SET_PATH = ROOT / "resources" / "decks" / "core_0_2"
DECK_SET_ENV = "STARSHOT_DECK_SET"

_KNOWN_ORIENTATIONS = {
    "forward",
    "turn_left",
    "turn_right",
    "slip_right",
    "slip_left",
    "u_turn_move",
    "u_turn_attack",
}
_KNOWN_WARP_DESTINATIONS = {"home", "bauble", "leader"}
_COPY_SUFFIXES = "abcdefghijklmnopqrstuvwxyz"
_SUPPORTED_CARD_TEXT_HINT = (
    "Supported examples include: Move 2; Turn Left; Turn Right; Move 2 Right; Move 2 Left; "
    "Attack Aim +2; Targeted Attack Aim +2; Damage +1; Defense +1; Range 3; Always Hits; "
    "Attack All; Warp Behind VP Leader; Move Overheat To Discard; Lead The Target; "
    "choices Forward, Turn Left, Turn Right."
)


@dataclass(frozen=True, slots=True)
class DeckCatalog:
    id: str
    name: str
    rules_version: str
    path: Path
    base_cards: tuple[Card, ...]
    desperation_cards: tuple[Card, ...]
    card_map: dict[str, Card]
    base_card_map: dict[str, Card]
    desperation_card_map: dict[str, Card]


@dataclass(frozen=True, slots=True)
class FaceSpec:
    family: CardFamily
    value: int = 0
    orientation_options: tuple[str, ...] = ("forward",)
    requires_target: bool = False
    is_hybrid: bool = False
    base_damage: int = 1
    aim_bonus: int = 0
    damage_bonus: int = 0
    defense_bonus: int = 0
    always_hits: bool = False
    movement_disabled: bool = False
    warp_destination: str | None = None
    max_range: int | None = None
    fixed_defense_threshold: int | None = None
    attacks_all: bool = False
    side_slip_direction: str | None = None
    double_turn_right: bool = False
    u_turn_move: bool = False
    u_turn_attack: bool = False
    active_cooling: bool = False
    lead_the_target: bool = False


_ACTIVE_CATALOG: DeckCatalog | None = None
_ACTIVE_CATALOG_PATH: Path | None = None


def default_deck_set_path() -> Path:
    return DEFAULT_DECK_SET_PATH


def active_deck_set_path() -> Path:
    configured = os.environ.get(DECK_SET_ENV)
    return Path(configured).expanduser() if configured else default_deck_set_path()


def active_catalog() -> DeckCatalog:
    global _ACTIVE_CATALOG, _ACTIVE_CATALOG_PATH

    catalog_path = active_deck_set_path().resolve()
    if _ACTIVE_CATALOG is None or _ACTIVE_CATALOG_PATH != catalog_path:
        _ACTIVE_CATALOG = load_deck_catalog(catalog_path)
        _ACTIVE_CATALOG_PATH = catalog_path
    return _ACTIVE_CATALOG


def load_deck_catalog(path: Path) -> DeckCatalog:
    deck_set_path = path.resolve()
    if not deck_set_path.exists():
        raise ValueError(f"Deck set path does not exist: {deck_set_path}")
    if not deck_set_path.is_dir():
        raise ValueError(f"Deck set path is not a directory: {deck_set_path}")

    manifest = _read_toml(deck_set_path / "manifest.toml")
    catalog_id = _required_str(manifest, "id", "manifest.toml")
    name = _required_str(manifest, "name", "manifest.toml")
    rules_version = _required_str(manifest, "rules_version", "manifest.toml")

    base_cards = tuple(_load_card_file(deck_set_path / "base_deck.toml", is_base=True))
    desperation_cards = tuple(_load_card_file(deck_set_path / "desperation_deck.toml", is_base=False))
    if not base_cards:
        raise ValueError("base_deck.toml must define at least one card.")
    if not desperation_cards:
        raise ValueError("desperation_deck.toml must define at least one card.")

    base_card_map = _card_map(base_cards, "base_deck.toml")
    desperation_card_map = _card_map(desperation_cards, "desperation_deck.toml")
    overlap = set(base_card_map).intersection(desperation_card_map)
    if overlap:
        ids = ", ".join(sorted(overlap))
        raise ValueError(f"Card ids cannot appear in both base and desperation decks: {ids}")

    card_map = {**base_card_map, **desperation_card_map}
    catalog = DeckCatalog(
        id=catalog_id,
        name=name,
        rules_version=rules_version,
        path=deck_set_path,
        base_cards=base_cards,
        desperation_cards=desperation_cards,
        card_map=card_map,
        base_card_map=base_card_map,
        desperation_card_map=desperation_card_map,
    )
    _validate_catalog(catalog)
    return catalog


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"Missing deck data file: {path}")
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Deck data file must contain a TOML table: {path}")
    return data


def _load_card_file(path: Path, *, is_base: bool) -> list[Card]:
    data = _read_toml(path)
    cards_data = data.get("cards")
    if not isinstance(cards_data, list):
        raise ValueError(f"{path.name} must contain a [[cards]] array.")

    copy_id_style = _copy_id_style(data.get("copy_id_style", "suffix_when_multiple"), path.name)
    generated_id_prefix = _optional_str(data.get("generated_id_prefix"), f"{path.name}.generated_id_prefix") or ""
    cards: list[Card] = []
    for index, card_data in enumerate(cards_data, start=1):
        if not isinstance(card_data, dict):
            raise ValueError(f"{path.name} card #{index} must be a table.")
        cards.extend(
            _expand_card(
                card_data,
                is_base=is_base,
                copy_id_style=copy_id_style,
                generated_id_prefix=generated_id_prefix,
                source=f"{path.name} card #{index}",
            )
        )
    return cards


def _expand_card(
    data: dict[str, Any],
    *,
    is_base: bool,
    copy_id_style: str,
    generated_id_prefix: str,
    source: str,
) -> list[Card]:
    name = _required_str(data, "name", source)
    prototype_id = _optional_str(data.get("id"), f"{source}.id") or f"{generated_id_prefix}{_slugify_name(name)}"
    copy_ids = _copy_ids(data.get("copies", 1), prototype_id, copy_id_style, source)
    side_text = _side_text(data, source)
    if side_text is not None:
        side_data = dict(data)
        side_data.update(side_text)
        return _expand_english_card(side_data, prototype_id, name, copy_ids, is_base=is_base, source=source)
    if "basic" in data or "desperate" in data or "cleanup" in data:
        return _expand_english_card(data, prototype_id, name, copy_ids, is_base=is_base, source=source)

    family = _family(data.get("family"), f"{source}.family")
    value = _int(data.get("value", 0), f"{source}.value")

    orientation_options = _orientation_options(
        data.get("orientation_options", ("forward", "turn_left", "turn_right")),
        f"{source}.orientation_options",
    )
    requires_target = _bool(data.get("requires_target", True), f"{source}.requires_target")
    is_hybrid = _bool(data.get("is_hybrid", False), f"{source}.is_hybrid")
    no_basic_face = _bool(data.get("no_basic_face", False), f"{source}.no_basic_face")
    desperate_face = _desperate_face(data.get("desperate_face"), source)

    cards: list[Card] = []
    for copy_id in copy_ids:
        cards.append(
            Card(
                id=copy_id,
                name=name,
                family=family,
                value=value,
                is_base=is_base,
                orientation_options=orientation_options,
                requires_target=requires_target,
                is_hybrid=is_hybrid,
                desperate_face=desperate_face,
                no_basic_face=no_basic_face,
            )
        )
    return cards


def _side_text(data: dict[str, Any], source: str) -> dict[str, Any] | None:
    side_keys = [key for key in data if re.fullmatch(r"side_[ab](_type|_\d+)", key)]
    if not side_keys:
        return None

    result: dict[str, list[str]] = {"basic": [], "desperate": []}
    for side in ("a", "b"):
        side_type_value = data.get(f"side_{side}_type")
        if side_type_value is None:
            continue
        side_type = _normalize_text(_str(side_type_value, f"{source}.side_{side}_type"))
        if side_type not in {"basic", "desperate"}:
            raise ValueError(f"{source}.side_{side}_type must be Basic or Desperate.")
        entries: list[str] = []
        index = 1
        while f"side_{side}_{index}" in data:
            entries.append(_str(data[f"side_{side}_{index}"], f"{source}.side_{side}_{index}"))
            index += 1
        if not entries:
            raise ValueError(f"{source}.side_{side}_type needs at least one side_{side}_N entry.")
        result[side_type].extend(entries)

    return {key: value for key, value in result.items() if value}


def _slugify_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower())
    return slug.strip("_")


def _expand_english_card(
    data: dict[str, Any],
    prototype_id: str,
    name: str,
    copy_ids: tuple[str, ...],
    *,
    is_base: bool,
    source: str,
) -> list[Card]:
    cleanup = _text_entries(data.get("cleanup", ()))
    no_basic_face = _bool(data.get("no_basic_face", False), f"{source}.no_basic_face")
    no_basic_face = no_basic_face or any(_normalize_text(entry) == "return to desperation deck" for entry in cleanup)

    basic_spec = _face_spec(data.get("basic"), f"{source}.basic") if "basic" in data else None
    desperate_spec = _face_spec(data.get("desperate"), f"{source}.desperate") if "desperate" in data else None
    if basic_spec is None and desperate_spec is None:
        raise ValueError(f"{source} must define basic or desperate card text.")
    if no_basic_face and desperate_spec is None:
        raise ValueError(f"{source} returns to the Desperation deck but has no desperate text.")

    front_spec = basic_spec or desperate_spec
    assert front_spec is not None
    cards: list[Card] = []
    for copy_id in copy_ids:
        cards.append(
            Card(
                id=copy_id,
                name=name,
                family=front_spec.family if front_spec.family != CardFamily.HYBRID else CardFamily.MOVE,
                value=front_spec.value,
                is_base=is_base,
                orientation_options=front_spec.orientation_options,
                requires_target=front_spec.requires_target,
                is_hybrid=front_spec.is_hybrid or front_spec.family == CardFamily.HYBRID,
                desperate_face=_desperate_face_from_spec(desperate_spec) if desperate_spec else None,
                no_basic_face=no_basic_face,
            )
        )
    return cards


def _copy_ids(value: Any, prototype_id: str, copy_id_style: str, source: str) -> tuple[str, ...]:
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 1:
            raise ValueError(f"{source}.copies must be at least 1.")
        if value > len(_COPY_SUFFIXES):
            raise ValueError(f"{source}.copies cannot exceed {len(_COPY_SUFFIXES)} with generated ids.")
        if value == 1 and copy_id_style == "suffix_when_multiple":
            return (prototype_id,)
        return tuple(f"{prototype_id}_{_COPY_SUFFIXES[index]}" for index in range(value))

    if isinstance(value, list) and value:
        copy_ids: list[str] = []
        for index, copy_id in enumerate(value, start=1):
            if not isinstance(copy_id, str) or not copy_id:
                raise ValueError(f"{source}.copies[{index}] must be a non-empty string.")
            copy_ids.append(copy_id)
        return tuple(copy_ids)

    raise ValueError(f"{source}.copies must be a positive integer or a non-empty list of card ids.")


def _copy_id_style(value: Any, source: str) -> str:
    style = _str(value, f"{source}.copy_id_style")
    if style not in {"always_suffix", "suffix_when_multiple"}:
        raise ValueError(f"{source}.copy_id_style must be always_suffix or suffix_when_multiple.")
    return style


def _desperate_face_from_spec(spec: FaceSpec | None) -> DesperateFace | None:
    if spec is None:
        return None
    return DesperateFace(
        family=spec.family,
        value=0 if spec.family == CardFamily.ATTACK else spec.value,
        base_damage=spec.base_damage,
        orientation_options=spec.orientation_options,
        requires_target=spec.requires_target,
        aim_bonus=spec.aim_bonus,
        damage_bonus=spec.damage_bonus,
        defense_bonus=spec.defense_bonus,
        always_hits=spec.always_hits,
        movement_disabled=spec.movement_disabled,
        warp_destination=spec.warp_destination,
        max_range=spec.max_range,
        fixed_defense_threshold=spec.fixed_defense_threshold,
        attacks_all=spec.attacks_all,
        side_slip_direction=spec.side_slip_direction,
        double_turn_right=spec.double_turn_right,
        u_turn_move=spec.u_turn_move,
        u_turn_attack=spec.u_turn_attack,
        active_cooling=spec.active_cooling,
        lead_the_target=spec.lead_the_target,
    )


def _face_spec(value: Any, field: str) -> FaceSpec:
    entries = _text_entries(value)
    alternatives: list[FaceSpec] = []
    for entry in entries:
        for alternative in _split_alternatives(entry):
            alternatives.append(_single_face_spec(alternative, field))
    if not alternatives:
        raise ValueError(f"{field} must contain at least one effect.")
    if len(alternatives) == 1:
        return alternatives[0]

    families = {alternative.family for alternative in alternatives}
    if families == {CardFamily.MOVE}:
        return _combine_move_alternatives(alternatives, field)
    if families.issubset({CardFamily.MOVE, CardFamily.ATTACK}):
        return _combine_mixed_alternatives(alternatives, field)
    raise ValueError(f"{field} has unsupported alternatives.")


def _single_face_spec(text: str, field: str) -> FaceSpec:
    normalized = _normalize_text(text)
    parts: list[str] = []
    for chunk in re.split(r"\s*;\s*", normalized):
        chunk = _normalize_text(chunk)
        if not chunk:
            continue
        if chunk.startswith("choice ") or chunk.startswith("choices "):
            parts.append(chunk)
        else:
            parts.extend(_normalize_text(part) for part in re.split(r"\s*,\s*", chunk) if part.strip())
    spec = FaceSpec(family=CardFamily.MOVE)
    saw_family = False
    choices: tuple[str, ...] | None = None

    for part in parts:
        if part.startswith("choices "):
            choices = _english_orientation_options(part.removeprefix("choices "), field)
            continue
        if part.startswith("choice "):
            choices = _english_orientation_options(part.removeprefix("choice "), field)
            continue
        next_spec = _phrase_spec(part, field)
        if next_spec is None:
            raise ValueError(f"{field} has unsupported effect text: {text!r}. {_SUPPORTED_CARD_TEXT_HINT}")
        spec = _merge_specs(spec, next_spec)
        saw_family = True

    if not saw_family:
        raise ValueError(f"{field} has unsupported effect text: {text!r}. {_SUPPORTED_CARD_TEXT_HINT}")
    if choices is not None:
        spec = _replace_spec(spec, orientation_options=choices)
    return spec


def _phrase_spec(part: str, field: str) -> FaceSpec | None:
    if match := re.fullmatch(r"move (\d+)", part):
        return FaceSpec(family=CardFamily.MOVE, value=int(match.group(1)), requires_target=False)
    if match := re.fullmatch(r"move (\d+) right", part):
        return FaceSpec(
            family=CardFamily.MOVE,
            value=int(match.group(1)),
            orientation_options=("slip_right",),
            requires_target=False,
            side_slip_direction="right",
        )
    if match := re.fullmatch(r"move (\d+) left", part):
        return FaceSpec(
            family=CardFamily.MOVE,
            value=int(match.group(1)),
            orientation_options=("slip_left",),
            requires_target=False,
            side_slip_direction="left",
        )
    if match := re.fullmatch(r"turn right twice then move (\d+)", part):
        return FaceSpec(family=CardFamily.MOVE, value=int(match.group(1)), requires_target=False, double_turn_right=True)
    if match := re.fullmatch(r"u-turn then move (\d+)", part):
        return FaceSpec(
            family=CardFamily.MOVE,
            value=int(match.group(1)),
            orientation_options=("u_turn_move",),
            requires_target=False,
            u_turn_move=True,
        )
    if match := re.fullmatch(r"u-turn attack aim \+(\d+)", part):
        return FaceSpec(
            family=CardFamily.ATTACK,
            value=int(match.group(1)),
            orientation_options=("u_turn_attack",),
            requires_target=False,
            aim_bonus=int(match.group(1)),
            u_turn_attack=True,
        )
    if part in {"turn left", "turn right"}:
        return FaceSpec(
            family=CardFamily.MOVE,
            value=0,
            orientation_options=("turn_left" if part == "turn left" else "turn_right",),
            requires_target=False,
        )
    if match := re.fullmatch(r"(targeted )?attack aim \+(\d+)", part):
        targeted = bool(match.group(1))
        aim = int(match.group(2))
        return FaceSpec(family=CardFamily.ATTACK, value=aim, requires_target=targeted, aim_bonus=aim)
    if match := re.fullmatch(r"(targeted )?attack damage \+(\d+)", part):
        targeted = bool(match.group(1))
        return FaceSpec(family=CardFamily.ATTACK, value=0, requires_target=targeted, damage_bonus=int(match.group(2)))
    if match := re.fullmatch(r"aim \+(\d+)", part):
        aim = int(match.group(1))
        return FaceSpec(family=CardFamily.ATTACK, value=aim, requires_target=False, aim_bonus=aim)
    if match := re.fullmatch(r"damage \+(\d+)", part):
        return FaceSpec(family=CardFamily.ATTACK, requires_target=False, damage_bonus=int(match.group(1)))
    if match := re.fullmatch(r"defense \+(\d+)", part):
        return FaceSpec(family=CardFamily.MOVE, requires_target=False, defense_bonus=int(match.group(1)))
    if match := re.fullmatch(r"range (\d+)", part):
        return FaceSpec(family=CardFamily.ATTACK, requires_target=False, max_range=int(match.group(1)))
    if part == "always hits":
        return FaceSpec(family=CardFamily.ATTACK, requires_target=False, aim_bonus=999, always_hits=True)
    if part == "attack all":
        return FaceSpec(family=CardFamily.ATTACK, requires_target=False, attacks_all=True)
    if part == "warp behind vp leader":
        return FaceSpec(family=CardFamily.MOVE, requires_target=False, warp_destination="leader")
    if part == "move overheat to discard":
        return FaceSpec(family=CardFamily.MOVE, requires_target=False, active_cooling=True)
    if part == "lead the target":
        return FaceSpec(family=CardFamily.ATTACK, requires_target=False, lead_the_target=True)
    return None


def _combine_move_alternatives(alternatives: list[FaceSpec], field: str) -> FaceSpec:
    first = alternatives[0]
    if any(_move_signature(alternative) != _move_signature(first) for alternative in alternatives):
        raise ValueError(f"{field} has multiple move alternatives that cannot share one card face.")
    orientation_options: list[str] = []
    side_slip = None
    u_turn_move_flag = False
    for alternative in alternatives:
        for option in alternative.orientation_options:
            if option not in orientation_options:
                orientation_options.append(option)
        side_slip = side_slip or alternative.side_slip_direction
        u_turn_move_flag = u_turn_move_flag or alternative.u_turn_move
    return _replace_spec(
        first,
        orientation_options=tuple(orientation_options),
        side_slip_direction=side_slip,
        u_turn_move=u_turn_move_flag,
    )


def _combine_mixed_alternatives(alternatives: list[FaceSpec], field: str) -> FaceSpec:
    move = next((alternative for alternative in alternatives if alternative.family == CardFamily.MOVE), None)
    attack = next((alternative for alternative in alternatives if alternative.family == CardFamily.ATTACK), None)
    if move is None or attack is None:
        raise ValueError(f"{field} needs both move and attack alternatives.")
    if len([alternative for alternative in alternatives if alternative.family == CardFamily.MOVE]) > 1:
        move = _combine_move_alternatives([alternative for alternative in alternatives if alternative.family == CardFamily.MOVE], field)
    if len([alternative for alternative in alternatives if alternative.family == CardFamily.ATTACK]) > 1:
        attack = _merge_attack_alternatives([alternative for alternative in alternatives if alternative.family == CardFamily.ATTACK])
    return FaceSpec(
        family=CardFamily.HYBRID,
        value=move.value or attack.value or attack.aim_bonus,
        orientation_options=move.orientation_options + tuple(
            option for option in attack.orientation_options if option not in move.orientation_options
        ),
        requires_target=move.requires_target or attack.requires_target,
        is_hybrid=True,
        base_damage=attack.base_damage,
        aim_bonus=attack.aim_bonus or attack.value,
        damage_bonus=attack.damage_bonus,
        defense_bonus=move.defense_bonus,
        always_hits=attack.always_hits,
        movement_disabled=move.movement_disabled,
        warp_destination=move.warp_destination,
        max_range=attack.max_range,
        fixed_defense_threshold=attack.fixed_defense_threshold,
        attacks_all=attack.attacks_all,
        side_slip_direction=move.side_slip_direction,
        double_turn_right=move.double_turn_right,
        u_turn_move=move.u_turn_move,
        u_turn_attack=attack.u_turn_attack,
        active_cooling=move.active_cooling,
        lead_the_target=attack.lead_the_target,
    )


def _merge_attack_alternatives(alternatives: list[FaceSpec]) -> FaceSpec:
    spec = alternatives[0]
    for alternative in alternatives[1:]:
        spec = _merge_specs(spec, alternative)
    return spec


def _merge_specs(left: FaceSpec, right: FaceSpec) -> FaceSpec:
    family = right.family if left.family == CardFamily.MOVE and left.value == 0 else left.family
    if left.family != right.family and left.value != 0:
        family = CardFamily.HYBRID
    return _replace_spec(
        left,
        family=family,
        value=right.value or left.value,
        orientation_options=right.orientation_options if right.orientation_options != ("forward",) else left.orientation_options,
        requires_target=left.requires_target or right.requires_target,
        is_hybrid=left.is_hybrid or right.is_hybrid or family == CardFamily.HYBRID,
        base_damage=right.base_damage if right.base_damage != 1 else left.base_damage,
        aim_bonus=right.aim_bonus or left.aim_bonus,
        damage_bonus=right.damage_bonus or left.damage_bonus,
        defense_bonus=right.defense_bonus or left.defense_bonus,
        always_hits=left.always_hits or right.always_hits,
        movement_disabled=left.movement_disabled or right.movement_disabled,
        warp_destination=right.warp_destination or left.warp_destination,
        max_range=right.max_range if right.max_range is not None else left.max_range,
        fixed_defense_threshold=(
            right.fixed_defense_threshold if right.fixed_defense_threshold is not None else left.fixed_defense_threshold
        ),
        attacks_all=left.attacks_all or right.attacks_all,
        side_slip_direction=right.side_slip_direction or left.side_slip_direction,
        double_turn_right=left.double_turn_right or right.double_turn_right,
        u_turn_move=left.u_turn_move or right.u_turn_move,
        u_turn_attack=left.u_turn_attack or right.u_turn_attack,
        active_cooling=left.active_cooling or right.active_cooling,
        lead_the_target=left.lead_the_target or right.lead_the_target,
    )


def _replace_spec(spec: FaceSpec, **changes: Any) -> FaceSpec:
    values = {
        "family": spec.family,
        "value": spec.value,
        "orientation_options": spec.orientation_options,
        "requires_target": spec.requires_target,
        "is_hybrid": spec.is_hybrid,
        "base_damage": spec.base_damage,
        "aim_bonus": spec.aim_bonus,
        "damage_bonus": spec.damage_bonus,
        "defense_bonus": spec.defense_bonus,
        "always_hits": spec.always_hits,
        "movement_disabled": spec.movement_disabled,
        "warp_destination": spec.warp_destination,
        "max_range": spec.max_range,
        "fixed_defense_threshold": spec.fixed_defense_threshold,
        "attacks_all": spec.attacks_all,
        "side_slip_direction": spec.side_slip_direction,
        "double_turn_right": spec.double_turn_right,
        "u_turn_move": spec.u_turn_move,
        "u_turn_attack": spec.u_turn_attack,
        "active_cooling": spec.active_cooling,
        "lead_the_target": spec.lead_the_target,
    }
    values.update(changes)
    return FaceSpec(**values)


def _move_signature(spec: FaceSpec) -> tuple[Any, ...]:
    return (
        spec.value,
        spec.defense_bonus,
        spec.movement_disabled,
        spec.warp_destination,
        spec.double_turn_right,
        spec.active_cooling,
    )


def _text_entries(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if value == ():
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(entry, str) and entry for entry in value):
        return tuple(value)
    raise ValueError("Card text fields must be a string or a list of strings.")


def _split_alternatives(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s+or\s+|\s*/\s*", text, flags=re.IGNORECASE) if part.strip()]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower().replace(" then ", " then "))


def _english_orientation_options(text: str, field: str) -> tuple[str, ...]:
    options = []
    for part in re.split(r"\s*,\s*|\s+or\s+", text):
        normalized = _normalize_text(part).replace(" ", "_")
        aliases = {
            "turn_left": "turn_left",
            "left": "turn_left",
            "turn_right": "turn_right",
            "right": "turn_right",
            "forward": "forward",
            "slip_right": "slip_right",
            "slip_left": "slip_left",
            "u-turn_move": "u_turn_move",
            "u-turn_attack": "u_turn_attack",
        }
        option = aliases.get(normalized, normalized)
        if option not in _KNOWN_ORIENTATIONS:
            raise ValueError(f"{field} has unknown orientation choice: {part}")
        options.append(option)
    if not options:
        raise ValueError(f"{field} choices must list at least one orientation.")
    return tuple(options)


def _desperate_face(data: Any, source: str) -> DesperateFace | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError(f"{source}.desperate_face must be a table.")

    warp_destination = data.get("warp_destination")
    if warp_destination is not None:
        warp_destination = _str(warp_destination, f"{source}.desperate_face.warp_destination")
        if warp_destination not in _KNOWN_WARP_DESTINATIONS:
            raise ValueError(f"{source}.desperate_face.warp_destination is unknown: {warp_destination}")

    return DesperateFace(
        family=_family(data.get("family"), f"{source}.desperate_face.family"),
        value=_int(data.get("value", 0), f"{source}.desperate_face.value"),
        base_damage=_int(data.get("base_damage", 1), f"{source}.desperate_face.base_damage"),
        orientation_options=_orientation_options(
            data.get("orientation_options", ("forward",)),
            f"{source}.desperate_face.orientation_options",
        ),
        requires_target=_bool(data.get("requires_target", False), f"{source}.desperate_face.requires_target"),
        aim_bonus=_int(data.get("aim_bonus", 0), f"{source}.desperate_face.aim_bonus"),
        damage_bonus=_int(data.get("damage_bonus", 0), f"{source}.desperate_face.damage_bonus"),
        defense_bonus=_int(data.get("defense_bonus", 0), f"{source}.desperate_face.defense_bonus"),
        always_hits=_bool(data.get("always_hits", False), f"{source}.desperate_face.always_hits"),
        movement_disabled=_bool(data.get("movement_disabled", False), f"{source}.desperate_face.movement_disabled"),
        warp_destination=warp_destination,
        max_range=_optional_int(data.get("max_range"), f"{source}.desperate_face.max_range"),
        fixed_defense_threshold=_optional_int(
            data.get("fixed_defense_threshold"),
            f"{source}.desperate_face.fixed_defense_threshold",
        ),
        attacks_all=_bool(data.get("attacks_all", False), f"{source}.desperate_face.attacks_all"),
        side_slip_direction=_optional_str(data.get("side_slip_direction"), f"{source}.desperate_face.side_slip_direction"),
        double_turn_right=_bool(data.get("double_turn_right", False), f"{source}.desperate_face.double_turn_right"),
        u_turn_move=_bool(data.get("u_turn_move", False), f"{source}.desperate_face.u_turn_move"),
        u_turn_attack=_bool(data.get("u_turn_attack", False), f"{source}.desperate_face.u_turn_attack"),
        active_cooling=_bool(data.get("active_cooling", False), f"{source}.desperate_face.active_cooling"),
        lead_the_target=_bool(data.get("lead_the_target", False), f"{source}.desperate_face.lead_the_target"),
    )


def _card_map(cards: tuple[Card, ...], source: str) -> dict[str, Card]:
    mapped: dict[str, Card] = {}
    for card in cards:
        if card.id in mapped:
            raise ValueError(f"Duplicate card id in {source}: {card.id}")
        mapped[card.id] = card
    return mapped


def _validate_catalog(catalog: DeckCatalog) -> None:
    for card in catalog.base_cards:
        if not card.is_base:
            raise ValueError(f"Base deck card must have is_base=True: {card.id}")
        _validate_card(card)
    for card in catalog.desperation_cards:
        if card.is_base:
            raise ValueError(f"Desperation card must have is_base=False: {card.id}")
        _validate_card(card)
    for card in catalog.card_map.values():
        _smoke_test_card_effects(card)


def _validate_card(card: Card) -> None:
    if card.value < 0:
        raise ValueError(f"Card value cannot be negative: {card.id}")
    if card.no_basic_face and card.desperate_face is None:
        raise ValueError(f"Card with no basic face needs a desperate face: {card.id}")
    if card.desperate_face and card.desperate_face.base_damage < 0:
        raise ValueError(f"Desperate face base_damage cannot be negative: {card.id}")
    if card.desperate_face and card.desperate_face.side_slip_direction not in (None, "right", "left"):
        raise ValueError(f"Unsupported side_slip_direction on {card.id}: {card.desperate_face.side_slip_direction}")


def _smoke_test_card_effects(card: Card) -> None:
    if card.is_hybrid:
        interpret_card(card, OrderCardSelection(card.id, mode="move"), SealMode.SEALED)
        interpret_card(card, OrderCardSelection(card.id, mode="attack"), SealMode.SEALED)
    else:
        interpret_card(card, OrderCardSelection(card.id), SealMode.SEALED)
    if card.desperate_face is not None:
        orientation = card.desperate_face.orientation_options[0]
        interpret_card(
            card,
            OrderCardSelection(
                card.id,
                face="desperate",
                orientation=orientation,
                mode="move" if card.desperate_face.family == CardFamily.HYBRID else None,
            ),
            SealMode.SEALED,
        )
        if card.desperate_face.family == CardFamily.HYBRID:
            interpret_card(
                card,
                OrderCardSelection(card.id, face="desperate", mode="attack"),
                SealMode.SEALED,
            )


def _required_str(data: dict[str, Any], key: str, source: str) -> str:
    return _str(data.get(key), f"{source}.{key}")


def _str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string.")
    return value


def _optional_str(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _str(value, field)


def _int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer.")
    return value


def _optional_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    return _int(value, field)


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean.")
    return value


def _family(value: Any, field: str) -> CardFamily:
    try:
        return CardFamily(_str(value, field))
    except ValueError as exc:
        raise ValueError(f"{field} must be one of: move, attack, hybrid.") from exc


def _orientation_options(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"{field} must be a non-empty list.")
    options: list[str] = []
    for index, option in enumerate(value, start=1):
        option = _str(option, f"{field}[{index}]")
        if option not in _KNOWN_ORIENTATIONS:
            raise ValueError(f"{field}[{index}] is unknown: {option}")
        options.append(option)
    return tuple(options)
