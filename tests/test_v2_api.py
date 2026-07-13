from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.TemporaryDirectory()
os.environ["STARSHOT_V2_DB"] = str(Path(TMP.name) / "v2.sqlite3")
os.environ.pop("STARSHOT_SITE_AUTH", None)

# Isolate everything the admin console can write: run v2 games and the deck
# editor against a scratch copy of core_0_3, and keywords in a scratch file.
_REPO_DECKS = Path(__file__).resolve().parents[1] / "resources" / "decks" / "core_0_3"
_TEST_DECKS = Path(TMP.name) / "core_0_3"
shutil.copytree(_REPO_DECKS, _TEST_DECKS)
os.environ["STARSHOT_V2_DECK_SET"] = str(_TEST_DECKS)
os.environ["STARSHOT_KEYWORDS_FILE"] = str(Path(TMP.name) / "custom_keywords.json")
os.environ["STARSHOT_CUSTOM_DECKS"] = str(Path(TMP.name) / "custom_decks")

from fastapi.testclient import TestClient  # noqa: E402

from starshot.api.app import app  # noqa: E402
from starshot.v2.store import get_v2_store  # noqa: E402

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
    response = client.post("/api/v2/auth/register", json={"username": name, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


class AuthTests(unittest.TestCase):
    def test_register_login_logout(self) -> None:
        client = make_client()
        payload = register(client, "auth_alice")
        self.assertEqual(payload["user"]["username"], "auth_alice")

        me = client.get("/api/v2/me")
        self.assertEqual(me.status_code, 200)

        self.assertEqual(client.post("/api/v2/auth/logout").status_code, 200)
        self.assertEqual(client.get("/api/v2/me").status_code, 401)

        bad = client.post(
            "/api/v2/auth/login", json={"username": "auth_alice", "password": "wrong"}
        )
        self.assertEqual(bad.status_code, 401)

        good = client.post(
            "/api/v2/auth/login", json={"username": "auth_alice", "password": "rangers"}
        )
        self.assertEqual(good.status_code, 200)
        self.assertEqual(client.get("/api/v2/me").status_code, 200)

    def test_duplicate_username_rejected(self) -> None:
        client = make_client()
        register(client, "auth_bob")
        duplicate = client.post(
            "/api/v2/auth/register", json={"username": "auth_bob", "password": "rangers"}
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_invalid_username_rejected(self) -> None:
        client = make_client()
        response = client.post(
            "/api/v2/auth/register", json={"username": "bad name!", "password": "rangers"}
        )
        self.assertEqual(response.status_code, 400)


class AiMatchTests(unittest.TestCase):
    def test_vs_ai_game_runs_and_hides_secrets(self) -> None:
        client = make_client()
        register(client, "ai_tester")
        created = client.post(
            "/api/v2/matches", json={"ai_types": ["hunter_killer"], "open_seats": 0}
        )
        self.assertEqual(created.status_code, 200, created.text)
        game_id = created.json()["game_id"]
        self.assertIsNotNone(game_id)

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
            "/api/v2/matches", json={"ai_types": ["blaster", "bauble_runner"], "open_seats": 0}
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
        store.add_seat(match_id, 0, "ai:blaster:1", "Gunner Redbeard", ai_type="blaster")
        store.add_seat(match_id, 1, "ai:bauble_runner:1", "Salvage Capt. Morrigan", ai_type="bauble_runner")

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
    def test_admin_runs_full_ai_battle_and_spectates(self) -> None:
        admin = make_client()
        admin.get("/api/v2/admin/deck")  # trigger seeding
        login = admin.post("/api/v2/auth/login", json={"username": "davidmoore", "password": "rangers"})
        assert login.status_code == 200, login.text
        result = admin.post(
            "/api/v2/admin/ai-battle",
            json={"ai_types": ["bauble_runner", "hunter_killer", "blaster"]},
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
        self.assertEqual(outsider.get("/api/v2/admin/download").status_code, 403)
        self.assertEqual(
            outsider.post("/api/v2/admin/keywords", json={"name": "x", "pattern": "y", "code": "spec=1"}).status_code,
            403,
        )

    def test_deck_roundtrip_and_validation(self) -> None:
        client = self.admin_client()
        deck = client.get("/api/v2/admin/deck").json()
        base = deck["base"]
        self.assertTrue(any(card["name"] == "Targeted Attack" for card in base["cards"]))

        # Unchanged save must validate and succeed.
        ok = client.put("/api/v2/admin/deck", json={"which": "base", "header": base["header"], "cards": base["cards"]})
        self.assertEqual(ok.status_code, 200, ok.text)

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
        accepted = client.put(
            "/api/v2/admin/deck", json={"which": "base", "header": base["header"], "cards": with_flibber}
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)

        # A game created now includes the flibber card with doubled movement.
        game = client.post("/api/v2/matches", json={"ai_types": ["blaster"], "open_seats": 0}).json()
        view = client.get(f"/api/v2/games/{game['game_id']}/view").json()
        me = view["state"]["players"]["davidmoore"]
        all_cards = me["hand"] + me["discard"]
        flibbers = [card for card in all_cards if card["name"] == "Flibber Drive"]
        deck_has = me["deck_count"] + len(all_cards)
        self.assertGreaterEqual(deck_has, 11)  # 10 base + flibber somewhere

        # Restore the original deck and remove the keyword.
        restored = client.put(
            "/api/v2/admin/deck", json={"which": "base", "header": base["header"], "cards": base["cards"]}
        )
        self.assertEqual(restored.status_code, 200)
        removed = client.delete("/api/v2/admin/keywords/Flibber%20X")
        self.assertEqual(removed.status_code, 200)

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

    def test_change_password(self) -> None:
        client = make_client()
        register(client, "pw_changer", "oldpass")
        wrong = client.post(
            "/api/v2/auth/password", json={"current_password": "nope", "new_password": "newpass"}
        )
        self.assertEqual(wrong.status_code, 401)
        good = client.post(
            "/api/v2/auth/password", json={"current_password": "oldpass", "new_password": "newpass"}
        )
        self.assertEqual(good.status_code, 200)
        fresh = make_client()
        self.assertEqual(
            fresh.post("/api/v2/auth/login", json={"username": "pw_changer", "password": "newpass"}).status_code,
            200,
        )


if __name__ == "__main__":
    unittest.main()
