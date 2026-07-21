from __future__ import annotations

import io
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

TMP = tempfile.TemporaryDirectory()
os.environ["STARSHOT_V2_DB"] = str(Path(TMP.name) / "v2.sqlite3")
os.environ.pop("STARSHOT_SITE_AUTH", None)
# Login throttling (1 attempt / 5s) would serialize the suite; the throttle
# itself is covered by an explicit test that re-enables it.
os.environ["STARSHOT_LOGIN_THROTTLE_SECONDS"] = "0"

# Isolate everything the admin console can write: run v2 games and the deck
# editor against a scratch copy of core_0_3, and keywords in a scratch file.
_REPO_DECKS = Path(__file__).resolve().parents[1] / "resources" / "decks" / "core_0_3"
_TEST_DECKS = Path(TMP.name) / "core_0_3"
shutil.copytree(_REPO_DECKS, _TEST_DECKS)
os.environ["STARSHOT_V2_DECK_SET"] = str(_TEST_DECKS)
os.environ["STARSHOT_KEYWORDS_FILE"] = str(Path(TMP.name) / "custom_keywords.json")
os.environ["STARSHOT_CUSTOM_DECKS"] = str(Path(TMP.name) / "custom_decks")
_TEST_HTPASSWD = Path(TMP.name) / ".htpasswd"
_TEST_HTPASSWD.write_text("david:rangers\n", encoding="utf-8")
os.environ["STARSHOT_SITE_HTPASSWD"] = str(_TEST_HTPASSWD)

from fastapi.testclient import TestClient  # noqa: E402

from starshot.api.app import app  # noqa: E402
from starshot.v2 import boss_designs  # noqa: E402
from starshot.v2 import ship_designs  # noqa: E402
from starshot.v2.store import get_v2_store  # noqa: E402

# Isolate runtime ship-design writes (starter-ship provisioning, player saves)
# to a scratch dir so tests never touch the repo's .starshot content. The
# bundled DESIGNS_DIR stays pointed at resources/ so the global Lightning Bug
# Alpha remains cloneable.
ship_designs.RUNTIME_DESIGNS_DIR = Path(TMP.name) / "ship_designs"
from tests.test_boss_designer import make_design  # noqa: E402

EMPTY_ORDERS = {
    "stacks": [
        {"action_number": 1, "seal_mode": "sealed", "cards": []},
        {"action_number": 2, "seal_mode": "sealed", "cards": []},
        {"action_number": 3, "seal_mode": "sealed", "cards": []},
    ]
}


def make_client() -> TestClient:
    return TestClient(app)


def register(client: TestClient, name: str, password: str = "rangers") -> dict:
    """Provision a signed-in test account. Ordinary username/password
    registration no longer exists, so accounts are created as Google-linked
    users (with a deterministic per-name subject) and logged in through the
    real /auth/google endpoint with the verifier mocked."""
    from unittest import mock

    store = get_v2_store()
    sub = f"test-sub-{name.lower()}"
    if store.get_user_by_external_sub("google", sub) is None:
        store.create_external_user("google", sub, name, display_name=name)
    with mock.patch(
        "starshot.v2.google_identity.verify_google_credential", return_value={"sub": sub}
    ):
        response = client.post("/api/v2/auth/google", json={"credential": "x" * 40})
    assert response.status_code == 200, response.text
    return response.json()


class AuthTests(unittest.TestCase):
    def test_ordinary_registration_removed(self) -> None:
        client = make_client()
        response = client.post(
            "/api/v2/auth/register", json={"username": "auth_alice", "password": "rangers"}
        )
        self.assertIn(response.status_code, (404, 405))

    def test_password_login_is_admin_only(self) -> None:
        client = make_client()
        register(client, "auth_pleb")
        client.post("/api/v2/auth/logout")
        response = client.post(
            "/api/v2/auth/login", json={"username": "auth_pleb", "password": "rangers"}
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_login_and_logout_invalidate_session(self) -> None:
        client = make_client()
        bad = client.post(
            "/api/v2/auth/login", json={"username": "davidmoore", "password": "wrong"}
        )
        self.assertEqual(bad.status_code, 401)
        good = client.post(
            "/api/v2/auth/login", json={"username": "davidmoore", "password": "rangers"}
        )
        self.assertEqual(good.status_code, 200)
        self.assertEqual(client.get("/api/v2/me").status_code, 200)
        self.assertEqual(client.post("/api/v2/auth/logout").status_code, 200)
        self.assertEqual(client.get("/api/v2/me").status_code, 401)


class GoogleAuthTests(unittest.TestCase):
    CLAIMS = {"iss": "https://accounts.google.com", "sub": "google-sub-123"}
    TOKEN = {"credential": "x" * 40}

    def test_google_login_creates_then_reuses_account(self) -> None:
        from unittest import mock

        client = make_client()
        with mock.patch(
            "starshot.v2.google_identity.verify_google_credential", return_value=self.CLAIMS
        ) as verify:
            first = client.post("/api/v2/auth/google", json=self.TOKEN)
        self.assertEqual(first.status_code, 200, first.text)
        verify.assert_called_once_with(self.TOKEN["credential"])
        user = first.json()["user"]
        self.assertTrue(user["username"].startswith("captain-"))
        self.assertEqual(client.get("/api/v2/me").status_code, 200)

        # The same sub on a fresh browser lands in the same account.
        other = make_client()
        with mock.patch(
            "starshot.v2.google_identity.verify_google_credential", return_value=self.CLAIMS
        ):
            second = other.post("/api/v2/auth/google", json=self.TOKEN)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["user"]["username"], user["username"])

        # No password back door into a Google-linked account.
        bad = make_client().post(
            "/api/v2/auth/login", json={"username": user["username"], "password": "!google"}
        )
        # Password sign-in is admin-only now, so this is rejected outright.
        self.assertEqual(bad.status_code, 403)

    def test_google_login_rejects_invalid_token(self) -> None:
        from unittest import mock

        client = make_client()
        with mock.patch(
            "starshot.v2.google_identity.verify_google_credential",
            side_effect=ValueError("bad token"),
        ):
            response = client.post("/api/v2/auth/google", json=self.TOKEN)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(client.get("/api/v2/me").status_code, 401)


class MicrosoftAuthTests(unittest.TestCase):
    CLAIMS = {
        "iss": "https://login.microsoftonline.com/tenant-1/v2.0",
        "tid": "tenant-1",
        "sub": "microsoft-sub-123",
    }
    TOKEN = {"credential": "x" * 40}

    def test_microsoft_login_creates_then_reuses_account(self) -> None:
        from unittest import mock

        client = make_client()
        with mock.patch(
            "starshot.v2.microsoft_identity.verify_microsoft_credential", return_value=self.CLAIMS
        ) as verify:
            first = client.post("/api/v2/auth/microsoft", json=self.TOKEN)
        self.assertEqual(first.status_code, 200, first.text)
        verify.assert_called_once_with(self.TOKEN["credential"])
        user = first.json()["user"]
        self.assertTrue(user["username"].startswith("captain-"))
        self.assertEqual(client.get("/api/v2/me").status_code, 200)

        # The same sub on a fresh browser lands in the same account.
        other = make_client()
        with mock.patch(
            "starshot.v2.microsoft_identity.verify_microsoft_credential", return_value=self.CLAIMS
        ):
            second = other.post("/api/v2/auth/microsoft", json=self.TOKEN)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["user"]["username"], user["username"])

        # No password back door into a Microsoft-linked account.
        bad = make_client().post(
            "/api/v2/auth/login", json={"username": user["username"], "password": "!microsoft"}
        )
        # Password sign-in is admin-only now, so this is rejected outright.
        self.assertEqual(bad.status_code, 403)

    def test_microsoft_login_rejects_invalid_token(self) -> None:
        from unittest import mock

        client = make_client()
        with mock.patch(
            "starshot.v2.microsoft_identity.verify_microsoft_credential",
            side_effect=ValueError("bad token"),
        ):
            response = client.post("/api/v2/auth/microsoft", json=self.TOKEN)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(client.get("/api/v2/me").status_code, 401)

    def test_google_and_microsoft_accounts_stay_independent(self) -> None:
        from unittest import mock

        # The same sub value from each provider must map to separate accounts.
        shared_sub = "shared-sub-999"
        with mock.patch(
            "starshot.v2.google_identity.verify_google_credential",
            return_value={"iss": "https://accounts.google.com", "sub": shared_sub},
        ):
            google_user = (
                make_client().post("/api/v2/auth/google", json=self.TOKEN).json()["user"]
            )
        with mock.patch(
            "starshot.v2.microsoft_identity.verify_microsoft_credential",
            return_value={**self.CLAIMS, "sub": shared_sub},
        ):
            microsoft_user = (
                make_client().post("/api/v2/auth/microsoft", json=self.TOKEN).json()["user"]
            )
        self.assertNotEqual(google_user["username"], microsoft_user["username"])


