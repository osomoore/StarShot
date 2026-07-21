"""SQLite persistence for the v2 multiplayer layer.

Everything (users, sessions, matchmaking queue, matches, game states) lives in
one database file so a single BEGIN IMMEDIATE transaction can cover races such
as two players joining the last open seat at the same time.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = ROOT / ".starshot" / "v2.sqlite3"

SESSION_TTL_DAYS = 30

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pass_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    draws INTEGER NOT NULL DEFAULT 0,
    games_played INTEGER NOT NULL DEFAULT 0,
    display_name TEXT,
    name_flagged INTEGER NOT NULL DEFAULT 0,
    matchmaking_ok INTEGER NOT NULL DEFAULT 1,
    leaderboard_ok INTEGER NOT NULL DEFAULT 1,
    must_rename INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS illegal_names (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,               -- open | active | complete | cancelled
    host_user_id INTEGER NOT NULL REFERENCES users(id),
    seats INTEGER NOT NULL,
    ai_level TEXT NOT NULL DEFAULT 'deck_hand',
    active_expansions_json TEXT NOT NULL DEFAULT '[]',
    star_breach_prey_player_id TEXT,
    game_id TEXT,
    stats_recorded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS match_seats (
    match_id TEXT NOT NULL REFERENCES matches(id),
    seat_index INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    user_id INTEGER,
    ai_type TEXT,
    display_name TEXT NOT NULL,
    PRIMARY KEY (match_id, seat_index)
);
CREATE TABLE IF NOT EXISTS queue (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    joined_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS presence (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS challenges (
    id TEXT PRIMARY KEY,
    from_user_id INTEGER NOT NULL REFERENCES users(id),
    to_user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL,               -- pending | accepted | declined | cancelled
    active_expansions_json TEXT NOT NULL DEFAULT '[]',
    game_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_battle_runs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,                 -- single | batch
    name TEXT NOT NULL,
    deck_set_id TEXT NOT NULL,
    deck_set_name TEXT NOT NULL,
    ai_types_json TEXT NOT NULL,
    run_count INTEGER NOT NULL,
    game_id TEXT,
    summary_json TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    liked TEXT NOT NULL DEFAULT '',
    disliked TEXT NOT NULL DEFAULT '',
    thoughts TEXT NOT NULL DEFAULT '',
    match_id TEXT,
    game_id TEXT,
    is_bug_report INTEGER NOT NULL DEFAULT 0,
    game_log TEXT NOT NULL DEFAULT '',
    screenshot_data_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leaderboard_results (
    user_id INTEGER NOT NULL REFERENCES users(id),
    category TEXT NOT NULL,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    draws INTEGER NOT NULL DEFAULT 0,
    games_played INTEGER NOT NULL DEFAULT 0,
    score INTEGER NOT NULL DEFAULT 0,
    ship_losses INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, category)
);
"""

# Columns added after the first production deploy; applied idempotently.
_MIGRATIONS = (
    "ALTER TABLE match_seats ADD COLUMN abandoned INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE match_seats ADD COLUMN stats_exempt INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE matches ADD COLUMN ai_level TEXT NOT NULL DEFAULT 'deck_hand'",
    "ALTER TABLE matches ADD COLUMN active_expansions_json TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE matches ADD COLUMN star_breach_prey_player_id TEXT",
    "ALTER TABLE challenges ADD COLUMN active_expansions_json TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE leaderboard_results ADD COLUMN score INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE leaderboard_results ADD COLUMN ship_losses INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE feedback ADD COLUMN is_bug_report INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE feedback ADD COLUMN game_log TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE feedback ADD COLUMN screenshot_data_url TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE matches ADD COLUMN star_breach_boss_design_id TEXT",
    "ALTER TABLE match_seats ADD COLUMN star_breach_role TEXT",
    "ALTER TABLE match_seats ADD COLUMN ship_design_id TEXT",
    "ALTER TABLE users ADD COLUMN display_name TEXT",
    "ALTER TABLE users ADD COLUMN name_flagged INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN matchmaking_ok INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE users ADD COLUMN leaderboard_ok INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE users ADD COLUMN must_rename INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN google_sub TEXT",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub)",
    "ALTER TABLE users ADD COLUMN microsoft_sub TEXT",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_microsoft_sub ON users(microsoft_sub)",
    "ALTER TABLE users ADD COLUMN discord_sub TEXT",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_discord_sub ON users(discord_sub)",
    # Verified email captured from external sign-ins; used to link a new
    # provider identity to an account that already proved the same address.
    "ALTER TABLE users ADD COLUMN email TEXT",
    "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email COLLATE NOCASE)",
    # Guest sessions, Terms/Privacy acceptance, onboarding, provider metadata,
    # and account deletion (deleted accounts stay as anonymized tombstones so
    # match history keeps valid foreign keys).
    "ALTER TABLE users ADD COLUMN is_guest INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN deleted_at TEXT",
    "ALTER TABLE users ADD COLUMN terms_version TEXT",
    "ALTER TABLE users ADD COLUMN privacy_version TEXT",
    "ALTER TABLE users ADD COLUMN policies_accepted_at TEXT",
    "ALTER TABLE users ADD COLUMN name_confirmed INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN google_email TEXT",
    "ALTER TABLE users ADD COLUMN google_linked_at TEXT",
    "ALTER TABLE users ADD COLUMN microsoft_email TEXT",
    "ALTER TABLE users ADD COLUMN microsoft_linked_at TEXT",
    "ALTER TABLE users ADD COLUMN discord_email TEXT",
    "ALTER TABLE users ADD COLUMN discord_linked_at TEXT",
    # When this session last proved its identity (login or reauthentication);
    # sensitive actions require this to be recent.
    "ALTER TABLE sessions ADD COLUMN reauthed_at TEXT",
    """CREATE TABLE IF NOT EXISTS admin_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_user_id INTEGER NOT NULL,
        target_user_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS badges (
        user_id INTEGER NOT NULL REFERENCES users(id),
        badge_id TEXT NOT NULL,
        earned_at TEXT NOT NULL,
        PRIMARY KEY (user_id, badge_id)
    )""",
    """CREATE TABLE IF NOT EXISTS campaign_components (
        user_id INTEGER NOT NULL REFERENCES users(id),
        component_id TEXT NOT NULL,
        earned_at TEXT NOT NULL,
        source_match_id TEXT,
        source_kind TEXT NOT NULL DEFAULT 'admin',
        PRIMARY KEY (user_id, component_id)
    )""",
    """CREATE TABLE IF NOT EXISTS campaign_awards (
        user_id INTEGER NOT NULL REFERENCES users(id),
        match_id TEXT NOT NULL,
        component_id TEXT NOT NULL,
        source_kind TEXT NOT NULL,
        earned_at TEXT NOT NULL,
        PRIMARY KEY (user_id, match_id)
    )""",
    """CREATE TABLE IF NOT EXISTS campaign_stardock (
        user_id INTEGER PRIMARY KEY REFERENCES users(id),
        initialized_at TEXT NOT NULL
    )""",
    # The player's persistent selected ship (the one they fly in every raid).
    # Stored as a playable ship ref: "user:<uid>:<id>" for an owned design,
    # a bare global design id, or "" for the stock base ship.
    "ALTER TABLE campaign_stardock ADD COLUMN selected_ship_design_id TEXT",
)

