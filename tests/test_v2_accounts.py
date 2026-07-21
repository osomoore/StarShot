"""Account management, guest access, policies, and authorization tests."""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

# Reuse test_v2_api's isolated environment (temp DB, throttle disabled, etc.).
from tests.test_v2_api import make_client, register  # noqa: E402

from starshot.v2 import boss_designs, ratelimit, ship_designs  # noqa: E402
from starshot.v2.store import get_v2_store  # noqa: E402

VALID_SHIP = None  # built lazily from designer meta


def admin_client():
    client = make_client()
    response = client.post(
        "/api/v2/auth/login", json={"username": "davidmoore", "password": "rangers"}
    )
    assert response.status_code == 200, response.text
    return client


def guest_client():
    client = make_client()
    response = client.post("/api/v2/auth/guest")
    assert response.status_code == 200, response.text
    return client, response.json()["user"]


def user_id_by_username(username: str) -> int:
    user = get_v2_store().get_user_by_name(username)
    assert user is not None, username
    return user["id"]


class PolicyDocumentTests(unittest.TestCase):
    def test_policy_pages_render_from_source_files(self) -> None:
        client = make_client()
        for path, marker in (("/v2/terms", "Terms of Service"), ("/v2/privacy", "Privacy Policy")):
            page = client.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertIn(marker, page.text)
            self.assertIn("Effective Date", page.text)

    def test_policies_api_reports_versions(self) -> None:
        data = make_client().get("/api/v2/policies").json()
        self.assertIn("terms", data)
        self.assertIn("privacy", data)
        self.assertTrue(data["terms"]["version"])
        self.assertTrue(data["privacy"]["version"])


class OnboardingTests(unittest.TestCase):
    def test_terms_and_name_onboarding_only_when_required(self) -> None:
        client = make_client()
        register(client, "onboard_alice")
        me = client.get("/api/v2/me").json()
        self.assertTrue(me["needs_terms"])
        self.assertTrue(me["needs_display_name"])

        versions = client.get("/api/v2/policies").json()
        accepted = client.post(
            "/api/v2/account/accept-policies",
            json={
                "terms_version": versions["terms"]["version"],
                "privacy_version": versions["privacy"]["version"],
            },
        )
        self.assertEqual(accepted.status_code, 200)
        named = client.post("/api/v2/profile/display-name", json={"display_name": "Onboard Alice"})
        self.assertEqual(named.status_code, 200)

        me = client.get("/api/v2/me").json()
        self.assertFalse(me["needs_terms"])
        self.assertFalse(me["needs_display_name"])

    def test_terms_reacceptance_required_after_version_change(self) -> None:
        client = make_client()
        register(client, "onboard_rev")
        versions = client.get("/api/v2/policies").json()
        client.post(
            "/api/v2/account/accept-policies",
            json={
                "terms_version": versions["terms"]["version"],
                "privacy_version": versions["privacy"]["version"],
            },
        )
        self.assertFalse(client.get("/api/v2/me").json()["needs_terms"])
        with mock.patch(
            "starshot.v2.policies.current_versions",
            return_value={"terms_version": "9999-01-01", "privacy_version": versions["privacy"]["version"]},
        ):
            self.assertTrue(client.get("/api/v2/me").json()["needs_terms"])

    def test_stale_policy_version_rejected(self) -> None:
        client = make_client()
        register(client, "onboard_stale")
        rejected = client.post(
            "/api/v2/account/accept-policies",
            json={"terms_version": "1900-01-01", "privacy_version": "1900-01-01"},
        )
        self.assertEqual(rejected.status_code, 409)

    def test_reserved_display_names_rejected(self) -> None:
        client = make_client()
        register(client, "onboard_reserved")
        for name in ("Admin", "Administrator", "Moderator", "Guest", "StarShot", "XxAdminxX"):
            response = client.post("/api/v2/profile/display-name", json={"display_name": name})
            self.assertEqual(response.status_code, 400, name)


