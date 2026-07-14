"""StarBreach cooperative expansion: scenario data and boss-ship geometry.

Scenario 1 — Bauble Breacher.  All coordinates in this module are boss-local
axial hexes with the Breacher Core at (0, 0); the boss is placed on the board
at (anchor_q, anchor_r) and every hull hex is anchor + local.

The layout is a code translation of docs/rules/starbreach_boss_scenario_01.jpg:
a radius-3 central body, plus a port wing (LC1/LC2 firing computers) and a
starboard wing (RC1/RC2), shield generators across the bow, and four fuel
tanks (E1-E4) along the stern.
"""

from __future__ import annotations

from dataclasses import dataclass


EXPANSION_ID = "star_breach"
SCENARIO_ID = "bauble_breacher"

BOSS_ANCHOR = (0, -9)
SHIELD_ARC_HP = 3
GLANCING_BLOW_ROLL = 1
DAMAGE_LANE_ROLLS = tuple(range(2, 9))  # seven lanes, d8 rolls 2-8

AREAS = ("forward", "port", "rear", "starboard")

HUNTER_KILLER_HP = 3
HUNTER_KILLER_MOVE = 2
HUNTER_KILLER_AIM = 1
TANK_PROXIMITY_JAMMER_RANGE = 3

# Progress-track spaces that unlock each Standard/Boss tier slot.
TIER_PROGRESS = {1: 2, 2: 4, 3: 6, 4: 8, 5: 10, 6: 12}

PROGRESS_PER_PREY_HIT = 1
PROGRESS_PER_PREY_KILL = 3


@dataclass(frozen=True, slots=True)
class StarBreachRole:
    id: str
    name: str
    text: str


ROLES: tuple[StarBreachRole, ...] = (
    StarBreachRole(
        "treasure_hunter",
        "Treasure Hunter",
        "No Overdrive draw penalty on Move-only orders. When this player collects a Bauble, every player draws one bonus card.",
    ),
    StarBreachRole(
        "tank",
        "Tank",
        "Starts with one extra Shield Charge. Proximity Jammer: enemies within 3 hexes target the Tank; enemy attacks against the Tank roll one fewer die.",
    ),
    StarBreachRole(
        "engineer",
        "Engineer",
        "Draws two extra cards. Attack orders may target allies as repairs: 1d6, a hit restores one HP; each ship repaired at most once per action.",
    ),
    StarBreachRole(
        "fighting_ace",
        "Fighting Ace",
        "Each attack: one extra attack die against fleet craft, or shifts the Boss Damage Lane roll by ±1. No Overdrive penalty on Attack-only orders.",
    ),
)

ROLES_BY_ID = {role.id: role for role in ROLES}

# First player is The Prey; roles deal round-robin so every role is in play.
ROLE_ASSIGN_ORDER = ("treasure_hunter", "tank", "fighting_ace", "engineer")


@dataclass(frozen=True, slots=True)
class BossComponent:
    id: str
    name: str
    component_type: str
    q: int
    r: int
    # Shield arcs this generator powers (shield generators only).
    shield_arcs: tuple[str, ...] = ()
    # Boss action phase whose slot this component drives (computers/tanks only).
    linked_phase: str | None = None


BOSS_COMPONENTS: tuple[BossComponent, ...] = (
    BossComponent("sg_left", "Shield Generator L", "shield_generator", -2, -1, shield_arcs=("port",)),
    BossComponent("sg_center", "Shield Generator C", "shield_generator", 0, -2, shield_arcs=("forward", "rear")),
    BossComponent("sg_right", "Shield Generator R", "shield_generator", 2, -3, shield_arcs=("starboard",)),
    BossComponent("fc_a", "Firing Computer LC1", "firing_computer", -5, 1, linked_phase="0.5"),
    BossComponent("fc_b", "Firing Computer LC2", "firing_computer", -5, 2, linked_phase="0.5"),
    BossComponent("fc_c", "Firing Computer RC1", "firing_computer", 5, -4, linked_phase="3.5"),
    BossComponent("fc_d", "Firing Computer RC2", "firing_computer", 5, -3, linked_phase="3.5"),
    BossComponent("fuel_a", "Fuel Tank E1", "fuel_tank", -2, 3, linked_phase="1.5"),
    BossComponent("fuel_b", "Fuel Tank E2", "fuel_tank", -1, 3, linked_phase="1.5"),
    BossComponent("fuel_c", "Fuel Tank E3", "fuel_tank", 1, 2, linked_phase="2.5"),
    BossComponent("fuel_d", "Fuel Tank E4", "fuel_tank", 2, 1, linked_phase="2.5"),
    BossComponent("core", "Breacher Core", "core", 0, 0),
)

BOSS_COMPONENT_BY_ID = {component.id: component for component in BOSS_COMPONENTS}
BOSS_COMPONENT_BY_HEX = {(component.q, component.r): component for component in BOSS_COMPONENTS}