# External sign-in providers and the users column holding each one's subject.
_EXTERNAL_SUB_COLUMNS = {
    "google": "google_sub",
    "microsoft": "microsoft_sub",
    "discord": "discord_sub",
}

# Effective public name: the chosen display name, or the username until one is set.
_DISPLAY = "COALESCE(NULLIF(u.display_name, ''), u.username)"
_DISPLAY_BARE = _DISPLAY.replace("u.", "")
# Visible on leaderboards: not admin-delisted, not carrying a flagged name,
# not a temporary guest, and not a deleted account's tombstone.
_LISTED = (
    "u.leaderboard_ok = 1 AND u.name_flagged = 0 "
    "AND COALESCE(u.is_guest, 0) = 0 AND u.deleted_at IS NULL"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class V2Store:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or os.environ.get("STARSHOT_V2_DB", DEFAULT_DB_PATH))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            for migration in _MIGRATIONS:
                try:
                    conn.execute(migration)
                except sqlite3.OperationalError:
                    pass  # column already exists

    @contextmanager
    def _connect(self, immediate: bool = False):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- users / sessions -------------------------------------------------

    def create_user(self, username: str, pass_hash: str) -> dict:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, pass_hash, created_at) VALUES (?, ?, ?)",
                (username, pass_hash, _now()),
            )
            return {"id": cursor.lastrowid, "username": username}

    def get_user_by_name(self, username: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
            ).fetchone()
            return dict(row) if row else None

    def get_user_by_external_sub(self, provider: str, sub: str) -> dict | None:
        column = _EXTERNAL_SUB_COLUMNS[provider]
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM users WHERE {column} = ?", (sub,)
            ).fetchone()
            return dict(row) if row else None

    def get_user_by_verified_email(self, email: str) -> dict | None:
        """The account that owns a verified email, if any. Only external
        sign-ins ever store an email, and only after the provider verified it,
        so a hit here is safe to link a new provider identity to. Oldest
        account wins if two somehow share the address."""
        if not email:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ? COLLATE NOCASE "
                "AND deleted_at IS NULL AND COALESCE(is_guest, 0) = 0 "
                "ORDER BY id ASC LIMIT 1",
                (email,),
            ).fetchone()
            return dict(row) if row else None

    def link_external_sub(
        self, user_id: int, provider: str, sub: str, email: str | None = None
    ) -> None:
        """Attach a provider identity to an existing account. Only fills the
        provider's slot when it is still empty (never clobbers a prior link),
        and backfills the verified email if the account had none."""
        column = _EXTERNAL_SUB_COLUMNS[provider]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE users SET {column} = ?, {provider}_email = ?, {provider}_linked_at = ? "
                f"WHERE id = ? AND {column} IS NULL",
                (sub, email, _now(), user_id),
            )
            if email:
                conn.execute(
                    "UPDATE users SET email = ? WHERE id = ? AND (email IS NULL OR email = '')",
                    (email, user_id),
                )

    def update_provider_email(self, user_id: int, provider: str, email: str | None) -> None:
        """Keep the provider-supplied email current on each sign-in."""
        if not email:
            return
        column = _EXTERNAL_SUB_COLUMNS[provider]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE users SET {provider}_email = ? WHERE id = ? AND {column} IS NOT NULL",
                (email, user_id),
            )

    def unlink_provider(self, user_id: int, provider: str) -> None:
        column = _EXTERNAL_SUB_COLUMNS[provider]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE users SET {column} = NULL, {provider}_email = NULL, "
                f"{provider}_linked_at = NULL WHERE id = ?",
                (user_id,),
            )

    def create_external_user(
        self,
        provider: str,
        sub: str,
        username: str,
        display_name: str | None = None,
        email: str | None = None,
    ) -> dict:
        # Externally-linked accounts have no usable password: the '!<provider>'
        # sentinel never parses as a pbkdf2 hash, so verify_password always
        # fails and the only way in is a fresh verified provider token.
        column = _EXTERNAL_SUB_COLUMNS[provider]
        with self._connect() as conn:
            cursor = conn.execute(
                f"INSERT INTO users (username, pass_hash, {column}, {provider}_email, "
                f"{provider}_linked_at, display_name, email, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (username, "!" + provider, sub, email, _now(), display_name, email, _now()),
            )
            return {"id": cursor.lastrowid, "username": username}

    def create_guest_user(self, username: str, display_name: str) -> dict:
        """A temporary guest: a users row (so match seats keep valid foreign
        keys) flagged is_guest, with no password and no provider links. The
        random display name is a placeholder — name_confirmed stays 0 so
        onboarding still offers the guest a chance to pick their own."""
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, pass_hash, display_name, is_guest, "
                "name_confirmed, created_at) VALUES (?, '!guest', ?, 1, 0, ?)",
                (username, display_name, _now()),
            )
            return {"id": cursor.lastrowid, "username": username}

    def claim_guest_account(self, user_id: int, provider: str, sub: str, email: str | None) -> None:
        """Convert a temporary guest into a permanent account by attaching a
        verified provider identity. The guest's row, id, and display name are
        kept; only the guest flag and password sentinel change, so any
        currently in-progress match keeps its seat intact."""
        column = _EXTERNAL_SUB_COLUMNS[provider]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE users SET is_guest = 0, pass_hash = ?, {column} = ?, "
                f"{provider}_email = ?, {provider}_linked_at = ? WHERE id = ?",
                ("!" + provider, sub, email, _now(), user_id),
            )

    def get_user(self, user_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def create_session(self, token_hash: str, user_id: int, ttl_days: int = SESSION_TTL_DAYS) -> None:
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=ttl_days)).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, reauthed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (token_hash, user_id, _now(), expires, _now()),
            )

    def get_session_user(self, token_hash: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ? AND s.expires_at > ? AND u.deleted_at IS NULL""",
                (token_hash, _now()),
            ).fetchone()
            return dict(row) if row else None

    def get_session(self, token_hash: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE token_hash = ? AND expires_at > ?",
                (token_hash, _now()),
            ).fetchone()
            return dict(row) if row else None

    def refresh_session_auth(self, token_hash: str) -> None:
        """Record that this session just re-proved its identity."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET reauthed_at = ? WHERE token_hash = ?",
                (_now(), token_hash),
            )

    def delete_session(self, token_hash: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def delete_sessions_for_user(self, user_id: int) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            return int(cursor.rowcount or 0)

    def update_password(self, user_id: int, pass_hash: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE users SET pass_hash = ? WHERE id = ?", (pass_hash, user_id))

    # -- display names & account moderation ----------------------------------

    def set_display_name(self, user_id: int, display_name: str, flagged: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET display_name = ?, name_flagged = ?, must_rename = 0, "
                "name_confirmed = 1 WHERE id = ?",
                (display_name, 1 if flagged else 0, user_id),
            )

    def set_policies_accepted(self, user_id: int, terms_version: str, privacy_version: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET terms_version = ?, privacy_version = ?, "
                "policies_accepted_at = ? WHERE id = ?",
                (terms_version, privacy_version, _now(), user_id),
            )

    def set_user_flags(
        self,
        user_id: int,
        matchmaking_ok: bool | None = None,
        leaderboard_ok: bool | None = None,
    ) -> None:
        with self._connect() as conn:
            if matchmaking_ok is not None:
                conn.execute(
                    "UPDATE users SET matchmaking_ok = ? WHERE id = ?",
                    (1 if matchmaking_ok else 0, user_id),
                )
            if leaderboard_ok is not None:
                conn.execute(
                    "UPDATE users SET leaderboard_ok = ? WHERE id = ?",
                    (1 if leaderboard_ok else 0, user_id),
                )

    def add_illegal_name(self, name: str) -> int:
        """Ban a display name. Every account currently wearing it is flagged
        and forced to pick a new name next time they reach the lobby. Returns
        how many accounts were caught wearing it."""
        with self._connect(immediate=True) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO illegal_names (name, created_at) VALUES (?, ?)",
                (name, _now()),
            )
            cursor = conn.execute(
                f"UPDATE users SET must_rename = 1, name_flagged = 1 "
                f"WHERE {_DISPLAY_BARE} = ? COLLATE NOCASE",
                (name,),
            )
            return int(cursor.rowcount or 0)

    def remove_illegal_name(self, name: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM illegal_names WHERE name = ?", (name,))
            return int(cursor.rowcount or 0)

    def list_illegal_names(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name, created_at FROM illegal_names ORDER BY name COLLATE NOCASE"
            ).fetchall()
            return [dict(row) for row in rows]

    def is_illegal_name(self, name: str) -> bool:
        with self._connect() as conn:
            return conn.execute(
                "SELECT 1 FROM illegal_names WHERE name = ?", (name,)
            ).fetchone() is not None

    def list_accounts(self) -> list[dict]:
        """Every live account on the server, for the admin console."""
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT u.id, u.username, {_DISPLAY} AS display_name,
                           u.wins, u.losses, u.draws, u.games_played, u.created_at,
                           u.name_flagged, u.matchmaking_ok, u.leaderboard_ok, u.must_rename,
                           COALESCE(u.is_guest, 0) AS is_guest,
                           (u.google_sub IS NOT NULL) AS has_google,
                           (u.microsoft_sub IS NOT NULL) AS has_microsoft,
                           (u.discord_sub IS NOT NULL) AS has_discord,
                           p.last_seen
                    FROM users u
                    LEFT JOIN presence p ON p.user_id = u.id
                    WHERE u.deleted_at IS NULL
                    ORDER BY u.username COLLATE NOCASE""",
            ).fetchall()
            accounts = []
            for row in rows:
                account = dict(row)
                account["providers"] = [
                    provider
                    for provider in ("google", "microsoft", "discord")
                    if account.pop(f"has_{provider}")
                ]
                accounts.append(account)
            return accounts

    def leaderboard_results_for_user(self, user_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT category, wins, losses, draws, games_played, score, ship_losses "
                "FROM leaderboard_results WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    # -- account deletion & admin audit --------------------------------------

    def delete_account(self, user_id: int) -> None:
        """Erase an account's private data and sessions. The users row stays
        as an anonymized tombstone so other players' match histories keep
        valid references; every credential, provider link, policy record, and
        stat is cleared and the account can never sign in again."""
        anonymous = f"deleted-{uuid.uuid4().hex[:10]}"
        with self._connect(immediate=True) as conn:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM queue WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM presence WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM leaderboard_results WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM campaign_components WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM campaign_awards WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM campaign_stardock WHERE user_id = ?", (user_id,))
            conn.execute(
                "DELETE FROM challenges WHERE from_user_id = ? OR to_user_id = ?",
                (user_id, user_id),
            )
            # Multiplayer records other players legitimately share: keep the
            # seats but strip the identity.
            conn.execute(
                "UPDATE match_seats SET user_id = NULL, display_name = 'Departed Captain' "
                "WHERE user_id = ?",
                (user_id,),
            )
            conn.execute("UPDATE matches SET status = 'cancelled' WHERE host_user_id = ? AND status = 'open'", (user_id,))
            conn.execute(
                """UPDATE users SET
                       username = ?, pass_hash = '!deleted', display_name = 'Departed Captain',
                       email = NULL, google_sub = NULL, google_email = NULL, google_linked_at = NULL,
                       microsoft_sub = NULL, microsoft_email = NULL, microsoft_linked_at = NULL,
                       discord_sub = NULL, discord_email = NULL, discord_linked_at = NULL,
                       terms_version = NULL, privacy_version = NULL, policies_accepted_at = NULL,
                       wins = 0, losses = 0, draws = 0, games_played = 0,
                       name_flagged = 0, must_rename = 0, name_confirmed = 0,
                       matchmaking_ok = 0, leaderboard_ok = 0, deleted_at = ?
                   WHERE id = ?""",
                (anonymous, _now(), user_id),
            )

    def record_admin_audit(self, admin_user_id: int, target_user_id: int, action: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO admin_audit (admin_user_id, target_user_id, action, created_at) "
                "VALUES (?, ?, ?, ?)",
                (admin_user_id, target_user_id, action, _now()),
            )

    def list_admin_audit(self, limit: int = 200) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM admin_audit ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def record_result(
        self,
        user_id: int,
        outcome: str,
        category: str = "humans",
        score: int = 0,
        ship_loss: bool = False,
    ) -> None:
        column = {"win": "wins", "loss": "losses", "draw": "draws"}[outcome]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE users SET {column} = {column} + 1, games_played = games_played + 1 WHERE id = ?",
                (user_id,),
            )
            conn.execute(
                "INSERT OR IGNORE INTO leaderboard_results (user_id, category) VALUES (?, ?)",
                (user_id, category),
            )
            conn.execute(
                f"UPDATE leaderboard_results SET {column} = {column} + 1, "
                "games_played = games_played + 1, score = score + ?, ship_losses = ship_losses + ? "
                "WHERE user_id = ? AND category = ?",
                (score, 1 if ship_loss else 0, user_id, category),
            )

    def leaderboard(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT u.username, {_DISPLAY} AS display_name,
                          u.wins, u.losses, u.draws, u.games_played,
                          COUNT(f.id) AS feedback_count
                   FROM users u
                   LEFT JOIN feedback f ON f.user_id = u.id
                   WHERE {_LISTED}
                   GROUP BY u.id
                   ORDER BY wins DESC, losses ASC, username ASC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def category_leaderboard(self, category: str, limit: int = 10, legacy_humans: bool = False) -> list[dict]:
        if category == "humans" and legacy_humans:
            return self.leaderboard(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT u.id AS user_id, u.username, {_DISPLAY} AS display_name,
                          COALESCE(r.wins, 0) AS wins,
                          COALESCE(r.losses, 0) AS losses,
                          COALESCE(r.draws, 0) AS draws,
                          COALESCE(r.games_played, 0) AS games_played,
                          COALESCE(r.score, 0) AS score,
                          COALESCE(r.ship_losses, 0) AS ship_losses,
                          COUNT(f.id) AS feedback_count
                   FROM users u
                   LEFT JOIN leaderboard_results r ON r.user_id = u.id AND r.category = ?
                   LEFT JOIN feedback f ON f.user_id = u.id
                   WHERE COALESCE(r.games_played, 0) > 0 AND {_LISTED}
                   GROUP BY u.id
                   ORDER BY
                     CASE WHEN ? = 'ai' THEN COALESCE(r.score, 0) ELSE COALESCE(r.wins, 0) END DESC,
                     COALESCE(r.games_played, 0) DESC,
                     username ASC LIMIT ?""",
                (category, category, limit),
            ).fetchall()
            result = []
            for row in rows:
                entry = dict(row)
                entry["average_score"] = (
                    entry["score"] / entry["games_played"] if entry["games_played"] else 0
                )
                result.append(entry)
            return result

    def leaderboard_bundle(self, limit: int = 10) -> dict:
        categories = [
            ("humans", "Flesh and Blood Victories"),
            ("ai", "Digital Scallywag Conquests"),
        ]
        boards = [
            {
                "key": key,
                "label": label,
                "entries": self.category_leaderboard(key, limit),
            }
            for key, label in categories
        ]
        return {"boards": boards, "titles": self.title_holders(), "infamy": self.infamy_leader()}

    def infamy_leader(self) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                f"""SELECT u.id AS user_id, u.username, {_DISPLAY} AS display_name,
                          SUM(r.ship_losses) AS ship_losses
                   FROM leaderboard_results r
                   JOIN users u ON u.id = r.user_id
                   WHERE {_LISTED}
                   GROUP BY u.id
                   HAVING ship_losses > 0
                   ORDER BY ship_losses DESC, u.username ASC
                   LIMIT 1"""
            ).fetchone()
        return dict(row) if row else None

    def title_holders(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT u.id AS user_id, u.username, {_DISPLAY} AS display_name,
                          r.category, r.wins, r.score
                   FROM leaderboard_results r
                   JOIN users u ON u.id = r.user_id
                   WHERE (r.wins > 0 OR r.score > 0) AND {_LISTED}"""
            ).fetchall()
            feedback_rows = conn.execute(
                "SELECT user_id, COUNT(*) AS feedback_count FROM feedback GROUP BY user_id"
            ).fetchall()
            feedback = {int(row["user_id"]): int(row["feedback_count"]) for row in feedback_rows}
            users = conn.execute(
                f"""SELECT u.id AS user_id, u.username, {_DISPLAY} AS display_name, u.wins
                    FROM users u WHERE u.wins > 0 AND {_LISTED}"""
            ).fetchall()
        scores: dict[int, dict] = {}
        for row in rows:
            user_id = int(row["user_id"])
            entry = scores.setdefault(
                user_id,
                {"user_id": user_id, "username": row["username"],
                 "display_name": row["display_name"], "points": 0, "wins": 0},
            )
            wins = int(row["wins"] or 0)
            entry["points"] += int(row["score"] or 0) if row["category"] == "ai" else wins * 3
            entry["wins"] += wins
        # Legacy aggregate wins predate category tracking. Treat them as players-only
        # only when the category table has no scored rows for that user.
        for row in users:
            user_id = int(row["user_id"])
            if user_id in scores:
                continue
            wins = int(row["wins"] or 0)
            scores[user_id] = {
                "user_id": user_id,
                "username": row["username"],
                "display_name": row["display_name"],
                "points": wins * 3,
                "wins": wins,
            }
        ranked = sorted(
            scores.values(),
            key=lambda entry: (-entry["points"], -entry["wins"], entry["username"].lower()),
        )[:2]
        titles = ["Pirate King", "First Mate"]
        for index, entry in enumerate(ranked):
            entry["title"] = titles[index]
            entry["feedback_count"] = feedback.get(entry["user_id"], 0)
        return ranked

    # -- playtest feedback --------------------------------------------------

    def feedback_count(self, user_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM feedback WHERE user_id = ?", (user_id,)
            ).fetchone()
            return int(row["n"] if row else 0)

    def create_feedback(
        self,
        *,
        user_id: int,
        rating: int,
        liked: str,
        disliked: str,
        thoughts: str,
        match_id: str | None = None,
        game_id: str | None = None,
        is_bug_report: bool = False,
        game_log: str = "",
        screenshot_data_url: str = "",
    ) -> dict:
        feedback_id = uuid.uuid4().hex[:12]
        created_at = _now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO feedback
                   (id, user_id, rating, liked, disliked, thoughts, match_id, game_id,
                    is_bug_report, game_log, screenshot_data_url, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    feedback_id,
                    user_id,
                    rating,
                    liked,
                    disliked,
                    thoughts,
                    match_id,
                    game_id,
                    1 if is_bug_report else 0,
                    game_log,
                    screenshot_data_url,
                    created_at,
                ),
            )
        return self.get_feedback(feedback_id)

    # -- badges ---------------------------------------------------------

    def award_badge(self, user_id: int, badge_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO badges (user_id, badge_id, earned_at) VALUES (?, ?, ?)",
                (user_id, badge_id, _now()),
            )
            return cursor.rowcount > 0

    def award_campaign_component(
        self, user_id: int, component_id: str, *, match_id: str | None = None,
        source_kind: str = "admin",
    ) -> bool:
        """Add one permanent component. Returns False when already owned."""
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO campaign_components "
                "(user_id, component_id, earned_at, source_match_id, source_kind) VALUES (?, ?, ?, ?, ?)",
                (user_id, component_id, _now(), match_id, source_kind),
            )
            return cursor.rowcount > 0

    def campaign_component_ids(self, user_id: int) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT component_id FROM campaign_components WHERE user_id = ? ORDER BY earned_at, component_id",
                (user_id,),
            ).fetchall()
        return [str(row["component_id"]) for row in rows]

    def record_campaign_award(
        self, user_id: int, match_id: str, component_id: str, source_kind: str,
    ) -> bool:
        """Record the match popup once. The inventory insert is deliberately
        separate so callers can choose an unowned item before this guard."""
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO campaign_awards "
                "(user_id, match_id, component_id, source_kind, earned_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, match_id, component_id, source_kind, _now()),
            )
            return cursor.rowcount > 0

    def campaign_award_for_match(self, user_id: int, match_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM campaign_awards WHERE user_id = ? AND match_id = ?",
                (user_id, match_id),
            ).fetchone()
        return dict(row) if row else None

    def initialize_stardock(self, user_id: int) -> bool:
        """Return True exactly once for an account's first StarDock visit."""
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO campaign_stardock (user_id, initialized_at) VALUES (?, ?)",
                (user_id, _now()),
            )
            return cursor.rowcount > 0

    def get_selected_ship_ref(self, user_id: int) -> str | None:
        """The player's persistent selected ship ref, or None if never set.

        None means "not yet provisioned" — the caller should run starter
        provisioning. "" is a real value meaning the stock base ship.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT selected_ship_design_id FROM campaign_stardock WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return None if row is None else row["selected_ship_design_id"]

    def set_selected_ship_ref(self, user_id: int, ref: str) -> None:
        """Persist the player's selected ship ref (upserting the row)."""
        with self._connect(immediate=True) as conn:
            conn.execute(
                "INSERT INTO campaign_stardock (user_id, initialized_at, selected_ship_design_id) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET selected_ship_design_id = excluded.selected_ship_design_id",
                (user_id, _now(), ref),
            )

    def user_badges(self, user_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT badge_id, earned_at FROM badges WHERE user_id = ? ORDER BY earned_at",
                (user_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_feedback(self, feedback_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT f.*, u.username FROM feedback f
                   JOIN users u ON u.id = f.user_id
                   WHERE f.id = ?""",
                (feedback_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_feedback_latest_by_user(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT f.*, u.username, counts.feedback_count
                   FROM feedback f
                   JOIN users u ON u.id = f.user_id
                   JOIN (
                     SELECT user_id, MAX(created_at) AS latest_at, COUNT(*) AS feedback_count
                     FROM feedback GROUP BY user_id
                   ) counts ON counts.user_id = f.user_id AND counts.latest_at = f.created_at
                   WHERE f.id = (
                     SELECT f2.id FROM feedback f2
                     WHERE f2.user_id = f.user_id
                     ORDER BY f2.created_at DESC, f2.id DESC LIMIT 1
                   )
                   ORDER BY f.created_at DESC"""
            ).fetchall()
            return [dict(row) for row in rows]

    def feedback_for_user(self, user_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT f.*, u.username FROM feedback f
                   JOIN users u ON u.id = f.user_id
                   WHERE f.user_id = ?
                   ORDER BY f.created_at DESC, f.id DESC""",
                (user_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_feedback(self, feedback_id: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
            return int(cursor.rowcount or 0)

    def delete_feedback_for_user(self, user_id: int) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM feedback WHERE user_id = ?", (user_id,))
            return int(cursor.rowcount or 0)

    # -- settings ------------------------------------------------------------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # -- AI battle analysis -------------------------------------------------

    def create_ai_battle_run(
        self,
        *,
        kind: str,
        name: str,
        deck_set_id: str,
        deck_set_name: str,
        ai_types: list[str],
        run_count: int,
        game_id: str | None,
        summary: dict,
        detail: dict,
    ) -> dict:
        run_id = uuid.uuid4().hex[:12]
        created_at = _now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO ai_battle_runs
                   (id, kind, name, deck_set_id, deck_set_name, ai_types_json, run_count,
                    game_id, summary_json, detail_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    kind,
                    name,
                    deck_set_id,
                    deck_set_name,
                    json.dumps(ai_types),
                    run_count,
                    game_id,
                    json.dumps(summary),
                    json.dumps(detail),
                    created_at,
                ),
            )
        return self.get_ai_battle_run(run_id)

    def list_ai_battle_runs(self, limit: int = 200) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, kind, name, deck_set_id, deck_set_name, ai_types_json, run_count,
                          game_id, summary_json, created_at
                   FROM ai_battle_runs ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [self._ai_battle_row_to_dict(row, include_detail=False) for row in rows]

    def get_ai_battle_run(self, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ai_battle_runs WHERE id = ?", (run_id,)).fetchone()
        return self._ai_battle_row_to_dict(row, include_detail=True) if row else None

    def _ai_battle_row_to_dict(self, row: sqlite3.Row, include_detail: bool) -> dict:
        result = dict(row)
        result["ai_types"] = json.loads(result.pop("ai_types_json"))
        result["summary"] = json.loads(result.pop("summary_json"))
        if include_detail:
            result["detail"] = json.loads(result.pop("detail_json"))
        else:
            result.pop("detail_json", None)
        return result

    # -- presence & challenges ----------------------------------------------

    def touch_presence(self, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO presence (user_id, last_seen) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET last_seen = excluded.last_seen",
                (user_id, _now()),
            )

    def active_players(self, within_seconds: int = 40) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=within_seconds)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT u.id, u.username, {_DISPLAY} AS display_name,
                          COALESCE(u.is_guest, 0) AS is_guest,
                          u.wins, u.losses, COUNT(f.id) AS feedback_count
                   FROM presence p
                   JOIN users u ON u.id = p.user_id
                   LEFT JOIN feedback f ON f.user_id = u.id
                   WHERE p.last_seen > ? AND u.matchmaking_ok = 1 AND u.name_flagged = 0
                         AND u.deleted_at IS NULL
                   GROUP BY u.id
                   ORDER BY u.username COLLATE NOCASE""",
                (cutoff,),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_challenge(self, from_user_id: int, to_user_id: int, active_expansions: list[str] | None = None) -> str:
        challenge_id = uuid.uuid4().hex[:12]
        with self._connect(immediate=True) as conn:
            # One live outgoing challenge at a time; new one replaces the old.
            conn.execute(
                "UPDATE challenges SET status = 'cancelled' WHERE from_user_id = ? AND status = 'pending'",
                (from_user_id,),
            )
            conn.execute(
                """INSERT INTO challenges
                   (id, from_user_id, to_user_id, status, active_expansions_json, created_at)
                   VALUES (?, ?, ?, 'pending', ?, ?)""",
                (challenge_id, from_user_id, to_user_id, json.dumps(active_expansions or []), _now()),
            )
        return challenge_id

    def get_challenge(self, challenge_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["active_expansions"] = json.loads(result.pop("active_expansions_json") or "[]")
            return result

    def set_challenge_status(self, challenge_id: str, status: str, game_id: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE challenges SET status = ?, game_id = COALESCE(?, game_id) WHERE id = ?",
                (status, game_id, challenge_id),
            )

    def challenges_for_user(self, user_id: int, max_age_seconds: int = 180) -> dict:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE challenges SET status = 'cancelled' WHERE status = 'pending' AND created_at <= ?",
                (cutoff,),
            )
            incoming = conn.execute(
                """SELECT c.id, u.username AS from_username, c.created_at FROM challenges c
                   JOIN users u ON u.id = c.from_user_id
                   WHERE c.to_user_id = ? AND c.status = 'pending' ORDER BY c.created_at""",
                (user_id,),
            ).fetchall()
            outgoing = conn.execute(
                """SELECT c.id, u.username AS to_username, c.status, c.game_id FROM challenges c
                   JOIN users u ON u.id = c.to_user_id
                   WHERE c.from_user_id = ? AND (c.status = 'pending' OR
                         (c.status = 'accepted' AND c.created_at > ?))
                   ORDER BY c.created_at DESC LIMIT 3""",
                (user_id, cutoff),
            ).fetchall()
            return {"incoming": [dict(row) for row in incoming], "outgoing": [dict(row) for row in outgoing]}

    # -- matchmaking queue -------------------------------------------------

    def join_queue_and_pair(self, user_id: int) -> int | None:
        """Join the quick-match queue. Returns the opponent's user id when a
        pairing happens, otherwise None (caller stays queued)."""
        stale = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        with self._connect(immediate=True) as conn:
            conn.execute("DELETE FROM queue WHERE joined_at <= ?", (stale,))
            row = conn.execute(
                "SELECT user_id FROM queue WHERE user_id != ? ORDER BY joined_at ASC LIMIT 1",
                (user_id,),
            ).fetchone()
            if row:
                conn.execute("DELETE FROM queue WHERE user_id IN (?, ?)", (row["user_id"], user_id))
                return row["user_id"]
            conn.execute(
                "INSERT OR IGNORE INTO queue (user_id, joined_at) VALUES (?, ?)", (user_id, _now())
            )
            return None

    def leave_queue(self, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM queue WHERE user_id = ?", (user_id,))

    def queue_status(self, user_id: int) -> dict:
        stale = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM queue WHERE joined_at <= ?", (stale,))
            count = conn.execute("SELECT COUNT(*) AS n FROM queue").fetchone()["n"]
            queued = (
                conn.execute("SELECT 1 FROM queue WHERE user_id = ?", (user_id,)).fetchone()
                is not None
            )
            return {"queued": queued, "waiting": count}

    # -- matches -----------------------------------------------------------

    def create_match(
        self,
        name: str,
        host_user_id: int,
        seats: int,
        status: str,
        ai_level: str = "deck_hand",
        active_expansions: list[str] | None = None,
        star_breach_prey_player_id: str | None = None,
        star_breach_boss_design_id: str | None = None,
    ) -> str:
        match_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO matches
                   (id, name, status, host_user_id, seats, ai_level, active_expansions_json, star_breach_prey_player_id, star_breach_boss_design_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    match_id,
                    name,
                    status,
                    host_user_id,
                    seats,
                    ai_level,
                    json.dumps(active_expansions or []),
                    star_breach_prey_player_id,
                    star_breach_boss_design_id,
                    _now(),
                    _now(),
                ),
            )
        return match_id

    def add_seat(
        self,
        match_id: str,
        seat_index: int,
        player_id: str,
        display_name: str,
        user_id: int | None = None,
        ai_type: str | None = None,
        star_breach_role: str | None = None,
        ship_design_id: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO match_seats (match_id, seat_index, player_id, user_id, ai_type, display_name, star_breach_role, ship_design_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (match_id, seat_index, player_id, user_id, ai_type, display_name, star_breach_role, ship_design_id),
            )

    def try_join_match(
        self,
        match_id: str,
        user_id: int,
        player_id: str,
        display_name: str,
        star_breach_role: str | None = None,
        ship_design_id: str | None = None,
    ) -> dict:
        """Claim the next free human seat. Raises ValueError when impossible."""
        with self._connect(immediate=True) as conn:
            match = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
            if match is None:
                raise KeyError(match_id)
            if match["status"] != "open":
                raise ValueError("Match is not open.")
            seats = conn.execute(
                "SELECT * FROM match_seats WHERE match_id = ? ORDER BY seat_index", (match_id,)
            ).fetchall()
            if any(seat["user_id"] == user_id for seat in seats):
                raise ValueError("Already seated in this match.")
            if len(seats) >= match["seats"]:
                raise ValueError("Match is full.")
            if star_breach_role and any(
                seat["star_breach_role"] == star_breach_role for seat in seats
            ):
                raise ValueError("That StarBreach role is already claimed.")
            seat_index = len(seats)
            conn.execute(
                """INSERT INTO match_seats (match_id, seat_index, player_id, user_id, ai_type, display_name, star_breach_role, ship_design_id)
                   VALUES (?, ?, ?, ?, NULL, ?, ?, ?)""",
                (match_id, seat_index, player_id, user_id, display_name, star_breach_role, ship_design_id),
            )
            conn.execute("UPDATE matches SET updated_at = ? WHERE id = ?", (_now(), match_id))
            return {"seat_index": seat_index, "full": seat_index + 1 >= match["seats"]}

    def leave_match(self, match_id: str, user_id: int) -> None:
        with self._connect(immediate=True) as conn:
            match = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
            if match is None:
                raise KeyError(match_id)
            if match["status"] != "open":
                raise ValueError("Cannot leave a match that has started.")
            conn.execute(
                "DELETE FROM match_seats WHERE match_id = ? AND user_id = ?", (match_id, user_id)
            )
            remaining = conn.execute(
                "SELECT COUNT(*) AS n FROM match_seats WHERE match_id = ? AND user_id IS NOT NULL",
                (match_id,),
            ).fetchone()["n"]
            if remaining == 0 or match["host_user_id"] == user_id:
                conn.execute("UPDATE matches SET status = 'cancelled', updated_at = ? WHERE id = ?", (_now(), match_id))
                conn.execute("DELETE FROM match_seats WHERE match_id = ?", (match_id,))

    def get_match(self, match_id: str) -> dict | None:
        with self._connect() as conn:
            match = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
            if match is None:
                return None
            seats = conn.execute(
                "SELECT * FROM match_seats WHERE match_id = ? ORDER BY seat_index", (match_id,)
            ).fetchall()
            result = dict(match)
            result["active_expansions"] = json.loads(result.pop("active_expansions_json") or "[]")
            result["seat_list"] = [dict(seat) for seat in seats]
            return result

    def get_match_by_game(self, game_id: str) -> dict | None:
        with self._connect() as conn:
            match = conn.execute("SELECT * FROM matches WHERE game_id = ?", (game_id,)).fetchone()
        return self.get_match(match["id"]) if match else None

    def set_match_started(self, match_id: str, game_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE matches SET status = 'active', game_id = ?, updated_at = ? WHERE id = ?",
                (game_id, _now(), match_id),
            )

    def set_match_status(self, match_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE matches SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), match_id)
            )

    def mark_stats_recorded(self, match_id: str) -> bool:
        """Returns True exactly once per match, guarding double stat counting."""
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT stats_recorded FROM matches WHERE id = ?", (match_id,)
            ).fetchone()
            if row is None or row["stats_recorded"]:
                return False
            conn.execute("UPDATE matches SET stats_recorded = 1 WHERE id = ?", (match_id,))
            return True

    def open_matches(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM matches WHERE status = 'open' ORDER BY created_at DESC LIMIT 25"
            ).fetchall()
        return [
            match
            for row in rows
            if (match := self.get_match(row["id"])) and len(match["seat_list"]) < match["seats"]
        ]

    def matches_for_user(self, user_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT DISTINCT m.id FROM matches m JOIN match_seats s ON s.match_id = m.id
                   WHERE s.user_id = ? AND s.abandoned = 0 AND m.status IN ('open', 'active', 'complete')
                   ORDER BY m.updated_at DESC LIMIT 20""",
                (user_id,),
            ).fetchall()
        return [match for row in rows if (match := self.get_match(row["id"]))]

    def active_match_count_for_user(self, user_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT COUNT(DISTINCT m.id) AS n FROM matches m JOIN match_seats s ON s.match_id = m.id
                   WHERE s.user_id = ? AND s.abandoned = 0 AND m.status IN ('open', 'active')""",
                (user_id,),
            ).fetchone()
        return row["n"] if row else 0

    def mark_seat_abandoned(self, match_id: str, user_id: int, stats_exempt: bool = False) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE match_seats SET abandoned = 1, stats_exempt = MAX(stats_exempt, ?) "
                "WHERE match_id = ? AND user_id = ?",
                (1 if stats_exempt else 0, match_id, user_id),
            )

    # -- game state blobs ----------------------------------------------------

    def create_game(self, state_dict: dict) -> str:
        game_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO games (id, state_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (game_id, json.dumps(state_dict, sort_keys=True), _now(), _now()),
            )
        return game_id

    def load_game(self, game_id: str) -> dict:
        with self._connect() as conn:
            row = conn.execute("SELECT state_json FROM games WHERE id = ?", (game_id,)).fetchone()
            if row is None:
                raise KeyError(game_id)
            return json.loads(row["state_json"])

    def save_game(self, game_id: str, state_dict: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE games SET state_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(state_dict, sort_keys=True), _now(), game_id),
            )


_STORE: V2Store | None = None


def get_v2_store() -> V2Store:
    global _STORE
    configured = Path(os.environ.get("STARSHOT_V2_DB", DEFAULT_DB_PATH))
    if _STORE is None or _STORE.db_path != configured:
        _STORE = V2Store(configured)
    return _STORE
