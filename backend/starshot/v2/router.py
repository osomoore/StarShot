"""HTTP API for StarShot v2: accounts, lobby, matchmaking, and secure play."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
import sqlite3

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from starshot import __version__
from starshot.rules import RulesError
from starshot.rules.expansion_modules import installed_expansion_ids
from starshot.v2 import security
from starshot.v2.ai import AI_LEVELS, AI_TYPES
from starshot.v2.service import (
    advance_game,
    ai_display_name,
    build_match_meta,
    forfeit_player,
    match_turn_info,
    refresh_game,
    seat_for_user,
    serialized_state,
    start_match_game,
    submit_player_orders,
)
from starshot.rules.engine import choose_captain
from starshot.rules.serialization import state_from_dict, state_to_dict
from starshot.v2.game_log import build_debug_log
from starshot.v2.store import get_v2_store
from starshot.v2.views import game_view

router = APIRouter(prefix="/api/v2", tags=["v2"])

SESSION_COOKIE = "starshot_v2_session"
SESSION_MAX_AGE = 30 * 24 * 3600
ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "backend" / "starshot"
FRONTEND_ROOT = ROOT / "frontend" / "v2"


# --------------------------------------------------------------------------
# Auth plumbing
# --------------------------------------------------------------------------


GUEST_SESSION_TTL_DAYS = 1
RECENT_AUTH_SECONDS = 10 * 60

GUEST_FORBIDDEN_DETAIL = (
    "Guests be just sailin' through — sign in with Google, Microsoft, or "
    "Discord to save yer legend."
)


def _current_user(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not signed in.")
    user = get_v2_store().get_session_user(security.session_token_hash(token))
    if user is None:
        raise HTTPException(status_code=401, detail="Session expired. Sign in again.")
    return user


def _registered_user(request: Request) -> dict:
    """The signed-in user, rejecting temporary guest sessions. Every account
    feature (profiles, designs, account management) goes through here so
    guest restrictions are enforced server-side in one place."""
    user = _current_user(request)
    if user.get("is_guest"):
        raise HTTPException(status_code=403, detail=GUEST_FORBIDDEN_DETAIL)
    return user


def _require_recent_auth(request: Request) -> None:
    """Sensitive actions (export, deletion, provider unlink) require that the
    session proved its identity within the last few minutes."""
    token = request.cookies.get(SESSION_COOKIE)
    session = get_v2_store().get_session(security.session_token_hash(token)) if token else None
    stamp = (session or {}).get("reauthed_at") or (session or {}).get("created_at")
    if stamp:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).total_seconds()
            if age <= RECENT_AUTH_SECONDS:
                return
        except ValueError:
            pass
    raise HTTPException(
        status_code=403,
        detail="Please sign in again to confirm it's you before this action.",
        headers={"X-StarShot-Reauth": "required"},
    )


def _set_session(response: Response, user_id: int, request: Request | None = None, *, guest: bool = False) -> None:
    store = get_v2_store()
    if request is not None:
        # Signing in again in the same browser (reauthentication): keep the
        # existing session and just refresh its proof-of-identity time.
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            existing = store.get_session_user(security.session_token_hash(token))
            if existing is not None and existing["id"] == user_id:
                store.refresh_session_auth(security.session_token_hash(token))
                return
    token = security.new_session_token()
    store.create_session(
        security.session_token_hash(token),
        user_id,
        ttl_days=GUEST_SESSION_TTL_DAYS if guest else 30,
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        # Guests get a browser-session cookie so the guest ends with the browser.
        max_age=None if guest else SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _check_maintenance(user: dict) -> None:
    """Block game-affecting actions while the site is under construction
    (admins keep full access to test their changes)."""
    from starshot.v2.admin import admin_usernames
    from starshot.v2.settings import maintenance_message

    message = maintenance_message()
    if message and user["username"].lower() not in admin_usernames():
        raise HTTPException(status_code=503, detail=f"⚓ Under construction: {message}")


def _display_name(user: dict) -> str:
    return user.get("display_name") or user["username"]


def _matchable(user: dict) -> bool:
    """Player matchmaking eligibility: not admin-blocked, name not flagged."""
    return bool(user.get("matchmaking_ok", 1)) and not user.get("name_flagged", 0)


UNMATCHABLE_DETAIL = (
    "Yer current name keeps ye off the player seas — change yer display name "
    "(or see the admiral) to battle other captains. AI raids are still open."
)


def _check_matchable(user: dict) -> None:
    if not _matchable(user):
        raise HTTPException(status_code=403, detail=UNMATCHABLE_DETAIL)


MAX_ACTIVE_MATCHES = 10


def _check_active_match_limit(user: dict) -> None:
    """Cap how many open/active raids a captain can have going at once
    (admins are exempt, since they need to test freely)."""
    from starshot.v2.admin import admin_usernames

    if user["username"].lower() in admin_usernames():
        return
    store = get_v2_store()
    if store.active_match_count_for_user(user["id"]) >= MAX_ACTIVE_MATCHES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Ye already have {MAX_ACTIVE_MATCHES} raids underway — that's the most a captain "
                "can juggle at once. Finish one, or hit the 🏳 next to a raid under Your Battles to "
                "abandon it, before launching or joining another."
            ),
        )


def _public_profile(user: dict) -> dict:
    store = get_v2_store()
    return {
        "username": user["username"],
        "display_name": _display_name(user),
        "is_guest": bool(user.get("is_guest", 0)),
        "name_flagged": bool(user.get("name_flagged", 0)),
        "must_rename": bool(user.get("must_rename", 0)),
        "matchmaking_ok": bool(user.get("matchmaking_ok", 1)),
        "leaderboard_ok": bool(user.get("leaderboard_ok", 1)),
        "wins": user["wins"],
        "losses": user["losses"],
        "draws": user["draws"],
        "games_played": user["games_played"],
        "created_at": user["created_at"],
        "feedback_count": user.get("feedback_count", store.feedback_count(user["id"])),
    }


def _validated_expansions(active_expansions: list[str]) -> list[str]:
    allowed_expansions = installed_expansion_ids()
    result = [expansion for expansion in dict.fromkeys(active_expansions) if expansion]
    unknown = [expansion for expansion in result if expansion not in allowed_expansions]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown expansion: {unknown[0]}")
    return result


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=20)
    password: str = Field(min_length=security.MIN_PASSWORD_LENGTH, max_length=128)


def _latest_mtime(root: Path, suffixes: set[str]) -> float | None:
    latest: float | None = None
    if not root.exists():
        return None
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        if "__pycache__" in path.parts:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        latest = mtime if latest is None else max(latest, mtime)
    return latest


def _iso_from_mtime(mtime: float | None) -> str | None:
    if mtime is None:
        return None
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _git_build_id() -> str | None:
    env_build = os.environ.get("STARSHOT_BUILD_ID") or os.environ.get("STARSHOT_BUILD_NUMBER")
    if env_build:
        return env_build
    git_dir = ROOT / ".git"
    head_path = git_dir / "HEAD"
    try:
        head = head_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if head.startswith("ref: "):
        ref_path = git_dir / head[5:].strip()
        try:
            head = ref_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
    return head[:12] if head else None


@router.get("/build-info")
def build_info() -> dict:
    backend_mtime = _latest_mtime(BACKEND_ROOT, {".py"})
    frontend_mtime = _latest_mtime(FRONTEND_ROOT, {".html", ".css", ".js"})
    return {
        "version": __version__,
        "build_id": _git_build_id(),
        "backend": {"built_at": _iso_from_mtime(backend_mtime)},
        "frontend": {"built_at": _iso_from_mtime(frontend_mtime)},
        "server_now": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


# Ordinary username/password registration and login are gone: players sign in
# only through verified Google/Microsoft/Discord identities (or as a guest).
# Password login remains solely for the special admin accounts.
@router.post("/auth/login")
def login(credentials: Credentials, request: Request, response: Response) -> dict:
    from starshot.v2 import ratelimit
    from starshot.v2.admin import admin_usernames, ensure_admin_seeded

    ratelimit.throttle_login(f"login:{credentials.username.strip().lower()}")
    ensure_admin_seeded()
    if credentials.username.strip().lower() not in admin_usernames():
        raise HTTPException(
            status_code=403,
            detail="Password sign-in is for the admiral only. Use Google, Microsoft, or Discord.",
        )
    store = get_v2_store()
    user = store.get_user_by_name(credentials.username)
    if user is None or not security.verify_password(credentials.password, user["pass_hash"]):
        raise HTTPException(status_code=401, detail="Wrong name or password, matey.")
    _set_session(response, user["id"], request)
    return {"user": _public_profile(user)}


@router.post("/auth/guest")
def guest_login(request: Request, response: Response) -> dict:
    """'Just Sailin' Through': a temporary guest session — not a permanent
    account. Guests can play, but nothing persists past the session."""
    from starshot.v2 import names, ratelimit

    ratelimit.throttle_guest_creation(ratelimit.client_ip(request))
    store = get_v2_store()
    user = None
    for _ in range(20):
        try:
            created = store.create_guest_user(
                "guest-" + secrets.token_hex(4), names.random_guest_name()
            )
            user = store.get_user(created["id"])
            break
        except sqlite3.IntegrityError:
            continue  # random username collided; retry
    if user is None:
        raise HTTPException(status_code=500, detail="Could not start a guest voyage. Try again.")
    _set_session(response, user["id"], guest=True)
    return {"user": _public_profile(user)}


class ExternalCredential(BaseModel):
    credential: str = Field(min_length=20, max_length=4096)
    # True when a signed-in user is attaching this provider to their existing
    # account (from the account page) rather than signing in with it.
    link: bool = False
    # True when a signed-in guest is "Claiming their Legend" — converting
    # their temporary voyage into a permanent account via this provider.
    claim: bool = False


def _link_provider_to_current(provider: str, sub: str, email: str | None, request: Request) -> dict:
    """Attach a freshly verified provider identity to the signed-in account.
    One provider identity can never belong to two StarShot accounts."""
    user = _registered_user(request)
    store = get_v2_store()
    existing = store.get_user_by_external_sub(provider, sub)
    if existing is not None:
        if existing["id"] == user["id"]:
            return {"user": _public_profile(user), "linked": True}
        raise HTTPException(
            status_code=409,
            detail="That sign-in identity already belongs to another StarShot account.",
        )
    if user.get(f"{provider}_sub"):
        raise HTTPException(
            status_code=409,
            detail=f"This account already has a {provider.title()} identity linked.",
        )
    store.link_external_sub(user["id"], provider, sub, email)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        store.refresh_session_auth(security.session_token_hash(token))
    return {"user": _public_profile(store.get_user(user["id"])), "linked": True}


def _claim_guest_account(provider: str, sub: str, email: str | None, request: Request) -> dict:
    """'Claim My Legend': convert the current guest session into a permanent
    account by attaching a verified provider identity. Keeps the same user
    row (and any match seat it currently holds) rather than creating a new
    account, so the voyage in progress isn't interrupted."""
    user = _current_user(request)
    if not user.get("is_guest"):
        raise HTTPException(
            status_code=400, detail="Only a guest voyage can be claimed as a permanent account."
        )
    store = get_v2_store()
    if store.get_user_by_external_sub(provider, sub) is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "That sign-in already has a permanent StarShot legend — log out "
                "of this guest voyage and sign in with it directly instead."
            ),
        )
    store.claim_guest_account(user["id"], provider, sub, email)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        store.refresh_session_auth(security.session_token_hash(token))
    return {"user": _public_profile(store.get_user(user["id"])), "claimed": True}


