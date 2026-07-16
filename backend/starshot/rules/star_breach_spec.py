"""Boss specs: one JSON-serializable document describing a StarBreach boss.

The engine reads all boss data (hull, shield areas, damage lanes, action
phases, fleet, progression) through the accessors in this module instead of
the ``star_breach`` constants directly. Two sources exist:

- ``default_spec()`` mirrors the stock Bauble Breacher scenario from
  ``star_breach.py`` exactly; ``StarBreachState.boss_spec is None`` means
  "use the default".
- ``spec_from_design(design)`` compiles a boss-designer document (the JSON
  saved by the admin Boss Ship Designer) into the same shape, so designed
  bosses are playable without touching the designer or the base scenario.

Specs are stored on ``StarBreachState.boss_spec`` and persisted with the
game, so later edits to a design never change games in flight. Everything in
a spec is plain JSON (string keys, lists for hexes) to survive round trips.
"""

from __future__ import annotations

from starshot.rules import star_breach as sb_data

_DIRECTIONS = sb_data._AXIAL_DIRECTIONS

# Start offsets from the boss nose for designed fleets (up to 6 craft).
_FLEET_OFFSETS = ((-7, 5), (0, 6), (7, -2), (-4, 7), (4, 3), (-2, -3))
_FLEET_COLORS = ("blue", "green", "yellow", "red", "purple", "orange")

_STACK_KEYS = ("0.5", "1.5", "2.5", "3.5", "starbreach")
_DEFAULT_STACK_KIND = {"0.5": "attack", "1.5": "move", "2.5": "move", "3.5": "attack", "starbreach": "attack"}


def _hex_key(q: int, r: int) -> str:
    return f"{q},{r}"


# ── the default (stock scenario) spec ───────────────────────────────────────


def default_spec() -> dict:
    """The Bauble Breacher scenario expressed as a spec. Behavior-identical
    to the module constants; built fresh so callers may not mutate it."""
    footprint = [list(hex_) for hex_ in sb_data.BOSS_FOOTPRINT]
    hex_area = {_hex_key(q, r): sb_data.region_of_hex(q, r) for q, r in sb_data.BOSS_FOOTPRINT}
    area_hexes: dict[str, list[list[int]]] = {area: [] for area in sb_data.AREAS}
    for q, r in sb_data.BOSS_FOOTPRINT:
        area_hexes[sb_data.region_of_hex(q, r)].append([q, r])
    generator_hex: dict[str, list[int] | None] = {area: None for area in sb_data.AREAS}
    for component in sb_data.BOSS_COMPONENTS:
        for area in component.shield_arcs:
            generator_hex[area] = [component.q, component.r]
    return {
        "source": "default",
        "name": "The StarBreacher",
        "footprint": footprint,
        "areas": list(sb_data.AREAS),
        "hex_area": hex_area,
        "area_hexes": area_hexes,
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
            for component in sb_data.BOSS_COMPONENTS
        ],
        "damage_lanes": {
            area: {str(roll): [list(hex_) for hex_ in lane] for roll, lane in lanes.items()}
            for area, lanes in sb_data.BOSS_DAMAGE_LANES.items()
        },
        # Sides of the damage-lane die per area (roll 1 is a glancing blow).
        "lane_die": {area: 8 for area in sb_data.AREAS},
        "initial_shield_hp": dict(sb_data.INITIAL_SHIELD_HP),
        "shield_max": dict(sb_data.INITIAL_SHIELD_HP),
        "shield_generator_hex": generator_hex,
        "board_hex_areas": list(sb_data.BOARD_HEX_AREAS),
        "phases": [
            {
                "key": key,
                "kind": kind,
                # Slot dicts stay minimal so default event payloads are unchanged.
                "slots": [
                    {"slot": "base"} if slot_type == "base"
                    else {"slot": "component", "component_id": detail} if slot_type == "component"
                    else {"slot": "tier", "tier": detail}
                    for slot_type, detail in slots
                ],
            }
            for key, kind, slots in sb_data.BOSS_PHASES
        ],
        "fleet_actions": {"0.5": ["attack"], "1.5": ["move"], "2.5": ["move"], "3.5": ["attack"], "starbreach": []},
        "tier_progress": {str(tier): threshold for tier, threshold in sb_data.TIER_PROGRESS.items()},
        # What each tier grants (for the battle-board UI).
        "tier_labels": {
            "1": {"kind": "attack", "stack": "0.5"},
            "2": {"kind": "move", "stack": "1.5"},
            "3": {"kind": "move", "stack": "2.5"},
            "4": {"kind": "attack", "stack": "3.5"},
            "5": {"kind": "breacher", "stack": "starbreach"},
            "6": {"kind": "breacher", "stack": "starbreach"},
        },
        # Tier -> fleet craft spawned when it powers up (designed bosses only).
        "tier_spawns": {},
        # None = built-in progress rules (prey hit +1, prey kill +3 total).
        "progress_triggers": None,
        "fleet": [
            {"id": craft_id, "kind": kind, "color": color, "hp": sb_data.HUNTER_KILLER_HP, "offset": [dq, dr]}
            for craft_id, kind, color, (dq, dr) in sb_data.FLEET_SCENARIO
        ],
        "fleet_move": sb_data.HUNTER_KILLER_MOVE,
        "fleet_aim": sb_data.HUNTER_KILLER_AIM,
    }


