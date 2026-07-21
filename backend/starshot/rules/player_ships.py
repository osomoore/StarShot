"""Compile player ship designs into playable layout specs.

A ship design (see ``starshot.v2.ship_designs``) is a plain JSON document:
tiles on a radius-5 hex grid, six player-placed secondary damage lanes, and
one chosen special upgrade. This module turns one into the "layout spec"
dict stored on ``ShipState.layout``: named components, the d12 damage-lane
table, the ship's starting deck composition, and its flat combat bonuses.
The spec lives in game state, so design edits never affect games in flight.

Damage lanes (ships face "up", toward decreasing r):

- The six PRIMARY lanes pass through the Core and are auto-generated from
  its position: rolls 1/7 (the Core's hex column, aft/fore), 4/12 (its row,
  port/starboard), and 2/10 (its diagonal, both directions). At most
  ``primary_lane_limit`` non-core components may sit on these lanes
  (default 10 — admin configurable).
- The six SECONDARY lanes (rolls 3, 5, 6, 8, 9, 11) are placed by the
  player: each is a full grid line plus a travel direction that must NOT
  pass through the Core, and must be placed so that shooting fully through
  it (destroying every component in the lane) separates at least
  ``secondary_lane_min_severed`` surviving non-core components from the
  Core (default 2 — admin configurable).

The starting deck is chosen by placing Engine / Double Engine / Cannon /
Double Cannon components against ``core_points`` Core Component points
(default 15):

- Engine        (1 point) adds a Move 1 card
- Double Engine (2 points) adds a Move 2 card
- Cannon        (1 point) adds a Targeted Attack Aim +1 card
- Double Cannon (2 points) adds a Targeted Attack Aim +2 card

Exactly ``DECK_SIZE`` (10) engine + cannon components must be placed, so
every designed ship flies a 10-card deck. The other required tiles — 1 Core,
2 Life Supports, 1 Bone Room, 1 Docking Bay — bring the ship to 15 tiles.
If the admin raises ``max_tiles`` above 15, the extra tiles are Structure.

Each ship also picks exactly one special upgrade:

- "shield":  +1 shield charge (3 total)
- "draw":    +1 card drawn per round (6 total)
- "defense": flat Defense bonus on all actions (default +1, admin config)
- "aim":     flat Aim bonus on all actions (default +1, admin config)
- "points":  +2 Core Component points (17 to spend)
"""

from __future__ import annotations

PLAYER_SHIP_GRID_RADIUS = 5  # hex radius 5 → 91 cells

# The five required non-deck tiles: 1 Core + 2 Life Supports + 1 Bone Room +
# 1 Docking Bay. With the 10 deck components that is the base 15-tile ship.
REQUIRED_LIFE_SUPPORTS = 2
DECK_SIZE = 10
BASE_TILE_TOTAL = 15

# Every captain starts StarDock with this finite common-parts palette. Earned
# campaign components are a separate inventory and may replace any of the ten
# engine/cannon slots, but common parts cannot exceed these quantities.
BASE_PALETTE_LIMITS = {
    "core": 1,
    "life_support": 2,
    "bone_room": 1,
    "docking_bay": 1,
    "double_cannon": 2,
    "cannon": 3,
    "double_engine": 3,
    "engine": 2,
}

BASE_SHIELDS = 2
BASE_DRAW = 5
UPGRADE_EXTRA_POINTS = 2

PRIMARY_LANE_ROLLS = (1, 2, 4, 7, 10, 12)
SECONDARY_LANE_ROLLS = (3, 5, 6, 8, 9, 11)
PRIMARY_LANE_DIRS = {1: 2, 7: 5, 4: 0, 12: 3, 2: 1, 10: 4}

# Admin-configurable StarDock rules. The v2 layer injects overrides into a
# design's "config" key (never persisted with the design); the rules layer
# stays pure and deterministic because the compiled spec is stored in state.
DEFAULT_STARDOCK_CONFIG = {
    "max_tiles": BASE_TILE_TOTAL,          # admin may raise above 15
    "primary_lane_limit": 10,              # non-core components on primary lanes
    "secondary_lane_min_severed": 2,       # components a secondary lane must sever
    "core_points": 15,                     # Core Component points for the deck
    "upgrade_defense_bonus": 1,            # flat Defense from the "defense" upgrade
    "upgrade_aim_bonus": 1,                # flat Aim from the "aim" upgrade
}