def _external_login(
    provider: str,
    sub: str,
    response: Response,
    request: Request | None = None,
    *,
    email: str | None = None,
    email_verified: bool = False,
) -> dict:
    """Sign in with a verified external identity; the provider's sub is the
    permanent linked identity. Google, Microsoft, and Discord all funnel through
    here so account linking and session creation live in one place.

    Resolution order:
      1. An account already linked to this (provider, sub) — log in.
      2. Otherwise, an account carrying the same *verified* email — link this
         provider identity to it and log in.
      3. Otherwise, create a new account with a generated username and a random
         piratey display name.
    """
    from starshot.v2 import names

    store = get_v2_store()
    verified_email = email if (email and email_verified) else None

    user = store.get_user_by_external_sub(provider, sub)
    if user is None and verified_email:
        existing = store.get_user_by_verified_email(verified_email)
        if existing is not None and not existing.get(f"{provider}_sub"):
            store.link_external_sub(existing["id"], provider, sub, verified_email)
            user = store.get_user_by_external_sub(provider, sub)
    if user is None:
        for _ in range(20):
            try:
                created = store.create_external_user(
                    provider,
                    sub,
                    "captain-" + secrets.token_hex(4),
                    names.random_pirate_name(),
                    email=verified_email,
                )
                user = store.get_user(created["id"])
                break
            except sqlite3.IntegrityError:
                # Either the random username collided (retry) or a parallel
                # sign-in already linked this sub (use that account).
                user = store.get_user_by_external_sub(provider, sub)
                if user is not None:
                    break
        if user is None:
            raise HTTPException(status_code=500, detail="Could not create yer account. Try again.")
    store.update_provider_email(user["id"], provider, email)
    _set_session(response, user["id"], request)
    return {"user": _public_profile(user)}


