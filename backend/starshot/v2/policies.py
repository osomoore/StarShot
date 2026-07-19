"""Terms of Service and Privacy Policy: single-source loading and rendering.

The legal text lives only in ``docs/rules/Terms_of_Service.txt`` and
``docs/rules/Privacy_Policy.txt``. Everything the site shows — the standalone
/v2/terms and /v2/privacy pages, the onboarding modal, and the guest popup
links — renders from those files, so editing a file updates every displayed
copy. Each document's version is its "Effective Date:" line; when the date
changes, users must accept the new version on their next login.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RULES_DIR = ROOT / "docs" / "rules"

POLICY_FILES = {
    "terms": ("Terms of Service", RULES_DIR / "Terms_of_Service.txt"),
    "privacy": ("Privacy Policy", RULES_DIR / "Privacy_Policy.txt"),
}

_EFFECTIVE_RE = re.compile(r"^\s*Effective Date:\s*(.+?)\s*$", re.IGNORECASE)
_NUMBERED_HEADING_RE = re.compile(r"^\d+\.\s+\S")

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

# Cached per (path, mtime) so edits show up without a restart.
_cache: dict[str, tuple[float, dict]] = {}


def _version_from_effective_date(raw: str) -> str:
    """Normalize 'July 19, 2026' to '2026-07-19'; fall back to the raw text."""
    match = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})$", raw.strip())
    if match:
        month = _MONTHS.get(match.group(1).lower())
        if month:
            return f"{match.group(3)}-{month:02d}-{int(match.group(2)):02d}"
    return raw.strip()


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 60:
        return False
    if _NUMBERED_HEADING_RE.match(stripped):
        return True
    # Short title-case line with no sentence punctuation at the end.
    return (
        len(stripped.split()) <= 6
        and not stripped.endswith((".", ":", ",", ";", "!", "?"))
        and stripped[0].isupper()
    )


def _parse(path: Path, title: str) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    effective_date = ""
    for line in lines:
        match = _EFFECTIVE_RE.match(line)
        if match:
            effective_date = match.group(1)
            break
    return {
        "title": title,
        "text": text,
        "effective_date": effective_date,
        "version": _version_from_effective_date(effective_date) if effective_date else "unversioned",
    }


def get_policy(kind: str) -> dict:
    """Load a policy document (parsed, cached by file mtime)."""
    title, path = POLICY_FILES[kind]
    mtime = path.stat().st_mtime
    cached = _cache.get(kind)
    if cached and cached[0] == mtime:
        return cached[1]
    parsed = _parse(path, title)
    _cache[kind] = (mtime, parsed)
    return parsed


def current_versions() -> dict:
    return {
        "terms_version": get_policy("terms")["version"],
        "privacy_version": get_policy("privacy")["version"],
    }


def policy_body_html(kind: str) -> str:
    """The document rendered as semantic HTML (headings + paragraphs)."""
    policy = get_policy(kind)
    parts: list[str] = []
    lines = policy["text"].splitlines()
    first_content = True
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        escaped = html.escape(stripped)
        if first_content:
            parts.append(f"<h1>{escaped}</h1>")
            first_content = False
        elif _EFFECTIVE_RE.match(stripped):
            parts.append(f'<p class="policy-effective">{escaped}</p>')
        elif _looks_like_heading(stripped):
            parts.append(f"<h2>{escaped}</h2>")
        else:
            parts.append(f"<p>{escaped}</p>")
    return "\n".join(parts)


def policy_page_html(kind: str) -> str:
    """A complete standalone page for /v2/terms and /v2/privacy."""
    policy = get_policy(kind)
    body = policy_body_html(kind)
    title = html.escape(policy["title"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — StarShot</title>
<link href="https://fonts.googleapis.com/css2?family=Pirata+One&family=IM+Fell+English:ital@0;1&family=Space+Grotesk:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/v2/static/pirate.css?v=61">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>☠</text></svg>">
<style>
  .policy-wrap {{ max-width: 760px; margin: 0 auto; padding: 32px 20px 60px; }}
  .policy-wrap .panel {{ padding: 26px 30px; }}
  .policy-wrap h1 {{ font-family: "Pirata One", serif; color: var(--gold-bright); font-size: 34px; margin: 0 0 6px; }}
  .policy-wrap h2 {{ font-family: "Pirata One", serif; color: var(--gold-bright); font-size: 22px; margin: 22px 0 8px; }}
  .policy-wrap p {{ font-family: "Space Grotesk", sans-serif; font-size: 15px; line-height: 1.6; color: var(--ink-dim); margin: 0 0 10px; }}
  .policy-effective {{ font-style: italic; }}
  .policy-links {{ margin-top: 18px; font-family: "Space Grotesk", sans-serif; font-size: 14px; }}
  body.policy-page {{ min-height: 100%; overflow: auto; }}
  :root[data-device="phone"] body.policy-page {{ overflow: auto; }}
</style>
</head>
<body class="policy-page">
<header class="topbar">
  <div class="brand"><span class="brand-skull">☠</span> StarShot <span class="brand-tag">{title.lower()}</span></div>
  <div class="topbar-right">
    <a class="btn ghost small" href="/v2">← Back to the game</a>
  </div>
</header>
<div class="policy-wrap">
  <div class="panel">
{body}
    <div class="policy-links">
      <a href="/v2/terms">Terms of Service</a> · <a href="/v2/privacy">Privacy Policy</a> · <a href="/v2/about">About</a>
    </div>
  </div>
</div>
</body>
</html>
"""
