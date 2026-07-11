from __future__ import annotations

import os
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

    cards: list[Card] = []
    for index, card_data in enumerate(cards_data, start=1):
        if not isinstance(card_data, dict):
            raise ValueError(f"{path.name} card #{index} must be a table.")
        cards.extend(_expand_card(card_data, is_base=is_base, source=f"{path.name} card #{index}"))
    return cards


def _expand_card(data: dict[str, Any], *, is_base: bool, source: str) -> list[Card]:
    prototype_id = _required_str(data, "id", source)
    name = _required_str(data, "name", source)
    family = _family(data.get("family"), f"{source}.family")
    value = _int(data.get("value", 0), f"{source}.value")
    copies = data.get("copies", [prototype_id])
    if not isinstance(copies, list) or not copies:
        raise ValueError(f"{source}.copies must be a non-empty list of card ids.")

    orientation_options = _orientation_options(
        data.get("orientation_options", ("forward", "turn_left", "turn_right")),
        f"{source}.orientation_options",
    )
    requires_target = _bool(data.get("requires_target", True), f"{source}.requires_target")
    is_hybrid = _bool(data.get("is_hybrid", False), f"{source}.is_hybrid")
    no_basic_face = _bool(data.get("no_basic_face", False), f"{source}.no_basic_face")
    desperate_face = _desperate_face(data.get("desperate_face"), source)

    cards: list[Card] = []
    for copy_index, copy_id in enumerate(copies, start=1):
        if not isinstance(copy_id, str) or not copy_id:
            raise ValueError(f"{source}.copies[{copy_index}] must be a non-empty string.")
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
            OrderCardSelection(card.id, face="desperate", orientation=orientation),
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