@router.post("/auth/google")
def google_login(body: ExternalCredential, request: Request, response: Response) -> dict:
    from starshot.v2 import google_identity, ratelimit

    ratelimit.throttle_login(f"google:{ratelimit.client_ip(request)}")
    try:
        claims = google_identity.verify_google_credential(body.credential)
    except ValueError:
        raise HTTPException(
            status_code=401, detail="Google sign-in could not be verified. Try again."
        )
    email = claims.get("email")
    verified = bool(claims.get("email_verified"))
    if body.link:
        return _link_provider_to_current(
            "google", str(claims["sub"]), email if verified else None, request
        )
    if body.claim:
        return _claim_guest_account(
            "google", str(claims["sub"]), email if verified else None, request
        )
    return _external_login(
        "google",
        str(claims["sub"]),
        response,
        request,
        email=email,
        email_verified=verified,
    )


@router.post("/auth/microsoft")
def microsoft_login(body: ExternalCredential, request: Request, response: Response) -> dict:
    from starshot.v2 import microsoft_identity, ratelimit

    ratelimit.throttle_login(f"microsoft:{ratelimit.client_ip(request)}")
    try:
        claims = microsoft_identity.verify_microsoft_credential(body.credential)
    except ValueError:
        raise HTTPException(
            status_code=401, detail="Microsoft sign-in could not be verified. Try again."
        )
    # Microsoft issues the token only after authenticating the account, so an
    # email/upn it carries belongs to that verified user.
    email = claims.get("email") or claims.get("preferred_username")
    email = email if isinstance(email, str) and "@" in email else None
    if body.link:
        return _link_provider_to_current("microsoft", str(claims["sub"]), email, request)
    if body.claim:
        return _claim_guest_account("microsoft", str(claims["sub"]), email, request)
    return _external_login(
        "microsoft",
        str(claims["sub"]),
        response,
        request,
        email=email,
        email_verified=True,
    )


class DiscordAuthCode(BaseModel):
    code: str = Field(min_length=1, max_length=512)
    code_verifier: str = Field(min_length=43, max_length=128)
    redirect_uri: str = Field(min_length=1, max_length=512)
    link: bool = False
    claim: bool = False


