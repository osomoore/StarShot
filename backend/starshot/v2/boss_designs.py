"""Boss ship designs: schema, validation, and file storage.

A boss design is a plain JSON document describing a custom StarBreach-style
boss: hull tiles on a boss-local axial hex grid, shield regions with damage
lanes, and a progression track. This module is intentionally free of FastAPI
and of the live rules engine so the designer can evolve without touching
either; `boss_designer_api.py` exposes it over HTTP.

Bundled developer designs are stored one-per-file under
``resources/boss_designs/<id>.json``. Server-created and server-edited
designs are stored under ``.starshot/content/boss_designs/`` so Git pulls do
not overwrite them.
Saving accepts any structurally sound document and returns a list of
``problems`` (human-readable warnings) so half-finished designs can be kept.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DESIGNS_DIR = ROOT / "resources" / "boss_designs"
RUNTIME_DESIGNS_DIR = ROOT / ".starshot" / "content" / "boss_designs"

# Mirrors backend/starshot/rules/hex.py (and board.js).
AXIAL_DIRECTIONS = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))

# Half of the editable grid width; hexes must satisfy the axial-disk bound.
GRID_RADIUS = 7

TILE_TYPES = ("generic", "shield_gen", "cannon", "engine", "core", "signal_jammer", "targeting_sensors")
LEGACY_TILE_TYPES = {"firing_computer": "cannon", "fuel_tank": "engine"}

# Passive component abilities: no action-stack element, active while the
# component hex is intact — or granted outright by an ability_link
# progression step. signal_jammer = +2 boss defense, targeting_sensors =
# +2 boss Aim.
ABILITY_TYPES = ("signal_jammer", "targeting_sensors")

# Boss action stacks a Cannon / Engine / action-link step can feed.
ACTION_STACKS = ("0.5", "1.5", "2.5", "3.5", "starbreach")

# Die rolls that hit a damage lane (1 is always a miss). A region with N
# lanes uses an (N+1)-sided die: rolls 2..N+1 are lanes. The default of 7
# lanes matches the stock scenario's d8.
DEFAULT_LANE_COUNT = 7
MAX_LANE_COUNT = 12
LANE_ROLLS = tuple(range(2, DEFAULT_LANE_COUNT + 2))


def lane_rolls(lane_count: int) -> tuple[int, ...]:
    return tuple(range(2, int(lane_count) + 2))

STEP_KINDS = ("filler", "action_link", "breacher_link", "ability_trigger", "spawn_fleet", "ability_link")
ACTION_TYPES = ("move", "shoot")

# Where spawn_fleet steps place their craft.
SPAWN_LOCATIONS = ("boss_front", "bauble", "fang")
SPAWN_MAX_COUNT = 3

# Player-owned designs are capped so the library stays browsable.
PLAYER_DESIGN_LIMIT = 10

# Behavior options (single choices for now; enums so the schema can grow).
BOSS_AIS = ("hunter_killer",)
FLEET_KINDS = ("hunter_killer",)
FLEET_AIS = ("hunter_killer",)
FLEET_MAX_COUNT = 6
FLEET_MAX_ACTION_COUNT = 9
# Fleet craft act during the numbered boss stacks (not the StarBreach stack).
FLEET_STACKS = ("0.5", "1.5", "2.5", "3.5")

TRIGGER_TYPES = (
    "bauble_pickup_boss",
    "bauble_pickup_fleet",
    "prey_hull_damage_boss",
    "prey_hull_damage_fleet",
    "player_kill",
)


class BossDesignError(ValueError):
    """A design document is structurally malformed and cannot be saved."""


def safe_design_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    if not slug:
        raise BossDesignError("Design id must contain letters or digits.")
    return slug[:60]


def default_behavior() -> dict:
    return {
        "boss_ai": "hunter_killer",
        "fleet": {"count": 0, "kind": "hunter_killer", "hp": 3, "ai": "hunter_killer", "actions": []},
    }


def empty_design(design_id: str, name: str) -> dict:
    return {
        "id": design_id,
        "name": name,
        "description": "",
        "tiles": [],
        "shield_regions": [],
        "progression": {"triggers": [], "steps": []},
        "behavior": default_behavior(),
    }


# ── normalization ───────────────────────────────────────────────────────────
# Coerce a client document into canonical shape, raising BossDesignError on
# anything that does not fit the schema. Game-design issues (disconnected
# hulls, missing lanes, ...) are left to validate_design().


def _as_int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise BossDesignError(f"{label} must be an integer.")
    return int(value)


def _as_hex(value, label: str) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise BossDesignError(f"{label} must be a [q, r] pair.")
    q = _as_int(value[0], f"{label} q")
    r = _as_int(value[1], f"{label} r")
    if abs(q) > GRID_RADIUS or abs(r) > GRID_RADIUS or abs(q + r) > GRID_RADIUS:
        raise BossDesignError(f"{label} ({q},{r}) is outside the radius-{GRID_RADIUS} grid.")
    return q, r


def _normalize_tile(raw, index: int) -> dict:
    if not isinstance(raw, dict):
        raise BossDesignError(f"tiles[{index}] must be an object.")
    label = f"tiles[{index}]"
    q, r = _as_hex((raw.get("q"), raw.get("r")), label)
    tile_type = LEGACY_TILE_TYPES.get(raw.get("type"), raw.get("type"))
    if tile_type not in TILE_TYPES:
        raise BossDesignError(f"{label}.type must be one of {', '.join(TILE_TYPES)}.")
    tile: dict = {"q": q, "r": r, "type": tile_type}
    if tile_type in ("shield_gen", "core"):
        number = _as_int(raw.get("number", 1), f"{label}.number")
        if not 1 <= number <= 9:
            raise BossDesignError(f"{label}.number must be 1-9.")
        tile["number"] = number
    if tile_type in ("cannon", "engine"):
        stack = str(raw.get("stack", ""))
        if stack not in ACTION_STACKS:
            raise BossDesignError(f"{label}.stack must be one of {', '.join(ACTION_STACKS)}.")
        tile["stack"] = stack
    return tile


def _normalize_region(raw, index: int) -> dict:
    if not isinstance(raw, dict):
        raise BossDesignError(f"shield_regions[{index}] must be an object.")
    label = f"shield_regions[{index}]"
    number = _as_int(raw.get("number"), f"{label}.number")
    if not 1 <= number <= 9:
        raise BossDesignError(f"{label}.number must be 1-9.")
    hexes = raw.get("hexes", [])
    if not isinstance(hexes, list):
        raise BossDesignError(f"{label}.hexes must be a list.")
    seen: list[list[int]] = []
    for i, entry in enumerate(hexes):
        q, r = _as_hex(entry, f"{label}.hexes[{i}]")
        if [q, r] not in seen:
            seen.append([q, r])
    generator = raw.get("generator")
    if generator is not None:
        generator = list(_as_hex(generator, f"{label}.generator"))
    lane_count = _as_int(raw.get("lane_count", DEFAULT_LANE_COUNT), f"{label}.lane_count")
    if not 1 <= lane_count <= MAX_LANE_COUNT:
        raise BossDesignError(f"{label}.lane_count must be 1-{MAX_LANE_COUNT}.")
    lanes = raw.get("lanes", [])
    if not isinstance(lanes, list):
        raise BossDesignError(f"{label}.lanes must be a list.")
    valid_rolls = lane_rolls(lane_count)
    normalized_lanes = []
    for i, lane in enumerate(lanes):
        if not isinstance(lane, dict):
            raise BossDesignError(f"{label}.lanes[{i}] must be an object.")
        roll = _as_int(lane.get("roll"), f"{label}.lanes[{i}].roll")
        if roll not in valid_rolls:
            raise BossDesignError(
                f"{label}.lanes[{i}].roll must be 2-{valid_rolls[-1]} (its lane_count is {lane_count})."
            )
        q, r = _as_hex((lane.get("q"), lane.get("r")), f"{label}.lanes[{i}]")
        facing = _as_int(lane.get("facing"), f"{label}.lanes[{i}].facing")
        if not 0 <= facing <= 5:
            raise BossDesignError(f"{label}.lanes[{i}].facing must be 0-5.")
        normalized_lanes.append({"roll": roll, "q": q, "r": r, "facing": facing})
    max_charges = _as_int(raw.get("max_charges", raw.get("charges", 3)), f"{label}.max_charges")
    charges = _as_int(raw.get("charges", max_charges), f"{label}.charges")
    if not 0 <= max_charges <= 9:
        raise BossDesignError(f"{label}.max_charges must be 0-9.")
    if not 0 <= charges <= max_charges:
        raise BossDesignError(f"{label}.charges must be 0-{max_charges} (its max_charges).")
    return {
        "number": number,
        "hexes": seen,
        "generator": generator,
        "lane_count": lane_count,
        "lanes": normalized_lanes,
        "charges": charges,
        "max_charges": max_charges,
    }


def _normalize_behavior(raw) -> dict:
    if raw is None:
        return default_behavior()
    if not isinstance(raw, dict):
        raise BossDesignError("behavior must be an object.")
    boss_ai = raw.get("boss_ai", "hunter_killer")
    if boss_ai not in BOSS_AIS:
        raise BossDesignError(f"behavior.boss_ai must be one of {', '.join(BOSS_AIS)}.")
    fleet_raw = raw.get("fleet") or {}
    if not isinstance(fleet_raw, dict):
        raise BossDesignError("behavior.fleet must be an object.")
    count = _as_int(fleet_raw.get("count", 0), "behavior.fleet.count")
    if not 0 <= count <= FLEET_MAX_COUNT:
        raise BossDesignError(f"behavior.fleet.count must be 0-{FLEET_MAX_COUNT}.")
    kind = fleet_raw.get("kind", "hunter_killer")
    if kind not in FLEET_KINDS:
        raise BossDesignError(f"behavior.fleet.kind must be one of {', '.join(FLEET_KINDS)}.")
    hp = _as_int(fleet_raw.get("hp", 3), "behavior.fleet.hp")
    if not 1 <= hp <= 9:
        raise BossDesignError("behavior.fleet.hp must be 1-9.")
    ai = fleet_raw.get("ai", "hunter_killer")
    if ai not in FLEET_AIS:
        raise BossDesignError(f"behavior.fleet.ai must be one of {', '.join(FLEET_AIS)}.")
    actions_raw = fleet_raw.get("actions", [])
    if not isinstance(actions_raw, list):
        raise BossDesignError("behavior.fleet.actions must be a list.")
    action_counts: dict[tuple[str, str], int] = {}
    for index, entry in enumerate(actions_raw):
        if not isinstance(entry, dict):
            raise BossDesignError(f"behavior.fleet.actions[{index}] must be an object.")
        stack = str(entry.get("stack", ""))
        if stack not in FLEET_STACKS:
            raise BossDesignError(f"behavior.fleet.actions[{index}].stack must be one of {', '.join(FLEET_STACKS)}.")
        action = entry.get("action")
        if action not in ACTION_TYPES:
            raise BossDesignError(f"behavior.fleet.actions[{index}].action must be 'move' or 'shoot'.")
        action_count = _as_int(entry.get("count", 1), f"behavior.fleet.actions[{index}].count")
        if not 0 <= action_count <= FLEET_MAX_ACTION_COUNT:
            raise BossDesignError(f"behavior.fleet.actions[{index}].count must be 0-{FLEET_MAX_ACTION_COUNT}.")
        if action_count:
            key = (stack, action)
            action_counts[key] = min(FLEET_MAX_ACTION_COUNT, action_counts.get(key, 0) + action_count)
    actions = [
        {"stack": stack, "action": action, "count": action_counts[(stack, action)]}
        for stack in FLEET_STACKS
        for action in ACTION_TYPES
        if (stack, action) in action_counts
    ]
    return {
        "boss_ai": boss_ai,
        "fleet": {"count": count, "kind": kind, "hp": hp, "ai": ai, "actions": actions},
    }


def _normalize_step(raw, index: int) -> dict:
    if raw is None:
        return {"kind": "filler"}
    if not isinstance(raw, dict):
        raise BossDesignError(f"progression.steps[{index}] must be an object.")
    label = f"progression.steps[{index}]"
    kind = raw.get("kind", raw.get("type"))
    if kind is None or kind == "":
        kind = "filler"
    if kind not in STEP_KINDS:
        raise BossDesignError(f"{label}.kind must be one of {', '.join(STEP_KINDS)}.")
    step: dict = {"kind": kind}
    if kind == "action_link":
        stack = str(raw.get("stack", ""))
        if stack not in ACTION_STACKS:
            raise BossDesignError(f"{label}.stack must be one of {', '.join(ACTION_STACKS)}.")
        action = raw.get("action")
        if action not in ACTION_TYPES:
            raise BossDesignError(f"{label}.action must be 'move' or 'shoot'.")
        step["stack"] = stack
        step["action"] = action
    elif kind == "breacher_link":
        core = raw.get("core")
        round_ = raw.get("round")
        if core is None and round_ is None:
            raise BossDesignError(f"{label} needs a core number and/or a round requirement.")
        if core is not None:
            core = _as_int(core, f"{label}.core")
            if not 1 <= core <= 9:
                raise BossDesignError(f"{label}.core must be 1-9.")
            step["core"] = core
        if round_ is not None:
            round_ = _as_int(round_, f"{label}.round")
            if not 1 <= round_ <= 99:
                raise BossDesignError(f"{label}.round must be 1-99.")
            step["round"] = round_
    elif kind == "ability_trigger":
        name = str(raw.get("name", "")).strip()
        if not name:
            raise BossDesignError(f"{label}.name must not be empty.")
        step["name"] = name[:80]
        step["notes"] = str(raw.get("notes", ""))[:400]
    elif kind == "ability_link":
        ability = raw.get("ability")
        if ability not in ABILITY_TYPES:
            raise BossDesignError(f"{label}.ability must be one of {', '.join(ABILITY_TYPES)}.")
        step["ability"] = ability
    elif kind == "spawn_fleet":
        count = _as_int(raw.get("count", 1), f"{label}.count")
        if not 1 <= count <= SPAWN_MAX_COUNT:
            raise BossDesignError(f"{label}.count must be 1-{SPAWN_MAX_COUNT}.")
        location = raw.get("location", "boss_front")
        if location not in SPAWN_LOCATIONS:
            raise BossDesignError(f"{label}.location must be one of {', '.join(SPAWN_LOCATIONS)}.")
        step["count"] = count
        step["location"] = location
    return step


def normalize_design(raw: dict) -> dict:
    """Canonical copy of `raw`, or raise BossDesignError."""
    if not isinstance(raw, dict):
        raise BossDesignError("Design must be a JSON object.")
    design_id = safe_design_id(raw.get("id", ""))
    name = str(raw.get("name", "")).strip()
    if not name:
        raise BossDesignError("Design needs a name.")

    tiles_raw = raw.get("tiles", [])
    if not isinstance(tiles_raw, list) or len(tiles_raw) > 400:
        raise BossDesignError("tiles must be a list (max 400).")
    tiles: list[dict] = []
    occupied: set[tuple[int, int]] = set()
    for index, entry in enumerate(tiles_raw):
        tile = _normalize_tile(entry, index)
        key = (tile["q"], tile["r"])
        if key in occupied:
            raise BossDesignError(f"Two tiles occupy hex ({key[0]},{key[1]}).")
        occupied.add(key)
        tiles.append(tile)

    regions_raw = raw.get("shield_regions", [])
    if not isinstance(regions_raw, list) or len(regions_raw) > 9:
        raise BossDesignError("shield_regions must be a list (max 9).")
    regions = [_normalize_region(entry, index) for index, entry in enumerate(regions_raw)]
    numbers = [region["number"] for region in regions]
    if len(numbers) != len(set(numbers)):
        raise BossDesignError("Shield region numbers must be unique.")

    progression_raw = raw.get("progression", {})
    if not isinstance(progression_raw, dict):
        raise BossDesignError("progression must be an object.")
    triggers_raw = progression_raw.get("triggers", [])
    if not isinstance(triggers_raw, list):
        raise BossDesignError("progression.triggers must be a list.")
    triggers = []
    for trigger in triggers_raw:
        if trigger not in TRIGGER_TYPES:
            raise BossDesignError(f"Unknown progression trigger: {trigger!r}.")
        if trigger not in triggers:
            triggers.append(trigger)
    steps_raw = progression_raw.get("steps", [])
    if not isinstance(steps_raw, list) or len(steps_raw) > 60:
        raise BossDesignError("progression.steps must be a list (max 60).")
    steps = [_normalize_step(entry, index) for index, entry in enumerate(steps_raw)]

    return {
        "id": design_id,
        "name": name[:80],
        "description": str(raw.get("description", ""))[:500],
        "tiles": tiles,
        "shield_regions": regions,
        "progression": {"triggers": triggers, "steps": steps},
        "behavior": _normalize_behavior(raw.get("behavior")),
    }


# ── design-quality validation (warnings, never fatal) ───────────────────────


def _neighbors(q: int, r: int):
    for dq, dr in AXIAL_DIRECTIONS:
        yield q + dq, r + dr


def _connected(hexes: set[tuple[int, int]]) -> bool:
    if not hexes:
        return True
    stack = [next(iter(hexes))]
    seen = {stack[0]}
    while stack:
        q, r = stack.pop()
        for neighbor in _neighbors(q, r):
            if neighbor in hexes and neighbor not in seen:
                seen.add(neighbor)
                stack.append(neighbor)
    return seen == hexes


def edge_facings(q: int, r: int, footprint: set[tuple[int, int]]) -> tuple[int, ...]:
    """Facing indexes whose neighbor hex is outside the ship footprint."""
    return tuple(
        index
        for index, (dq, dr) in enumerate(AXIAL_DIRECTIONS)
        if (q + dq, r + dr) not in footprint
    )


def validate_design(design: dict) -> list[str]:
    """Human-readable warnings for a normalized design."""
    problems: list[str] = []
    tiles = design["tiles"]
    footprint = {(tile["q"], tile["r"]) for tile in tiles}
    tile_by_hex = {(tile["q"], tile["r"]): tile for tile in tiles}

    if not tiles:
        problems.append("The ship has no tiles yet.")
    elif not _connected(footprint):
        problems.append("The hull is not fully connected.")
    if tiles and not design["shield_regions"]:
        problems.append("The ship needs at least one shield region so players can target and damage it.")

    core_numbers = [tile["number"] for tile in tiles if tile["type"] == "core"]
    for number in sorted(set(n for n in core_numbers if core_numbers.count(n) > 1)):
        problems.append(f"Core number {number} is used by more than one core tile.")

    shield_gens = [tile for tile in tiles if tile["type"] == "shield_gen"]
    region_numbers = {region["number"] for region in design["shield_regions"]}
    for tile in shield_gens:
        if tile["number"] not in region_numbers:
            problems.append(
                f"Shield generator {tile['number']} at ({tile['q']},{tile['r']}) has no matching shield region."
            )

    for region in design["shield_regions"]:
        tag = f"Shield region {region['number']}"
        hexes = {tuple(h) for h in region["hexes"]}
        if not hexes:
            problems.append(f"{tag} has no protected hexes.")
        missing = sorted(h for h in hexes if h not in footprint)
        for q, r in missing:
            problems.append(f"{tag} protects ({q},{r}), which is not a ship tile.")
        present = hexes & footprint
        if present and not _connected(present):
            problems.append(f"{tag} hexes are not continuous.")
        generator = region["generator"]
        if generator is None:
            matches = [t for t in shield_gens if t["number"] == region["number"]]
            if not matches:
                problems.append(f"{tag} has no shield generator powering it.")
        else:
            tile = tile_by_hex.get(tuple(generator))
            if tile is None or tile["type"] != "shield_gen":
                problems.append(f"{tag} generator at ({generator[0]},{generator[1]}) is not a shield generator tile.")
            elif tile["number"] != region["number"]:
                problems.append(
                    f"{tag} is powered by a generator numbered {tile['number']} (expected {region['number']})."
                )

        rolls = [lane["roll"] for lane in region["lanes"]]
        for roll in sorted(set(r for r in rolls if rolls.count(r) > 1)):
            problems.append(f"{tag} assigns lane {roll} more than once.")
        # Fewer than seven lanes is allowed: unassigned rolls reroll in play.
        if not rolls and hexes:
            problems.append(f"{tag} has no damage lanes — hits could never damage it.")
        for lane in region["lanes"]:
            spot = (lane["q"], lane["r"])
            if spot not in hexes:
                problems.append(f"{tag} lane {lane['roll']} starts at ({spot[0]},{spot[1]}), outside the region.")
            elif spot in footprint and lane["facing"] not in edge_facings(spot[0], spot[1], footprint):
                problems.append(f"{tag} lane {lane['roll']} does not enter from the ship edge.")

    steps = design["progression"]["steps"]
    if steps and not design["progression"]["triggers"]:
        problems.append("The progression track has steps but no way to progress (pick at least one trigger).")
    core_set = set(core_numbers)
    for index, step in enumerate(steps):
        if step["kind"] == "breacher_link" and "core" in step and step["core"] not in core_set:
            problems.append(f"Progression step {index + 1} links to core {step['core']}, which is not on the ship.")

    fleet = design["behavior"]["fleet"]
    if fleet["count"] > 0 and not fleet["actions"]:
        problems.append("The fleet has craft but no action counts — it would never move or shoot.")

    return problems


def is_design_valid(design: dict) -> bool:
    """Playable = normalized and free of design problems."""
    return not validate_design(design)


# ── storage ─────────────────────────────────────────────────────────────────
# Bundled developer designs live under resources/boss_designs. Runtime
# server/admin/player saves live under .starshot/content/boss_designs. Every
# storage function takes an optional owner_id: None = the shared global library.

PLAYERS_SUBDIR = "players"
SOURCE_DEVELOPER = "developer"
SOURCE_SERVER = "server"


def _bundled_design_dir(owner_id: int | None = None) -> Path:
    if owner_id is None:
        return DESIGNS_DIR
    return DESIGNS_DIR / PLAYERS_SUBDIR / str(int(owner_id))


def _runtime_design_dir(owner_id: int | None = None) -> Path:
    if owner_id is None:
        return RUNTIME_DESIGNS_DIR
    return RUNTIME_DESIGNS_DIR / PLAYERS_SUBDIR / str(int(owner_id))


def _design_dir(owner_id: int | None = None) -> Path:
    """Runtime save directory. Kept for tests/old callers."""
    return _runtime_design_dir(owner_id)


def _design_path(design_id: str, owner_id: int | None = None) -> Path:
    return _runtime_design_dir(owner_id) / f"{safe_design_id(design_id)}.json"


def _design_source_dirs(owner_id: int | None = None) -> tuple[tuple[str, Path], ...]:
    return (
        (SOURCE_DEVELOPER, _bundled_design_dir(owner_id)),
        (SOURCE_SERVER, _runtime_design_dir(owner_id)),
    )


def _json_fingerprint(data: dict) -> str:
    try:
        data = normalize_design(data)
    except BossDesignError:
        pass
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _read_design_file(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _raw_design_records(owner_id: int | None = None) -> list[dict]:
    records: list[dict] = []
    for source, directory in _design_source_dirs(owner_id):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            data = _read_design_file(path)
            if data is None:
                continue
            try:
                design_id = safe_design_id(data.get("id", path.stem))
            except BossDesignError:
                design_id = safe_design_id(path.stem)
            records.append(
                {
                    "id": design_id,
                    "visible_id": design_id,
                    "source": source,
                    "path": path,
                    "mtime": path.stat().st_mtime,
                    "data": data,
                    "fingerprint": _json_fingerprint(data),
                    "conflict_of": None,
                }
            )
    return records


def _unique_visible_id(base_id: str, source: str, used: set[str]) -> str:
    stem = safe_design_id(f"{base_id}_{source}")
    candidate = stem
    suffix = 2
    while candidate in used:
        candidate = safe_design_id(f"{stem}_{suffix}")
        suffix += 1
    used.add(candidate)
    return candidate


def _merged_design_records(owner_id: int | None = None) -> list[dict]:
    by_id: dict[str, list[dict]] = {}
    for record in _raw_design_records(owner_id):
        by_id.setdefault(record["id"], []).append(record)

    merged: list[dict] = []
    used: set[str] = set()
    for design_id in sorted(by_id):
        records = by_id[design_id]
        fingerprints = {record["fingerprint"] for record in records}
        if len(fingerprints) <= 1:
            chosen = sorted(records, key=lambda item: (item["source"] == SOURCE_SERVER, item["mtime"]))[-1]
            chosen = dict(chosen)
            chosen["visible_id"] = design_id
            used.add(design_id)
            merged.append(chosen)
            continue

        ordered = sorted(records, key=lambda item: (item["mtime"], item["source"] == SOURCE_SERVER), reverse=True)
        newest = dict(ordered[0])
        newest["visible_id"] = design_id
        used.add(design_id)
        merged.append(newest)
        for record in ordered[1:]:
            alternate = dict(record)
            alternate["visible_id"] = _unique_visible_id(design_id, alternate["source"], used)
            alternate["conflict_of"] = design_id
            merged.append(alternate)
    return sorted(merged, key=lambda item: item["visible_id"])


def _record_for_design_id(design_id: str, owner_id: int | None = None) -> dict | None:
    wanted = safe_design_id(design_id)
    for record in _merged_design_records(owner_id):
        if record["visible_id"] == wanted:
            return record
    return None


def list_designs(owner_id: int | None = None) -> list[dict]:
    entries = []
    for record in _merged_design_records(owner_id):
        data = record["data"]
        try:
            valid = is_design_valid(normalize_design(data))
        except BossDesignError:
            valid = False
        entries.append(
            {
                "id": record["visible_id"],
                "source_id": data.get("id", record["id"]),
                "name": data.get("name", record["visible_id"]),
                "tile_count": len(data.get("tiles", [])),
                "region_count": len(data.get("shield_regions", [])),
                "step_count": len(data.get("progression", {}).get("steps", [])),
                "valid": valid,
                "source": record["source"],
                "conflict_of": record["conflict_of"],
            }
        )
    return entries


def list_player_owner_ids() -> list[int]:
    """User ids that have at least one saved boss design."""
    owners: set[int] = set()
    for players_dir in (DESIGNS_DIR / PLAYERS_SUBDIR, RUNTIME_DESIGNS_DIR / PLAYERS_SUBDIR):
        if not players_dir.exists():
            continue
        for child in sorted(players_dir.iterdir()):
            if child.is_dir() and child.name.isdigit() and any(child.glob("*.json")):
                owners.add(int(child.name))
    return sorted(owners)


def load_design(design_id: str, owner_id: int | None = None) -> dict | None:
    record = _record_for_design_id(design_id, owner_id)
    if record is None:
        return None
    design = normalize_design(record["data"])
    if record["visible_id"] != design["id"]:
        design["id"] = record["visible_id"]
        design["name"] = f"{design['name']} ({record['source']})"
    return design


def save_design(raw: dict, owner_id: int | None = None) -> tuple[dict, list[str]]:
    """Normalize, persist to runtime storage, and return (design, problems).

    Bundled Git designs are never overwritten by server saves; editing one
    creates a runtime override with the same id.
    """
    design = normalize_design(raw)
    directory = _design_dir(owner_id)
    if owner_id is not None and not _design_path(design["id"], owner_id).exists():
        existing_ids = {entry["id"] for entry in list_designs(owner_id)}
        if design["id"] not in existing_ids and len(existing_ids) >= PLAYER_DESIGN_LIMIT:
            raise BossDesignError(
                f"You already have {PLAYER_DESIGN_LIMIT} boss designs — delete one to make room."
            )
    directory.mkdir(parents=True, exist_ok=True)
    _design_path(design["id"], owner_id).write_text(
        json.dumps(design, indent=2), encoding="utf-8"
    )
    return design, validate_design(design)


def delete_design(design_id: str, owner_id: int | None = None) -> bool:
    path = _design_path(design_id, owner_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def unique_design_id(base_id: str, owner_id: int | None = None) -> str:
    """`base_id`, or `base_id_2`, `base_id_3`, ... — first id free in the
    target library."""
    existing = {entry["id"] for entry in list_designs(owner_id)}
    candidate = safe_design_id(base_id)
    suffix = 2
    while candidate in existing:
        candidate = f"{safe_design_id(base_id)}_{suffix}"
        suffix += 1
    return candidate


def clone_design_to_global(owner_id: int, design_id: str, new_name: str | None = None) -> tuple[dict, list[str]]:
    """Copy a player's design into the shared global library (admin action)."""
    design = load_design(design_id, owner_id)
    if design is None:
        raise BossDesignError("No such player boss design.")
    design["id"] = unique_design_id(design["id"], None)
    if new_name:
        design["name"] = str(new_name).strip()[:80] or design["name"]
    return save_design(design, None)