class GuestTests(unittest.TestCase):
    def test_guest_is_marked_and_has_guest_name(self) -> None:
        client, user = guest_client()
        self.assertTrue(user["is_guest"])
        self.assertTrue(user["display_name"].startswith("Guest "))
        me = client.get("/api/v2/me").json()
        self.assertTrue(me["user"]["is_guest"])
        self.assertFalse(me["needs_terms"])

    def test_guest_onboarding_offers_a_display_name_once(self) -> None:
        client, _user = guest_client()
        me = client.get("/api/v2/me").json()
        self.assertTrue(me["needs_display_name"])
        named = client.post("/api/v2/profile/display-name", json={"display_name": "Salty Sam"})
        self.assertEqual(named.status_code, 200, named.text)
        self.assertTrue(named.json()["user"]["is_guest"])
        me = client.get("/api/v2/me").json()
        self.assertFalse(me["needs_display_name"])
        self.assertEqual(me["user"]["display_name"], "Salty Sam")

    def test_guest_can_build_ships_but_not_bosses(self) -> None:
        client, _user = guest_client()
        # Guests fly and build their own ships (discarded when the voyage ends).
        ship = client.put("/api/v2/my/ship-designs", json={"id": "guest_ship", "name": "Guest Ship"})
        self.assertEqual(ship.status_code, 200, ship.text)
        self.assertEqual(client.get("/api/v2/my/ship-designs").status_code, 200)
        # Boss building stays for registered captains only.
        boss = client.put("/api/v2/my/boss-designs", json={"id": "guest_boss", "name": "Guest Boss"})
        self.assertEqual(boss.status_code, 403)
        self.assertEqual(client.get("/api/v2/my/boss-designs").status_code, 403)

    def test_guest_cannot_use_account_or_profile_apis(self) -> None:
        client, _user = guest_client()
        self.assertEqual(client.get("/api/v2/account").status_code, 403)
        self.assertEqual(client.get("/api/v2/account/export").status_code, 403)
        self.assertEqual(client.post("/api/v2/account/delete", json={"confirm": "DELETE"}).status_code, 403)

    def test_guest_feedback_survives_logout_anonymized(self) -> None:
        client, user = guest_client()
        store = get_v2_store()
        guest_id = store.get_user_by_name(user["username"])["id"]

        feedback = client.post(
            "/api/v2/feedback",
            json={"rating": 5, "thoughts": "Guest bug report.", "is_bug_report": True},
        )
        self.assertEqual(feedback.status_code, 200, feedback.text)
        self.assertEqual(feedback.json()["feedback_count"], 1)

        self.assertEqual(client.post("/api/v2/auth/logout").status_code, 200)
        tombstone = store.get_user(guest_id)
        self.assertIsNotNone(tombstone["deleted_at"])
        self.assertNotEqual(tombstone["username"], user["username"])

        entries = store.feedback_for_user(guest_id)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["thoughts"], "Guest bug report.")
        self.assertEqual(entries[0]["username"], tombstone["username"])

    def test_guest_results_never_reach_leaderboards(self) -> None:
        client, user = guest_client()
        store = get_v2_store()
        guest_row = store.get_user_by_name(user["username"])
        # Even if a result were recorded for a guest, listings exclude guests.
        store.record_result(guest_row["id"], "win")
        board = client.get("/api/v2/leaderboard").json()
        names = {entry["username"] for entry in board["leaderboard"]}
        self.assertNotIn(user["username"], names)
        for sub_board in board.get("boards", []):
            self.assertNotIn(
                user["username"], {entry["username"] for entry in sub_board["entries"]}
            )

    def test_guest_logout_destroys_guest_identity(self) -> None:
        client, user = guest_client()
        store = get_v2_store()
        guest_id = store.get_user_by_name(user["username"])["id"]
        self.assertEqual(client.post("/api/v2/auth/logout").status_code, 200)
        self.assertEqual(client.get("/api/v2/me").status_code, 401)
        tombstone = store.get_user(guest_id)
        self.assertIsNotNone(tombstone["deleted_at"])
        self.assertNotEqual(tombstone["username"], user["username"])

    def test_claiming_converts_guest_into_permanent_account(self) -> None:
        client, user = guest_client()
        client.post("/api/v2/profile/display-name", json={"display_name": "Claimant"})
        guest_id = user_id_by_username(user["username"])

        with mock.patch(
            "starshot.v2.google_identity.verify_google_credential",
            return_value={"sub": "claim-sub-1", "email": "claimant@example.com", "email_verified": True},
        ):
            claimed = client.post(
                "/api/v2/auth/google", json={"credential": "x" * 40, "claim": True}
            )
        self.assertEqual(claimed.status_code, 200, claimed.text)
        claimed_user = claimed.json()["user"]
        self.assertFalse(claimed_user["is_guest"])
        self.assertEqual(claimed_user["display_name"], "Claimant")
        self.assertEqual(user_id_by_username(claimed_user["username"]), guest_id)

        # It's now a full account: /account works, and Terms are still owed
        # (a guest never accepted them) while the display name carries over.
        me = client.get("/api/v2/me").json()
        self.assertFalse(me["needs_display_name"])
        self.assertTrue(me["needs_terms"])
        account = client.get("/api/v2/account").json()["account"]
        self.assertEqual(account["providers"][0]["provider"], "google")

    def test_only_a_guest_can_claim(self) -> None:
        client = make_client()
        register(client, "claim_registered")
        with mock.patch(
            "starshot.v2.microsoft_identity.verify_microsoft_credential",
            return_value={"sub": "claim-sub-2"},
        ):
            response = client.post(
                "/api/v2/auth/microsoft", json={"credential": "x" * 40, "claim": True}
            )
        self.assertEqual(response.status_code, 400)

    def test_cannot_claim_with_an_identity_already_in_use(self) -> None:
        make_client()
        owner = make_client()
        register(owner, "claim_owner")  # owns google sub "test-sub-claim_owner"
        guest, _user = guest_client()
        with mock.patch(
            "starshot.v2.google_identity.verify_google_credential",
            return_value={"sub": "test-sub-claim_owner"},
        ):
            response = guest.post(
                "/api/v2/auth/google", json={"credential": "x" * 40, "claim": True}
            )
        self.assertEqual(response.status_code, 409)
        # The guest voyage survives the failed claim attempt.
        self.assertTrue(guest.get("/api/v2/me").json()["user"]["is_guest"])

    def test_guest_creation_is_rate_limited(self) -> None:
        ratelimit.reset()
        os.environ["STARSHOT_LOGIN_THROTTLE_SECONDS"] = "5"
        try:
            first = make_client().post("/api/v2/auth/guest")
            self.assertEqual(first.status_code, 200)
            second = make_client().post("/api/v2/auth/guest")
            self.assertEqual(second.status_code, 429)
        finally:
            os.environ["STARSHOT_LOGIN_THROTTLE_SECONDS"] = "0"
            ratelimit.reset()