@router.post("/auth/discord")
def discord_login(body: DiscordAuthCode, request: Request, response: Response) -> dict:
    from starshot.v2 import discord_identity, ratelimit

    ratelimit.throttle_login(f"discord:{ratelimit.client_ip(request)}")
    try:
        user = discord_identity.exchange_discord_code(
            body.code, body.code_verifier, body.redirect_uri
        )
    except ValueError:
        raise HTTPException(
            status_code=401, detail="Discord sign-in could not be verified. Try again."
        )
    email = user.get("email") if user.get("email_verified") else None
    if body.link:
        return _link_provider_to_current("discord", user["sub"], email, request)
    if body.claim:
        return _claim_guest_account("discord", user["sub"], email, request)
    return _external_login(
        "discord",
        user["sub"],
        response,
        request,
        email=user.get("email"),
        email_verified=bool(user.get("email_verified")),
    )


@router.post("/auth/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        store = get_v2_store()
        token_hash = security.session_token_hash(token)
        user = store.get_session_user(token_hash)
        store.delete_session(token_hash)
        # A guest is a temporary session, not an account: leaving the ship
        # scuttles the guest identity and any content tied to it.
        if user is not None and user.get("is_guest"):
            store.delete_account(user["id"])
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


def onboarding_flags(user: dict) -> dict:
    """What first-login (or re-acceptance) onboarding still owes us. Guests
    skip Terms/Privacy (they accepted the guest notice instead, and have no
    persistent account for a policy version to attach to) but still get
    offered a chance to pick their own display name."""
    from starshot.v2 import policies

    if user.get("is_guest"):
        return {"needs_terms": False, "needs_display_name": not bool(user.get("name_confirmed"))}
    current = policies.current_versions()
    return {
        "needs_terms": (
            user.get("terms_version") != current["terms_version"]
            or user.get("privacy_version") != current["privacy_version"]
        ),
        "needs_display_name": not bool(user.get("name_confirmed")),
    }


@router.get("/me")
def me(request: Request) -> dict:
    from starshot.v2.admin import admin_usernames

    user = _current_user(request)
    store = get_v2_store()
    matches = [build_match_meta(match, None) for match in store.matches_for_user(user["id"])]
    return {
        "user": _public_profile(user),
        "matches": matches,
        "is_admin": user["username"].lower() in admin_usernames(),
        **onboarding_flags(user),
    }


@router.get("/policies")
def get_policies() -> dict:
    """Current Terms of Service and Privacy Policy (single-source documents)."""
    from starshot.v2 import policies

    return {
        kind: {
            "title": policy["title"],
            "version": policy["version"],
            "effective_date": policy["effective_date"],
            "text": policy["text"],
        }
        for kind, policy in ((k, policies.get_policy(k)) for k in ("terms", "privacy"))
    }


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=security.MIN_PASSWORD_LENGTH, max_length=128)


@router.post("/auth/password")
def change_password(body: PasswordChange, request: Request) -> dict:
    user = _registered_user(request)
    if not security.verify_password(body.current_password, user["pass_hash"]):
        raise HTTPException(status_code=401, detail="Current password is wrong.")
    get_v2_store().update_password(user["id"], security.hash_password(body.new_password))
    return {"ok": True}


class DisplayNameChange(BaseModel):
    display_name: str = Field(min_length=3, max_length=24)


FLAGGED_NAME_WARNING = (
    "That name be on the reprehensible side, captain. Ye may keep it, but yer "
    "name will be hidden from the leaderboards and ye won't be matched "
    "against other players until ye pick a friendlier one."
)


@router.post("/profile/display-name")
def set_display_name(body: DisplayNameChange, request: Request) -> dict:
    from starshot.v2 import names

    # Guests may set a display name too — needed for first-login onboarding
    # and for the name to read sensibly if they later claim the account.
    user = _current_user(request)
    store = get_v2_store()
    proposed = " ".join(body.display_name.split())
    if not names.valid_display_name(proposed):
        raise HTTPException(
            status_code=400,
            detail="Display names are 3-24 characters: letters, digits, spaces, ' - _ or .",
        )
    if names.is_reserved_name(proposed):
        raise HTTPException(
            status_code=400,
            detail="That name be reserved for the crown — no posing as admins, moderators, guests, or StarShot itself.",
        )
    if store.is_illegal_name(proposed):
        raise HTTPException(
            status_code=400,
            detail="The admiral has banned that name from these seas. Pick another.",
        )
    flagged = names.name_is_objectionable(proposed)
    store.set_display_name(user["id"], proposed, flagged)
    return {
        "user": _public_profile(store.get_user(user["id"])),
        "flagged": flagged,
        "warning": FLAGGED_NAME_WARNING if flagged else None,
    }


@router.get("/profile/random-name")
def random_display_name(request: Request) -> dict:
    from starshot.v2 import names

    _current_user(request)
    store = get_v2_store()
    name = names.random_pirate_name()
    for _attempt in range(10):
        if not store.is_illegal_name(name):
            break
        name = names.random_pirate_name()
    return {"name": name}


@router.get("/players/{username}")
def player_profile(username: str) -> dict:
    user = get_v2_store().get_user_by_name(username)
    if user is None:
        raise HTTPException(status_code=404, detail="No such pirate.")
    return {"user": _public_profile(user)}


