"""Player ship designs (StarDock): schema, validation, and file storage.

A player ship design is a plain JSON document describing a custom player
ship on a radius-5 hex grid:

- ``tiles``: component tiles. A battle-ready ship places 1 Core, 2 Life
  Supports, 1 Bone Room, 1 Docking Bay, and exactly 10 Engine / Double
  Engine / Cannon / Double Cannon components paid for with 15 Core
  Component points (Engine/Cannon 1 point, Double 2 points) — those 10
  components ARE the ship's 10-card starting deck (Move 1 / Move 2 /
  Aim +1 / Aim +2). All tiles must be contiguous. If the admin raises the
  tile total above 15, the extras are Structure tiles.
- ``lanes``: the six player-placed secondary damage lanes (rolls 3, 5, 6,
  8, 9, 11): each an anchor hex plus a travel direction. A lane may not
  pass through the Core, and shooting fully through it must sever at least
  2 (admin configurable) surviving non-core components from the Core. At
  most 10 (admin configurable) non-core components may sit on the six
  primary lanes that pass through the Core.
- ``upgrade``: exactly one special upgrade — "shield" (+1 shield charge),
  "draw" (+1 card per round), "defense"/"aim" (flat bonus on all actions,
  admin configurable), or "points" (+2 Core Component points).

This module is intentionally free of FastAPI and of the live rules engine
loop so the designer can evolve without touching either;
``ship_designer_api.py`` exposes it over HTTP and
``starshot.rules.player_ships`` compiles designs for play.

Bundled developer designs are stored one-per-file under
``resources/ship_designs/<id>.json``. Server-created and server-edited
designs are stored under ``.starshot/content/ship_designs/`` so Git pulls do
not overwrite them. Saving accepts any structurally sound document and
returns a list of ``problems`` (human-readable warnings) so half-finished
designs can be kept.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from starshot.rules.player_ships import (
    AXIAL_DIRECTIONS,
    BASE_TILE_TOTAL,
    CORE_TILE_COSTS,
    DECK_SIZE,
    LEGACY_TILE_TYPES,
    PLAYER_SHIP_GRID_RADIUS,
    PRIMARY_LANE_DIRS,
    PLAYER_TILE_TYPES,
    REQUIRED_LIFE_SUPPORTS,
    SECONDARY_LANE_ROLLS,
    SHIP_UPGRADES,
    core_points_budget,
    core_points_spent,
    core_tile,
    deck_component_count,
    lane_cells,
    lane_number,
    lane_severed_count,
    points_breakdown,
    primary_lane_tile_count,
    primary_lane_id,
    secondary_lane_id,
    secondary_lanes,
    stardock_config,
)

ROOT = Path(__file__).resolve().parents[3]
DESIGNS_DIR = ROOT / "resources" / "ship_designs"
RUNTIME_DESIGNS_DIR = ROOT / ".starshot" / "content" / "ship_designs"

GRID_RADIUS = PLAYER_SHIP_GRID_RADIUS
TILE_TYPES = PLAYER_TILE_TYPES


def active_stardock_config() -> dict:
    """The admin-configured StarDock rule numbers (falls back to the rules
    defaults when settings are unavailable, e.g. in rules-only tests)."""
    try:
        from starshot.v2.settings import stardock_config as configured

        return configured()
    except Exception:
        return stardock_config()


def with_active_config(design: dict) -> dict:
    """A copy of `design` carrying the current admin config, ready for
    validation/compilation. The config never persists with the design."""
    return {**design, "config": active_stardock_config()}

# Player-owned designs are capped so the library stays browsable.
PLAYER_DESIGN_LIMIT = 10


class ShipDesignError(ValueError):
    """A design document is structurally malformed and cannot be saved."""


def safe_design_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    if not slug:
        raise ShipDesignError("Design id must contain letters or digits.")
    return slug[:60]


def empty_design(design_id: str, name: str) -> dict:
    return {
        "id": design_id,
        "name": name,
        "description": "",
        "tiles": [],
        "lanes": {},
        "upgrade": None,
    }


# ── normalization ───────────────────────────────────────────────────────────


def _as_int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise ShipDesignError(f"{label} must be an integer.")
    return int(value)


def _as_hex(value, label: str) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ShipDesignError(f"{label} must be a [q, r] pair.")
    q = _as_int(value[0], f"{label} q")
    r = _as_int(value[1], f"{label} r")
    if abs(q) > GRID_RADIUS or abs(r) > GRID_RADIUS or abs(q + r) > GRID_RADIUS:
        raise ShipDesignError(f"{label} ({q},{r}) is outside the radius-{GRID_RADIUS} ship grid.")
    return q, r


def _normalize_tile(raw, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ShipDesignError(f"tiles[{index}] must be an object.")
    label = f"tiles[{index}]"
    q, r = _as_hex((raw.get("q"), raw.get("r")), label)
    tile_type = raw.get("type")
    if tile_type not in TILE_TYPES and tile_type not in LEGACY_TILE_TYPES:
        raise ShipDesignError(f"{label}.type must be one of {', '.join(TILE_TYPES)}.")
    return {"q": q, "r": r, "type": tile_type}


def _normalize_lanes(raw) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ShipDesignError("lanes must be an object keyed by lane roll.")
    lanes: dict[str, dict] = {}
    for key, value in raw.items():
        try:
            roll = int(key)
        except (TypeError, ValueError):
            raise ShipDesignError(f"lanes key {key!r} is not a lane roll.") from None
        if roll not in SECONDARY_LANE_ROLLS:
            raise ShipDesignError(
                f"Lane roll {roll} is not a secondary lane (allowed: "
                f"{', '.join(str(r) for r in SECONDARY_LANE_ROLLS)})."
            )
        if not isinstance(value, dict):
            raise ShipDesignError(f"lanes[{roll}] must be an object.")
        label = f"lanes[{roll}]"
        q, r = _as_hex((value.get("q"), value.get("r")), label)
        direction = _as_int(value.get("dir"), f"{label}.dir")
        if not 0 <= direction <= 5:
            raise ShipDesignError(f"{label}.dir must be 0-5.")
        # canonicalize the anchor to the lane's entry cell
        cells = lane_cells(q, r, direction)
        entry_q, entry_r = cells[0]
        lanes[str(roll)] = {"q": entry_q, "r": entry_r, "dir": direction}
    return lanes


def _normalize_lane_numbers(raw) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ShipDesignError("lane_numbers must be an object keyed by lane id.")
    numbers: dict[str, int] = {}
    for key, value in raw.items():
        text_key = str(key)
        if not (text_key.startswith("p:") or text_key.startswith("s:")):
            raise ShipDesignError(f"lane_numbers key {key!r} is not a lane id.")
        number = _as_int(value, f"lane_numbers[{text_key}]")
        if not 1 <= number <= 12:
            raise ShipDesignError(f"lane_numbers[{text_key}] must be 1-12.")
        numbers[text_key] = number
    return numbers


def normalize_design(raw: dict) -> dict:
    """Canonical copy of `raw`, or raise ShipDesignError. Legacy pre-overhaul
    documents (shields/draw stats, old tile types) still normalize so they
    can be opened, but old stats are dropped and old tiles flag problems."""
    if not isinstance(raw, dict):
        raise ShipDesignError("Design must be a JSON object.")
    design_id = safe_design_id(raw.get("id", ""))
    name = str(raw.get("name", "")).strip()
    if not name:
        raise ShipDesignError("Design needs a name.")

    tiles_raw = raw.get("tiles", [])
    if not isinstance(tiles_raw, list) or len(tiles_raw) > 91:
        raise ShipDesignError("tiles must be a list (max 91).")
    tiles: list[dict] = []
    occupied: set[tuple[int, int]] = set()
    for index, entry in enumerate(tiles_raw):
        tile = _normalize_tile(entry, index)
        key = (tile["q"], tile["r"])
        if key in occupied:
            raise ShipDesignError(f"Two tiles occupy hex ({key[0]},{key[1]}).")
        occupied.add(key)
        tiles.append(tile)

    upgrade = raw.get("upgrade") or None
    if upgrade is not None and upgrade not in SHIP_UPGRADES:
        raise ShipDesignError(f"upgrade must be one of {', '.join(SHIP_UPGRADES)}.")

    return {
        "id": design_id,
        "name": name[:80],
        "description": str(raw.get("description", ""))[:500],
        "tiles": tiles,
        "lanes": _normalize_lanes(raw.get("lanes")),
        "lane_numbers": _normalize_lane_numbers(raw.get("lane_numbers")),
        "upgrade": upgrade,
    }


# ── design-quality validation (warnings, never fatal) ───────────────────────


def _active_lane_numbers(design: dict) -> dict[str, int]:
    numbers: dict[str, int] = {}
    for default_roll, direction in PRIMARY_LANE_DIRS.items():
        lane_id = primary_lane_id(direction)
        numbers[lane_id] = lane_number(design, lane_id, default_roll)
    for default_roll, lane in secondary_lanes(design).items():
        direction = int(lane["dir"])
        cells = lane_cells(int(lane["q"]), int(lane["r"]), direction)
        lane_id = secondary_lane_id(cells, direction)
        numbers[lane_id] = lane_number(design, lane_id, default_roll)
    return numbers


def _connected(hexes: set[tuple[int, int]]) -> bool:
    if not hexes:
        return True
    stack = [next(iter(hexes))]
    seen = {stack[0]}
    while stack:
        q, r = stack.pop()
        for dq, dr in AXIAL_DIRECTIONS:
            neighbor = (q + dq, r + dr)
            if neighbor in hexes and neighbor not in seen:
                seen.add(neighbor)
                stack.append(neighbor)
    return seen == hexes


def validate_design(design: dict, config: dict | None = None) -> list[str]:
    """Human-readable warnings for a normalized design. A design is
    battle-ready only when this list is empty. `config` defaults to the
    admin-configured StarDock rule numbers."""
    if config is None:
        config = design.get("config") or active_stardock_config()
    config = stardock_config({"config": config})  # fill any missing keys with defaults
    design = {**design, "config": config}
    problems: list[str] = []
    tiles = design["tiles"]
    footprint = {(tile["q"], tile["r"]) for tile in tiles}

    counts: dict[str, int] = {}
    for tile in tiles:
        counts[tile["type"]] = counts.get(tile["type"], 0) + 1

    legacy = sorted(set(counts) & set(LEGACY_TILE_TYPES))
    if legacy:
        problems.append(
            "This design uses retired tile types from before the StarDock overhaul: "
            + ", ".join(legacy)
            + ". Replace them with current components."
        )

    if not tiles:
        problems.append("The ship has no tiles yet.")
    elif not _connected(footprint):
        problems.append("All ship tiles must be contiguous — the hull is not fully connected.")

    cores = counts.get("core", 0)
    if cores != 1:
        problems.append(
            "The ship needs exactly 1 Core." if cores == 0 else "The ship may only have 1 Core."
        )
    life_supports = counts.get("life_support", 0)
    if life_supports != REQUIRED_LIFE_SUPPORTS:
        problems.append(f"The ship needs exactly {REQUIRED_LIFE_SUPPORTS} Life Supports (it has {life_supports}).")
    if counts.get("bone_room", 0) != 1:
        problems.append(f"The ship needs exactly 1 Bone Room (it has {counts.get('bone_room', 0)}).")
    if counts.get("docking_bay", 0) != 1:
        problems.append(f"The ship needs exactly 1 Docking Bay (it has {counts.get('docking_bay', 0)}).")

    max_tiles = config["max_tiles"]
    if len(tiles) != max_tiles:
        problems.append(f"A battle-ready ship places exactly {max_tiles} tiles (it has {len(tiles)}).")
    structure_allowed = max_tiles - BASE_TILE_TOTAL
    if counts.get("structure", 0) != structure_allowed:
        if structure_allowed == 0:
            if counts.get("structure", 0):
                problems.append("Structure tiles are only allowed when the admin raises the tile total above 15.")
        else:
            problems.append(
                f"Place exactly {structure_allowed} Structure tiles (it has {counts.get('structure', 0)})."
            )

    deck_components = deck_component_count(design)
    if deck_components != DECK_SIZE:
        problems.append(
            f"Place exactly {DECK_SIZE} Engine/Cannon components — they form the 10-card deck "
            f"(it has {deck_components})."
        )
    spent = core_points_spent(design)
    budget = core_points_budget(design)
    if spent > budget:
        problems.append(
            f"Engine/Cannon components cost {spent} Core Component points — over the {budget}-point budget."
        )

    core = core_tile(design)
    primary_limit = config["primary_lane_limit"]
    if core is not None and primary_lane_tile_count(design) > primary_limit:
        problems.append(
            f"At most {primary_limit} components (plus the Core) may sit on the primary damage lanes "
            f"through the Core (it has {primary_lane_tile_count(design)})."
        )

    lanes = secondary_lanes(design)
    missing = [str(roll) for roll in SECONDARY_LANE_ROLLS if roll not in lanes]
    if missing:
        problems.append(f"Place all 6 secondary damage lanes (missing: {', '.join(missing)}).")
    min_severed = config["secondary_lane_min_severed"]
    seen_lines: dict[tuple, int] = {}
    for roll in sorted(lanes):
        lane = lanes[roll]
        cells = lane_cells(int(lane["q"]), int(lane["r"]), int(lane["dir"]))
        line_key = (cells[0], int(lane["dir"]) % 6)
        if line_key in seen_lines:
            problems.append(f"Lanes {seen_lines[line_key]} and {roll} are the same line and direction.")
        seen_lines[line_key] = roll
        if core is not None and (core["q"], core["r"]) in cells:
            problems.append(f"Secondary lane {roll} passes through the Core — that line is a primary lane.")
            continue
        if core is not None and lane_severed_count(design, cells) < min_severed:
            problems.append(
                f"Secondary lane {roll} must be placed so shooting fully through it severs at least "
                f"{min_severed} non-core components from the Core."
            )

    active_numbers = _active_lane_numbers(design)
    if len(active_numbers) == 12:
        values = list(active_numbers.values())
        if sorted(values) != list(range(1, 13)):
            problems.append("Lane numbering must assign each damage lane a unique number from 1 to 12.")

    if design.get("upgrade") not in SHIP_UPGRADES:
        problems.append("Choose the ship's special upgrade.")

    return problems


def is_design_valid(design: dict) -> bool:
    """Playable = normalized and free of design problems."""
    return not validate_design(design)


# ── storage ─────────────────────────────────────────────────────────────────
# Bundled developer designs live under resources/ship_designs. Runtime
# server/admin/player saves live under .starshot/content/ship_designs. Every
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
    except ShipDesignError:
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
            except ShipDesignError:
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
        points = None
        upgrade = None
        try:
            design = normalize_design(data)
            valid = is_design_valid(design)
            points = points_breakdown(design)["core_points_spent"]
            upgrade = design.get("upgrade")
        except ShipDesignError:
            valid = False
        entries.append(
            {
                "id": record["visible_id"],
                "source_id": data.get("id", record["id"]),
                "name": data.get("name", record["visible_id"]),
                "tile_count": len(data.get("tiles", [])),
                "points": points,
                "upgrade": upgrade,
                "valid": valid,
                "source": record["source"],
                "conflict_of": record["conflict_of"],
            }
        )
    return entries


def list_player_owner_ids() -> list[int]:
    """User ids that have at least one saved ship design."""
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
    directory = _runtime_design_dir(owner_id)
    if owner_id is not None and not _design_path(design["id"], owner_id).exists():
        existing_ids = {entry["id"] for entry in list_designs(owner_id)}
        if design["id"] not in existing_ids and len(existing_ids) >= PLAYER_DESIGN_LIMIT:
            raise ShipDesignError(
                f"You already have {PLAYER_DESIGN_LIMIT} ship designs — delete one to make room."
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
        raise ShipDesignError("No such player ship design.")
    design["id"] = unique_design_id(design["id"], None)
    if new_name:
        design["name"] = str(new_name).strip()[:80] or design["name"]
    return save_design(design, None)