# Deck-defining tile types and their Core Component point costs / cards.
CORE_TILE_COSTS = {"engine": 1, "double_engine": 2, "cannon": 1, "double_cannon": 2}
BONUS_TILE_TYPE = "bonus_component"
DECK_CARD_FOR_TILE = {
    "engine": "move_1",
    "double_engine": "move_2",
    "cannon": "aim_1",
    "double_cannon": "aim_2",
}
DECK_CARD_KINDS = ("move_1", "move_2", "aim_1", "aim_2")

PLAYER_TILE_TYPES = (
    "engine",
    "double_engine",
    "cannon",
    "double_cannon",
    "bone_room",
    "docking_bay",
    "life_support",
    "core",
    "structure",
    BONUS_TILE_TYPE,
)

# Pre-StarDock-overhaul tile types: still normalized so old saved designs can
# be opened and edited, but they make a design not battle-ready.
LEGACY_TILE_TYPES = ("weapon", "crew", "bay", "shield_generator", "signal_jammer", "targeting_sensors")

SHIP_UPGRADES = ("shield", "draw", "defense", "aim", "points")

# Legacy passive components (kept so pre-overhaul games in flight and their
# engine hooks keep working; no longer placeable in the designer).
SIGNAL_JAMMER_TYPE = "signal_jammer"
TARGETING_SENSORS_TYPE = "targeting_sensors"
SIGNAL_JAMMER_DEFENSE_BONUS = 2
TARGETING_SENSORS_AIM_BONUS = 2

# Mirrors backend/starshot/rules/hex.py (and board.js).
AXIAL_DIRECTIONS = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))

# "core" compiles to the "bridge" component type so all existing engine rules
# (connectivity, ship death, captain effects) apply unchanged.
_COMPONENT_TYPE_FOR_TILE = {
    "core": "bridge",
    "cannon": "weapon",
    "double_cannon": "weapon",
    "double_engine": "engine",
    "bone_room": "crew",
    "docking_bay": "bay",
}
_COMPONENT_NAMES = {
    "engine": "Engine",
    "double_engine": "Double Engine",
    "cannon": "Cannon",
    "double_cannon": "Double Cannon",
    "bone_room": "Bone Room",
    "docking_bay": "Docking Bay",
    "life_support": "Life Support",
    "core": "Core",
    "structure": "Structure",
    # legacy
    "weapon": "Ion Cannon",
    "crew": "Crew Quarters",
    "bay": "Docking Bay",
    "shield_generator": "Shield Generator",
    "signal_jammer": "Signal Jammer",
    "targeting_sensors": "Targeting Sensors",
}


def stardock_config(design: dict | None = None) -> dict:
    """The StarDock rule numbers governing `design`: the defaults overlaid
    with any server-injected overrides on the design's "config" key."""
    config = dict(DEFAULT_STARDOCK_CONFIG)
    overrides = (design or {}).get("config") or {}
    for key in config:
        if key in overrides:
            try:
                config[key] = int(overrides[key])
            except (TypeError, ValueError):
                pass
    config["max_tiles"] = max(config["max_tiles"], BASE_TILE_TOTAL)
    for key in ("primary_lane_limit", "secondary_lane_min_severed", "upgrade_defense_bonus", "upgrade_aim_bonus"):
        config[key] = max(config[key], 0)
    config["core_points"] = max(config["core_points"], DECK_SIZE)
    return config


def grid_cells(radius: int = PLAYER_SHIP_GRID_RADIUS) -> list[tuple[int, int]]:
    return [
        (q, r)
        for q in range(-radius, radius + 1)
        for r in range(-radius, radius + 1)
        if abs(q + r) <= radius
    ]