@router.get("/leaderboard")
def leaderboard() -> dict:
    store = get_v2_store()
    return {"leaderboard": store.leaderboard(), **store.leaderboard_bundle()}


class FeedbackRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    liked: str = Field(default="", max_length=2000)
    disliked: str = Field(default="", max_length=2000)
    thoughts: str = Field(default="", max_length=3000)
    match_id: str | None = Field(default=None, max_length=40)
    game_id: str | None = Field(default=None, max_length=80)
    is_bug_report: bool = False
    screenshot_data_url: str = Field(default="", max_length=2_500_000)


@router.post("/feedback")
def submit_feedback(body: FeedbackRequest, request: Request) -> dict:
    # Guests can report rough edges too. If that temporary identity is later
    # destroyed, the feedback stays attached to the anonymized tombstone user.
    user = _current_user(request)
    store = get_v2_store()
    game_log = ""
    screenshot_data_url = ""
    if body.is_bug_report and body.game_id:
        match = store.get_match_by_game(body.game_id)
        if match and seat_for_user(match, user["id"]):
            try:
                game_log = build_debug_log(store.load_game(body.game_id), match, game_id=body.game_id)
            except KeyError:
                game_log = ""
            if body.screenshot_data_url.startswith((
                "data:image/png;base64,",
                "data:image/jpeg;base64,",
                "data:image/webp;base64,",
            )):
                screenshot_data_url = body.screenshot_data_url
    feedback = store.create_feedback(
        user_id=user["id"],
        rating=body.rating,
        liked=body.liked.strip(),
        disliked=body.disliked.strip(),
        thoughts=body.thoughts.strip(),
        match_id=body.match_id,
        game_id=body.game_id,
        is_bug_report=body.is_bug_report,
        game_log=game_log,
        screenshot_data_url=screenshot_data_url,
    )
    return {
        "ok": True,
        "feedback": feedback,
        "feedback_count": store.feedback_count(user["id"]),
    }


# --------------------------------------------------------------------------
# Lobby & matchmaking
# --------------------------------------------------------------------------


@router.get("/lobby")
def lobby(request: Request) -> dict:
    user = _current_user(request)
    store = get_v2_store()
    store.touch_presence(user["id"])
    my_matches = []
    for match in store.matches_for_user(user["id"]):
        meta = build_match_meta(match, None)
        seat = seat_for_user(match, user["id"])
        if match["status"] in ("active", "complete") and seat:
            meta["turn"] = match_turn_info(store, match, seat["player_id"])
        my_matches.append(meta)
    from starshot.v2.settings import maintenance_message

    return {
        "queue": store.queue_status(user["id"]),
        "open_matches": [build_match_meta(match, None) for match in store.open_matches()],
        "my_matches": my_matches,
        "ai_types": AI_TYPES,
        "ai_difficulties": AI_LEVELS,
        "active_players": [
            player for player in store.active_players() if player["id"] != user["id"]
        ],
        "challenges": store.challenges_for_user(user["id"]),
        "maintenance": maintenance_message(),
    }


class ChallengeRequest(BaseModel):
    username: str = Field(min_length=3, max_length=20)
    active_expansions: list[str] = Field(default_factory=list, max_length=4)


@router.post("/lobby/challenge")
def send_challenge(body: ChallengeRequest, request: Request) -> dict:
    user = _current_user(request)
    _check_maintenance(user)
    _check_matchable(user)
    store = get_v2_store()
    target = store.get_user_by_name(body.username)
    if target is None:
        raise HTTPException(status_code=404, detail="No such captain.")
    if target["id"] == user["id"]:
        raise HTTPException(status_code=400, detail="Duelling yerself is a court-martial offense.")
    if not _matchable(target):
        raise HTTPException(status_code=400, detail="That captain isn't taking challenges right now.")
    challenge_id = store.create_challenge(
        user["id"],
        target["id"],
        active_expansions=_validated_expansions(body.active_expansions),
    )
    return {"challenge_id": challenge_id}


class ChallengeResponse(BaseModel):
    accept: bool


@router.post("/lobby/challenge/{challenge_id}/respond")
def respond_challenge(challenge_id: str, body: ChallengeResponse, request: Request) -> dict:
    user = _current_user(request)
    store = get_v2_store()
    challenge = store.get_challenge(challenge_id)
    if challenge is None or challenge["to_user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Challenge not found.")
    if challenge["status"] != "pending":
        raise HTTPException(status_code=400, detail="Challenge already settled.")
    if not body.accept:
        store.set_challenge_status(challenge_id, "declined")
        return {"accepted": False}
    _check_maintenance(user)
    _check_matchable(user)
    _check_active_match_limit(user)
    challenger = store.get_user(challenge["from_user_id"])
    store.leave_queue(user["id"])
    store.leave_queue(challenger["id"])
    match_id = store.create_match(
        name=f"{_display_name(challenger)} vs {_display_name(user)} (duel)",
        host_user_id=challenger["id"],
        seats=2,
        status="open",
        active_expansions=challenge.get("active_expansions") or [],
    )
    store.add_seat(match_id, 0, challenger["username"], _display_name(challenger), user_id=challenger["id"])
    store.add_seat(match_id, 1, user["username"], _display_name(user), user_id=user["id"])
    game_id = start_match_game(store, store.get_match(match_id))
    store.set_challenge_status(challenge_id, "accepted", game_id=game_id)
    return {"accepted": True, "match_id": match_id, "game_id": game_id}