class DiscordAuthTests(unittest.TestCase):
    USER = {
        "sub": "discord-sub-123",
        "email": "cap@example.com",
        "email_verified": True,
        "username": "SaltyCap",
        "avatar_url": None,
    }
    BODY = {
        "code": "auth-code-abc",
        "code_verifier": "v" * 43,
        "redirect_uri": "https://david.cybrwzrds.com/v2",
    }

    def test_discord_login_creates_then_reuses_account(self) -> None:
        from unittest import mock

        client = make_client()
        with mock.patch(
            "starshot.v2.discord_identity.exchange_discord_code", return_value=self.USER
        ) as exchange:
            first = client.post("/api/v2/auth/discord", json=self.BODY)
        self.assertEqual(first.status_code, 200, first.text)
        exchange.assert_called_once_with(
            self.BODY["code"], self.BODY["code_verifier"], self.BODY["redirect_uri"]
        )
        user = first.json()["user"]

        # A second sign-in with the same Discord id reuses the same account.
        other = make_client()
        with mock.patch(
            "starshot.v2.discord_identity.exchange_discord_code", return_value=self.USER
        ):
            second = other.post("/api/v2/auth/discord", json=self.BODY)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["user"]["username"], user["username"])

        # No password back door into a Discord-linked account.
        bad = make_client().post(
            "/api/v2/auth/login", json={"username": user["username"], "password": "!discord"}
        )
        # Password sign-in is admin-only now, so this is rejected outright.
        self.assertEqual(bad.status_code, 403)

    def test_discord_login_rejects_failed_exchange(self) -> None:
        from unittest import mock

        client = make_client()
        with mock.patch(
            "starshot.v2.discord_identity.exchange_discord_code",
            side_effect=ValueError("bad code"),
        ):
            response = client.post("/api/v2/auth/discord", json=self.BODY)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(client.get("/api/v2/me").status_code, 401)

    def test_discord_links_to_existing_account_by_verified_email(self) -> None:
        from unittest import mock

        shared_email = "shared@example.com"
        # First, a Google sign-in creates an account carrying the verified email.
        with mock.patch(
            "starshot.v2.google_identity.verify_google_credential",
            return_value={
                "iss": "https://accounts.google.com",
                "sub": "google-email-link",
                "email": shared_email,
                "email_verified": True,
            },
        ):
            google_user = (
                make_client()
                .post("/api/v2/auth/google", json={"credential": "x" * 40})
                .json()["user"]
            )

        # A Discord sign-in with the same verified email links to that account.
        with mock.patch(
            "starshot.v2.discord_identity.exchange_discord_code",
            return_value={**self.USER, "sub": "discord-email-link", "email": shared_email},
        ):
            discord_user = (
                make_client().post("/api/v2/auth/discord", json=self.BODY).json()["user"]
            )
        self.assertEqual(discord_user["username"], google_user["username"])

    def test_discord_unverified_email_does_not_link(self) -> None:
        from unittest import mock

        shared_email = "unverified@example.com"
        with mock.patch(
            "starshot.v2.google_identity.verify_google_credential",
            return_value={
                "iss": "https://accounts.google.com",
                "sub": "google-noverify-link",
                "email": shared_email,
                "email_verified": True,
            },
        ):
            google_user = (
                make_client()
                .post("/api/v2/auth/google", json={"credential": "x" * 40})
                .json()["user"]
            )
        with mock.patch(
            "starshot.v2.discord_identity.exchange_discord_code",
            return_value={
                **self.USER,
                "sub": "discord-noverify-link",
                "email": shared_email,
                "email_verified": False,
            },
        ):
            discord_user = (
                make_client().post("/api/v2/auth/discord", json=self.BODY).json()["user"]
            )
        self.assertNotEqual(discord_user["username"], google_user["username"])


class FeedbackTests(unittest.TestCase):
    def admin_client(self) -> TestClient:
        client = make_client()
        client.get("/api/v2/admin/deck")
        login = client.post("/api/v2/auth/login", json={"username": "davidmoore", "password": "rangers"})
        self.assertEqual(login.status_code, 200, login.text)
        return client

    def test_feedback_repeats_increment_badge_and_admin_history(self) -> None:
        player = make_client()
        register(player, "feedback_alice")

        first = player.post(
            "/api/v2/feedback",
            json={
                "rating": 4,
                "liked": "Fast turns",
                "disliked": "Tiny buttons",
                "thoughts": "Good bones.",
            },
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["feedback_count"], 1)

        second = player.post(
            "/api/v2/feedback",
            json={
                "rating": 2,
                "liked": "Ships",
                "disliked": "Hard to read",
                "thoughts": "Needs clearer summaries.",
                "game_id": "game-feedback-test",
                "is_bug_report": True,
            },
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["feedback_count"], 2)

        me = player.get("/api/v2/me").json()["user"]
        self.assertEqual(me["feedback_count"], 2)
        leaderboard = player.get("/api/v2/leaderboard").json()["leaderboard"]
        row = next(entry for entry in leaderboard if entry["username"] == "feedback_alice")
        self.assertEqual(row["feedback_count"], 2)

        admin = self.admin_client()
        latest = admin.get("/api/v2/admin/feedback")
        self.assertEqual(latest.status_code, 200, latest.text)
        latest_row = next(entry for entry in latest.json()["entries"] if entry["username"] == "feedback_alice")
        self.assertEqual(latest_row["rating"], 2)
        self.assertEqual(latest_row["feedback_count"], 2)
        self.assertEqual(latest_row["is_bug_report"], 1)

        history = admin.get(f"/api/v2/admin/feedback/users/{latest_row['user_id']}")
        self.assertEqual(history.status_code, 200, history.text)
        entries = history.json()["entries"]
        self.assertEqual([entry["rating"] for entry in entries], [2, 4])
        self.assertEqual(entries[0]["game_id"], "game-feedback-test")
        self.assertEqual(entries[0]["is_bug_report"], 1)

    def test_debug_log_export_includes_state_and_event_details(self) -> None:
        alice = make_client()
        bob = make_client()
        register(alice, "log_alice")
        register(bob, "log_bob")
        create = alice.post("/api/v2/matches", json={"open_seats": 1})
        self.assertEqual(create.status_code, 200, create.text)
        match_id = create.json()["match"]["id"]
        joined = bob.post(f"/api/v2/matches/{match_id}/join")
        self.assertEqual(joined.status_code, 200, joined.text)
        game_id = joined.json()["game_id"]

        exported = alice.get(f"/api/v2/games/{game_id}/debug-log")
        self.assertEqual(exported.status_code, 200, exported.text)
        text = exported.json()["log"]
        self.assertIn("StarShot Debug Log", text)
        self.assertIn("Vaults", text)
        self.assertIn("Round 1", text)
        self.assertIn("Event Log JSON", text)

        feedback = alice.post(
            "/api/v2/feedback",
            json={
                "rating": 3,
                "thoughts": "Something odd happened.",
                "game_id": game_id,
                "match_id": match_id,
                "is_bug_report": True,
                "screenshot_data_url": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjwvc3ZnPg==",
            },
        )
        self.assertEqual(feedback.status_code, 200, feedback.text)
        self.assertIn("StarShot Debug Log", feedback.json()["feedback"]["game_log"])
        self.assertTrue(feedback.json()["feedback"]["screenshot_data_url"].startswith("data:image/svg+xml;base64,"))

    def test_feedback_validates_rating(self) -> None:
        player = make_client()
        register(player, "feedback_bob")
        response = player.post("/api/v2/feedback", json={"rating": 6})
        self.assertEqual(response.status_code, 422)