# ── compiling a designer document into a spec ───────────────────────────────


def _lane_ray(design_footprint: set[tuple[int, int]], q: int, r: int, facing: int) -> list[list[int]]:
    """Hull hexes a lane pierces: the entry hex, then inward (opposite the
    entry face) until the ray leaves the footprint."""
    dq, dr = _DIRECTIONS[(facing + 3) % 6]
    ray = [[q, r]]
    while (q + dq, r + dr) in design_footprint:
        q, r = q + dq, r + dr
        ray.append([q, r])
    return ray


def _design_component_id(tile: dict) -> str:
    short = {"shield_gen": "sg", "firing_computer": "fc", "fuel_tank": "ft", "core": "core"}[tile["type"]]
    return f"{short}_{tile['q']}_{tile['r']}"


def spec_from_design(design: dict) -> dict:
    """Compile a normalized boss-designer document into a runtime spec."""
    tiles = design["tiles"]
    footprint_set = {(tile["q"], tile["r"]) for tile in tiles}
    footprint = sorted(footprint_set)
    tile_by_hex = {(tile["q"], tile["r"]): tile for tile in tiles}
    regions = design["shield_regions"]
    areas = [str(region["number"]) for region in regions]

    # Region -> powering generator hex: the explicit pick, else the first
    # shield-gen tile with the matching number.
    generator_hex: dict[str, list[int] | None] = {}
    for region in regions:
        area = str(region["number"])
        chosen = region["generator"]
        if chosen is None:
            match = next(
                (t for t in tiles if t["type"] == "shield_gen" and t["number"] == region["number"]),
                None,
            )
            chosen = [match["q"], match["r"]] if match else None
        generator_hex[area] = list(chosen) if chosen else None

    hex_area = {_hex_key(q, r): "" for q, r in footprint}
    area_hexes: dict[str, list[list[int]]] = {}
    damage_lanes: dict[str, dict[str, list[list[int]]]] = {}
    for region in regions:
        area = str(region["number"])
        covered: list[list[int]] = []
        seen: set[tuple[int, int]] = set()

        def cover(q: int, r: int) -> None:
            if (q, r) in footprint_set and (q, r) not in seen:
                seen.add((q, r))
                covered.append([q, r])

        for q, r in region["hexes"]:
            hex_area[_hex_key(q, r)] = area
            cover(q, r)
        lanes: dict[str, list[list[int]]] = {}
        for lane in region["lanes"]:
            ray = _lane_ray(footprint_set, lane["q"], lane["r"], lane["facing"])
            lanes[str(lane["roll"])] = ray
            for q, r in ray:
                cover(q, r)
        damage_lanes[area] = lanes
        area_hexes[area] = covered

    components = []
    # Auto-number components per type in tile order so the UI can say
    # "Cannon 2" / "Engine 1" instead of raw coordinates.
    type_counts: dict[str, int] = {}
    for tile in tiles:
        if tile["type"] == "generic":
            continue
        type_counts[tile["type"]] = type_counts.get(tile["type"], 0) + 1
        sequence = type_counts[tile["type"]]
        component = {
            "id": _design_component_id(tile),
            "name": tile["type"].replace("_", " ").title(),
            "type": {"shield_gen": "shield_generator"}.get(tile["type"], tile["type"]),
            "q": tile["q"],
            "r": tile["r"],
            "number": sequence,
            "shield_arcs": [],
            "linked_phase": tile.get("stack"),
        }
        if tile["type"] == "shield_gen":
            component["name"] = f"Shield Generator {tile['number']}"
            component["number"] = tile["number"]
            component["shield_arcs"] = [
                area for area, gen in generator_hex.items() if gen == [tile["q"], tile["r"]]
            ]
        elif tile["type"] == "core":
            component["name"] = f"Core {tile['number']}"
            component["number"] = tile["number"]
        elif tile["type"] == "firing_computer":
            component["name"] = f"Cannon {sequence}"
        elif tile["type"] == "fuel_tank":
            component["name"] = f"Engine {sequence}"
        components.append(component)

    core_hex_by_number = {
        tile["number"]: [tile["q"], tile["r"]] for tile in tiles if tile["type"] == "core"
    }

    # Action phases: firing computers / fuel tanks feed their stack; progression
    # steps add tier slots (tier N = step N, unlocked at progress >= N).
    phase_slots: dict[str, list[dict]] = {key: [] for key in _STACK_KEYS}
    for tile in tiles:
        if tile["type"] == "firing_computer":
            phase_slots[tile["stack"]].append(
                {"slot": "component", "component_id": _design_component_id(tile), "kind": "attack"}
            )
        elif tile["type"] == "fuel_tank":
            phase_slots[tile["stack"]].append(
                {"slot": "component", "component_id": _design_component_id(tile), "kind": "move"}
            )
    steps = design["progression"]["steps"]
    fleet_config = design["behavior"]["fleet"]
    tier_labels: dict[str, dict] = {}
    tier_spawns: dict[str, dict] = {}
    for index, step in enumerate(steps):
        tier = index + 1
        if step["kind"] == "action_link":
            kind = "attack" if step["action"] == "shoot" else "move"
            phase_slots[step["stack"]].append({"slot": "tier", "tier": tier, "kind": kind})
            tier_labels[str(tier)] = {"kind": kind, "stack": step["stack"]}
        elif step["kind"] == "breacher_link":
            slot = {"slot": "tier", "tier": tier, "kind": "attack"}
            core_number = step.get("core")
            if core_number is not None:
                core_hex = core_hex_by_number.get(core_number)
                if core_hex is None:
                    continue  # validation flags this; never becomes active
                slot["core_hex"] = core_hex
            if step.get("round") is not None:
                slot["min_round"] = step["round"]
            phase_slots["starbreach"].append(slot)
            tier_labels[str(tier)] = {"kind": "breacher", "stack": "starbreach"}
        elif step["kind"] == "spawn_fleet":
            tier_spawns[str(tier)] = {
                "count": step["count"],
                "location": step["location"],
                "kind": fleet_config["kind"],
                "hp": fleet_config["hp"],
            }
            tier_labels[str(tier)] = {"kind": "spawn", "stack": None}
        elif step["kind"] == "ability_trigger":
            tier_labels[str(tier)] = {"kind": "ability", "stack": None}
        else:
            tier_labels[str(tier)] = {"kind": "filler", "stack": None}

    phases = []
    for key in _STACK_KEYS:
        slots = phase_slots[key]
        kinds = {slot["kind"] for slot in slots}
        kind = "attack" if "attack" in kinds else ("move" if kinds else _DEFAULT_STACK_KIND[key])
        phases.append({"key": key, "kind": kind, "slots": slots})

    fleet = [
        {
            "id": f"fleet_{index + 1}",
            "kind": fleet_config["kind"],
            "color": _FLEET_COLORS[index % len(_FLEET_COLORS)],
            "hp": fleet_config["hp"],
            "offset": list(_FLEET_OFFSETS[index % len(_FLEET_OFFSETS)]),
        }
        for index in range(fleet_config["count"])
    ]
    fleet_actions: dict[str, list[str]] = {key: [] for key in _STACK_KEYS}
    for entry in fleet_config["actions"]:
        fleet_actions[entry["stack"]].append("attack" if entry["action"] == "shoot" else "move")

    return {
        "source": f"design:{design['id']}",
        "name": design["name"],
        "footprint": [list(hex_) for hex_ in footprint],
        "areas": areas,
        "hex_area": hex_area,
        "area_hexes": area_hexes,
        "components": components,
        "damage_lanes": damage_lanes,
        "lane_die": {
            str(region["number"]): int(region.get("lane_count", 7)) + 1 for region in regions
        },
        "initial_shield_hp": {str(region["number"]): region["charges"] for region in regions},
        "shield_max": {str(region["number"]): region["max_charges"] for region in regions},
        "shield_generator_hex": generator_hex,
        "board_hex_areas": [areas[index % len(areas)] for index in range(3)] if areas else [],
        "phases": phases,
        "fleet_actions": fleet_actions,
        "tier_progress": {str(index + 1): index + 1 for index in range(len(steps))},
        "tier_labels": tier_labels,
        "tier_spawns": tier_spawns,
        "progress_triggers": list(design["progression"]["triggers"]),
        "fleet": fleet,
        "fleet_move": sb_data.HUNTER_KILLER_MOVE,
        "fleet_aim": sb_data.HUNTER_KILLER_AIM,
    }


