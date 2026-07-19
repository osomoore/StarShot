"""Discord sign-in: OAuth2 Authorization Code + PKCE.

Unlike Google and Microsoft (which hand the browser a signed ID token we verify
locally), Discord has no ID-token flow, so we run the authorization-code dance:
the browser sends us the one-time ``code`` plus the PKCE ``code_verifier`` it
generated, and we redeem them server-side for an access token, then read the
user from Discord's API. No client secret is involved — Discord is configured as
a Public Client, so PKCE alone proves the exchange came from the app that
started the flow. The Client ID is public by design (it ships to every browser),
so the default lives in code and STARSHOT_DISCORD_CLIENT_ID can override it.
"""

from __future__ import annotations

import os

DISCORD_CLIENT_ID = os.environ.get(
    "STARSHOT_DISCORD_CLIENT_ID",
    "1528360566857535590",
)

_TOKEN_URL = "https://discord.com/api/oauth2/token"
_USER_URL = "https://discord.com/api/users/@me"
_HTTP_TIMEOUT = 10


def _avatar_url(user: dict) -> str | None:
    """The user's avatar image URL, if they have one set."""
    user_id = user.get("id")
    avatar = user.get("avatar")
    if not user_id or not avatar:
        return None
    ext = "gif" if str(avatar).startswith("a_") else "png"
    return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.{ext}"


def exchange_discord_code(code: str, code_verifier: str, redirect_uri: str) -> dict:
    """Redeem an authorization code (with PKCE) and return the Discord user.

    Discord validates PKCE by recomputing the code_challenge from the
    code_verifier we send here; a mismatch (or a stale/forged code) makes the
    token request fail, which we surface as ValueError. Returns a dict with
    ``sub`` (the permanent Discord user id) plus email/username/avatar.
    """
    # Imported lazily so tests that stub this function need no network stack.
    import requests

    try:
        token_response = requests.post(
            _TOKEN_URL,
            data={
                "client_id": DISCORD_CLIENT_ID,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ValueError(f"Discord token exchange failed: {exc}") from exc
    if not token_response.ok:
        raise ValueError(
            f"Discord rejected the authorization code ({token_response.status_code})."
        )
    access_token = token_response.json().get("access_token")
    if not access_token:
        raise ValueError("Discord returned no access token.")

    try:
        user_response = requests.get(
            _USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ValueError(f"Could not reach Discord: {exc}") from exc
    if not user_response.ok:
        raise ValueError(
            f"Discord user lookup failed ({user_response.status_code})."
        )
    user = user_response.json()
    sub = user.get("id")
    if not sub:
        raise ValueError("Discord user is missing an id.")
    return {
        "sub": str(sub),
        "email": user.get("email"),
        # Discord only reports an email as verified when both fields agree.
        "email_verified": bool(user.get("verified")) and bool(user.get("email")),
        "username": user.get("global_name") or user.get("username"),
        "avatar_url": _avatar_url(user),
    }