class LeaderboardTests(unittest.TestCase):
    def test_leaderboard_bundle_has_real_player_ai_and_infamy_boards(self) -> None:
        alpha = make_client()
        beta = make_client()
        register(alpha, "leader_alpha")
        register(beta, "leader_beta")
        store = get_v2_store()
        alpha_user = store.get_user_by_name("leader_alpha")
        beta_user = store.get_user_by_name("leader_beta")

        store.record_result(alpha_user["id"], "win", category="humans")
        store.record_result(alpha_user["id"], "win", category="ai", score=2, ship_loss=True)
        store.record_result(beta_user["id"], "win", category="ai", score=3)
        store.record_result(beta_user["id"], "loss", category="ai", ship_loss=True)
        store.record_result(beta_user["id"], "loss", category="ai", ship_loss=True)

        payload = alpha.get("/api/v2/leaderboard").json()
        self.assertEqual(
            {board["key"] for board in payload["boards"]},
            {"humans", "ai"},
        )
        ai_board = next(board for board in payload["boards"] if board["key"] == "ai")
        self.assertEqual(ai_board["label"], "Digital Scallywag Conquests")
        self.assertEqual(ai_board["entries"][0]["username"], "leader_beta")
        self.assertEqual(ai_board["entries"][0]["score"], 3)
        self.assertEqual(ai_board["entries"][0]["games_played"], 3)
        self.assertAlmostEqual(ai_board["entries"][0]["average_score"], 1.0)
        self.assertEqual(payload["infamy"]["username"], "leader_beta")
        self.assertEqual(payload["infamy"]["ship_losses"], 2)