def _hex_disk(center_q: int, center_r: int, radius: int) -> set[tuple[int, int]]:
    hexes: set[tuple[int, int]] = set()
    for dq in range(-radius, radius + 1):
        dr_min = max(-radius, -dq - radius)
        dr_max = min(radius, -dq + radius)
        for dr in range(dr_min, dr_max + 1):
            hexes.add((center_q + dq, center_r + dr))
    return hexes


# Central body plus the two cannon wings.
BOSS_FOOTPRINT: tuple[tuple[int, int], ...] = tuple(
    sorted(_hex_disk(0, 0, 3) | _hex_disk(-5, 2, 1) | _hex_disk(5, -3, 1))
)
BOSS_FOOTPRINT_SET = frozenset(BOSS_FOOTPRINT)


def region_of_hex(q: int, r: int) -> str:
    """Which of the four functional regions a boss-local hull hex belongs to."""
    if q <= -3:
        return "port"
    if q >= 3:
        return "starboard"
    return "forward" if (2 * r + q) < 0 else "rear"


def _build_damage_lanes() -> dict[str, dict[int, tuple[tuple[int, int], ...]]]:
    lanes: dict[str, dict[int, tuple[tuple[int, int], ...]]] = {area: {} for area in AREAS}
    for roll in DAMAGE_LANE_ROLLS:
        line = roll - 5  # -3 .. 3
        column = sorted((hex_ for hex_ in BOSS_FOOTPRINT if hex_[0] == line), key=lambda h: h[1])
        row = sorted((hex_ for hex_ in BOSS_FOOTPRINT if hex_[1] == line), key=lambda h: h[0])
        diagonal = sorted((hex_ for hex_ in BOSS_FOOTPRINT if hex_[0] + hex_[1] == line), key=lambda h: -h[0])
        lanes["forward"][roll] = tuple(column)                     # bow -> stern
        lanes["rear"][roll] = tuple(reversed(column))              # stern -> bow
        lanes["port"][roll] = tuple(row)                           # port -> starboard
        lanes["starboard"][roll] = tuple(diagonal)                 # starboard -> port
    return lanes


BOSS_DAMAGE_LANES = _build_damage_lanes()

# Boss action phases in resolution order.  Each slot is ("base"|"component"|"tier", detail).
BOSS_PHASES: tuple[tuple[str, str, tuple[tuple[str, object], ...]], ...] = (
    ("0.5", "attack", (("base", None), ("component", "fc_a"), ("component", "fc_b"), ("tier", 1))),
    ("1.5", "move", (("base", None), ("component", "fuel_a"), ("component", "fuel_b"), ("tier", 2))),
    ("2.5", "move", (("base", None), ("component", "fuel_c"), ("component", "fuel_d"), ("tier", 3))),
    ("3.5", "attack", (("base", None), ("component", "fc_c"), ("component", "fc_d"), ("tier", 4))),
    ("starbreach", "attack", (("tier", 5), ("tier", 6))),
)

BOSS_PHASES_BY_PLAYER_ACTION = {1: "0.5", 2: "1.5", 3: "2.5"}

# Hunter-Killer fleet for the Bauble Breacher scenario (boss-local start offsets).
FLEET_SCENARIO: tuple[tuple[str, str, str, tuple[int, int]], ...] = (
    ("hk_blue", "hunter_killer", "blue", (-7, 4)),
    ("hk_green", "hunter_killer", "green", (0, 5)),
    ("hk_yellow", "hunter_killer", "yellow", (7, -3)),
)


def unlocked_tiers(progress: int) -> tuple[int, ...]:
    return tuple(tier for tier, threshold in TIER_PROGRESS.items() if progress >= threshold)


def destroyed_component_ids(destroyed_hexes: set[tuple[int, int]]) -> set[str]:
    return {
        component.id
        for component in BOSS_COMPONENTS
        if (component.q, component.r) in destroyed_hexes
    }


def intact_hull_hexes(state_destroyed: set[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    return tuple(hex_ for hex_ in BOSS_FOOTPRINT if hex_ not in state_destroyed)


def first_intact_lane_hex(
    area: str,
    lane_roll: int,
    destroyed_hexes: set[tuple[int, int]],
) -> tuple[int, int] | None:
    for hex_ in BOSS_DAMAGE_LANES[area].get(lane_roll, ()):
        if hex_ not in destroyed_hexes:
            return hex_
    return None


def role_to_dict(role: StarBreachRole) -> dict:
    return {"id": role.id, "name": role.name, "text": role.text}


def boss_layout_to_dict() -> dict:
    return {
        "footprint": [
            {"q": q, "r": r, "area": region_of_hex(q, r)} for q, r in BOSS_FOOTPRINT
        ],
        "components": [
            {
                "id": component.id,
                "name": component.name,
                "type": component.component_type,
                "q": component.q,
                "r": component.r,
                "shield_arcs": list(component.shield_arcs),
                "linked_phase": component.linked_phase,
            }
            for component in BOSS_COMPONENTS
        ],
        "areas": list(AREAS),
        "damage_lanes": {
            area: {str(roll): [list(hex_) for hex_ in lane] for roll, lane in lanes.items()}
            for area, lanes in BOSS_DAMAGE_LANES.items()
        },
    }