def in_grid(q: int, r: int, radius: int = PLAYER_SHIP_GRID_RADIUS) -> bool:
    return abs(q) <= radius and abs(r) <= radius and abs(q + r) <= radius


def _sorted_tiles(design: dict) -> list[dict]:
    """Deterministic tile order (top-to-bottom, port-to-starboard) so
    component ids stay stable no matter the placement order."""
    return sorted(design.get("tiles", []), key=lambda tile: (tile["r"], tile["q"]))


def core_tile(design: dict) -> dict | None:
    cores = [tile for tile in design.get("tiles", []) if tile["type"] == "core"]
    return cores[0] if len(cores) == 1 else None


def on_primary_lane(q: int, r: int, core: dict) -> bool:
    """Whether (q, r) sits on one of the three axes through the Core."""
    cq, cr = core["q"], core["r"]
    return q == cq or r == cr or q + r == cq + cr


def primary_lane_tile_count(design: dict) -> int:
    """Non-core tiles on the primary damage lanes (the axes through the
    Core). Capped at the configured primary_lane_limit."""
    core = core_tile(design)
    if core is None:
        return 0
    return sum(
        1
        for tile in design.get("tiles", [])
        if (tile["q"], tile["r"]) != (core["q"], core["r"]) and on_primary_lane(tile["q"], tile["r"], core)
    )


def core_points_spent(design: dict) -> int:
    bonuses = design.get("bonus_components") or {}
    return sum(
        int((bonuses.get(tile.get("reward_id")) or {}).get("cost", 0))
        if tile["type"] == BONUS_TILE_TYPE else CORE_TILE_COSTS.get(tile["type"], 0)
        for tile in design.get("tiles", [])
    )


def core_points_budget(design: dict) -> int:
    config = stardock_config(design)
    return config["core_points"] + (UPGRADE_EXTRA_POINTS if design.get("upgrade") == "points" else 0)


def deck_counts(design: dict) -> dict[str, int]:
    """How many of each starting deck card the placed components grant."""
    counts = {kind: 0 for kind in DECK_CARD_KINDS}
    for tile in design.get("tiles", []):
        kind = DECK_CARD_FOR_TILE.get(tile["type"])
        if kind:
            counts[kind] += 1
    return counts


def deck_component_count(design: dict) -> int:
    return sum(1 for tile in design.get("tiles", []) if tile["type"] in CORE_TILE_COSTS or tile["type"] == BONUS_TILE_TYPE)


def bonus_card_ids(design: dict) -> list[str]:
    bonuses = design.get("bonus_components") or {}
    return [
        str(bonuses[tile["reward_id"]]["card_id"])
        for tile in design.get("tiles", [])
        if tile.get("type") == BONUS_TILE_TYPE and tile.get("reward_id") in bonuses
    ]


def bonus_cards(design: dict) -> list[dict]:
    """Compiled campaign cards contributed by placed reward components."""
    bonuses = design.get("bonus_components") or {}
    cards: list[dict] = []
    for tile in design.get("tiles", []):
        if tile.get("type") != BONUS_TILE_TYPE:
            continue
        bonus = bonuses.get(tile.get("reward_id")) or {}
        starting_cards = bonus.get("starting_cards")
        if isinstance(starting_cards, list):
            cards.extend(card for card in starting_cards if isinstance(card, dict))
    return cards


# ── lanes ───────────────────────────────────────────────────────────────────


def lane_cells(q: int, r: int, direction: int, radius: int = PLAYER_SHIP_GRID_RADIUS) -> list[tuple[int, int]]:
    """All grid cells on the line through (q, r) along AXIAL_DIRECTIONS
    [direction], ordered in travel order (entry cell first)."""
    dq, dr = AXIAL_DIRECTIONS[direction % 6]
    # walk backwards to the entry edge, then forward across the grid
    while in_grid(q - dq, r - dr, radius):
        q, r = q - dq, r - dr
    cells = []
    while in_grid(q, r, radius):
        cells.append((q, r))
        q, r = q + dq, r + dr
    return cells