class AiMatchTests(unittest.TestCase):
    def test_vs_ai_game_runs_and_hides_secrets(self) -> None:
        client = make_client()
        register(client, "ai_tester")
        created = client.post(
            "/api/v2/matches", json={"ai_types": ["hunter_killer"], "ai_level": "buccaneer", "open_seats": 0}
        )
        self.assertEqual(created.status_code, 200, created.text)
        game_id = created.json()["game_id"]
        self.assertIsNotNone(game_id)
        self.assertEqual(created.json()["match"]["ai_level"], "buccaneer")

        view = client.get(f"/api/v2/games/{game_id}/view").json()
        state = view["state"]
        self.assertEqual(view["you"], "ai_tester")
        self.assertEqual(state["deck_set"]["id"], "core_0_3_sides")
        self.assertNotIn("rng_seed", state)
        self.assertNotIn("rng_step", state)

        mine = state["players"]["ai_tester"]
        self.assertIn("hand", mine)
        self.assertNotIn("deck", mine)
        ai_player = state["players"]["ai:hunter_killer:1"]
        self.assertNotIn("hand", ai_player)
        self.assertNotIn("deck", ai_player)
        # The AI must already have submitted hidden orders for round 1.
        self.assertTrue(ai_player["has_submitted_orders"])
        self.assertIsNone(ai_player["prepared_orders"])
        # Other players' orders_submitted events must not include the stacks.
        for event in state["event_log"]:
            if event["type"] == "orders_submitted" and event["player_id"] != "ai_tester":
                self.assertNotIn("stacks", event)

    def test_vs_ai_game_plays_to_completion(self) -> None:
        client = make_client()
        register(client, "ai_finisher")
        created = client.post(
            "/api/v2/matches", json={"ai_types": ["blaster", "vault_runner"], "open_seats": 0}
        )
        game_id = created.json()["game_id"]
        for _ in range(12):
            view = client.get(f"/api/v2/games/{game_id}/view").json()
            state = view["state"]
            if state["phase"] == "complete":
                break
            response = client.post(
                f"/api/v2/games/{game_id}/orders", json={"orders": EMPTY_ORDERS}
            )
            self.assertEqual(response.status_code, 200, response.text)
        final = client.get(f"/api/v2/games/{game_id}/view").json()["state"]
        self.assertEqual(final["phase"], "complete")
        self.assertIsNotNone(final["result"])
        # Completion recorded stats for the human exactly once.
        me = client.get("/api/v2/me").json()
        self.assertEqual(me["user"]["games_played"], 1)

    def test_star_command_requires_captain_choice_and_reveals_starfall(self) -> None:
        client = make_client()
        register(client, "starcommand_tester")
        created = client.post(
            "/api/v2/matches",
            json={
                "ai_types": ["hunter_killer"],
                "open_seats": 0,
                "active_expansions": ["star_command"],
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["match"]["active_expansions"], ["star_command"])
        game_id = created.json()["game_id"]

        view = client.get(f"/api/v2/games/{game_id}/view").json()
        state = view["state"]
        self.assertIn("star_command", state["active_expansions"])
        self.assertIsNotNone(state["active_starfall"])
        self.assertTrue(any(event["type"] == "starfall_revealed" for event in state["event_log"]))
        mine = state["players"]["starcommand_tester"]
        self.assertIsNone(mine["captain"])
        self.assertEqual(len(mine["captain_options"]), 3)

        blocked = client.post(f"/api/v2/games/{game_id}/orders", json={"orders": EMPTY_ORDERS})
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("captain", blocked.json()["detail"].lower())

        chosen = client.post(
            f"/api/v2/games/{game_id}/captain",
            json={"captain_id": mine["captain_options"][0]["id"]},
        )
        self.assertEqual(chosen.status_code, 200, chosen.text)
        after = chosen.json()["state"]["players"]["starcommand_tester"]
        self.assertIsNotNone(after["captain"])

    def test_star_breach_host_can_choose_ai_prey(self) -> None:
        client = make_client()
        register(client, "prey_picker")
        tempdir = tempfile.TemporaryDirectory()
        old_bundled = boss_designs.DESIGNS_DIR
        old_runtime = boss_designs.RUNTIME_DESIGNS_DIR
        root = Path(tempdir.name)
        boss_designs.DESIGNS_DIR = root / "bundled"
        boss_designs.RUNTIME_DESIGNS_DIR = root / "runtime"
        try:
            boss_designs.save_design(make_design(id="prey_test_boss", name="Prey Test Boss"))
            created = client.post(
                "/api/v2/matches",
                json={
                    "ai_types": ["hunter_killer", "blaster"],
                    "open_seats": 0,
                    "active_expansions": ["star_breach"],
                    "star_breach_prey_player_id": "__ai__:1",
                    "star_breach_boss_design_id": "prey_test_boss",
                },
            )
            self.assertEqual(created.status_code, 200, created.text)
            game_id = created.json()["game_id"]
            state = client.get(f"/api/v2/games/{game_id}/view").json()["state"]
            self.assertEqual(state["star_breach"]["prey_player_id"], "ai:blaster:1")
        finally:
            boss_designs.DESIGNS_DIR = old_bundled
            boss_designs.RUNTIME_DESIGNS_DIR = old_runtime
            tempdir.cleanup()


class SelectedShipTests(unittest.TestCase):
    def _total_deck(self, player: dict) -> int:
        return player["deck_count"] + len(player.get("hand", [])) + len(player.get("discard", []))

    def test_first_visit_provisions_and_selects_starter_ship(self) -> None:
        client = make_client()
        register(client, "ship_ada")
        data = client.get("/api/v2/my/ship").json()
        self.assertTrue(data["can_edit"])
        self.assertEqual(data["selected"]["name"], "Lightning Bug Alpha")
        uid = get_v2_store().get_user_by_name("ship_ada")["id"]
        self.assertEqual(data["selected"]["ref"], f"user:{uid}:lightningbug")
        # The starter copy is owned and offered; the base ship is retired.
        refs = {opt["ref"] for opt in data["options"]}
        self.assertNotIn("", refs)  # no base ship option
        self.assertEqual(refs, {f"user:{uid}:lightningbug"})

    def test_provisioning_is_idempotent(self) -> None:
        client = make_client()
        register(client, "ship_ida")
        client.get("/api/v2/my/ship")
        client.get("/api/v2/my/ship")
        owned = client.get("/api/v2/my/ship-designs").json()["designs"]
        self.assertEqual([d["id"] for d in owned], ["lightningbug"])

    def test_base_ship_is_retired(self) -> None:
        client = make_client()
        register(client, "ship_bob")
        # Selecting the retired base ship (empty id) is rejected.
        rejected = client.put("/api/v2/my/ship", json={"ship_design_id": ""})
        self.assertEqual(rejected.status_code, 400, rejected.text)

    def test_select_persists_across_reads(self) -> None:
        client = make_client()
        register(client, "ship_bud")
        uid = get_v2_store().get_user_by_name("ship_bud")["id"]
        # Clone a second ship, then switch to it and confirm it sticks.
        client.get("/api/v2/my/ship")
        design = client.get(f"/api/v2/my/ship-designs/lightningbug").json()["design"]
        design["id"] = "second_ship"
        design["name"] = "Second Ship"
        client.put("/api/v2/my/ship-designs", json=design)
        chosen = client.put("/api/v2/my/ship", json={"ship_design_id": f"user:{uid}:second_ship"})
        self.assertEqual(chosen.status_code, 200, chosen.text)
        self.assertEqual(client.get("/api/v2/my/ship").json()["selected"]["ref"], f"user:{uid}:second_ship")

    def test_cannot_select_another_captains_ship(self) -> None:
        client = make_client()
        register(client, "ship_carol")
        # Another captain's owned ref is rejected.
        rejected = client.put("/api/v2/my/ship", json={"ship_design_id": "user:999999:lightningbug"})
        self.assertEqual(rejected.status_code, 403, rejected.text)
        # A ship that does not exist is a 400.
        missing = client.put("/api/v2/my/ship", json={"ship_design_id": "no_such_global_ship"})
        self.assertEqual(missing.status_code, 400, missing.text)

    def test_created_match_flies_selected_ship(self) -> None:
        client = make_client()
        register(client, "ship_dave")
        client.get("/api/v2/my/ship")  # provision
        game = client.post("/api/v2/matches", json={"ai_types": ["blaster"], "open_seats": 0}).json()
        view = client.get(f"/api/v2/games/{game['game_id']}/view").json()
        me = view["state"]["players"]["ship_dave"]
        self.assertEqual((me.get("ship") or {}).get("layout", {}).get("layout_id"), "design_lightningbug")
        self.assertEqual(self._total_deck(me), 10)  # the ship's component-derived deck

    def test_guest_flies_and_builds_a_starter_ship(self) -> None:
        client = make_client()
        client.post("/api/v2/auth/guest")
        body = client.get("/api/v2/my/ship").json()
        # Guests get an editable Firefly starter, not the retired base ship.
        self.assertTrue(body["can_edit"])
        self.assertTrue(body["is_guest"])
        self.assertEqual(body["selected"]["name"], "Lightning Bug Alpha")
        self.assertEqual([opt["name"] for opt in body["options"]], ["Lightning Bug Alpha"])
        # A guest can build a new ship of their own.
        saved = client.put("/api/v2/my/ship-designs", json={"id": "guest_ship", "name": "Guest Ship", "tiles": [], "lanes": {}})
        self.assertEqual(saved.status_code, 200, saved.text)
        # And flies their selected ship into battle (its component-derived deck).
        game = client.post("/api/v2/matches", json={"ai_types": ["blaster"], "open_seats": 0}).json()
        view = client.get(f"/api/v2/games/{game['game_id']}/view").json()
        me = next(p for pid, p in view["state"]["players"].items() if pid.startswith("guest-"))
        self.assertEqual((me.get("ship") or {}).get("layout", {}).get("layout_id"), "design_lightningbug")

    def test_guest_ships_are_purged_on_logout(self) -> None:
        from starshot.v2 import ship_designs as sd
        client = make_client()
        guest = client.post("/api/v2/auth/guest").json()["user"]
        uid = get_v2_store().get_user_by_name(guest["username"])["id"]
        client.put("/api/v2/my/ship-designs", json={"id": "guest_ship", "name": "Guest Ship", "tiles": [], "lanes": {}})
        self.assertTrue(sd.list_designs(uid))
        client.post("/api/v2/auth/logout")
        self.assertEqual(sd.list_designs(uid), [])

    def test_delete_last_ship_restores_default(self) -> None:
        client = make_client()
        register(client, "ship_last")
        # Provision the starter and get it.
        ship1 = client.get("/api/v2/my/ship").json()
        ref1 = ship1["selected"]["ref"]
        # Extract the bare id (the actual design id to delete).
        uid = get_v2_store().get_user_by_name("ship_last")["id"]
        from starshot.v2.service import parse_ship_design_ref
        _, bare_id = parse_ship_design_ref(ref1)
        # Delete the only ship.
        response = client.delete(f"/api/v2/my/ship-designs/{bare_id}").json()
        # Should indicate the default was restored.
        self.assertTrue(response["restored_default"])
        self.assertTrue(response["default_ship"]["name"])
        # Player still has a ship to fly.
        ship2 = client.get("/api/v2/my/ship").json()
        self.assertNotEqual(ship2["selected"]["ref"], "")
        self.assertTrue(any(opt["ref"] for opt in ship2["options"]))

    def test_admin_default_starting_ship_applies_to_new_accounts(self) -> None:
        admin = make_client()
        admin.post("/api/v2/auth/login", json={"username": "davidmoore", "password": "rangers"})
        try:
            saved = admin.post("/api/v2/admin/settings", json={"default_starting_ship_design_id": "vanguard"})
            self.assertEqual(saved.status_code, 200, saved.text)
            from starshot.v2.settings import invalidate_cache
            invalidate_cache()
            newbie = make_client()
            register(newbie, "ship_erin")
            self.assertEqual(newbie.get("/api/v2/my/ship").json()["selected"]["name"], "Vanguard")
        finally:
            admin.post("/api/v2/admin/settings", json={"default_starting_ship_design_id": ""})
            from starshot.v2.settings import invalidate_cache
            invalidate_cache()


class SecurityTests(unittest.TestCase):
    def test_outsiders_cannot_view_or_act(self) -> None:
        client_a = make_client()
        register(client_a, "sec_owner")
        game_id = client_a.post(
            "/api/v2/matches", json={"ai_types": ["blaster"], "open_seats": 0}
        ).json()["game_id"]

        client_b = make_client()
        register(client_b, "sec_intruder")
        self.assertEqual(client_b.get(f"/api/v2/games/{game_id}/view").status_code, 403)
        self.assertEqual(
            client_b.post(f"/api/v2/games/{game_id}/orders", json={"orders": EMPTY_ORDERS}).status_code,
            403,
        )
        anonymous = make_client()
        self.assertEqual(anonymous.get(f"/api/v2/games/{game_id}/view").status_code, 401)


class MatchmakingTests(unittest.TestCase):
    def test_quick_match_pairs_two_players(self) -> None:
        client_a = make_client()
        register(client_a, "queue_anne")
        first = client_a.post("/api/v2/lobby/queue", json={"action": "join"}).json()
        self.assertTrue(first["queued"])
        self.assertFalse(first["matched"])

        client_b = make_client()
        register(client_b, "queue_bart")
        second = client_b.post("/api/v2/lobby/queue", json={"action": "join"}).json()
        self.assertTrue(second["matched"])
        game_id = second["game_id"]

        # Both players (and only they) can view; each sees only their own hand.
        for client, username in ((client_a, "queue_anne"), (client_b, "queue_bart")):
            view = client.get(f"/api/v2/games/{game_id}/view").json()
            self.assertEqual(view["you"], username)
            self.assertIn("hand", view["state"]["players"][username])

        # Play a full round: both submit, server resolves automatically.
        for client in (client_a, client_b):
            response = client.post(
                f"/api/v2/games/{game_id}/orders", json={"orders": EMPTY_ORDERS}
            )
            self.assertEqual(response.status_code, 200, response.text)
        state = client_a.get(f"/api/v2/games/{game_id}/view").json()["state"]
        self.assertIn(state["phase"], ("give_orders", "complete"))
        self.assertEqual(state["round_number"], 2)

    def test_open_match_join_flow(self) -> None:
        host = make_client()
        register(host, "open_host")
        created = host.post(
            "/api/v2/matches", json={"ai_types": ["hunter_killer"], "open_seats": 1}
        ).json()
        self.assertIsNone(created["game_id"])
        match_id = created["match"]["id"]

        joiner = make_client()
        register(joiner, "open_joiner")
        lobby = joiner.get("/api/v2/lobby").json()
        self.assertTrue(any(match["id"] == match_id for match in lobby["open_matches"]))
        joined = joiner.post(f"/api/v2/matches/{match_id}/join").json()
        self.assertIsNotNone(joined["game_id"])

    def test_lobby_hides_full_open_matches(self) -> None:
        host = make_client()
        register(host, "full_open_host")
        store = get_v2_store()
        host_user = store.get_user_by_name("full_open_host")
        match_id = store.create_match("Full AI table", host_user["id"], seats=2, status="open")
        store.add_seat(match_id, 0, "ai:blaster:1", "Cannoneer Israel Hands", ai_type="blaster")
        store.add_seat(match_id, 1, "ai:vault_runner:1", "Freebooter Ben Gunn", ai_type="vault_runner")

        joiner = make_client()
        register(joiner, "full_open_joiner")
        lobby = joiner.get("/api/v2/lobby").json()

        self.assertFalse(any(match["id"] == match_id for match in lobby["open_matches"]))


class PresenceAndChallengeTests(unittest.TestCase):
    def test_presence_challenge_accept_flow(self) -> None:
        alice, bob = make_client(), make_client()
        register(alice, "duel_alice")
        register(bob, "duel_bob")
        alice.get("/api/v2/lobby")  # touch presence
        lobby_b = bob.get("/api/v2/lobby").json()
        self.assertIn("duel_alice", [p["username"] for p in lobby_b["active_players"]])
        self.assertNotIn("duel_bob", [p["username"] for p in lobby_b["active_players"]])

        sent = alice.post("/api/v2/lobby/challenge", json={"username": "duel_bob"})
        self.assertEqual(sent.status_code, 200, sent.text)

        incoming = bob.get("/api/v2/lobby").json()["challenges"]["incoming"]
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0]["from_username"], "duel_alice")

        accepted = bob.post(f"/api/v2/lobby/challenge/{incoming[0]['id']}/respond", json={"accept": True}).json()
        self.assertTrue(accepted["accepted"])
        game_id = accepted["game_id"]

        outgoing = alice.get("/api/v2/lobby").json()["challenges"]["outgoing"]
        self.assertTrue(any(c["status"] == "accepted" and c["game_id"] == game_id for c in outgoing))
        # Both can play, and self-challenge is rejected.
        self.assertEqual(alice.get(f"/api/v2/games/{game_id}/view").status_code, 200)
        self.assertEqual(bob.get(f"/api/v2/games/{game_id}/view").status_code, 200)
        self.assertEqual(
            alice.post("/api/v2/lobby/challenge", json={"username": "duel_alice"}).status_code, 400
        )

    def test_starting_any_match_clears_quick_match_queue(self) -> None:
        # Regression: a stale queue entry made the lobby bounce players back
        # into their newest active game forever ("locked in on battle screen").
        client = make_client()
        register(client, "queue_stuck")
        joined = client.post("/api/v2/lobby/queue", json={"action": "join"}).json()
        self.assertTrue(joined["queued"])
        client.post("/api/v2/matches", json={"ai_types": ["blaster"], "open_seats": 0})
        status = client.get("/api/v2/lobby").json()["queue"]
        self.assertFalse(status["queued"])

    def test_challenge_decline(self) -> None:
        alice, bob = make_client(), make_client()
        register(alice, "decl_alice")
        register(bob, "decl_bob")
        alice.post("/api/v2/lobby/challenge", json={"username": "decl_bob"})
        incoming = bob.get("/api/v2/lobby").json()["challenges"]["incoming"]
        bob.post(f"/api/v2/lobby/challenge/{incoming[0]['id']}/respond", json={"accept": False})
        self.assertEqual(len(bob.get("/api/v2/lobby").json()["challenges"]["incoming"]), 0)


