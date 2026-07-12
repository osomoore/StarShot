"""Admin console API: deck editor, keyword manager, project download.

Access is restricted to the admin account (username ``davidmoore`` by
default, override with the STARSHOT_ADMINS env var, comma-separated). The
account is auto-seeded on first use with the site password so it exists
before anyone can squat the name; change it from the console afterwards.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import tomllib
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from starshot.rules.custom_keywords import (
    compile_keyword,
    load_custom_keywords,
    run_keyword,
    save_custom_keywords,
)
from starshot.rules.deck_data import clear_catalog_cache, load_deck_catalog
from starshot.v2 import security
from starshot.v2.service import CORE_0_3_PATH
from starshot.v2.store import get_v2_store

ROOT = Path(__file__).resolve().parents[3]

admin_router = APIRouter(prefix="/api/v2/admin", tags=["v2-admin"])

DEFAULT_ADMINS = "davidmoore"
SEED_ADMIN_PASSWORD = "rangers"

DECK_FILES = {"base": "base_deck.toml", "desperation": "desperation_deck.toml"}


def admin_usernames() -> set[str]:
    return {name.strip().lower() for name in os.environ.get("STARSHOT_ADMINS", DEFAULT_ADMINS).split(",") if name.strip()}


def ensure_admin_seeded() -> None:
    store = get_v2_store()
    for name in admin_usernames():
        if store.get_user_by_name(name) is None:
            store.create_user(name, security.hash_password(SEED_ADMIN_PASSWORD))


def _admin_user(request: Request) -> dict:
    from starshot.v2.router import _current_user

    ensure_admin_seeded()
    user = _current_user(request)
    if user["username"].lower() not in admin_usernames():
        raise HTTPException(status_code=403, detail="Captain's quarters — admins only.")
    return user


# ── deck editor ────────────────────────────────────────────────────────────


def _toml_escape(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _serialize_deck_toml(header: dict, cards: list[dict]) -> str:
    lines: list[str] = []
    for key, value in header.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (int, float)):
            rendered = str(value)
        else:
            rendered = _toml_escape(str(value))
        lines.append(f"{key} = {rendered}")
    for card in cards:
        lines.append("")
        lines.append("[[cards]]")
        ordered = ["name", "copies", "side_a_type", "side_a_1", "side_a_2", "side_b_type", "side_b_1", "side_b_2"]
        keys = [key for key in ordered if key in card] + [key for key in card if key not in ordered]
        for key in keys:
            value = card[key]
            if value is None or value == "":
                continue
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            elif isinstance(value, int):
                rendered = str(value)
            else:
                rendered = _toml_escape(str(value))
            lines.append(f"{key} = {rendered}")
    return "\n".join(lines) + "\n"


def _read_deck_file(which: str) -> dict:
    path = CORE_0_3_PATH / DECK_FILES[which]
    data = tomllib.loads(path.read_text())
    cards = data.pop("cards", [])
    return {"header": data, "cards": cards, "raw": path.read_text()}


def _read_rules_config_file() -> dict:
    path = CORE_0_3_PATH / "config.toml"
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        data = {}
    return {
        "overheat_pile": str(data.get("overheat_pile", "no")).strip().lower() in {"yes", "true", "on", "1"},
        "allow_mixed_card_type_stacks": str(data.get("allow_mixed_card_type_stacks", "no")).strip().lower() in {"yes", "true", "on", "1"},
        "overdrive_style": str(data.get("overdrive_style", "copy_action")).strip() or "copy_action",
        "allow_overdrive_desperation": str(data.get("allow_overdrive_desperation", "no")).strip().lower() in {"yes", "true", "on", "1"},
    }


def _write_rules_config_file(config: dict) -> None:
    path = CORE_0_3_PATH / "config.toml"
    text = (
        f"overheat_pile = {_toml_escape('yes' if config.get('overheat_pile') else 'no')}\n"
        f"allow_mixed_card_type_stacks = {_toml_escape('yes' if config.get('allow_mixed_card_type_stacks') else 'no')}\n"
        f"overdrive_style = {_toml_escape(config.get('overdrive_style') or 'copy_action')}\n"
        f"allow_overdrive_desperation = {_toml_escape('yes' if config.get('allow_overdrive_desperation') else 'no')}\n"
    )
    path.write_text(text, encoding="utf-8")


def _validate_deck_candidate(which: str, toml_text: str) -> None:
    """Validate by loading a scratch copy of the whole deck set."""
    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        for name in ("manifest.toml", "config.toml", *DECK_FILES.values()):
            shutil.copy(CORE_0_3_PATH / name, temp_path / name)
        (temp_path / DECK_FILES[which]).write_text(toml_text)
        load_deck_catalog(temp_path)  # raises ValueError with a precise message


def _deck_sets_payload() -> list[dict]:
    from starshot.v2.service import core_deck_path, scan_deck_sets

    active = str(core_deck_path().resolve())
    sets = scan_deck_sets()
    for deck_set in sets:
        deck_set["active"] = deck_set["path"] == active
    return sets


@admin_router.get("/deck")
def get_deck(request: Request) -> dict:
    _admin_user(request)
    import tomllib

    active_manifest = {}
    try:
        active_manifest = tomllib.loads((CORE_0_3_PATH / "manifest.toml").read_text())
    except (OSError, ValueError):
        pass
    return {
        "deck_path": str(CORE_0_3_PATH),
        "active_id": active_manifest.get("id"),
        "active_name": active_manifest.get("name"),
        "sets": _deck_sets_payload(),
        "base": _read_deck_file("base"),
        "desperation": _read_deck_file("desperation"),
    }


class DeckSaveAs(BaseModel):
    name: str = Field(min_length=2, max_length=40)


@admin_router.post("/deck/save-as")
def deck_save_as(body: DeckSaveAs, request: Request) -> dict:
    """Snapshot the active deck set's cards under a new name."""
    import re as _re

    from starshot.v2.service import CUSTOM_DECKS_ROOT

    _admin_user(request)
    slug = _re.sub(r"[^a-z0-9]+", "_", body.name.lower()).strip("_")
    if not slug:
        raise HTTPException(status_code=400, detail="Give the deck a pronounceable name.")
    target = CUSTOM_DECKS_ROOT / slug
    target.mkdir(parents=True, exist_ok=True)
    import tomllib

    source_manifest = tomllib.loads((CORE_0_3_PATH / "manifest.toml").read_text())
    manifest_text = (
        f'id = "custom_{slug}"\n'
        f"name = {_toml_escape(body.name)}\n"
        f'rules_version = {_toml_escape(source_manifest.get("rules_version", "0.3"))}\n'
        f"description = {_toml_escape('Custom deck set saved from the admin console.')}\n"
    )
    (target / "manifest.toml").write_text(manifest_text)
    for name in ("config.toml", "base_deck.toml", "desperation_deck.toml"):
        shutil.copy(CORE_0_3_PATH / name, target / name)
    try:
        load_deck_catalog(target)
    except ValueError as exc:
        shutil.rmtree(target, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Saved deck failed validation: {exc}")
    clear_catalog_cache()
    return {"ok": True, "id": f"custom_{slug}", "sets": _deck_sets_payload()}


class DeckActivate(BaseModel):
    id: str = Field(min_length=1, max_length=80)


@admin_router.post("/deck/activate")
def deck_activate(body: DeckActivate, request: Request) -> dict:
    """Choose the deck set NEW games use. Games in flight keep their own set."""
    from starshot.v2.service import scan_deck_sets
    from starshot.v2.settings import ACTIVE_DECK_KEY, invalidate_cache

    _admin_user(request)
    match = next((s for s in scan_deck_sets() if s["id"] == body.id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="No deck set with that id.")
    try:
        load_deck_catalog(Path(match["path"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"That deck set fails validation: {exc}")
    get_v2_store().set_setting(ACTIVE_DECK_KEY, match["path"])
    invalidate_cache()
    clear_catalog_cache()
    return {"ok": True, "sets": _deck_sets_payload()}


class DeckUpdate(BaseModel):
    which: str = Field(pattern="^(base|desperation)$")
    header: dict
    cards: list[dict] = Field(max_length=200)


@admin_router.put("/deck")
def put_deck(body: DeckUpdate, request: Request) -> dict:
    _admin_user(request)
    toml_text = _serialize_deck_toml(body.header, body.cards)
    try:
        _validate_deck_candidate(body.which, toml_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    (CORE_0_3_PATH / DECK_FILES[body.which]).write_text(toml_text)
    clear_catalog_cache()
    return {"ok": True, "note": "Saved. New games use the updated deck; games already in flight that reference removed cards may fail to resolve."}


# ── keyword manager ────────────────────────────────────────────────────────

# Read-only mirror of the built-in phrases in rules/deck_data._phrase_spec,
# expressed in the same form as custom keywords so they can be copied.
BUILTIN_KEYWORDS = [
    {"name": "Move X", "pattern": r"move (\d+)",
     "code": "spec = FaceSpec(family=CardFamily.MOVE, value=int(match.group(1)), requires_target=False)"},
    {"name": "Move X Right (slip)", "pattern": r"move (\d+) right",
     "code": "spec = FaceSpec(family=CardFamily.MOVE, value=int(match.group(1)), orientation_options=('slip_right',), requires_target=False, side_slip_direction='right')"},
    {"name": "Move X Left (slip)", "pattern": r"move (\d+) left",
     "code": "spec = FaceSpec(family=CardFamily.MOVE, value=int(match.group(1)), orientation_options=('slip_left',), requires_target=False, side_slip_direction='left')"},
    {"name": "Move X then turn twice", "pattern": r"move (\d+) then turn (right|left) twice",
     "code": "spec = FaceSpec(family=CardFamily.MOVE, value=int(match.group(1)), orientation_options=('turn_' + match.group(2),), requires_target=False, double_turn_after_move=True)"},
    {"name": "U-Turn Move X", "pattern": r"u-turn(?: then)? move (\d+)",
     "code": "spec = FaceSpec(family=CardFamily.MOVE, value=int(match.group(1)), orientation_options=('u_turn_move',), requires_target=False, u_turn_move=True)"},
    {"name": "U-Turn Attack Damage +X", "pattern": r"u-turn attack damage \+(\d+)",
     "code": "spec = FaceSpec(family=CardFamily.ATTACK, value=0, orientation_options=('u_turn_attack',), requires_target=False, damage_bonus=int(match.group(1)), u_turn_attack=True)"},
    {"name": "Turn Left / Turn Right", "pattern": r"turn (left|right)",
     "code": "spec = FaceSpec(family=CardFamily.MOVE, value=0, orientation_options=('turn_' + match.group(1),), requires_target=False)"},
    {"name": "(Targeted) Attack", "pattern": r"(targeted )?attack",
     "code": "spec = FaceSpec(family=CardFamily.ATTACK, requires_target=bool(match.group(1)))"},
    {"name": "(Targeted) Attack Aim +X", "pattern": r"(targeted )?attack aim \+(\d+)",
     "code": "spec = FaceSpec(family=CardFamily.ATTACK, value=int(match.group(2)), requires_target=bool(match.group(1)), aim_bonus=int(match.group(2)))"},
    {"name": "(Targeted) Attack Damage +X", "pattern": r"(targeted )?attack damage \+(\d+)",
     "code": "spec = FaceSpec(family=CardFamily.ATTACK, value=0, requires_target=bool(match.group(1)), damage_bonus=int(match.group(2)))"},
    {"name": "Aim +X", "pattern": r"aim \+(\d+)",
     "code": "spec = FaceSpec(family=CardFamily.ATTACK, value=int(match.group(1)), requires_target=False, aim_bonus=int(match.group(1)))"},
    {"name": "Damage +X", "pattern": r"damage \+(\d+)",
     "code": "spec = FaceSpec(family=CardFamily.ATTACK, requires_target=False, damage_bonus=int(match.group(1)))"},
    {"name": "Defense +X", "pattern": r"defense \+(\d+)",
     "code": "spec = FaceSpec(family=CardFamily.MOVE, requires_target=False, defense_bonus=int(match.group(1)))"},
    {"name": "Range X", "pattern": r"range (\d+)",
     "code": "spec = FaceSpec(family=CardFamily.ATTACK, requires_target=False, max_range=int(match.group(1)))"},
    {"name": "Always Hits", "pattern": r"always hits",
     "code": "spec = FaceSpec(family=CardFamily.ATTACK, requires_target=False, aim_bonus=999, always_hits=True)"},
    {"name": "Attack All", "pattern": r"attack all",
     "code": "spec = FaceSpec(family=CardFamily.ATTACK, requires_target=False, attacks_all=True)"},
    {"name": "Warp Behind VP Leader", "pattern": r"warp behind vp leader",
     "code": "spec = FaceSpec(family=CardFamily.MOVE, requires_target=False, warp_destination='leader')"},
    {"name": "Move Overheat To Discard", "pattern": r"move overheat to discard",
     "code": "spec = FaceSpec(family=CardFamily.MOVE, requires_target=False, active_cooling=True)"},
    {"name": "Lead The Target", "pattern": r"lead the target",
     "code": "spec = FaceSpec(family=CardFamily.ATTACK, requires_target=False, lead_the_target=True)"},
]


@admin_router.get("/keywords")
def get_keywords(request: Request) -> dict:
    _admin_user(request)
    customs = load_custom_keywords()
    status = []
    for entry in customs:
        problem = None
        try:
            compile_keyword(entry)
        except ValueError as exc:
            problem = str(exc)
        status.append({**entry, "problem": problem})
    return {"builtins": BUILTIN_KEYWORDS, "customs": status}


class KeywordBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    pattern: str = Field(min_length=1, max_length=300)
    code: str = Field(min_length=1, max_length=4000)
    enabled: bool = True


@admin_router.post("/keywords")
def save_keyword(body: KeywordBody, request: Request) -> dict:
    _admin_user(request)
    entry = body.model_dump()
    try:
        compile_keyword(entry)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    customs = [existing for existing in load_custom_keywords() if existing.get("name") != body.name]
    customs.append(entry)
    save_custom_keywords(customs)
    clear_catalog_cache()
    return {"ok": True}


@admin_router.delete("/keywords/{name}")
def delete_keyword(name: str, request: Request) -> dict:
    _admin_user(request)
    customs = load_custom_keywords()
    remaining = [entry for entry in customs if entry.get("name") != name]
    if len(remaining) == len(customs):
        raise HTTPException(status_code=404, detail="No such keyword.")
    save_custom_keywords(remaining)
    clear_catalog_cache()
    return {"ok": True}


class KeywordTest(BaseModel):
    pattern: str
    code: str
    sample: str = Field(max_length=200)


@admin_router.post("/keywords/test")
def test_keyword(body: KeywordTest, request: Request) -> dict:
    _admin_user(request)
    entry = {"name": "(test)", "pattern": body.pattern, "code": body.code}
    sample = " ".join(body.sample.strip().lower().split())
    try:
        spec = run_keyword(entry, sample)
    except ValueError as exc:
        return {"matched": False, "error": str(exc)}
    if spec is None:
        return {"matched": False, "error": None}
    fields = {key: getattr(spec, key) for key in spec.__dataclass_fields__}  # type: ignore[attr-defined]
    fields = {key: (value if not hasattr(value, "value") else value.value) for key, value in fields.items()
              if value not in (None, 0, False, ()) or key in ("family", "value")}
    return {"matched": True, "error": None, "spec": {k: (list(v) if isinstance(v, tuple) else v) for k, v in fields.items()}}


# ── site settings ──────────────────────────────────────────────────────────


@admin_router.get("/settings")
def get_settings(request: Request) -> dict:
    from starshot.v2.settings import maintenance_message, site_auth_enabled

    _admin_user(request)
    return {
        "site_auth": site_auth_enabled(),
        "maintenance": maintenance_message(),
        "rules_config": _read_rules_config_file(),
    }


class SettingsUpdate(BaseModel):
    site_auth: bool | None = None
    maintenance: str | None = Field(default=None, max_length=500)
    allow_mixed_card_type_stacks: bool | None = None
    overdrive_style: str | None = Field(default=None, pattern="^(copy_action|combine_cards)$")
    allow_overdrive_desperation: bool | None = None


@admin_router.post("/settings")
def update_settings(body: SettingsUpdate, request: Request) -> dict:
    from starshot.v2.settings import (
        MAINTENANCE_KEY,
        SITE_AUTH_KEY,
        invalidate_cache,
        maintenance_message,
        site_auth_enabled,
    )

    _admin_user(request)
    store = get_v2_store()
    if body.site_auth is not None:
        store.set_setting(SITE_AUTH_KEY, "on" if body.site_auth else "off")
    if body.maintenance is not None:
        store.set_setting(MAINTENANCE_KEY, body.maintenance.strip())
    if (
        body.allow_mixed_card_type_stacks is not None
        or body.overdrive_style is not None
        or body.allow_overdrive_desperation is not None
    ):
        config = _read_rules_config_file()
        if body.allow_mixed_card_type_stacks is not None:
            config["allow_mixed_card_type_stacks"] = body.allow_mixed_card_type_stacks
        if body.overdrive_style is not None:
            config["overdrive_style"] = body.overdrive_style
        if body.allow_overdrive_desperation is not None:
            config["allow_overdrive_desperation"] = body.allow_overdrive_desperation
        _write_rules_config_file(config)
        try:
            load_deck_catalog(Path(str(CORE_0_3_PATH)))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Rules config failed validation: {exc}") from exc
        clear_catalog_cache()
    invalidate_cache()
    return {
        "site_auth": site_auth_enabled(),
        "maintenance": maintenance_message(),
        "rules_config": _read_rules_config_file(),
    }


# ── AI battle runner ───────────────────────────────────────────────────────


class AiBattleRequest(BaseModel):
    ai_types: list[str] = Field(min_length=2, max_length=4)


@admin_router.post("/ai-battle")
def ai_battle(body: AiBattleRequest, request: Request) -> dict:
    from starshot.v2.ai import AI_TYPES
    from starshot.v2.service import run_ai_battle

    user = _admin_user(request)
    for ai_type in body.ai_types:
        if ai_type not in AI_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown AI type: {ai_type}")
    return run_ai_battle(get_v2_store(), user, body.ai_types)


# ── project download ───────────────────────────────────────────────────────

_ZIP_EXCLUDE_DIRS = {".git", ".starshot", ".local", ".cache", ".config", ".claude",
                     ".pytest_cache", ".tmp_pdf_extract", "__pycache__", "node_modules"}
_ZIP_EXCLUDE_FILES = {".htpasswd", ".claude.json"}
_ZIP_EXCLUDE_SUFFIXES = (".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".log", ".pyc")


@admin_router.get("/download")
def download_project(request: Request) -> Response:
    _admin_user(request)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            parts = set(relative.parts[:-1])
            if parts & _ZIP_EXCLUDE_DIRS:
                continue
            if relative.name in _ZIP_EXCLUDE_FILES or relative.name.endswith(_ZIP_EXCLUDE_SUFFIXES):
                continue
            archive.writestr(f"StarShot/{relative}", path.read_bytes())
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="starshot-project.zip"'},
    )