def secondary_lanes(design: dict) -> dict[int, dict]:
    """The design's placed secondary lanes: {roll: {"q", "r", "dir"}}."""
    lanes = {}
    for key, value in (design.get("lanes") or {}).items():
        try:
            roll = int(key)
        except (TypeError, ValueError):
            continue
        if roll in SECONDARY_LANE_ROLLS and isinstance(value, dict):
            lanes[roll] = value
    return lanes


def secondary_lane_cells(design: dict) -> dict[int, list[tuple[int, int]]]:
    return {
        roll: lane_cells(int(lane["q"]), int(lane["r"]), int(lane["dir"]))
        for roll, lane in secondary_lanes(design).items()
    }


def _lane_key(cells: list[tuple[int, int]], direction: int) -> str:
    q, r = cells[0]
    return f"{q},{r}|{direction % 6}"


def primary_lane_id(direction: int) -> str:
    return f"p:{direction % 6}"


def secondary_lane_id(cells: list[tuple[int, int]], direction: int) -> str:
    return f"s:{_lane_key(cells, direction)}"


def lane_number(design: dict, lane_id: str, default_roll: int) -> int:
    try:
        number = int((design.get("lane_numbers") or {}).get(lane_id, default_roll))
    except (TypeError, ValueError):
        return default_roll
    return number if 1 <= number <= 12 else default_roll


def lane_severed_count(design: dict, cells: list[tuple[int, int]]) -> int:
    """How many surviving non-core components get separated from the Core
    when every component on `cells` is destroyed."""
    core = core_tile(design)
    if core is None:
        return 0
    core_coord = (core["q"], core["r"])
    lane_set = set(cells)
    if core_coord in lane_set:
        return 0
    remaining = {(tile["q"], tile["r"]) for tile in design.get("tiles", [])} - lane_set
    if core_coord not in remaining:
        return 0
    reached = {core_coord}
    frontier = [core_coord]
    while frontier:
        q, r = frontier.pop()
        for dq, dr in AXIAL_DIRECTIONS:
            neighbor = (q + dq, r + dr)
            if neighbor in remaining and neighbor not in reached:
                reached.add(neighbor)
                frontier.append(neighbor)
    return len(remaining) - len(reached)


def _line(tiles_by_coord: dict[tuple[int, int], str], selector, order_key, reverse: bool) -> tuple[str, ...]:
    coords = [coord for coord in tiles_by_coord if selector(coord)]
    coords.sort(key=order_key, reverse=reverse)
    return tuple(tiles_by_coord[coord] for coord in coords)


def _generate_default_damage_lanes(design: dict, component_ids: dict[tuple[int, int], str]) -> dict[int, tuple[str, ...]]:
    """The d12 lane table for a design: six auto primary lanes through the
    Core plus the player's six placed secondary lanes. Lanes over empty
    lines are empty: those rolls simply miss."""
    lanes: dict[int, tuple[str, ...]] = {roll: () for roll in range(1, 13)}
    core = core_tile(design)
    if core is not None:
        cq, cr = core["q"], core["r"]
        by_r = lambda coord: coord[1]
        by_q = lambda coord: coord[0]
        lanes[1] = _line(component_ids, lambda c: c[0] == cq, by_r, reverse=True)   # aft → fore
        lanes[7] = _line(component_ids, lambda c: c[0] == cq, by_r, reverse=False)  # fore → aft
        lanes[4] = _line(component_ids, lambda c: c[1] == cr, by_q, reverse=False)  # port → starboard
        lanes[12] = _line(component_ids, lambda c: c[1] == cr, by_q, reverse=True)  # starboard → port
        lanes[2] = _line(component_ids, lambda c: c[0] + c[1] == cq + cr, by_q, reverse=False)
        lanes[10] = _line(component_ids, lambda c: c[0] + c[1] == cq + cr, by_q, reverse=True)
    for roll, cells in secondary_lane_cells(design).items():
        lanes[roll] = tuple(component_ids[coord] for coord in cells if coord in component_ids)
    return lanes


