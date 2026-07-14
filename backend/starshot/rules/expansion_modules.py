from __future__ import annotations

from importlib import import_module
from typing import Protocol

from starshot.rules.models import GameState


class ExpansionModule(Protocol):
    EXPANSION_ID: str


_MODULES = {
    "star_breach": "starshot.rules.star_breach_engine",
    "star_command": "starshot.rules.star_command_engine",
}


def installed_expansion_ids() -> set[str]:
    return set(_MODULES)


def expansion_module(expansion_id: str) -> ExpansionModule:
    try:
        module_path = _MODULES[expansion_id]
    except KeyError as exc:
        raise ValueError(f"Unknown expansion: {expansion_id}") from exc
    return import_module(module_path)


def active_expansion_modules(state: GameState) -> list[ExpansionModule]:
    return [expansion_module(expansion_id) for expansion_id in state.active_expansions if expansion_id in _MODULES]