# ── accessors (engine/serialization read boss data only through these) ──────


def spec_for(sb) -> dict:
    """The spec governing a StarBreachState (its own, or the stock default)."""
    return sb.boss_spec if getattr(sb, "boss_spec", None) else default_spec()


def footprint_set(spec: dict) -> set[tuple[int, int]]:
    return {(hex_[0], hex_[1]) for hex_ in spec["footprint"]}


def hull_size(spec: dict) -> int:
    return len(spec["footprint"])


def area_of_hex(spec: dict, q: int, r: int) -> str:
    return spec["hex_area"].get(_hex_key(q, r), "")


def area_has_intact_hull(spec: dict, area: str, destroyed: set[tuple[int, int]]) -> bool:
    return any(
        (hex_[0], hex_[1]) not in destroyed for hex_ in spec["area_hexes"].get(area, ())
    )


def lane_die(spec: dict, area: str) -> int:
    """Sides of the damage-lane die for an area (roll 1 is a glancing blow).
    Specs saved before lane counts were configurable default to the d8."""
    return int((spec.get("lane_die") or {}).get(area, 8))


def first_intact_lane_hex(
    spec: dict, area: str, lane_roll: int, destroyed: set[tuple[int, int]]
) -> tuple[int, int] | None:
    for hex_ in spec["damage_lanes"].get(area, {}).get(str(lane_roll), ()):
        if (hex_[0], hex_[1]) not in destroyed:
            return (hex_[0], hex_[1])
    return None


