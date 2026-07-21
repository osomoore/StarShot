"""Self-service account management: overview, policy acceptance, linked
providers, data export, and account deletion.

Every endpoint identifies the account from the validated server session
(never from a client-supplied id), rejects guest sessions, and the sensitive
ones (unlink, export, delete) also require recent reauthentication.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from starshot.v2 import boss_designs, policies, ship_designs
from starshot.v2.router import (
    SESSION_COOKIE,
    _public_profile,
    _registered_user,
    _require_recent_auth,
    onboarding_flags,
)
from starshot.v2.store import get_v2_store

account_router = APIRouter(prefix="/api/v2/account", tags=["v2-account"])

PROVIDERS = ("google", "microsoft", "discord")
PROVIDER_LABELS = {"google": "Google", "microsoft": "Microsoft", "discord": "Discord"}


def linked_providers(user: dict) -> list[dict]:
    """The account's connected sign-in providers. Only non-secret metadata:
    never tokens, secrets, or session material."""
    return [
        {
            "provider": provider,
            "label": PROVIDER_LABELS[provider],
            "email": user.get(f"{provider}_email"),
            "linked_at": user.get(f"{provider}_linked_at"),
        }
        for provider in PROVIDERS
        if user.get(f"{provider}_sub")
    ]


def purge_account(user_id: int) -> None:
    """Full account cleanup shared by self-service and admin deletion:
    sessions, credentials, private data, designs, leaderboard presence, and
    anonymized multiplayer records. No tokens or secrets are logged."""
    store = get_v2_store()
    ship_designs.delete_owner_designs(user_id)
    boss_designs.delete_owner_designs(user_id)
    # There are no stored provider access/refresh tokens to revoke: StarShot
    # only keeps provider subject ids and emails, which this erases.
    store.delete_account(user_id)


def cleanup_expired_guests() -> int:
    """Remove expired guest accounts and all their content (ships, bosses, etc).
    Guests are temporary sessions; when the session expires, the guest account
    and everything they created should be deleted. Returns the count of guests purged."""
    store = get_v2_store()
    expired_ids = store.get_expired_guest_ids()
    for user_id in expired_ids:
        purge_account(user_id)
    return len(expired_ids)


@account_router.get("")
def account_overview(request: Request) -> dict:
    user = _registered_user(request)
    return {
        "account": {
            "display_name": user.get("display_name") or user["username"],
            "username": user["username"],
            "created_at": user["created_at"],
            "wins": user["wins"],
            "losses": user["losses"],
            "draws": user["draws"],
            "games_played": user["games_played"],
            "providers": linked_providers(user),
            "policies": {
                "terms_version": user.get("terms_version"),
                "privacy_version": user.get("privacy_version"),
                "accepted_at": user.get("policies_accepted_at"),
                **policies.current_versions(),
            },
        },
        **onboarding_flags(user),
    }


class PolicyAcceptance(BaseModel):
    terms_version: str = Field(min_length=1, max_length=40)
    privacy_version: str = Field(min_length=1, max_length=40)


@account_router.post("/accept-policies")
def accept_policies(body: PolicyAcceptance, request: Request) -> dict:
    """Record acceptance of the current Terms and acknowledgement of the
    current Privacy Policy. Stale versions are rejected so a user can't
    'accept' a document that changed under them."""
    user = _registered_user(request)
    current = policies.current_versions()
    if (
        body.terms_version != current["terms_version"]
        or body.privacy_version != current["privacy_version"]
    ):
        raise HTTPException(
            status_code=409,
            detail="The Terms or Privacy Policy changed. Reload and review the current versions.",
        )
    store = get_v2_store()
    store.set_policies_accepted(user["id"], body.terms_version, body.privacy_version)
    fresh = store.get_user(user["id"])
    return {"ok": True, "user": _public_profile(fresh), **onboarding_flags(fresh)}


@account_router.delete("/providers/{provider}")
def unlink_provider(provider: str, request: Request) -> dict:
    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown sign-in provider.")
    user = _registered_user(request)
    _require_recent_auth(request)
    if not user.get(f"{provider}_sub"):
        raise HTTPException(status_code=404, detail="That provider is not linked to this account.")
    remaining = [p for p in linked_providers(user) if p["provider"] != provider]
    if not remaining:
        raise HTTPException(
            status_code=400,
            detail="Ye can't cast off yer last way aboard — link another provider first.",
        )
    get_v2_store().unlink_provider(user["id"], provider)
    fresh = get_v2_store().get_user(user["id"])
    return {"ok": True, "providers": linked_providers(fresh)}


@account_router.get("/export")
def export_account_data(request: Request) -> Response:
    """Download My Data: the account's portable data as a JSON attachment.
    Generated on the fly for the authenticated account only — nothing is
    written to server storage. Explicitly excludes credentials, tokens,
    session material, admin notes, and anything about other users."""
    user = _registered_user(request)
    _require_recent_auth(request)
    store = get_v2_store()
    user_id = user["id"]

    def full_designs(module):
        return [
            design
            for entry in module.list_designs(user_id)
            if (design := module.load_design(entry["id"], user_id)) is not None
        ]

    match_history = [
        {
            "match_id": match["id"],
            "name": match["name"],
            "status": match["status"],
            "created_at": match["created_at"],
            "seats": len(match["seat_list"]),
        }
        for match in store.matches_for_user(user_id)
    ]
    feedback = [
        {
            "created_at": entry["created_at"],
            "rating": entry["rating"],
            "liked": entry["liked"],
            "disliked": entry["disliked"],
            "thoughts": entry["thoughts"],
            "is_bug_report": bool(entry["is_bug_report"]),
        }
        for entry in store.feedback_for_user(user_id)
    ]
    from starshot.v2.campaign import inventory_for_user

    data = {
        "export_format": "starshot-account-data/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "account": {
            "display_name": user.get("display_name") or user["username"],
            "username": user["username"],
            "created_at": user["created_at"],
            "policies": {
                "terms_version": user.get("terms_version"),
                "privacy_version": user.get("privacy_version"),
                "accepted_at": user.get("policies_accepted_at"),
            },
        },
        "authentication_providers": [
            {
                "provider": entry["provider"],
                "provider_account_id": user.get(f"{entry['provider']}_sub"),
                "email": entry["email"],
                "linked_at": entry["linked_at"],
            }
            for entry in linked_providers(user)
        ],
        "statistics": {
            "wins": user["wins"],
            "losses": user["losses"],
            "draws": user["draws"],
            "games_played": user["games_played"],
        },
        "leaderboard_records": store.leaderboard_results_for_user(user_id),
        "stardock_ships": full_designs(ship_designs),
        "campaign_components": inventory_for_user(user_id, store),
        "starbreach_bosses": full_designs(boss_designs),
        "match_history": match_history,
        "feedback": feedback,
    }
    filename = f"starshot-account-data-{datetime.now(timezone.utc):%Y-%m-%d}.json"
    return Response(
        content=json.dumps(data, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class DeleteConfirmation(BaseModel):
    confirm: str = Field(max_length=20)


@account_router.post("/delete")
def delete_account(body: DeleteConfirmation, request: Request, response: Response) -> dict:
    """Delete My Account: requires recent reauthentication plus the typed
    DELETE confirmation. Invalidates every session, erases credentials and
    private data, removes designs, and anonymizes leaderboard/match records."""
    user = _registered_user(request)
    _require_recent_auth(request)
    if body.confirm.strip() != "DELETE":
        raise HTTPException(status_code=400, detail='Type DELETE to confirm account deletion.')
    from starshot.v2.admin import admin_usernames

    if user["username"].lower() in admin_usernames():
        raise HTTPException(
            status_code=400,
            detail="Admin accounts cannot self-destruct. Remove admin status first.",
        )
    purge_account(user["id"])
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True, "deleted": True}