@router.post("/lobby/challenge/{challenge_id}/cancel")
def cancel_challenge(challenge_id: str, request: Request) -> dict:
    user = _current_user(request)
    store = get_v2_store()
    challenge = store.get_challenge(challenge_id)
    if challenge is None or user["id"] not in (challenge["from_user_id"], challenge["to_user_id"]):
        raise HTTPException(status_code=404, detail="Challenge not found.")
    store.set_challenge_status(challenge_id, "cancelled")
    return {"ok": True}


class QueueRequest(BaseModel):
    action: str = Field(pattern="^(join|leave)$")


@router.post("/lobby/queue")
def quick_match(body: QueueRequest, request: Request) -> dict:
    user = _current_user(request)
    if body.action == "join":
        _check_maintenance(user)
        _check_matchable(user)
    store = get_v2_store()
    if body.action == "leave":
        store.leave_queue(user["id"])
        return {"queued": False, "matched": False}
    opponent_id = store.join_queue_and_pair(user["id"])
    if opponent_id is None:
        return {"queued": True, "matched": False}
    opponent = store.get_user(opponent_id)
    match_id = store.create_match(
        name=f"{_display_name(opponent)} vs {_display_name(user)}",
        host_user_id=opponent_id,
        seats=2,
        status="open",
    )
    store.add_seat(match_id, 0, opponent["username"], _display_name(opponent), user_id=opponent_id)
    store.add_seat(match_id, 1, user["username"], _display_name(user), user_id=user["id"])
    match = store.get_match(match_id)
    game_id = start_match_game(store, match)
    return {"queued": False, "matched": True, "match_id": match_id, "game_id": game_id}


class CreateMatchRequest(BaseModel):
    name: str = Field(default="", max_length=40)
    ai_types: list[str] = Field(default_factory=list, max_length=3)
    ai_level: str = Field(default="deck_hand")
    open_seats: int = Field(default=0, ge=0, le=3)
    active_expansions: list[str] = Field(default_factory=list, max_length=4)
    star_breach_prey_player_id: str | None = Field(default=None, max_length=80)
    star_breach_boss_design_id: str | None = Field(default=None, max_length=80)
    star_breach_role: str | None = Field(default=None, max_length=40)
    ship_design_id: str | None = Field(default=None, max_length=140)


def _validated_star_breach_role(role: str | None) -> str | None:
    if not role:
        return None
    from starshot.rules.star_breach import ROLES_BY_ID

    if role not in ROLES_BY_ID:
        raise HTTPException(status_code=400, detail=f"Unknown StarBreach role: {role}")
    return role


def _validated_ship_design_id(ship_design_id: str | None, user: dict) -> str | None:
    """A seat's ship pick: empty = base ship; otherwise a battle-ready global
    design or one of the picker's own designs (`user:<uid>:<id>`)."""
    if not ship_design_id:
        return None
    from starshot.v2.service import _load_playable_ship_design, parse_ship_design_ref

    try:
        owner_id, _bare = parse_ship_design_ref(ship_design_id)
        if owner_id is not None and owner_id != user["id"]:
            raise ValueError("You can only fly your own ship designs.")
        _load_playable_ship_design(ship_design_id)  # fail fast at pick time
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ship_design_id


def _resolve_requested_prey_id(body: CreateMatchRequest, host_username: str) -> str | None:
    requested = body.star_breach_prey_player_id
    if not requested:
        return None
    if requested == "__host__":
        return host_username
    ai_ids: list[str] = []
    counts: dict[str, int] = {}
    for ai_type in body.ai_types:
        counts[ai_type] = counts.get(ai_type, 0) + 1
        ai_ids.append(f"ai:{ai_type}:{counts[ai_type]}")
    if requested.startswith("__ai__:"):
        try:
            index = int(requested.split(":", 1)[1])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Unknown StarBreach Prey selection.") from exc
        if index < 0 or index >= len(ai_ids):
            raise HTTPException(status_code=400, detail="Unknown StarBreach Prey selection.")
        return ai_ids[index]
    if requested == host_username or requested in ai_ids:
        return requested
    raise HTTPException(status_code=400, detail="Unknown StarBreach Prey selection.")