def component_by_hex(spec: dict, q: int, r: int) -> dict | None:
    for component in spec["components"]:
        if component["q"] == q and component["r"] == r:
            return component
    return None


def destroyed_component_ids(spec: dict, destroyed_hexes: set[tuple[int, int]]) -> set[str]:
    return {
        component["id"]
        for component in spec["components"]
        if (component["q"], component["r"]) in destroyed_hexes
    }


def shield_generator_intact(spec: dict, area: str, destroyed_hexes: set[tuple[int, int]]) -> bool:
    """No assigned generator hex = intrinsic charge (depletes but can't be
    knocked out); otherwise the generator hex must be intact."""
    generator = spec["shield_generator_hex"].get(area)
    if generator is None:
        return area in spec["areas"]
    return (generator[0], generator[1]) not in destroyed_hexes


def board_hex_areas(spec: dict) -> tuple[str, ...]:
    return tuple(spec["board_hex_areas"])


def phase_kind(spec: dict, phase_key: str) -> str:
    for phase in spec["phases"]:
        if phase["key"] == phase_key:
            return phase["kind"]
    raise KeyError(f"Unknown boss phase: {phase_key}")


def phase_slots(spec: dict, phase_key: str) -> list[dict]:
    for phase in spec["phases"]:
        if phase["key"] == phase_key:
            return phase["slots"]
    return []


def fleet_action_kinds(spec: dict, phase_key: str) -> list[str]:
    return list(spec["fleet_actions"].get(phase_key, ()))