class TurnAndAbandonTests(unittest.TestCase):
    def test_your_turn_flags_and_abandon_forfeit(self) -> None:
        alice, bob = make_client(), make_client()
        register(alice, "turn_alice")
        register(bob, "turn_bob")
        alice.post("/api/v2/lobby/queue", json={"action": "join"})
        paired = bob.post("/api/v2/lobby/queue", json={"action": "join"}).json()
        game_id = paired["game_id"]

        def my_match(client):
            matches = client.get("/api/v2/lobby").json()["my_matches"]
            return next(m for m in matches if m["game_id"] == game_id)

        self.assertTrue(my_match(alice)["turn"]["your_turn"])
        alice.post(f"/api/v2/games/{game_id}/orders", json={"orders": EMPTY_ORDERS})
        self.assertFalse(my_match(alice)["turn"]["your_turn"])  # waiting on bob
        self.assertTrue(my_match(bob)["turn"]["your_turn"])

        # Bob strikes his colors: forfeits, match leaves his list, game ends
        # with Alice the last captain flying.
        response = bob.post(f"/api/v2/matches/{my_match(bob)['id']}/abandon")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["forfeited"])
        bob_matches = bob.get("/api/v2/lobby").json()["my_matches"]
        self.assertFalse(any(m["game_id"] == game_id for m in bob_matches))
        state = alice.get(f"/api/v2/games/{game_id}/view").json()["state"]
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(state["result"]["winner_ids"], ["turn_alice"])
        self.assertTrue(any(e["type"] == "player_forfeited" for e in state["event_log"]))
        # Alice's battles list flags that her rival struck their colors.
        alice_match = my_match(alice)
        self.assertEqual(alice_match["status"], "complete")
        self.assertIn("turn_bob", alice_match["turn"]["forfeited"])

    def test_dismiss_complete_match(self) -> None:
        client = make_client()
        register(client, "dismiss_dave")
        created = client.post("/api/v2/matches", json={"ai_types": ["blaster"], "open_seats": 0}).json()
        game_id = created["game_id"]
        for _ in range(10):
            state = client.get(f"/api/v2/games/{game_id}/view").json()["state"]
            if state["phase"] == "complete":
                break
            client.post(f"/api/v2/games/{game_id}/orders", json={"orders": EMPTY_ORDERS})
        match_id = created["match"]["id"]
        self.assertEqual(client.post(f"/api/v2/matches/{match_id}/abandon").json()["forfeited"], False)
        matches = client.get("/api/v2/lobby").json()["my_matches"]
        self.assertFalse(any(m["id"] == match_id for m in matches))


class AiBattleTests(unittest.TestCase):
    def admin_client(self) -> TestClient:
        admin = make_client()
        admin.get("/api/v2/admin/deck")  # trigger seeding
        login = admin.post("/api/v2/auth/login", json={"username": "davidmoore", "password": "rangers"})
        assert login.status_code == 200, login.text
        return admin

    def test_admin_runs_full_ai_battle_and_spectates(self) -> None:
        admin = self.admin_client()
        result = admin.post(
            "/api/v2/admin/ai-battle",
            json={"ai_types": ["vault_runner", "hunter_killer", "blaster"]},
        ).json()
        self.assertTrue(result["complete"])
        self.assertTrue(result["winners"])
        self.assertEqual(len(result["players"]), 3)

        # Admin spectates the finished game; hidden info stays hidden.
        view = admin.get(f"/api/v2/games/{result['game_id']}/view").json()
        self.assertIsNone(view["you"])
        for player in view["state"]["players"].values():
            self.assertNotIn("hand", player)
            self.assertNotIn("deck", player)
        # Spectators may not submit orders; outsiders may not even look.
        self.assertEqual(
            admin.post(f"/api/v2/games/{result['game_id']}/orders", json={"orders": EMPTY_ORDERS}).status_code,
            403,
        )
        outsider = make_client()
        register(outsider, "battle_peeker")
        self.assertEqual(outsider.get(f"/api/v2/games/{result['game_id']}/view").status_code, 403)
        self.assertEqual(
            outsider.post("/api/v2/admin/ai-battle", json={"ai_types": ["blaster", "blaster"]}).status_code,
            403,
        )

    def test_admin_batch_ai_battle_history_summary(self) -> None:
        admin = self.admin_client()
        deck_sets = admin.get("/api/v2/admin/deck").json()["sets"]
        active_deck = next(deck_set for deck_set in deck_sets if deck_set.get("active"))
        self.assertFalse(active_deck.get("deprecated", False))
        deck_set_id = active_deck["id"]

        batch = admin.post(
            "/api/v2/admin/ai-battle-batch",
            json={"ai_types": ["vault_runner", "hunter_killer"], "run_count": 3, "deck_set_id": deck_set_id},
        ).json()

        self.assertEqual(batch["run_count"], 3)
        self.assertIsNone(batch["history_entry"]["game_id"])
        self.assertGreaterEqual(batch["average_total_vp"], 0)
        self.assertEqual({entry["ai_type"] for entry in batch["ai_rankings"]}, {"vault_runner", "hunter_killer"})

        history = admin.get("/api/v2/admin/ai-battles").json()["entries"]
        entry = next(entry for entry in history if entry["id"] == batch["history_entry"]["id"])
        self.assertEqual(entry["kind"], "batch")
        self.assertEqual(entry["deck_set_id"], deck_set_id)

        detail = admin.get(f"/api/v2/admin/ai-battles/{entry['id']}").json()["entry"]["detail"]
        self.assertEqual(len(detail["runs"]), 3)
        self.assertTrue(detail["notes"])

    def test_admin_batch_ai_battle_job_reports_progress(self) -> None:
        admin = self.admin_client()
        created = admin.post(
            "/api/v2/admin/ai-battle-batch/jobs",
            json={"ai_types": ["vault_runner", "hunter_killer"], "run_count": 1},
        ).json()

        self.assertEqual(created["total"], 1)
        self.assertIn(created["status"], {"running", "complete"})

        current = admin.get(f"/api/v2/admin/ai-battle-batch/jobs/{created['id']}").json()
        self.assertEqual(current["status"], "complete")
        self.assertEqual(current["remaining"], 0)
        self.assertEqual(current["completed"], 1)
        self.assertEqual(current["result"]["run_count"], 1)


