"""Compile player ship designs into playable layout specs.

A ship design (see ``starshot.v2.ship_designs``) is a plain JSON document:
tiles on a radius-2 hex grid plus a shield-charge count and a base card draw.
This module turns one into the "layout spec" dict stored on
``ShipState.layout``: named components plus the auto-generated d12 damage-lane
table. The spec lives in game state, so design edits never affect games in
flight.

Damage lanes are derived from the core position (ships face "up", toward
decreasing r, exactly like the printed base ship board):

- lanes 1/7:  the hex column through the core, entered from aft / from fore
- lanes 4/12: the hex row through the core, entered from port / starboard
- lanes 2/10: the hex diagonal through the core, both directions
- lanes 5/11: the row through the hex directly forward of the core
- lanes 3/9:  the diagonal through that forward hex, both directions
- lanes 6/8:  the columns adjacent to the core, entered from the fore side

Applied to the base ship layout this reproduces its printed lane table
exactly (see tests/test_player_ships.py).

Point costs (PLAYER_SHIP_POINT_BUDGET = 19):

- 1 point per shield charge
- 1 point per base card drawn
- 1 point per non-core tile in a damage lane that contains the core
  (i.e. tiles on the three axes through the core — the core's armor)
- 1 point per Signal Jammer (+2 defense while intact)
- 1 point per Targeting Sensors (+2 Aim while intact)

The base ship prices out at exactly 19: 2 shields + 5 draw + 12 armor tiles.
"""

from __future__ import annotations

PLAYER_SHIP_POINT_BUDGET = 19
PLAYER_SHIP_GRID_RADIUS = 2  # hex diameter 5 → 19 cells
PLAYER_SHIP_MAX_TILES = 15
MIN_SHIELDS, MAX_SHIELDS = 0, 3
MIN_DRAW, MAX_DRAW = 3, 6
MAX_SIGNAL_JAMMERS = 2
MAX_TARGETING_SENSORS = 2
REQUIRED_LIFE_SUPPORTS = 2

# Designer tile types. "core" compiles to the "bridge" component type so all
# existing engine rules (connectivity, ship death, captain effects) apply.
PLAYER_TILE_TYPES = (
    "weapon",
    "crew",
    "engine",
    "bay",
    "shield_generator",
    "life_support",
    "core",
    "signal_jammer",
    "targeting_sensors",
)

# Passive combat components (1 point each, optional).
SIGNAL_JAMMER_TYPE = "signal_jammer"
TARGETING_SENSORS_TYPE = "targeting_sensors"
SIGNAL_JAMMER_DEFENSE_BONUS = 2
TARGETING_SENSORS_AIM_BONUS = 2

_COMPONENT_TYPE_FOR_TILE = {"core": "bridge"}
_COMPONENT_NAMES = {
    "weapon": "Ion Cannon",
    "crew": "Crew Quarters",
    "engine": "Engine",
    "bay": "Docking Bay",
    "shield_generator": "Shield Generator",
    "life_support": "Life Support",
    "core": "Command Bridge",
    "signal_jammer": "Signal Jammer",
    "targeting_sensors": "Targeting Sensors",
}


def _sorted_tiles(design: dict) -> list[dict]:
    """Deterministic tile order (top-to-bottom, port-to-starboard) so
    component ids stay stable no matter the placement order."""
    return sorted(design.get("tiles", []), key=lambda tile: (tile["r"], tile["q"]))


def core_tile(design: dict) -> dict | None:
    cores = [tile for tile in design.get("tiles", []) if tile["type"] == "core"]
    return cores[0] if len(cores) == 1 else None


def _line(tiles_by_coord: dict[tuple[int, int], str], selector, order_key, reverse: bool) -> tuple[str, ...]:
    coords = [coord for coord in tiles_by_coord if selector(coord)]
    coords.sort(key=order_key, reverse=reverse)
    return tuple(tiles_by_coord[coord] for coord in coords)