def tier_progress_map(spec: dict) -> dict[int, int]:
    return {int(tier): threshold for tier, threshold in spec["tier_progress"].items()}


def max_progress(spec: dict) -> int:
    thresholds = tier_progress_map(spec).values()
    return max(thresholds, default=0)


def unlocked_tiers(spec: dict, progress: int) -> tuple[int, ...]:
    return tuple(
        tier for tier, threshold in sorted(tier_progress_map(spec).items()) if progress >= threshold
    )


def slot_is_active(
    spec: dict,
    slot: dict,
    destroyed_hexes: set[tuple[int, int]],
    active_tiers: set[int],
    round_number: int,
) -> bool:
    if slot["slot"] == "base":
        return True
    if slot["slot"] == "component":
        return slot["component_id"] not in destroyed_component_ids(spec, destroyed_hexes)
    if slot["slot"] == "tier":
        if slot["tier"] not in active_tiers:
            return False
        core_hex = slot.get("core_hex")
        if core_hex is not None and (core_hex[0], core_hex[1]) in destroyed_hexes:
            return False
        min_round = slot.get("min_round")
        return min_round is None or round_number >= min_round
    return False


def active_phase_slots(
    spec: dict,
    phase_key: str,
    destroyed_hexes: set[tuple[int, int]],
    active_tiers: set[int],
    round_number: int,
) -> list[dict]:
    return [
        slot
        for slot in phase_slots(spec, phase_key)
        if slot_is_active(spec, slot, destroyed_hexes, active_tiers, round_number)
    ]


def expected_phase_actions(
    spec: dict,
    destroyed_hexes: set[tuple[int, int]],
    active_tiers: tuple[int, ...],
    round_number: int,
) -> dict[str, int]:
    tiers = set(active_tiers)
    return {
        phase["key"]: len(active_phase_slots(spec, phase["key"], destroyed_hexes, tiers, round_number))
        for phase in spec["phases"]
    }


def tier_spawns(spec: dict) -> dict[int, dict]:
    return {int(tier): dict(entry) for tier, entry in (spec.get("tier_spawns") or {}).items()}


def tier_labels(spec: dict) -> dict[str, dict]:
    labels = {str(tier): dict(entry) for tier, entry in (spec.get("tier_labels") or {}).items()}
    for tier in spec.get("tier_progress", {}):
        labels.setdefault(str(tier), {"kind": "filler", "stack": None})
    for phase in spec.get("phases", ()):
        stack = phase.get("key")
        for slot in phase.get("slots", ()):
            if slot.get("slot") != "tier":
                continue
            tier = str(slot.get("tier"))
            kind = slot.get("kind") or phase.get("kind") or "attack"
            if stack == "starbreach":
                kind = "breacher"
            labels[tier] = {"kind": kind, "stack": stack}
    for tier in spec.get("tier_spawns", {}):
        labels[str(tier)] = {"kind": "spawn", "stack": None}
    return labels


def boss_layout_to_dict(spec: dict) -> dict:
    """The client-facing layout document (same shape the UI already renders)."""
    return {
        "name": spec["name"],
        "footprint": [
            {"q": hex_[0], "r": hex_[1], "area": area_of_hex(spec, hex_[0], hex_[1])}
            for hex_ in spec["footprint"]
        ],
        "components": [dict(component) for component in spec["components"]],
        "areas": list(spec["areas"]),
        "damage_lanes": {
            area: {roll: [list(hex_) for hex_ in lane] for roll, lane in lanes.items()}
            for area, lanes in spec["damage_lanes"].items()
        },
        # Battle board data: every phase's slots (with component links), what
        # each progression tier grants, and any tier fleet spawns.
        "phases": [
            {"key": phase["key"], "kind": phase["kind"], "slots": [dict(slot) for slot in phase["slots"]]}
            for phase in spec["phases"]
        ],
        "fleet_actions": {key: list(kinds) for key, kinds in spec.get("fleet_actions", {}).items()},
        "tier_labels": tier_labels(spec),
        "tier_spawns": {str(tier): dict(entry) for tier, entry in (spec.get("tier_spawns") or {}).items()},
    }


def progress_triggers(spec: dict) -> list[str] | None:
    """None = built-in stock rules; a list = designer-selected triggers."""
    return spec["progress_triggers"]