class SiteSettingsTests(unittest.TestCase):
    def admin_client(self) -> TestClient:
        client = make_client()
        client.get("/api/v2/admin/deck")
        response = client.post("/api/v2/auth/login", json={"username": "davidmoore", "password": "rangers"})
        assert response.status_code == 200, response.text
        return client

    def test_maintenance_mode_blocks_players_but_not_admin(self) -> None:
        admin = self.admin_client()
        player = make_client()
        register(player, "maint_player")
        try:
            saved = admin.post("/api/v2/admin/settings", json={"maintenance": "Refitting the cannons"})
            self.assertEqual(saved.status_code, 200)
            blocked = player.post("/api/v2/matches", json={"ai_types": ["blaster"], "open_seats": 0})
            self.assertEqual(blocked.status_code, 503)
            self.assertIn("Refitting the cannons", blocked.json()["detail"])
            self.assertEqual(
                player.post("/api/v2/lobby/queue", json={"action": "join"}).status_code, 503
            )
            # The lobby still loads and carries the banner message.
            lobby = player.get("/api/v2/lobby").json()
            self.assertEqual(lobby["maintenance"], "Refitting the cannons")
            # The admin sails on unimpeded.
            allowed = admin.post("/api/v2/matches", json={"ai_types": ["blaster"], "open_seats": 0})
            self.assertEqual(allowed.status_code, 200, allowed.text)
        finally:
            admin.post("/api/v2/admin/settings", json={"maintenance": ""})
        reopened = player.post("/api/v2/matches", json={"ai_types": ["blaster"], "open_seats": 0})
        self.assertEqual(reopened.status_code, 200)

    def test_site_auth_toggle(self) -> None:
        admin = self.admin_client()
        anonymous = make_client()
        try:
            # Gate on: unauthenticated requests bounce with a Basic challenge.
            admin.post("/api/v2/admin/settings", json={"site_auth": True})
            gated = anonymous.get("/api/health")
            self.assertEqual(gated.status_code, 401)
            self.assertIn("WWW-Authenticate", gated.headers)
            # Correct Basic credentials (repo .htpasswd: david/rangers) pass.
            passed = anonymous.get("/api/health", auth=("david", "rangers"))
            self.assertEqual(passed.status_code, 200)
        finally:
            admin.post("/api/v2/admin/settings", json={"site_auth": False}, auth=("david", "rangers"))
        self.assertEqual(anonymous.get("/api/health").status_code, 200)


class DeckSetTests(unittest.TestCase):
    def admin_client(self) -> TestClient:
        client = make_client()
        client.get("/api/v2/admin/deck")
        response = client.post("/api/v2/auth/login", json={"username": "davidmoore", "password": "rangers"})
        assert response.status_code == 200, response.text
        return client

    def test_save_as_activate_and_per_game_binding(self) -> None:
        admin = self.admin_client()
        # A game created under the stock set, before any switching.
        old_game = admin.post("/api/v2/matches", json={"ai_types": ["blaster"], "open_seats": 0}).json()["game_id"]

        saved = admin.post("/api/v2/admin/deck/save-as", json={"name": "Test Brew"})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["id"], "custom_test_brew")

        try:
            activated = admin.post("/api/v2/admin/deck/activate", json={"id": "custom_test_brew"})
            self.assertEqual(activated.status_code, 200, activated.text)

            # New games are born on the custom set…
            new_game = admin.post("/api/v2/matches", json={"ai_types": ["blaster"], "open_seats": 0}).json()["game_id"]
            new_view = admin.get(f"/api/v2/games/{new_game}/view").json()
            self.assertEqual(new_view["state"]["deck_set_id"], "custom_test_brew")

            # …while the old battle keeps its original set and stays playable.
            old_view = admin.get(f"/api/v2/games/{old_game}/view").json()
            self.assertEqual(old_view["state"]["deck_set_id"], "core_0_3_sides")
            if old_view["state"]["phase"] == "give_orders":
                played = admin.post(f"/api/v2/games/{old_game}/orders", json={"orders": EMPTY_ORDERS})
                self.assertEqual(played.status_code, 200, played.text)
        finally:
            back = admin.post("/api/v2/admin/deck/activate", json={"id": "core_0_3_sides"})
            self.assertEqual(back.status_code, 200, back.text)


class EarlyAbandonTests(unittest.TestCase):
    def test_abandon_before_round1_orders_is_not_a_loss(self) -> None:
        alice, bob = make_client(), make_client()
        register(alice, "early_alice")
        register(bob, "early_bob")
        alice.post("/api/v2/lobby/queue", json={"action": "join"})
        game_id = bob.post("/api/v2/lobby/queue", json={"action": "join"}).json()["game_id"]
        match = next(
            m for m in bob.get("/api/v2/lobby").json()["my_matches"] if m["game_id"] == game_id
        )
        # Bob bails before sealing any orders: no loss on his ledger.
        response = bob.post(f"/api/v2/matches/{match['id']}/abandon")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["counted_as_loss"])
        bob_profile = bob.get("/api/v2/me").json()["user"]
        self.assertEqual(bob_profile["losses"], 0)
        self.assertEqual(bob_profile["games_played"], 0)
        # Alice still collects the win for holding the field.
        alice_profile = alice.get("/api/v2/me").json()["user"]
        self.assertEqual(alice_profile["wins"], 1)

    def test_abandon_after_orders_counts_as_loss(self) -> None:
        alice, bob = make_client(), make_client()
        register(alice, "late_alice")
        register(bob, "late_bob")
        alice.post("/api/v2/lobby/queue", json={"action": "join"})
        game_id = bob.post("/api/v2/lobby/queue", json={"action": "join"}).json()["game_id"]
        bob.post(f"/api/v2/games/{game_id}/orders", json={"orders": EMPTY_ORDERS})
        match = next(
            m for m in bob.get("/api/v2/lobby").json()["my_matches"] if m["game_id"] == game_id
        )
        response = bob.post(f"/api/v2/matches/{match['id']}/abandon")
        self.assertTrue(response.json()["counted_as_loss"])
        bob_profile = bob.get("/api/v2/me").json()["user"]
        self.assertEqual(bob_profile["losses"], 1)


