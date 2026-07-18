"""Admin console API: deck editor, keyword manager, project download.

Access is restricted to the admin account (username ``davidmoore`` by
default, override with the STARSHOT_ADMINS env var, comma-separated). The
account is auto-seeded on first use with the site password so it exists
before anyone can squat the name; change it from the console afterwards.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import tomllib
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
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
AI_CHANGELOG_PATH = ROOT / "docs" / "context" / "ai_changelog.md"

admin_router = APIRouter(prefix="/api/v2/admin", tags=["v2-admin"])

DEFAULT_ADMINS = "davidmoore"
SEED_ADMIN_PASSWORD = "rangers"

DECK_FILES = {"base": "base_deck.toml", "desperation": "desperation_deck.toml"}
DECK_SET_FILES = ("manifest.toml", "config.toml", "base_deck.toml", "desperation_deck.toml")
_AI_BATCH_JOBS: dict[str, dict] = {}
_AI_BATCH_JOBS_LOCK = threading.Lock()


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


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "deck_set"


def _serialize_toml_table(data: dict) -> str:
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (int, float)):
            rendered = str(value)
        else:
            rendered = _toml_escape(str(value))
        lines.append(f"{key} = {rendered}")
    return "\n".join(lines) + "\n"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _admin_build_id() -> str | None:
    env_build = os.environ.get("STARSHOT_BUILD_ID") or os.environ.get("STARSHOT_BUILD_NUMBER")
    if env_build:
        return env_build
    git_dir = ROOT / ".git"
    head_path = git_dir / "HEAD"
    try:
        head = head_path.read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref_path = git_dir / head.split(" ", 1)[1]
            head = ref_path.read_text(encoding="utf-8").strip()
        return head[:12] if head else None
    except OSError:
        return None


def _read_manifest(path: Path) -> dict:
    return tomllib.loads((path / "manifest.toml").read_text(encoding="utf-8"))


def _write_manifest(path: Path, manifest: dict) -> None:
    (path / "manifest.toml").write_text(_serialize_toml_table(manifest), encoding="utf-8")


def _touch_deck_set(path: Path, *, uploaded: bool = False) -> dict:
    manifest = _read_manifest(path)
    now = _now_iso()
    if uploaded:
        manifest["uploaded_at"] = now
    manifest["modified_at"] = now
    _write_manifest(path, manifest)
    return manifest


def _deck_set_slug_from_manifest(path: Path) -> str:
    try:
        manifest = _read_manifest(path)
    except (OSError, tomllib.TOMLDecodeError):
        return _safe_slug(path.name)
    return _safe_slug(str(manifest.get("id") or path.name).removeprefix("custom_"))


def _editable_active_deck_path() -> Path:
    """Return a runtime deck-set path safe for admin writes.

    Bundled deck sets remain developer content. If the active deck is bundled,
    copy it into the runtime custom deck root and make that copy active before
    writing.
    """
    from starshot.v2.service import CUSTOM_DECKS_ROOT, custom_decks_root
    from starshot.v2.settings import ACTIVE_DECK_KEY, invalidate_cache

    active = Path(str(CORE_0_3_PATH)).resolve()
    runtime_root = custom_decks_root().resolve()
    try:
        active.relative_to(runtime_root)
        return active
    except ValueError:
        pass

    target = Path(str(CUSTOM_DECKS_ROOT)) / _deck_set_slug_from_manifest(active)
    if not target.exists():
        target.mkdir(parents=True, exist_ok=True)
        for filename in DECK_SET_FILES:
            shutil.copy(active / filename, target / filename)
        custom_keywords = active / "custom_keywords.json"
        if custom_keywords.exists():
            shutil.copy(custom_keywords, target / "custom_keywords.json")
    get_v2_store().set_setting(ACTIVE_DECK_KEY, str(target.resolve()))
    invalidate_cache()
    return target


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


def _read_deck_file(which: str, deck_path: Path | None = None) -> dict:
    path = (deck_path or Path(str(CORE_0_3_PATH))) / DECK_FILES[which]
    data = tomllib.loads(path.read_text())
    cards = data.pop("cards", [])
    return {"header": data, "cards": cards, "raw": path.read_text()}


def _read_rules_config_file(deck_path: Path | None = None) -> dict:
    path = (deck_path or Path(str(CORE_0_3_PATH))) / "config.toml"
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


def _write_rules_config_file(config: dict, deck_path: Path | None = None) -> None:
    path = (deck_path or Path(str(CORE_0_3_PATH))) / "config.toml"
    text = (
        f"overheat_pile = {_toml_escape('yes' if config.get('overheat_pile') else 'no')}\n"
        f"allow_mixed_card_type_stacks = {_toml_escape('yes' if config.get('allow_mixed_card_type_stacks') else 'no')}\n"
        f"overdrive_style = {_toml_escape(config.get('overdrive_style') or 'copy_action')}\n"
        f"allow_overdrive_desperation = {_toml_escape('yes' if config.get('allow_overdrive_desperation') else 'no')}\n"
    )
    path.write_text(text, encoding="utf-8")


def _validate_deck_candidate(which: str, toml_text: str, deck_path: Path | None = None) -> None:
    """Validate by loading a scratch copy of the whole deck set."""
    source = deck_path or Path(str(CORE_0_3_PATH))
    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        for name in ("manifest.toml", "config.toml", *DECK_FILES.values()):
            shutil.copy(source / name, temp_path / name)
        (temp_path / DECK_FILES[which]).write_text(toml_text)
        load_deck_catalog(temp_path)  # raises ValueError with a precise message


def _deck_sets_payload() -> list[dict]:
    from starshot.v2.service import core_deck_path, scan_deck_sets

    active = str(core_deck_path().resolve())
    sets = scan_deck_sets()
    for deck_set in sets:
        deck_set["active"] = deck_set["path"] == active
    return sets


def _deck_set_by_id(deck_set_id: str) -> dict | None:
    from starshot.v2.service import materialize_runtime_deck_set, scan_deck_sets

    return next((deck_set for deck_set in scan_deck_sets() if deck_set["id"] == deck_set_id), None)


def _deletable_deck_set_path(deck_set: dict) -> Path:
    from starshot.v2.service import LEGACY_CUSTOM_DECKS_ROOT, custom_decks_root

    if not deck_set.get("custom"):
        raise HTTPException(status_code=400, detail="Stock deck sets cannot be deleted.")
    deck_path = Path(deck_set["path"]).resolve()
    allowed_roots = [custom_decks_root().resolve(), LEGACY_CUSTOM_DECKS_ROOT.resolve()]
    if not any(_path_is_under(deck_path, root) and deck_path != root for root in allowed_roots):
        raise HTTPException(status_code=400, detail="That deck set is outside the custom deck folders.")
    if not deck_path.is_dir():
        raise HTTPException(status_code=404, detail="Deck set folder is already gone.")
    return deck_path


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@contextmanager
def _temporary_keywords_file(path: Path | None):
    if path is None:
        yield
        return
    old = os.environ.get("STARSHOT_KEYWORDS_FILE")
    os.environ["STARSHOT_KEYWORDS_FILE"] = str(path)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("STARSHOT_KEYWORDS_FILE", None)
        else:
            os.environ["STARSHOT_KEYWORDS_FILE"] = old


def _bundle_member_names(archive: zipfile.ZipFile) -> dict[str, str]:
    files = [name for name in archive.namelist() if not name.endswith("/")]
    manifest_names = [name for name in files if Path(name).name == "manifest.toml"]
    if not manifest_names:
        raise ValueError("Deck set zip must contain manifest.toml.")
    manifest = sorted(manifest_names, key=lambda name: (name.count("/"), name))[0]
    prefix = manifest.removesuffix("manifest.toml")
    members: dict[str, str] = {}
    for filename in DECK_SET_FILES:
        candidate = prefix + filename
        if candidate not in files:
            raise ValueError(f"Deck set zip is missing {filename}.")
        members[filename] = candidate
    keyword_candidate = prefix + "custom_keywords.json"
    if keyword_candidate in files:
        members["custom_keywords.json"] = keyword_candidate
    return members


def _read_zip_member(archive: zipfile.ZipFile, member: str) -> bytes:
    info = archive.getinfo(member)
    if info.file_size > 2_000_000:
        raise ValueError(f"{Path(member).name} is too large for a deck set bundle.")
    return archive.read(info)


def _extract_deck_bundle(content: bytes, destination: Path) -> tuple[dict, list[dict] | None]:
    if len(content) > 8_000_000:
        raise ValueError("Deck set zip is too large.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ValueError("Upload a valid .zip deck set bundle.") from exc
    with archive:
        members = _bundle_member_names(archive)
        for filename in DECK_SET_FILES:
            (destination / filename).write_bytes(_read_zip_member(archive, members[filename]))
        try:
            manifest = tomllib.loads((destination / "manifest.toml").read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"Invalid manifest.toml: {exc}") from exc
        keywords = None
        keyword_member = members.get("custom_keywords.json")
        if keyword_member:
            try:
                data = json.loads(_read_zip_member(archive, keyword_member).decode("utf-8"))
                keywords = data.get("keywords", data if isinstance(data, list) else None)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid custom_keywords.json: {exc}") from exc
            if not isinstance(keywords, list):
                raise ValueError("custom_keywords.json must contain a keywords array.")
            for entry in keywords:
                if not isinstance(entry, dict):
                    raise ValueError("Each custom keyword must be an object.")
                compile_keyword(entry)
            (destination / "custom_keywords.json").write_text(json.dumps({"keywords": keywords}, indent=2), encoding="utf-8")
        return manifest, keywords


def _installable_manifest(manifest: dict) -> tuple[dict, str]:
    original_id = str(manifest.get("id") or "").strip()
    name = str(manifest.get("name") or original_id or "Imported Deck Set").strip()
    if not original_id:
        raise ValueError("manifest.toml.id must be a non-empty string.")
    installed_id = original_id
    existing = _deck_set_by_id(original_id)
    if not original_id.startswith("custom_") or (existing and not existing.get("custom")):
        installed_id = "custom_" + _safe_slug(original_id or name)
    installed = dict(manifest)
    installed["id"] = installed_id
    if installed_id != original_id and "Imported" not in name:
        installed["name"] = f"{name} Imported"
    return installed, installed_id


@admin_router.get("/deck")
def get_deck(request: Request) -> dict:
    _admin_user(request)
    import tomllib

    active_manifest = {}
    try:
        active_manifest = _read_manifest(Path(str(CORE_0_3_PATH)))
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
    now = _now_iso()
    manifest_text = (
        f'id = "custom_{slug}"\n'
        f"name = {_toml_escape(body.name)}\n"
        f'rules_version = {_toml_escape(source_manifest.get("rules_version", "0.3"))}\n'
        f"description = {_toml_escape('Custom deck set saved from the admin console.')}\n"
        f"uploaded_at = {_toml_escape(now)}\n"
        f"modified_at = {_toml_escape(now)}\n"
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


class DeckRename(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=80)


@admin_router.post("/deck/rename")
def deck_rename(body: DeckRename, request: Request) -> dict:
    """Rename a deck set for admin display; the stable deck-set id is unchanged."""
    from starshot.v2.service import materialize_runtime_deck_set

    _admin_user(request)
    deck_set = _deck_set_by_id(body.id)
    if deck_set is None:
        raise HTTPException(status_code=404, detail="No deck set with that id.")
    deck_set = materialize_runtime_deck_set(deck_set, force=True)
    deck_path = Path(deck_set["path"])
    try:
        manifest = _read_manifest(deck_path)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Cannot read that deck set manifest: {exc}") from exc
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Give the deck a pronounceable name.")
    manifest["name"] = name
    manifest["modified_at"] = _now_iso()
    _write_manifest(deck_path, manifest)
    clear_catalog_cache()
    return {"ok": True, "id": body.id, "name": manifest["name"], "sets": _deck_sets_payload()}


class DeckDeprecation(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    deprecated: bool


@admin_router.post("/deck/deprecation")
def deck_deprecation(body: DeckDeprecation, request: Request) -> dict:
    """Mark a deck set deprecated/restored without changing its stable id."""
    from starshot.v2.service import core_deck_path

    _admin_user(request)
    deck_set = _deck_set_by_id(body.id)
    if deck_set is None:
        raise HTTPException(status_code=404, detail="No deck set with that id.")
    deck_path = Path(deck_set["path"])
    if body.deprecated and deck_path.resolve() == core_deck_path().resolve():
        raise HTTPException(status_code=400, detail="Make another deck set active before deprecating this one.")
    try:
        manifest = _read_manifest(deck_path)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Cannot read that deck set manifest: {exc}") from exc
    manifest["deprecated"] = body.deprecated
    manifest["modified_at"] = _now_iso()
    _write_manifest(deck_path, manifest)
    clear_catalog_cache()
    return {"ok": True, "id": body.id, "deprecated": body.deprecated, "sets": _deck_sets_payload()}


class DeckActivate(BaseModel):
    id: str = Field(min_length=1, max_length=80)


@admin_router.post("/deck/activate")
def deck_activate(body: DeckActivate, request: Request) -> dict:
    """Choose the deck set NEW games use. Games in flight keep their own set."""
    from starshot.v2.service import materialize_runtime_deck_set, scan_deck_sets
    from starshot.v2.settings import ACTIVE_DECK_KEY, invalidate_cache

    _admin_user(request)
    match = next((s for s in scan_deck_sets() if s["id"] == body.id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="No deck set with that id.")
    if match.get("deprecated"):
        raise HTTPException(status_code=400, detail="Deprecated deck sets cannot be made active.")
    match = materialize_runtime_deck_set(match)
    try:
        load_deck_catalog(Path(match["path"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"That deck set fails validation: {exc}")
    get_v2_store().set_setting(ACTIVE_DECK_KEY, match["path"])
    invalidate_cache()
    clear_catalog_cache()
    return {"ok": True, "sets": _deck_sets_payload()}


@admin_router.delete("/deck/{deck_set_id}")
def deck_delete(deck_set_id: str, request: Request) -> dict:
    """Delete a custom deck set from server storage."""
    from starshot.v2.service import core_deck_path

    _admin_user(request)
    deck_set = _deck_set_by_id(deck_set_id)
    if deck_set is None:
        raise HTTPException(status_code=404, detail="No deck set with that id.")
    deck_path = _deletable_deck_set_path(deck_set)
    if deck_path == core_deck_path().resolve():
        raise HTTPException(status_code=400, detail="Make another deck set active before deleting this one.")
    try:
        shutil.rmtree(deck_path)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Could not delete deck set: {exc}") from exc
    clear_catalog_cache()
    return {"ok": True, "deleted": deck_set_id, "sets": _deck_sets_payload()}


@admin_router.get("/deck/export/{deck_set_id}")
def deck_export(deck_set_id: str, request: Request) -> Response:
    """Download a complete deck set bundle for offline editing."""
    _admin_user(request)
    deck_set = _deck_set_by_id(deck_set_id)
    if deck_set is None:
        raise HTTPException(status_code=404, detail="No deck set with that id.")
    deck_path = Path(deck_set["path"])
    try:
        load_deck_catalog(deck_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"That deck set fails validation: {exc}")

    buffer = io.BytesIO()
    root_name = _safe_slug(deck_set_id)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename in DECK_SET_FILES:
            archive.writestr(f"{root_name}/{filename}", (deck_path / filename).read_bytes())
        archive.writestr(
            f"{root_name}/custom_keywords.json",
            json.dumps({"keywords": load_custom_keywords()}, indent=2).encode("utf-8"),
        )
        archive.writestr(
            f"{root_name}/README.txt",
            (
                "StarShot deck set bundle.\n"
                "Edit manifest.toml, config.toml, base_deck.toml, desperation_deck.toml, "
                "and custom_keywords.json, then upload the zip in the admin deck editor.\n"
            ).encode("utf-8"),
        )
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="starshot-deck-set-{_safe_slug(deck_set_id)}.zip"'},
    )


@admin_router.post("/deck/import")
async def deck_import(request: Request, activate: bool = False) -> dict:
    """Upload, validate, and install a deck set bundle under custom decks."""
    from starshot.v2.service import CUSTOM_DECKS_ROOT
    from starshot.v2.settings import ACTIVE_DECK_KEY, invalidate_cache

    _admin_user(request)
    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        try:
            manifest, keywords = _extract_deck_bundle(await request.body(), temp_path)
            installed_manifest, installed_id = _installable_manifest(manifest)
            now = _now_iso()
            installed_manifest["uploaded_at"] = now
            installed_manifest["modified_at"] = now
            (temp_path / "manifest.toml").write_text(_serialize_toml_table(installed_manifest), encoding="utf-8")
            keyword_path = temp_path / "custom_keywords.json" if keywords is not None else None
            with _temporary_keywords_file(keyword_path):
                load_deck_catalog(temp_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        target = Path(str(CUSTOM_DECKS_ROOT)) / _safe_slug(installed_id.removeprefix("custom_"))
        staging = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.mkdir()
        for filename in DECK_SET_FILES:
            shutil.copy(temp_path / filename, staging / filename)
        try:
            if target.exists():
                shutil.rmtree(target)
            staging.replace(target)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    if keywords is not None:
        save_custom_keywords(keywords)
    clear_catalog_cache()
    if activate:
        get_v2_store().set_setting(ACTIVE_DECK_KEY, str(target.resolve()))
        invalidate_cache()
    return {
        "ok": True,
        "id": installed_id,
        "name": installed_manifest.get("name", installed_id),
        "activated": activate,
        "keywords_imported": keywords is not None,
        "sets": _deck_sets_payload(),
    }


class DeckUpdate(BaseModel):
    which: str = Field(pattern="^(base|desperation)$")
    header: dict
    cards: list[dict] = Field(max_length=200)


@admin_router.put("/deck")
def put_deck(body: DeckUpdate, request: Request) -> dict:
    _admin_user(request)
    deck_path = _editable_active_deck_path()
    toml_text = _serialize_deck_toml(body.header, body.cards)
    try:
        _validate_deck_candidate(body.which, toml_text, deck_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    (deck_path / DECK_FILES[body.which]).write_text(toml_text)
    _touch_deck_set(deck_path)
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
    from starshot.v2 import boss_designs
    from starshot.v2.settings import (
        allowed_starbreach_boss_design_ids,
        default_starbreach_boss_design_id,
        maintenance_message,
        site_auth_enabled,
        stardock_config,
    )

    _admin_user(request)
    playable_bosses = [
        {"id": entry["id"], "name": entry["name"], "valid": entry["valid"]}
        for entry in boss_designs.list_designs()
        if entry["valid"]
    ]
    return {
        "site_auth": site_auth_enabled(),
        "maintenance": maintenance_message(),
        "rules_config": _read_rules_config_file(),
        "star_breach": {
            "boss_designs": playable_bosses,
            "default_boss_design_id": default_starbreach_boss_design_id(),
            "allowed_boss_design_ids": sorted(allowed_starbreach_boss_design_ids()),
        },
        "stardock": stardock_config(),
    }


class SettingsUpdate(BaseModel):
    site_auth: bool | None = None
    maintenance: str | None = Field(default=None, max_length=500)
    allow_mixed_card_type_stacks: bool | None = None
    overdrive_style: str | None = Field(default=None, pattern="^(copy_action|combine_cards)$")
    allow_overdrive_desperation: bool | None = None
    default_starbreach_boss_design_id: str | None = Field(default=None, max_length=80)
    allowed_starbreach_boss_design_ids: list[str] | None = Field(default=None, max_length=200)
    # StarDock (player ship designer) rule numbers
    stardock_max_tiles: int | None = Field(default=None, ge=15, le=60)
    stardock_primary_lane_limit: int | None = Field(default=None, ge=0, le=40)
    stardock_secondary_lane_min_severed: int | None = Field(default=None, ge=0, le=12)
    stardock_upgrade_defense_bonus: int | None = Field(default=None, ge=0, le=10)
    stardock_upgrade_aim_bonus: int | None = Field(default=None, ge=0, le=10)


@admin_router.post("/settings")
def update_settings(body: SettingsUpdate, request: Request) -> dict:
    from starshot.v2 import boss_designs
    from starshot.v2.settings import (
        ALLOWED_STARBREACH_BOSSES_KEY,
        DEFAULT_STARBREACH_BOSS_KEY,
        MAINTENANCE_KEY,
        SITE_AUTH_KEY,
        STARDOCK_CONFIG_KEYS,
        invalidate_cache,
        maintenance_message,
        site_auth_enabled,
    )

    _admin_user(request)
    store = get_v2_store()
    if body.site_auth is not None:
        store.set_setting(SITE_AUTH_KEY, "on" if body.site_auth else "off")
    for stardock_key in STARDOCK_CONFIG_KEYS:
        value = getattr(body, f"stardock_{stardock_key}", None)
        if value is not None:
            store.set_setting(f"stardock_{stardock_key}", str(int(value)))
    if body.maintenance is not None:
        store.set_setting(MAINTENANCE_KEY, body.maintenance.strip())
    valid_boss_ids = {entry["id"] for entry in boss_designs.list_designs() if entry["valid"]}
    if body.allowed_starbreach_boss_design_ids is not None:
        allowed = []
        for boss_id in body.allowed_starbreach_boss_design_ids:
            boss_id = str(boss_id).strip()
            if not boss_id:
                continue
            if boss_id not in valid_boss_ids:
                raise HTTPException(status_code=400, detail=f"Unknown playable StarBreach boss: {boss_id}")
            if boss_id not in allowed:
                allowed.append(boss_id)
        store.set_setting(ALLOWED_STARBREACH_BOSSES_KEY, ",".join(allowed))
    if body.default_starbreach_boss_design_id is not None:
        default_boss = body.default_starbreach_boss_design_id.strip()
        if default_boss and default_boss not in valid_boss_ids:
            raise HTTPException(status_code=400, detail=f"Unknown playable StarBreach boss: {default_boss}")
        allowed_raw = store.get_setting(ALLOWED_STARBREACH_BOSSES_KEY) or ""
        allowed_now = {entry.strip() for entry in allowed_raw.split(",") if entry.strip()}
        if default_boss and allowed_now and default_boss not in allowed_now:
            raise HTTPException(status_code=400, detail="Default StarBreach boss must be in the allowed list.")
        store.set_setting(DEFAULT_STARBREACH_BOSS_KEY, default_boss)
    if (
        body.allow_mixed_card_type_stacks is not None
        or body.overdrive_style is not None
        or body.allow_overdrive_desperation is not None
    ):
        deck_path = _editable_active_deck_path()
        config = _read_rules_config_file(deck_path)
        if body.allow_mixed_card_type_stacks is not None:
            config["allow_mixed_card_type_stacks"] = body.allow_mixed_card_type_stacks
        if body.overdrive_style is not None:
            config["overdrive_style"] = body.overdrive_style
        if body.allow_overdrive_desperation is not None:
            config["allow_overdrive_desperation"] = body.allow_overdrive_desperation
        _write_rules_config_file(config, deck_path)
        try:
            load_deck_catalog(deck_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Rules config failed validation: {exc}") from exc
        _touch_deck_set(deck_path)
        clear_catalog_cache()
    invalidate_cache()
    settings_now = get_settings(request)
    return {
        "site_auth": site_auth_enabled(),
        "maintenance": maintenance_message(),
        "rules_config": _read_rules_config_file(),
        "star_breach": settings_now["star_breach"],
        "stardock": settings_now["stardock"],
    }


@admin_router.post("/server-update")
def server_update(request: Request) -> dict:
    _admin_user(request)
    flag_path = ROOT / ".starshot" / "pull_flag"
    flag_path.write_text("1")
    return {"ok": True, "note": "Server update requested. The container will pull and restart within 60 seconds."}


# ── AI battle runner ───────────────────────────────────────────────────────


class AiBattleRequest(BaseModel):
    ai_types: list[str] = Field(min_length=2, max_length=4)
    deck_set_id: str | None = Field(default=None, max_length=80)


@admin_router.post("/ai-battle")
def ai_battle(body: AiBattleRequest, request: Request) -> dict:
    from starshot.v2.ai import AI_TYPES
    from starshot.v2.service import run_ai_battle

    user = _admin_user(request)
    for ai_type in body.ai_types:
        if ai_type not in AI_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown AI type: {ai_type}")
    try:
        return run_ai_battle(get_v2_store(), user, body.ai_types, deck_set_id=body.deck_set_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class AiBattleBatchRequest(AiBattleRequest):
    run_count: int = Field(default=100, ge=1, le=500)


@admin_router.post("/ai-battle-batch")
def ai_battle_batch(body: AiBattleBatchRequest, request: Request) -> dict:
    from starshot.v2.ai import AI_TYPES
    from starshot.v2.service import run_ai_battle_batch

    user = _admin_user(request)
    for ai_type in body.ai_types:
        if ai_type not in AI_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown AI type: {ai_type}")
    try:
        return run_ai_battle_batch(
            get_v2_store(),
            user,
            body.ai_types,
            run_count=body.run_count,
            deck_set_id=body.deck_set_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _set_ai_batch_job(job_id: str, **changes) -> None:
    with _AI_BATCH_JOBS_LOCK:
        job = _AI_BATCH_JOBS.get(job_id)
        if job is not None:
            job.update(changes)


def _run_ai_batch_job(job_id: str, user: dict, body: AiBattleBatchRequest) -> None:
    from starshot.v2.service import run_ai_battle_batch

    def progress(completed: int, total: int) -> None:
        _set_ai_batch_job(job_id, completed=completed, remaining=max(0, total - completed), total=total)

    try:
        result = run_ai_battle_batch(
            get_v2_store(),
            user,
            body.ai_types,
            run_count=body.run_count,
            deck_set_id=body.deck_set_id,
            progress_callback=progress,
        )
        _set_ai_batch_job(
            job_id,
            status="complete",
            completed=body.run_count,
            remaining=0,
            result=result,
            history_entry_id=result.get("history_entry", {}).get("id"),
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the admin progress UI
        _set_ai_batch_job(job_id, status="error", error=str(exc))


@admin_router.post("/ai-battle-batch/jobs")
def ai_battle_batch_job(body: AiBattleBatchRequest, request: Request, background_tasks: BackgroundTasks) -> dict:
    from starshot.v2.ai import AI_TYPES

    user = _admin_user(request)
    for ai_type in body.ai_types:
        if ai_type not in AI_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown AI type: {ai_type}")
    job_id = uuid.uuid4().hex[:12]
    with _AI_BATCH_JOBS_LOCK:
        _AI_BATCH_JOBS[job_id] = {
            "id": job_id,
            "status": "running",
            "total": body.run_count,
            "completed": 0,
            "remaining": body.run_count,
            "result": None,
            "error": None,
        }
    background_tasks.add_task(_run_ai_batch_job, job_id, user, body)
    return dict(_AI_BATCH_JOBS[job_id])


@admin_router.get("/ai-battle-batch/jobs/{job_id}")
def ai_battle_batch_job_status(job_id: str, request: Request) -> dict:
    _admin_user(request)
    with _AI_BATCH_JOBS_LOCK:
        job = _AI_BATCH_JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="AI batch job not found.")
        return dict(job)


@admin_router.get("/ai-battles")
def ai_battle_history(request: Request) -> dict:
    _admin_user(request)
    return {"entries": get_v2_store().list_ai_battle_runs()}


@admin_router.get("/ai-battles/{entry_id}")
def ai_battle_detail(entry_id: str, request: Request) -> dict:
    _admin_user(request)
    entry = get_v2_store().get_ai_battle_run(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="AI battle entry not found.")
    return {"entry": entry}


# ── account moderation ─────────────────────────────────────────────────────


@admin_router.get("/accounts")
def list_accounts(request: Request) -> dict:
    _admin_user(request)
    store = get_v2_store()
    return {"accounts": store.list_accounts(), "illegal_names": store.list_illegal_names()}


class AccountFlags(BaseModel):
    matchmaking_ok: bool | None = None
    leaderboard_ok: bool | None = None


@admin_router.post("/accounts/{user_id}/flags")
def set_account_flags(user_id: int, body: AccountFlags, request: Request) -> dict:
    _admin_user(request)
    store = get_v2_store()
    if store.get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found.")
    store.set_user_flags(
        user_id,
        matchmaking_ok=body.matchmaking_ok,
        leaderboard_ok=body.leaderboard_ok,
    )
    return {"ok": True, "accounts": store.list_accounts()}


@admin_router.post("/accounts/{user_id}/ban-name")
def ban_account_name(user_id: int, request: Request) -> dict:
    """Add the player's current display name to the illegal list. Everyone
    wearing that name is flagged (hidden/unmatched) and must rename next time
    they reach the lobby."""
    _admin_user(request)
    store = get_v2_store()
    user = store.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    banned_name = user.get("display_name") or user["username"]
    affected = store.add_illegal_name(banned_name)
    return {
        "ok": True,
        "banned_name": banned_name,
        "affected_accounts": affected,
        "accounts": store.list_accounts(),
        "illegal_names": store.list_illegal_names(),
    }


@admin_router.delete("/illegal-names/{name}")
def remove_illegal_name(name: str, request: Request) -> dict:
    _admin_user(request)
    store = get_v2_store()
    if not store.remove_illegal_name(name):
        raise HTTPException(status_code=404, detail="That name isn't on the illegal list.")
    return {"ok": True, "illegal_names": store.list_illegal_names()}


@admin_router.get("/feedback")
def feedback_summary(request: Request) -> dict:
    _admin_user(request)
    return {"entries": get_v2_store().list_feedback_latest_by_user()}


@admin_router.get("/feedback/users/{user_id}")
def feedback_for_user(user_id: int, request: Request) -> dict:
    _admin_user(request)
    user = get_v2_store().get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return {
        "user": {"id": user["id"], "username": user["username"]},
        "entries": get_v2_store().feedback_for_user(user_id),
    }


@admin_router.delete("/feedback/{feedback_id}")
def delete_feedback(feedback_id: str, request: Request) -> dict:
    _admin_user(request)
    deleted = get_v2_store().delete_feedback(feedback_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Feedback entry not found.")
    return {"ok": True, "deleted": deleted}


@admin_router.delete("/feedback/users/{user_id}")
def delete_feedback_for_user(user_id: int, request: Request) -> dict:
    _admin_user(request)
    user = get_v2_store().get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    deleted = get_v2_store().delete_feedback_for_user(user_id)
    return {"ok": True, "deleted": deleted}


# ── project download ───────────────────────────────────────────────────────

@admin_router.get("/ai-changelog")
def ai_changelog(request: Request) -> dict:
    _admin_user(request)
    try:
        text = AI_CHANGELOG_PATH.read_text(encoding="utf-8")
        modified_at = datetime.fromtimestamp(
            AI_CHANGELOG_PATH.stat().st_mtime,
            tz=timezone.utc,
        ).isoformat().replace("+00:00", "Z")
    except OSError:
        text = ""
        modified_at = None
    return {
        "path": str(AI_CHANGELOG_PATH.relative_to(ROOT)),
        "build_id": _admin_build_id(),
        "modified_at": modified_at,
        "text": text,
    }


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