@router.post("/matches")
def create_match(body: CreateMatchRequest, request: Request) -> dict:
    user = _current_user(request)
    _check_maintenance(user)
    _check_active_match_limit(user)
    if body.open_seats > 0:
        _check_matchable(user)  # AI-only raids stay open to everyone
    for ai_type in body.ai_types:
        if ai_type not in AI_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown AI type: {ai_type}")
    if body.ai_types and body.ai_level not in AI_LEVELS:
        raise HTTPException(status_code=400, detail=f"Unknown AI level: {body.ai_level}")
    active_expansions = _validated_expansions(body.active_expansions)
    prey_player_id = _resolve_requested_prey_id(body, user["username"]) if "star_breach" in active_expansions else None
    host_role = _validated_star_breach_role(body.star_breach_role) if "star_breach" in active_expansions else None
    boss_design_id = body.star_breach_boss_design_id if "star_breach" in active_expansions else None
    if "star_breach" in active_expansions and not boss_design_id:
        from starshot.v2.settings import default_starbreach_boss_design_id

        boss_design_id = default_starbreach_boss_design_id() or None
    if "star_breach" in active_expansions and not boss_design_id:
        raise HTTPException(
            status_code=400,
            detail="Pick a battle-ready StarBreach boss design before launching.",
        )
    if boss_design_id:
        from starshot.v2.service import _load_playable_boss_design, parse_boss_design_ref
        from starshot.v2.settings import allowed_starbreach_boss_design_ids

        try:
            owner_id, _bare = parse_boss_design_ref(boss_design_id)
            if owner_id is not None and owner_id != user["id"]:
                raise ValueError("You can only launch battles against your own boss designs.")
            allowed = allowed_starbreach_boss_design_ids()
            if owner_id is None and allowed and boss_design_id not in allowed:
                raise ValueError("That StarBreach boss is not allowed for new games.")
            _load_playable_boss_design(boss_design_id)  # fail fast at creation
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    total = 1 + len(body.ai_types) + body.open_seats
    minimum = 1 if "star_breach" in active_expansions else 2
    if total < minimum or total > 4:
        raise HTTPException(status_code=400, detail=f"Matches need {minimum} to 4 combatants.")
    store = get_v2_store()
    store.leave_queue(user["id"])  # starting your own battle cancels quick-match
    name = body.name.strip() or f"{_display_name(user)}'s raid"
    match_id = store.create_match(
        name,
        user["id"],
        seats=total,
        status="open",
        ai_level=body.ai_level,
        active_expansions=active_expansions,
        star_breach_prey_player_id=prey_player_id,
        star_breach_boss_design_id=boss_design_id,
    )
    store.add_seat(
        match_id,
        0,
        user["username"],
        _display_name(user),
        user_id=user["id"],
        star_breach_role=host_role,
        ship_design_id=_validated_ship_design_id(body.ship_design_id, user),
    )
    counts: dict[str, int] = {}
    for index, ai_type in enumerate(body.ai_types):
        counts[ai_type] = counts.get(ai_type, 0) + 1
        store.add_seat(
            match_id,
            index + 1,
            f"ai:{ai_type}:{counts[ai_type]}",
            ai_display_name(ai_type, counts[ai_type]),
            ai_type=ai_type,
        )
    match = store.get_match(match_id)
    game_id = None
    if body.open_seats == 0:
        game_id = start_match_game(store, match)
        match = store.get_match(match_id)
    return {"match": build_match_meta(match, None), "game_id": game_id}


class JoinMatchRequest(BaseModel):
    star_breach_role: str | None = Field(default=None, max_length=40)
    ship_design_id: str | None = Field(default=None, max_length=140)