def generate_damage_lanes(design: dict, component_ids: dict[tuple[int, int], str]) -> dict[int, tuple[str, ...]]:
    """The d12 lane table for a design (see module docstring). Lanes over
    empty lines are empty: those rolls simply miss."""
    core = core_tile(design)
    if core is None:
        return {roll: () for roll in range(1, 13)}
    cq, cr = core["q"], core["r"]

    def col(c):
        return lambda coord: coord[0] == c

    def row(c):
        return lambda coord: coord[1] == c

    def diag(c):
        return lambda coord: coord[0] + coord[1] == c

    by_r = lambda coord: coord[1]
    by_q = lambda coord: coord[0]

    return {
        # through the core
        1: _line(component_ids, col(cq), by_r, reverse=True),        # aft → fore
        7: _line(component_ids, col(cq), by_r, reverse=False),       # fore → aft
        4: _line(component_ids, row(cr), by_q, reverse=False),       # port → starboard
        12: _line(component_ids, row(cr), by_q, reverse=True),       # starboard → port
        2: _line(component_ids, diag(cq + cr), by_q, reverse=False),
        10: _line(component_ids, diag(cq + cr), by_q, reverse=True),
        # through the hex directly forward of the core
        5: _line(component_ids, row(cr - 1), by_q, reverse=False),
        11: _line(component_ids, row(cr - 1), by_q, reverse=True),
        3: _line(component_ids, diag(cq + cr - 1), by_q, reverse=False),
        9: _line(component_ids, diag(cq + cr - 1), by_q, reverse=True),
        # the flanking columns, entered from the fore side
        6: _line(component_ids, col(cq - 1), by_r, reverse=False),
        8: _line(component_ids, col(cq + 1), by_r, reverse=False),
    }


def core_armor_tile_count(design: dict) -> int:
    """Non-core tiles that sit in a damage lane containing the core: the
    tiles on the three hex axes through the core. Each costs 1 point."""
    core = core_tile(design)
    if core is None:
        return 0
    cq, cr = core["q"], core["r"]
    count = 0
    for tile in design.get("tiles", []):
        q, r = tile["q"], tile["r"]
        if (q, r) == (cq, cr):
            continue
        if q == cq or r == cr or q + r == cq + cr:
            count += 1
    return count


def points_breakdown(design: dict) -> dict:
    tiles = design.get("tiles", [])
    breakdown = {
        "shields": int(design.get("shields", 0)),
        "draw": int(design.get("draw", MIN_DRAW)),
        "core_armor": core_armor_tile_count(design),
        "signal_jammers": sum(1 for tile in tiles if tile["type"] == SIGNAL_JAMMER_TYPE),
        "targeting_sensors": sum(1 for tile in tiles if tile["type"] == TARGETING_SENSORS_TYPE),
    }
    breakdown["total"] = sum(breakdown.values())
    breakdown["budget"] = PLAYER_SHIP_POINT_BUDGET
    return breakdown


def component_entries(design: dict) -> list[dict]:
    """Stable component list (id, name, type, q, r) for a design's tiles.
    Components of the same type are numbered in board order."""
    counts: dict[str, int] = {}
    totals: dict[str, int] = {}
    for tile in design.get("tiles", []):
        totals[tile["type"]] = totals.get(tile["type"], 0) + 1
    entries = []
    for tile in _sorted_tiles(design):
        tile_type = tile["type"]
        counts[tile_type] = counts.get(tile_type, 0) + 1
        base_name = _COMPONENT_NAMES.get(tile_type, tile_type.replace("_", " ").title())
        name = base_name if totals[tile_type] == 1 else f"{base_name} {counts[tile_type]}"
        entries.append(
            {
                "id": f"{tile_type}_{counts[tile_type]}",
                "name": name,
                "type": _COMPONENT_TYPE_FOR_TILE.get(tile_type, tile_type),
                "q": tile["q"],
                "r": tile["r"],
            }
        )
    return entries


def compile_layout_spec(design: dict) -> dict:
    """The layout spec stored on ShipState.layout for a game using this
    design. The design must already be normalized (v2.ship_designs)."""
    entries = component_entries(design)
    component_ids = {(entry["q"], entry["r"]): entry["id"] for entry in entries}
    lanes = generate_damage_lanes(design, component_ids)
    return {
        "layout_id": f"design_{design.get('id', 'custom')}",
        "name": design.get("name", "Custom Ship"),
        "components": entries,
        "damage_lanes": {str(roll): list(ids) for roll, ids in lanes.items()},
        "max_shields": int(design.get("shields", 0)),
        "base_draw": int(design.get("draw", MIN_DRAW)),
    }
