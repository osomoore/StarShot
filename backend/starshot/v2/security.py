"""Password hashing, session tokens, and htpasswd verification.

Uses only the standard library (pbkdf2_hmac + secrets) so the project keeps
its fastapi/uvicorn-only dependency footprint.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from pathlib import Path

PBKDF2_ITERATIONS = 210_000

USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,20}$")
MIN_PASSWORD_LENGTH = 4


def valid_username(username: str) -> bool:
    return bool(USERNAME_RE.match(username or ""))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def session_token_hash(token: str) -> str:
    # Sessions are stored hashed so a leaked database does not leak live tokens.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_htpasswd(path: Path) -> dict[str, str]:
    users: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            name, hashed = line.split(":", 1)
            users[name] = hashed
    except OSError:
        pass
    return users


def verify_htpasswd_password(password: str, stored: str) -> bool:
    """Verify against {SHA} or plaintext htpasswd entries (stdlib-checkable formats)."""
    if stored.startswith("{SHA}"):
        digest = base64.b64encode(hashlib.sha1(password.encode("utf-8")).digest()).decode("ascii")
        return hmac.compare_digest(digest, stored[5:])
    if stored.startswith(("$apr1$", "$2y$", "$2b$")):
        # MD5-apr1/bcrypt entries need Apache/passlib; not verifiable with stdlib.
        return False
    return hmac.compare_digest(password, stored)
