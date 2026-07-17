"""Player ship designs: schema, validation, and file storage.

A player ship design is a plain JSON document describing a custom player
ship: component tiles on a radius-2 hex grid (hex diameter 5, 19 spaces)
plus two designed stats — shield charges and base card draw. Ships are
priced in points (budget 19, matching the stock base ship exactly):

- 1 point per shield charge (0-3)
- 1 point per base card drawn (3-6)
- 1 point per non-core tile in a damage lane containing the core
  (the tiles on the three hex axes through the core)
- 1 point per Signal Jammer (+2 defense while intact, max 2)
- 1 point per Targeting Sensors (+2 Aim while intact, max 2)

A battle-ready ship places exactly 15 tiles (leaving 4 empty spaces),
including exactly 1 Core and exactly 2 Life Supports, fully connected,
within the point budget.

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
    MAX_DRAW,
    MAX_SHIELDS,
    MAX_SIGNAL_JAMMERS,
    MAX_TARGETING_SENSORS,
    MIN_DRAW,
    MIN_SHIELDS,
    PLAYER_SHIP_GRID_RADIUS,
    PLAYER_SHIP_MAX_TILES,
    PLAYER_SHIP_POINT_BUDGET,
    PLAYER_TILE_TYPES,
    REQUIRED_LIFE_SUPPORTS,
    points_breakdown,
)

ROOT = Path(__file__).resolve().parents[3]
DESIGNS_DIR = ROOT / "resources" / "ship_designs"
RUNTIME_DESIGNS_DIR = ROOT / ".starshot" / "content" / "ship_designs"

# Mirrors backend/starshot/rules/hex.py (and board.js).
AXIAL_DIRECTIONS = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))

GRID_RADIUS = PLAYER_SHIP_GRID_RADIUS
TILE_TYPES = PLAYER_TILE_TYPES

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
        "shields": 2,
        "draw": 5,
        "tiles": [],
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
    if tile_type not in TILE_TYPES:
        raise ShipDesignError(f"{label}.type must be one of {', '.join(TILE_TYPES)}.")
    return {"q": q, "r": r, "type": tile_type}


def normalize_design(raw: dict) -> dict:
    """Canonical copy of `raw`, or raise ShipDesignError."""
    if not isinstance(raw, dict):
        raise ShipDesignError("Design must be a JSON object.")
    design_id = safe_design_id(raw.get("id", ""))
    name = str(raw.get("name", "")).strip()
    if not name:
        raise ShipDesignError("Design needs a name.")

    shields = _as_int(raw.get("shields", 2), "shields")
    if not MIN_SHIELDS <= shields <= MAX_SHIELDS:
        raise ShipDesignError(f"shields must be {MIN_SHIELDS}-{MAX_SHIELDS}.")
    draw = _as_int(raw.get("draw", 5), "draw")
    if not MIN_DRAW <= draw <= MAX_DRAW:
        raise ShipDesignError(f"draw must be {MIN_DRAW}-{MAX_DRAW}.")

    tiles_raw = raw.get("tiles", [])
    if not isinstance(tiles_raw, list) or len(tiles_raw) > 40:
        raise ShipDesignError("tiles must be a list (max 40).")
    tiles: list[dict] = []
    occupied: set[tuple[int, int]] = set()
    for index, entry in enumerate(tiles_raw):
        tile = _normalize_tile(entry, index)
        key = (tile["q"], tile["r"])
        if key in occupied:
            raise ShipDesignError(f"Two tiles occupy hex ({key[0]},{key[1]}).")
        occupied.add(key)
        tiles.append(tile)

    return {
        "id": design_id,
        "name": name[:80],
        "description": str(raw.get("description", ""))[:500],
        "shields": shields,
        "draw": draw,
        "tiles": tiles,
    }


# ── design-quality validation (warnings, never fatal) ───────────────────────


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


def validate_design(design: dict) -> list[str]:
    """Human-readable warnings for a normalized design. A design is
    battle-ready only when this list is empty."""
    problems: list[str] = []
    tiles = design["tiles"]
    footprint = {(tile["q"], tile["r"]) for tile in tiles}

    counts: dict[str, int] = {}
    for tile in tiles:
        counts[tile["type"]] = counts.get(tile["type"], 0) + 1

    if not tiles:
        problems.append("The ship has no tiles yet.")
    elif not _connected(footprint):
        problems.append("The hull is not fully connected.")

    cores = counts.get("core", 0)
    if cores != 1:
        problems.append(
            "The ship needs exactly 1 Core." if cores == 0 else "The ship may only have 1 Core."
        )
    life_supports = counts.get("life_support", 0)
    if life_supports != REQUIRED_LIFE_SUPPORTS:
        problems.append(f"The ship needs exactly {REQUIRED_LIFE_SUPPORTS} Life Supports (it has {life_supports}).")

    if len(tiles) != PLAYER_SHIP_MAX_TILES:
        problems.append(
            f"A battle-ready ship places exactly {PLAYER_SHIP_MAX_TILES} tiles (it has {len(tiles)})."
        )
    if counts.get("signal_jammer", 0) > MAX_SIGNAL_JAMMERS:
        problems.append(f"At most {MAX_SIGNAL_JAMMERS} Signal Jammers are allowed.")
    if counts.get("targeting_sensors", 0) > MAX_TARGETING_SENSORS:
        problems.append(f"At most {MAX_TARGETING_SENSORS} Targeting Sensors are allowed.")

    breakdown = points_breakdown(design)
    if breakdown["total"] > PLAYER_SHIP_POINT_BUDGET:
        problems.append(
            f"The design costs {breakdown['total']} points — over the {PLAYER_SHIP_POINT_BUDGET}-point budget."
        )

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
        try:
            design = normalize_design(data)
            valid = is_design_valid(design)
            points = points_breakdown(design)["total"]
        except ShipDesignError:
            valid = False
        entries.append(
            {
                "id": record["visible_id"],
                "source_id": data.get("id", record["id"]),
                "name": data.get("name", record["visible_id"]),
                "tile_count": len(data.get("tiles", [])),
                "shields": data.get("shields"),
                "draw": data.get("draw"),
                "points": points,
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