@router.post("/matches/{match_id}/join")
def join_match(match_id: str, request: Request, body: JoinMatchRequest | None = None) -> dict:
    user = _current_user(request)
    _check_maintenance(user)
    _check_matchable(user)
    _check_active_match_limit(user)
    store = get_v2_store()
    existing = store.get_match(match_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Match not found.")
    role = (
        _validated_star_breach_role(body.star_breach_role if body else None)
        if "star_breach" in (existing.get("active_expansions") or [])
        else None
    )
    ship_design_id = _validated_ship_design_id(body.ship_design_id if body else None, user)
    store.leave_queue(user["id"])
    try:
        result = store.try_join_match(
            match_id,
            user["id"],
            user["username"],
            _display_name(user),
            star_breach_role=role,
            ship_design_id=ship_design_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Match not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    match = store.get_match(match_id)
    game_id = None
    if result["full"]:
        game_id = start_match_game(store, match)
        match = store.get_match(match_id)
    return {"match": build_match_meta(match, None), "game_id": game_id}


@router.post("/matches/{match_id}/leave")
def leave_match(match_id: str, request: Request) -> dict:
    user = _current_user(request)
    try:
        get_v2_store().leave_match(match_id, user["id"])
    except KeyError:
        raise HTTPException(status_code=404, detail="Match not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.post("/matches/{match_id}/start")
def start_match(match_id: str, request: Request) -> dict:
    user = _current_user(request)
    _check_maintenance(user)
    store = get_v2_store()
    match = store.get_match(match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found.")
    if match["host_user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only the host can give the launch order.")
    if match["status"] != "open":
        raise HTTPException(status_code=400, detail="Match already started.")
    if len(match["seat_list"]) < 2:
        raise HTTPException(status_code=400, detail="Need at least two combatants.")
    game_id = start_match_game(store, match)
    match = store.get_match(match_id)
    return {"match": build_match_meta(match, None), "game_id": game_id}


@router.post("/matches/{match_id}/abandon")
def abandon_match(match_id: str, request: Request) -> dict:
    """Strike the colors: forfeit an active game (or dismiss an open/finished
    one) and drop it from your battles list."""
    user = _current_user(request)
    store = get_v2_store()
    match = store.get_match(match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found.")
    seat = seat_for_user(match, user["id"])
    if seat is None:
        raise HTTPException(status_code=403, detail="You are not in this match.")
    if match["status"] == "open":
        try:
            store.leave_match(match_id, user["id"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "forfeited": False}
    if match["status"] == "active":
        # Bailing before sealing round-1 orders costs no loss — mark the seat
        # exempt BEFORE the forfeit possibly completes the game and records stats.
        turn = match_turn_info(store, match, seat["player_id"]) or {}
        early = turn.get("phase") == "give_orders" and turn.get("round_number") == 1 and turn.get("your_turn")
        store.mark_seat_abandoned(match_id, user["id"], stats_exempt=bool(early))
        forfeit_player(store, store.get_match(match_id), seat["player_id"])
        return {"ok": True, "forfeited": True, "counted_as_loss": not early}
    store.mark_seat_abandoned(match_id, user["id"])
    return {"ok": True, "forfeited": False}


@router.get("/matches/{match_id}")
def match_detail(match_id: str, request: Request) -> dict:
    _current_user(request)
    match = get_v2_store().get_match(match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found.")
    return {"match": build_match_meta(match, None)}


# --------------------------------------------------------------------------
# Game play
# --------------------------------------------------------------------------


def _match_and_seat(request: Request, game_id: str) -> tuple[dict, dict, dict | None]:
    """Returns (user, match, seat). Seat is None for a spectating host — e.g.
    the admin watching an AI-only battle they launched."""
    user = _current_user(request)
    store = get_v2_store()
    match = store.get_match_by_game(game_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Game not found.")
    seat = seat_for_user(match, user["id"])
    if seat is None:
        human_seats = [s for s in match["seat_list"] if not s["ai_type"]]
        if match["host_user_id"] == user["id"] and not human_seats:
            return user, match, None  # spectator on an AI-only battle
        raise HTTPException(status_code=403, detail="You are not aboard this battle.")
    return user, match, seat


@router.get("/games/{game_id}/view")
def view_game(game_id: str, request: Request, since: int = -1) -> dict:
    _, match, seat = _match_and_seat(request, game_id)
    store = get_v2_store()
    try:
        state_dict = serialized_state(store, game_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Game not found.")
    version = len(state_dict.get("event_log") or [])
    if since >= 0 and version == since and match["status"] != "open":
        return {"unchanged": True, "version": version}
    # Push AI/resolution forward in case the game is waiting only on bots.
    state = refresh_game(store, match)
    state_dict = serialized_state(store, game_id)
    viewer_player_id = seat["player_id"] if seat else None
    view = game_view(state_dict, viewer_player_id)
    return {
        "unchanged": False,
        "version": view["version"],
        "match": build_match_meta(get_v2_store().get_match(match["id"]), state),
        "you": viewer_player_id,
        "state": view,
    }


@router.get("/games/{game_id}/debug-log")
def debug_log(game_id: str, request: Request) -> dict:
    _, match, seat = _match_and_seat(request, game_id)
    if seat is None:
        raise HTTPException(status_code=403, detail="Spectators cannot export battle logs.")
    store = get_v2_store()
    try:
        state_dict = store.load_game(game_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Game not found.")
    return {"log": build_debug_log(state_dict, match, game_id=game_id)}


class OrdersRequest(BaseModel):
    orders: dict


class CaptainChoiceRequest(BaseModel):
    captain_id: str = Field(max_length=80)


@router.post("/games/{game_id}/captain")
def choose_captain_endpoint(game_id: str, body: CaptainChoiceRequest, request: Request) -> dict:
    _, match, seat = _match_and_seat(request, game_id)
    if seat is None:
        raise HTTPException(status_code=403, detail="Spectators don't choose captains.")
    _check_maintenance(_)
    store = get_v2_store()
    try:
        raw = store.load_game(game_id)
        from starshot.v2.service import deck_path_for_game
        from starshot.rules.deck_data import deck_set_override

        deck_path = deck_path_for_game(raw)
        with deck_set_override(deck_path):
            state = choose_captain(state_from_dict(raw), seat["player_id"], body.captain_id)
            state = advance_game(state, match, deck_path)
            store.save_game(game_id, state_to_dict(state, reveal_orders=True))
    except KeyError:
        raise HTTPException(status_code=404, detail="Game not found.")
    except (RulesError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    state_dict = serialized_state(store, game_id)
    view = game_view(state_dict, seat["player_id"])
    return {
        "version": view["version"],
        "match": build_match_meta(store.get_match(match["id"]), state),
        "you": seat["player_id"],
        "state": view,
    }


@router.post("/games/{game_id}/orders")
def submit_orders_endpoint(game_id: str, body: OrdersRequest, request: Request) -> dict:
    _, match, seat = _match_and_seat(request, game_id)
    if seat is None:
        raise HTTPException(status_code=403, detail="Spectators don't give orders.")
    _check_maintenance(_)
    store = get_v2_store()
    try:
        state = submit_player_orders(store, match, seat["player_id"], body.orders)
    except KeyError:
        raise HTTPException(status_code=404, detail="Game not found.")
    except (RulesError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    state_dict = serialized_state(store, game_id)
    view = game_view(state_dict, seat["player_id"])
    return {
        "version": view["version"],
        "match": build_match_meta(store.get_match(match["id"]), state),
        "you": seat["player_id"],
        "state": view,
    }