def generate_damage_lanes(design: dict, component_ids: dict[tuple[int, int], str]) -> dict[int, tuple[str, ...]]:
    """The d12 lane table for a design, honoring optional StarDock lane_numbers."""
    lanes: dict[int, tuple[str, ...]] = {roll: () for roll in range(1, 13)}
    core = core_tile(design)
    if core is not None:
        cq, cr = core["q"], core["r"]
        by_r = lambda coord: coord[1]
        by_q = lambda coord: coord[0]
        primary_entries = (
            (1, 2, _line(component_ids, lambda c: c[0] == cq, by_r, reverse=True)),
            (7, 5, _line(component_ids, lambda c: c[0] == cq, by_r, reverse=False)),
            (4, 0, _line(component_ids, lambda c: c[1] == cr, by_q, reverse=False)),
            (12, 3, _line(component_ids, lambda c: c[1] == cr, by_q, reverse=True)),
            (2, 1, _line(component_ids, lambda c: c[0] + c[1] == cq + cr, by_q, reverse=False)),
            (10, 4, _line(component_ids, lambda c: c[0] + c[1] == cq + cr, by_q, reverse=True)),
        )
        for default_roll, direction, components in primary_entries:
            roll = lane_number(design, primary_lane_id(direction), default_roll)
            lanes[roll] = components
    for default_roll, lane in secondary_lanes(design).items():
        direction = int(lane["dir"])
        cells = lane_cells(int(lane["q"]), int(lane["r"]), direction)
        roll = lane_number(design, secondary_lane_id(cells, direction), default_roll)
        lanes[roll] = tuple(component_ids[coord] for coord in cells if coord in component_ids)
    return lanes


# ── summary for UI and validation ───────────────────────────────────────────


def points_breakdown(design: dict) -> dict:
    """Core Component point spend and deck summary for the designer UI."""
    counts = deck_counts(design)
    breakdown = {
        "core_points_spent": core_points_spent(design),
        "core_points_budget": core_points_budget(design),
        "deck_components": deck_component_count(design),
        "deck_size_required": DECK_SIZE,
        "deck": counts,
        "primary_lane_tiles": primary_lane_tile_count(design),
        "primary_lane_limit": stardock_config(design)["primary_lane_limit"],
    }
    breakdown["total"] = breakdown["core_points_spent"]
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
        bonus = (design.get("bonus_components") or {}).get(tile.get("reward_id"), {})
        base_name = bonus.get("name") or _COMPONENT_NAMES.get(tile_type, tile_type.replace("_", " ").title())
        name = base_name if totals[tile_type] == 1 else f"{base_name} {counts[tile_type]}"
        entries.append(
            {
                "id": f"{tile_type}_{counts[tile_type]}",
                "name": name,
                "type": bonus.get("component_type") or _COMPONENT_TYPE_FOR_TILE.get(tile_type, tile_type),
                "q": tile["q"],
                "r": tile["r"],
            }
        )
    return entries


def compile_layout_spec(design: dict) -> dict:
    """The layout spec stored on ShipState.layout for a game using this
    design. The design must already be normalized (v2.ship_designs)."""
    config = stardock_config(design)
    upgrade = design.get("upgrade")
    entries = component_entries(design)
    component_ids = {(entry["q"], entry["r"]): entry["id"] for entry in entries}
    lanes = generate_damage_lanes(design, component_ids)
    return {
        "layout_id": f"design_{design.get('id', 'custom')}",
        "name": design.get("name", "Custom Ship"),
        "components": entries,
        "damage_lanes": {str(roll): list(ids) for roll, ids in lanes.items()},
        "max_shields": BASE_SHIELDS + (1 if upgrade == "shield" else 0),
        "base_draw": BASE_DRAW + (1 if upgrade == "draw" else 0),
        "aim_bonus": config["upgrade_aim_bonus"] if upgrade == "aim" else 0,
        "defense_bonus": config["upgrade_defense_bonus"] if upgrade == "defense" else 0,
        "upgrade": upgrade,
        "deck": deck_counts(design),
        "bonus_card_ids": bonus_card_ids(design),
        "bonus_cards": bonus_cards(design),
    }
