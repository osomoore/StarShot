"""Admin-defined card-text keywords.

A keyword maps a regex over normalized card side-text (lowercase, single
spaces) to a ``FaceSpec``. Custom keywords are stored as JSON and tried
BEFORE the built-in phrases in ``deck_data._phrase_spec``, so an admin can
both add new card text and override what existing text means.

The ``code`` of a keyword is a Python snippet executed with ``match`` (the
``re.Match``), ``FaceSpec`` and ``CardFamily`` in scope; it must assign the
result to a variable named ``spec``. Snippets are written by the site admin
through an authenticated console — they run with full interpreter rights by
design (this is the admin's own server).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_KEYWORDS_PATH = ROOT / ".starshot" / "custom_keywords.json"

_cache: dict[str, Any] = {"mtime": None, "path": None, "entries": [], "compiled": []}


def keywords_path() -> Path:
    return Path(os.environ.get("STARSHOT_KEYWORDS_FILE", DEFAULT_KEYWORDS_PATH))


def load_custom_keywords() -> list[dict]:
    path = keywords_path()
    try:
        return json.loads(path.read_text())["keywords"]
    except (OSError, KeyError, ValueError):
        return []


def save_custom_keywords(entries: list[dict]) -> None:
    path = keywords_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"keywords": entries}, indent=2))
    _cache["mtime"] = None  # force recompile on next parse


def compile_keyword(entry: dict):
    """Compile one keyword entry; returns (pattern, code_object). Raises ValueError."""
    try:
        pattern = re.compile(entry["pattern"])
    except re.error as exc:
        raise ValueError(f"Bad pattern for keyword {entry.get('name')!r}: {exc}")
    try:
        code = compile(entry["code"], f"<keyword:{entry.get('name')}>", "exec")
    except SyntaxError as exc:
        raise ValueError(f"Bad python for keyword {entry.get('name')!r}: {exc}")
    return pattern, code


def run_keyword(entry: dict, text: str):
    """Try one keyword against text. Returns a FaceSpec or None. Raises ValueError
    when the keyword matches but its code fails or returns garbage."""
    from starshot.rules.deck_data import FaceSpec  # late import to avoid cycle
    from starshot.rules.models import CardFamily

    pattern, code = compile_keyword(entry)
    match = pattern.fullmatch(text)
    if match is None:
        return None
    namespace: dict[str, Any] = {"match": match, "FaceSpec": FaceSpec, "CardFamily": CardFamily, "re": re}
    try:
        exec(code, namespace)  # noqa: S102 — admin-authored, admin-only, by design
    except Exception as exc:
        raise ValueError(f"Keyword {entry.get('name')!r} crashed on {text!r}: {exc}")
    spec = namespace.get("spec")
    if not isinstance(spec, FaceSpec):
        raise ValueError(f"Keyword {entry.get('name')!r} must assign a FaceSpec to `spec`.")
    return spec


def custom_phrase_spec(text: str):
    """Registry hook used by the deck parser: first matching enabled custom
    keyword wins. Returns a FaceSpec or None."""
    path = keywords_path()
    mtime = path.stat().st_mtime if path.exists() else None
    if _cache["mtime"] != mtime or _cache["path"] != path:
        entries = [entry for entry in load_custom_keywords() if entry.get("enabled", True)]
        compiled = []
        for entry in entries:
            try:
                compiled.append((entry, *compile_keyword(entry)))
            except ValueError:
                continue  # broken keywords are skipped at parse time; the admin UI surfaces them
        _cache.update({"mtime": mtime, "path": path, "entries": entries, "compiled": compiled})
    for entry, pattern, _code in _cache["compiled"]:
        if pattern.fullmatch(text):
            return run_keyword(entry, text)
    return None