class AdminTests(unittest.TestCase):
    def admin_client(self) -> TestClient:
        client = make_client()
        response = client.post(
            "/api/v2/auth/login", json={"username": "davidmoore", "password": "rangers"}
        )
        if response.status_code != 200:
            # Seeding happens on first admin-endpoint touch; poke one then retry.
            client.get("/api/v2/admin/deck")
            response = client.post(
                "/api/v2/auth/login", json={"username": "davidmoore", "password": "rangers"}
            )
        assert response.status_code == 200, response.text
        return client

    def test_admin_endpoints_locked_down(self) -> None:
        anonymous = make_client()
        self.assertEqual(anonymous.get("/api/v2/admin/deck").status_code, 401)
        outsider = make_client()
        register(outsider, "admin_snoop")
        self.assertEqual(outsider.get("/api/v2/admin/deck").status_code, 403)
        self.assertEqual(anonymous.get("/api/v2/admin/ai-changelog").status_code, 401)
        self.assertEqual(outsider.get("/api/v2/admin/ai-changelog").status_code, 403)
        self.assertEqual(outsider.get("/api/v2/admin/download").status_code, 403)
        self.assertEqual(
            outsider.post("/api/v2/admin/keywords", json={"name": "x", "pattern": "y", "code": "spec=1"}).status_code,
            403,
        )

    def test_ai_changelog_visible_to_admin(self) -> None:
        client = self.admin_client()
        response = client.get("/api/v2/admin/ai-changelog")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["path"].replace("\\", "/").endswith("docs/context/ai_changelog.md"))
        self.assertIn("StarShot AI Change Log", payload["text"])
        self.assertIn("Codex", payload["text"])
        self.assertTrue(payload["build_id"])

    def test_starbreach_boss_defaults_and_allowed_list(self) -> None:
        client = self.admin_client()
        tempdir = tempfile.TemporaryDirectory()
        old_bundled = boss_designs.DESIGNS_DIR
        old_runtime = boss_designs.RUNTIME_DESIGNS_DIR
        root = Path(tempdir.name)
        boss_designs.DESIGNS_DIR = root / "bundled"
        boss_designs.RUNTIME_DESIGNS_DIR = root / "runtime"
        try:
            boss_designs.save_design(make_design(id="allowed_boss", name="Allowed Boss"))
            boss_designs.save_design(make_design(id="blocked_boss", name="Blocked Boss"))

            saved = client.post(
                "/api/v2/admin/settings",
                json={
                    "default_starbreach_boss_design_id": "allowed_boss",
                    "allowed_starbreach_boss_design_ids": ["allowed_boss"],
                },
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            star_breach = saved.json()["star_breach"]
            self.assertEqual(star_breach["default_boss_design_id"], "allowed_boss")
            self.assertEqual(star_breach["allowed_boss_design_ids"], ["allowed_boss"])

            public = client.get("/api/v2/boss-designs")
            self.assertEqual(public.status_code, 200, public.text)
            self.assertEqual(public.json()["default_design_id"], "allowed_boss")
            self.assertEqual([entry["id"] for entry in public.json()["designs"]], ["allowed_boss"])

            rejected = client.post(
                "/api/v2/matches",
                json={
                    "active_expansions": ["star_breach"],
                    "star_breach_boss_design_id": "blocked_boss",
                    "open_seats": 0,
                },
            )
            self.assertEqual(rejected.status_code, 400)
            self.assertIn("not allowed", rejected.json()["detail"])

            created = client.post(
                "/api/v2/matches",
                json={"active_expansions": ["star_breach"], "open_seats": 0},
            )
            self.assertEqual(created.status_code, 200, created.text)
        finally:
            client.post(
                "/api/v2/admin/settings",
                json={
                    "default_starbreach_boss_design_id": "",
                    "allowed_starbreach_boss_design_ids": [],
                },
            )
            boss_designs.DESIGNS_DIR = old_bundled
            boss_designs.RUNTIME_DESIGNS_DIR = old_runtime
            tempdir.cleanup()

    def test_deck_roundtrip_and_validation(self) -> None:
        client = self.admin_client()
        deck = client.get("/api/v2/admin/deck").json()
        base = deck["base"]
        self.assertTrue(any(card["name"] == "Targeted Attack" for card in base["cards"]))

        # Unchanged save must validate and succeed.
        ok = client.put("/api/v2/admin/deck", json={"which": "base", "header": base["header"], "cards": base["cards"]})
        self.assertEqual(ok.status_code, 200, ok.text)
        from starshot.v2.service import core_deck_path

        active_path = core_deck_path().resolve()
        self.assertTrue(str(active_path).startswith(str(Path(os.environ["STARSHOT_CUSTOM_DECKS"]).resolve())))

        # A card with unparseable text is rejected with a useful message.
        broken = base["cards"] + [{"name": "Bad Card", "copies": 1, "side_a_type": "Basic", "side_a_1": "Flibber 3"}]
        rejected = client.put("/api/v2/admin/deck", json={"which": "base", "header": base["header"], "cards": broken})
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("unsupported effect text", rejected.json()["detail"])

        # New games still start fine after the failed save.
        game = client.post("/api/v2/matches", json={"ai_types": ["blaster"], "open_seats": 0})
        self.assertEqual(game.status_code, 200, game.text)

    def test_custom_keyword_enables_new_card_text(self) -> None:
        client = self.admin_client()
        keyword = {
            "name": "Flibber X",
            "pattern": r"flibber (\d+)",
            "code": "spec = FaceSpec(family=CardFamily.MOVE, value=int(match.group(1)) * 2, requires_target=False)",
            "enabled": True,
        }
        saved = client.post("/api/v2/admin/keywords", json=keyword)
        self.assertEqual(saved.status_code, 200, saved.text)

        tested = client.post(
            "/api/v2/admin/keywords/test",
            json={"pattern": keyword["pattern"], "code": keyword["code"], "sample": "Flibber 3"},
        ).json()
        self.assertTrue(tested["matched"])
        self.assertEqual(tested["spec"]["value"], 6)

        # The new keyword makes previously-invalid card text saveable.
        deck = client.get("/api/v2/admin/deck").json()
        base = deck["base"]
        with_flibber = base["cards"] + [
            {"name": "Flibber Drive", "copies": 1, "side_a_type": "Basic", "side_a_1": "Flibber 3"}
        ]
        # Adding the keyword makes previously-unparseable card text saveable:
        # the deck editor validates the new "Flibber 3" face through the keyword.
        # (Ships supply their own component-derived decks in play, so this is
        # verified at the deck-editor boundary rather than in a live game.)
        accepted = client.put(
            "/api/v2/admin/deck", json={"which": "base", "header": base["header"], "cards": with_flibber}
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        # Without the keyword the same text is rejected: remove it, retry, restore.
        client.delete("/api/v2/admin/keywords/Flibber%20X")
        rejected = client.put(
            "/api/v2/admin/deck", json={"which": "base", "header": base["header"], "cards": with_flibber}
        )
        self.assertEqual(rejected.status_code, 400, rejected.text)

        # Restore the original deck (the keyword was already removed above).
        restored = client.put(
            "/api/v2/admin/deck", json={"which": "base", "header": base["header"], "cards": base["cards"]}
        )
        self.assertEqual(restored.status_code, 200)

    def test_project_zip_download(self) -> None:
        client = self.admin_client()
        response = client.get("/api/v2/admin/download")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        import io
        import zipfile
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            self.assertIn("StarShot/pyproject.toml", names)
            self.assertTrue(any(name.endswith("engine.py") for name in names))
            self.assertFalse(any(".htpasswd" in name or name.endswith(".sqlite3") for name in names))

    def test_deck_set_export_import_and_validation(self) -> None:
        client = self.admin_client()
        exported = client.get("/api/v2/admin/deck/export/core_0_3_sides")
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertEqual(exported.headers["content-type"], "application/zip")

        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            names = archive.namelist()
            self.assertTrue(any(name.endswith("manifest.toml") for name in names))
            self.assertTrue(any(name.endswith("base_deck.toml") for name in names))
            self.assertTrue(any(name.endswith("desperation_deck.toml") for name in names))
            self.assertTrue(any(name.endswith("custom_keywords.json") for name in names))

            upload_buffer = io.BytesIO()
            with zipfile.ZipFile(upload_buffer, "w", zipfile.ZIP_DEFLATED) as upload:
                for name in names:
                    data = archive.read(name)
                    if name.endswith("manifest.toml"):
                        text = data.decode("utf-8")
                        text = text.replace('id = "core_0_3_sides"', 'id = "custom_api_bundle"')
                        text = text.replace('name = "StarShot Core 0.3"', 'name = "API Bundle"')
                        data = text.encode("utf-8")
                    upload.writestr(name, data)

        try:
            imported = client.post(
                "/api/v2/admin/deck/import?activate=true",
                content=upload_buffer.getvalue(),
                headers={"content-type": "application/zip"},
            )
            self.assertEqual(imported.status_code, 200, imported.text)
            self.assertEqual(imported.json()["id"], "custom_api_bundle")
            self.assertTrue(imported.json()["activated"])
            deck = client.get("/api/v2/admin/deck").json()
            self.assertEqual(deck["active_id"], "custom_api_bundle")
            imported_set = next(deck_set for deck_set in deck["sets"] if deck_set["id"] == "custom_api_bundle")
            self.assertEqual(imported_set["name"], "API Bundle")
            self.assertTrue(imported_set["uploaded_at"])
            self.assertTrue(imported_set["modified_at"])

            renamed = client.post(
                "/api/v2/admin/deck/rename",
                json={"id": "custom_api_bundle", "name": "Renamed API Bundle"},
            )
            self.assertEqual(renamed.status_code, 200, renamed.text)
            renamed_set = next(deck_set for deck_set in renamed.json()["sets"] if deck_set["id"] == "custom_api_bundle")
            self.assertEqual(renamed_set["name"], "Renamed API Bundle")
            self.assertTrue(renamed_set["modified_at"])

            active_delete = client.delete("/api/v2/admin/deck/custom_api_bundle")
            self.assertEqual(active_delete.status_code, 400)
            self.assertIn("active", active_delete.json()["detail"])

            active_deprecate = client.post(
                "/api/v2/admin/deck/deprecation",
                json={"id": "custom_api_bundle", "deprecated": True},
            )
            self.assertEqual(active_deprecate.status_code, 400)
            self.assertIn("active", active_deprecate.json()["detail"])
        finally:
            restored = client.post("/api/v2/admin/deck/activate", json={"id": "core_0_3_sides"})
            self.assertEqual(restored.status_code, 200, restored.text)

        stock_delete = client.delete("/api/v2/admin/deck/core_0_2_sides")
        self.assertEqual(stock_delete.status_code, 400)
        self.assertIn("Stock deck sets", stock_delete.json()["detail"])

        deprecated = client.post(
            "/api/v2/admin/deck/deprecation",
            json={"id": "custom_api_bundle", "deprecated": True},
        )
        self.assertEqual(deprecated.status_code, 200, deprecated.text)
        deprecated_set = next(deck_set for deck_set in deprecated.json()["sets"] if deck_set["id"] == "custom_api_bundle")
        self.assertTrue(deprecated_set["deprecated"])
        rejected_battle = client.post(
            "/api/v2/admin/ai-battle-batch",
            json={"ai_types": ["vault_runner", "hunter_killer"], "run_count": 1, "deck_set_id": "custom_api_bundle"},
        )
        self.assertEqual(rejected_battle.status_code, 400)
        self.assertIn("deprecated", rejected_battle.json()["detail"])

        deleted = client.delete("/api/v2/admin/deck/custom_api_bundle")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertNotIn("custom_api_bundle", [deck_set["id"] for deck_set in deleted.json()["sets"]])
        self.assertFalse((Path(os.environ["STARSHOT_CUSTOM_DECKS"]) / "api_bundle").exists())

        bad_buffer = io.BytesIO()
        with zipfile.ZipFile(bad_buffer, "w", zipfile.ZIP_DEFLATED) as bad:
            bad.writestr("broken/manifest.toml", 'id = "custom_broken"\nname = "Broken"\nrules_version = "0.3"\n')
        rejected = client.post(
            "/api/v2/admin/deck/import",
            content=bad_buffer.getvalue(),
            headers={"content-type": "application/zip"},
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("missing config.toml", rejected.json()["detail"])

    def test_change_password(self) -> None:
        # Only the admin has a password these days; change it and back again.
        client = make_client()
        login = client.post("/api/v2/auth/login", json={"username": "davidmoore", "password": "rangers"})
        self.assertEqual(login.status_code, 200, login.text)
        wrong = client.post(
            "/api/v2/auth/password", json={"current_password": "nope", "new_password": "newpass"}
        )
        self.assertEqual(wrong.status_code, 401)
        good = client.post(
            "/api/v2/auth/password", json={"current_password": "rangers", "new_password": "newpass"}
        )
        self.assertEqual(good.status_code, 200)
        try:
            fresh = make_client()
            self.assertEqual(
                fresh.post("/api/v2/auth/login", json={"username": "davidmoore", "password": "newpass"}).status_code,
                200,
            )
        finally:
            restore = client.post(
                "/api/v2/auth/password", json={"current_password": "newpass", "new_password": "rangers"}
            )
            self.assertEqual(restore.status_code, 200)


class DisplayNameTests(unittest.TestCase):
    def admin_client(self) -> TestClient:
        client = make_client()
        client.get("/api/v2/admin/deck")  # seeds the admin account
        login = client.post("/api/v2/auth/login", json={"username": "davidmoore", "password": "rangers"})
        self.assertEqual(login.status_code, 200, login.text)
        return client

    def user_id_for(self, admin: TestClient, username: str) -> int:
        accounts = admin.get("/api/v2/admin/accounts").json()["accounts"]
        return next(entry["id"] for entry in accounts if entry["username"] == username)

    def test_display_name_defaults_to_username_and_can_change(self) -> None:
        client = make_client()
        register(client, "name_alice")
        me = client.get("/api/v2/me").json()
        self.assertEqual(me["user"]["display_name"], "name_alice")

        result = client.post("/api/v2/profile/display-name", json={"display_name": "Salty Alice"})
        self.assertEqual(result.status_code, 200, result.text)
        payload = result.json()
        self.assertFalse(payload["flagged"])
        self.assertIsNone(payload["warning"])
        self.assertEqual(payload["user"]["display_name"], "Salty Alice")

        bad = client.post("/api/v2/profile/display-name", json={"display_name": "x<script>y"})
        self.assertEqual(bad.status_code, 400)

    def test_random_name_endpoint(self) -> None:
        client = make_client()
        register(client, "name_random")
        result = client.get("/api/v2/profile/random-name")
        self.assertEqual(result.status_code, 200)
        self.assertGreaterEqual(len(result.json()["name"]), 3)

    def test_flagged_name_warns_hides_and_blocks_matchmaking(self) -> None:
        client = make_client()
        register(client, "name_flagged")
        result = client.post("/api/v2/profile/display-name", json={"display_name": "Sh1t Storm"})
        self.assertEqual(result.status_code, 200, result.text)
        payload = result.json()
        self.assertTrue(payload["flagged"])
        self.assertIn("hidden from the leaderboards", payload["warning"])

        board = client.get("/api/v2/leaderboard").json()
        self.assertNotIn("name_flagged", [entry["username"] for entry in board["leaderboard"]])

        queue = client.post("/api/v2/lobby/queue", json={"action": "join"})
        self.assertEqual(queue.status_code, 403)

        # AI-only raids stay open to flagged names; open-seat raids do not.
        blocked = client.post("/api/v2/matches", json={"ai_types": ["blaster"], "open_seats": 1})
        self.assertEqual(blocked.status_code, 403)
        allowed = client.post("/api/v2/matches", json={"ai_types": ["blaster"], "open_seats": 0})
        self.assertEqual(allowed.status_code, 200, allowed.text)

        # Renaming to something clean restores standing.
        clean = client.post("/api/v2/profile/display-name", json={"display_name": "Reformed Rob"})
        self.assertFalse(clean.json()["flagged"])
        queue = client.post("/api/v2/lobby/queue", json={"action": "join"})
        self.assertEqual(queue.status_code, 200)
        client.post("/api/v2/lobby/queue", json={"action": "leave"})

    def test_seat_display_names_use_display_name(self) -> None:
        client = make_client()
        register(client, "name_seat")
        client.post("/api/v2/profile/display-name", json={"display_name": "Dread Pirate Seat"})
        result = client.post("/api/v2/matches", json={"ai_types": ["blaster"], "open_seats": 0})
        self.assertEqual(result.status_code, 200, result.text)
        seats = result.json()["match"]["seat_list"]
        human = next(seat for seat in seats if not seat["is_ai"])
        self.assertEqual(human["display_name"], "Dread Pirate Seat")
        self.assertEqual(human["player_id"], "name_seat")

    def test_admin_ban_name_forces_rename(self) -> None:
        client = make_client()
        register(client, "name_banned")
        client.post("/api/v2/profile/display-name", json={"display_name": "Innocent Looking"})
        admin = self.admin_client()
        user_id = self.user_id_for(admin, "name_banned")

        result = admin.post(f"/api/v2/admin/accounts/{user_id}/ban-name")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["banned_name"], "Innocent Looking")
        self.assertIn("Innocent Looking", [entry["name"] for entry in result.json()["illegal_names"]])

        me = client.get("/api/v2/me").json()["user"]
        self.assertTrue(me["must_rename"])
        self.assertTrue(me["name_flagged"])

        # The banned name (any casing) cannot be re-taken.
        retake = client.post("/api/v2/profile/display-name", json={"display_name": "innocent looking"})
        self.assertEqual(retake.status_code, 400)

        renamed = client.post("/api/v2/profile/display-name", json={"display_name": "Fresh Start"})
        self.assertEqual(renamed.status_code, 200)
        me = client.get("/api/v2/me").json()["user"]
        self.assertFalse(me["must_rename"])
        self.assertFalse(me["name_flagged"])

        # Un-ban clears the list.
        removed = admin.delete("/api/v2/admin/illegal-names/Innocent%20Looking")
        self.assertEqual(removed.status_code, 200)
        self.assertNotIn(
            "Innocent Looking",
            [entry["name"] for entry in removed.json()["illegal_names"]],
        )

    def test_admin_toggles_hide_from_leaderboard_and_matchmaking(self) -> None:
        client = make_client()
        register(client, "name_toggle")
        admin = self.admin_client()
        user_id = self.user_id_for(admin, "name_toggle")

        result = admin.post(
            f"/api/v2/admin/accounts/{user_id}/flags",
            json={"leaderboard_ok": False, "matchmaking_ok": False},
        )
        self.assertEqual(result.status_code, 200, result.text)
        board = client.get("/api/v2/leaderboard").json()
        self.assertNotIn("name_toggle", [entry["username"] for entry in board["leaderboard"]])
        queue = client.post("/api/v2/lobby/queue", json={"action": "join"})
        self.assertEqual(queue.status_code, 403)

        admin.post(
            f"/api/v2/admin/accounts/{user_id}/flags",
            json={"leaderboard_ok": True, "matchmaking_ok": True},
        )
        board = client.get("/api/v2/leaderboard").json()
        self.assertIn("name_toggle", [entry["username"] for entry in board["leaderboard"]])


if __name__ == "__main__":
    unittest.main()