class LoginThrottleTests(unittest.TestCase):
    def test_login_attempts_throttled_to_one_per_interval(self) -> None:
        ratelimit.reset()
        os.environ["STARSHOT_LOGIN_THROTTLE_SECONDS"] = "5"
        try:
            client = make_client()
            first = client.post(
                "/api/v2/auth/login", json={"username": "throttle_user", "password": "x" * 8}
            )
            self.assertNotEqual(first.status_code, 429)
            second = client.post(
                "/api/v2/auth/login", json={"username": "throttle_user", "password": "x" * 8}
            )
            self.assertEqual(second.status_code, 429)
        finally:
            os.environ["STARSHOT_LOGIN_THROTTLE_SECONDS"] = "0"
            ratelimit.reset()


class ProviderLinkTests(unittest.TestCase):
    def test_provider_identity_cannot_join_two_accounts(self) -> None:
        owner = make_client()
        register(owner, "link_owner")
        other = make_client()
        register(other, "link_other")
        # link_owner's Google sub is taken; link_other tries to link it.
        with mock.patch(
            "starshot.v2.google_identity.verify_google_credential",
            return_value={"sub": "test-sub-link_owner"},
        ):
            response = other.post(
                "/api/v2/auth/google", json={"credential": "x" * 40, "link": True}
            )
        self.assertEqual(response.status_code, 409)

    def test_linking_and_listing_providers(self) -> None:
        client = make_client()
        register(client, "link_lister")
        with mock.patch(
            "starshot.v2.microsoft_identity.verify_microsoft_credential",
            return_value={"sub": "ms-link-lister", "email": "lister@example.com"},
        ):
            linked = client.post(
                "/api/v2/auth/microsoft", json={"credential": "x" * 40, "link": True}
            )
        self.assertEqual(linked.status_code, 200, linked.text)
        account = client.get("/api/v2/account").json()["account"]
        providers = {entry["provider"]: entry for entry in account["providers"]}
        self.assertIn("google", providers)
        self.assertIn("microsoft", providers)
        self.assertEqual(providers["microsoft"]["email"], "lister@example.com")
        self.assertTrue(providers["microsoft"]["linked_at"])

    def test_final_provider_cannot_be_unlinked(self) -> None:
        client = make_client()
        register(client, "link_final")
        response = client.request("DELETE", "/api/v2/account/providers/google")
        self.assertEqual(response.status_code, 400)

    def test_unlink_requires_recent_auth_and_leaves_one_provider(self) -> None:
        client = make_client()
        register(client, "link_unlinker")
        with mock.patch(
            "starshot.v2.microsoft_identity.verify_microsoft_credential",
            return_value={"sub": "ms-link-unlinker"},
        ):
            client.post("/api/v2/auth/microsoft", json={"credential": "x" * 40, "link": True})
        unlink = client.request("DELETE", "/api/v2/account/providers/microsoft")
        self.assertEqual(unlink.status_code, 200, unlink.text)
        providers = [entry["provider"] for entry in unlink.json()["providers"]]
        self.assertEqual(providers, ["google"])
        # Stale session: sensitive actions demand fresh authentication.
        _make_session_stale("link_unlinker")
        with mock.patch(
            "starshot.v2.microsoft_identity.verify_microsoft_credential",
            return_value={"sub": "ms-link-unlinker-2"},
        ):
            client.post("/api/v2/auth/microsoft", json={"credential": "x" * 40, "link": True})
        _make_session_stale("link_unlinker")
        stale = client.request("DELETE", "/api/v2/account/providers/microsoft")
        self.assertEqual(stale.status_code, 403)


def _make_session_stale(username: str) -> None:
    """Backdate every session auth-time for a user (test helper)."""
    import sqlite3

    store = get_v2_store()
    user = store.get_user_by_name(username)
    conn = sqlite3.connect(store.db_path)
    conn.execute(
        "UPDATE sessions SET reauthed_at = '2000-01-01T00:00:00+00:00', "
        "created_at = '2000-01-01T00:00:00+00:00' WHERE user_id = ?",
        (user["id"],),
    )
    conn.commit()
    conn.close()


class DataExportTests(unittest.TestCase):
    def test_export_contains_user_data_but_no_secrets(self) -> None:
        client = make_client()
        register(client, "export_erin")
        client.post("/api/v2/profile/display-name", json={"display_name": "Export Erin"})
        response = client.get("/api/v2/account/export")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("starshot-account-data-", response.headers.get("content-disposition", ""))
        data = json.loads(response.content)
        self.assertEqual(data["account"]["display_name"], "Export Erin")
        self.assertEqual(data["account"]["username"], "export_erin")
        providers = {entry["provider"] for entry in data["authentication_providers"]}
        self.assertIn("google", providers)
        self.assertIn("statistics", data)
        self.assertIn("stardock_ships", data)
        self.assertIn("starbreach_bosses", data)
        text = response.text.lower()
        for forbidden in ("pass_hash", "access_token", "refresh_token", "token_hash", "session", "csrf"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_export_requires_recent_auth(self) -> None:
        client = make_client()
        register(client, "export_stale")
        _make_session_stale("export_stale")
        self.assertEqual(client.get("/api/v2/account/export").status_code, 403)

    def test_export_is_scoped_to_the_session_account(self) -> None:
        alice = make_client()
        register(alice, "export_alice")
        bob = make_client()
        register(bob, "export_bob")
        data = json.loads(alice.get("/api/v2/account/export").content)
        self.assertEqual(data["account"]["username"], "export_alice")
        self.assertNotIn("export_bob", json.dumps(data))
        # No cross-account access: anonymous callers get nothing.
        self.assertEqual(make_client().get("/api/v2/account/export").status_code, 401)
        self.assertEqual(make_client().get("/api/v2/account").status_code, 401)


class AccountDeletionTests(unittest.TestCase):
    def _saved_ship(self, client) -> str:
        meta = client.get("/api/v2/my/ship-designs").json()["meta"]
        design = {
            "id": "delete_me_ship",
            "name": "Delete Me",
            "tiles": [],
            "lanes": {},
        }
        saved = client.put("/api/v2/my/ship-designs", json=design)
        assert saved.status_code == 200, saved.text
        return saved.json()["design"]["id"]

    def test_self_deletion_cleans_everything_and_invalidates_sessions(self) -> None:
        client = make_client()
        register(client, "delete_dora")
        user_id = user_id_by_username("delete_dora")
        self._saved_ship(client)
        store = get_v2_store()
        store.record_result(user_id, "win")
        store.create_feedback(
            user_id=user_id,
            rating=4,
            liked="Useful",
            disliked="",
            thoughts="Keep this after deletion.",
            is_bug_report=True,
        )
        self.assertIn(
            "delete_dora",
            {entry["username"] for entry in store.leaderboard(limit=100)},
        )
        # A second session for the same account, to prove it dies too.
        second = make_client()
        register(second, "delete_dora")

        needs_confirm = client.post("/api/v2/account/delete", json={"confirm": "nope"})
        self.assertEqual(needs_confirm.status_code, 400)
        deleted = client.post("/api/v2/account/delete", json={"confirm": "DELETE"})
        self.assertEqual(deleted.status_code, 200, deleted.text)

        self.assertEqual(client.get("/api/v2/me").status_code, 401)
        self.assertEqual(second.get("/api/v2/me").status_code, 401)
        self.assertNotIn(
            "delete_dora",
            {entry["username"] for entry in store.leaderboard(limit=100)},
        )
        self.assertEqual(ship_designs.list_designs(user_id), [])
        self.assertEqual(boss_designs.list_designs(user_id), [])
        tombstone = store.get_user(user_id)
        self.assertIsNotNone(tombstone["deleted_at"])
        self.assertIsNone(tombstone["google_sub"])
        self.assertEqual(tombstone["pass_hash"], "!deleted")
        preserved_feedback = store.feedback_for_user(user_id)
        self.assertEqual(len(preserved_feedback), 1)
        self.assertEqual(preserved_feedback[0]["thoughts"], "Keep this after deletion.")
        self.assertEqual(preserved_feedback[0]["username"], tombstone["username"])
        # The freed identity cannot be signed into again.
        with mock.patch(
            "starshot.v2.google_identity.verify_google_credential",
            return_value={"sub": "test-sub-delete_dora"},
        ):
            relogin = make_client().post("/api/v2/auth/google", json={"credential": "x" * 40})
        # A fresh account is created instead of resurrecting the old one.
        self.assertEqual(relogin.status_code, 200)
        self.assertNotEqual(relogin.json()["user"]["username"], "delete_dora")

    def test_deletion_requires_recent_auth(self) -> None:
        client = make_client()
        register(client, "delete_stale")
        _make_session_stale("delete_stale")
        response = client.post("/api/v2/account/delete", json={"confirm": "DELETE"})
        self.assertEqual(response.status_code, 403)


class AdminAccountManagementTests(unittest.TestCase):
    def test_non_admin_cannot_use_admin_deletion(self) -> None:
        client = make_client()
        register(client, "admin_wannabe")
        victim = make_client()
        register(victim, "admin_victim")
        victim_id = user_id_by_username("admin_victim")
        response = client.post(
            f"/api/v2/admin/accounts/{victim_id}/delete", json={"confirm": "DELETE"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(victim.get("/api/v2/me").status_code, 200)

    def test_admin_deletes_account_with_audit_entry(self) -> None:
        target = make_client()
        register(target, "admin_target")
        target_id = user_id_by_username("admin_target")
        admin = admin_client()
        admin_id = user_id_by_username("davidmoore")

        wrong = admin.post(f"/api/v2/admin/accounts/{target_id}/delete", json={"confirm": "no"})
        self.assertEqual(wrong.status_code, 400)
        response = admin.post(
            f"/api/v2/admin/accounts/{target_id}/delete", json={"confirm": "DELETE"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(target.get("/api/v2/me").status_code, 401)

        audit = get_v2_store().list_admin_audit()
        entry = next(item for item in audit if item["target_user_id"] == target_id)
        self.assertEqual(entry["admin_user_id"], admin_id)
        self.assertEqual(entry["action"], "delete_account")
        self.assertTrue(entry["created_at"])
        self.assertNotIn("token", json.dumps(entry).lower())

    def test_admin_cannot_delete_self_or_any_admin(self) -> None:
        admin = admin_client()
        admin_id = user_id_by_username("davidmoore")
        response = admin.post(
            f"/api/v2/admin/accounts/{admin_id}/delete", json={"confirm": "DELETE"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(admin.get("/api/v2/me").status_code, 200)


if __name__ == "__main__":
    unittest.main()
