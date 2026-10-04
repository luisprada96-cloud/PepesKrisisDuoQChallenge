import copy
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import server


def penalty(base_id, scope="ONE", requirements=None, assigned_ms=1000):
    return {
        "id": f"test-{base_id}-{scope}",
        "penalty": {"id": f"{base_id}_{scope.lower()}", "baseId": base_id, "scope": scope},
        "scope": scope,
        "status": "ACTIVE",
        "resolved": False,
        "assignedAtEpochMs": assigned_ms,
        "requirements": requirements or {},
    }


def match(p1, p2, end_ms=2000):
    return {"matchId": "EUW1_TEST", "gameStartTimestamp": 1000, "gameEndTimestamp": end_ms, "player1Stats": p1, "player2Stats": p2}


class ShellPenaltyTests(unittest.TestCase):
    def test_one_and_both_no_flash(self):
        duo = {"activeDebuffs": [penalty("no_flash", "ONE"), penalty("no_flash", "BOTH")]}
        game = match({"summonerSpellIds": [4, 12]}, {"summonerSpellIds": [14, 12]})
        self.assertEqual(server.evaluate_active_penalties(duo, game), 1)
        self.assertEqual(duo["activeDebuffs"][0]["status"], "COMPLETED")
        self.assertEqual(duo["activeDebuffs"][1]["status"], "ACTIVE")

    def test_same_match_can_complete_multiple_penalties(self):
        requirements = {"mainRoles": {"player1": "TOP", "player2": "JUNGLE"}}
        duo = {"activeDebuffs": [penalty("no_flash"), penalty("autofill", requirements=requirements)]}
        game = match(
            {"summonerSpellIds": [14, 12], "position": "MIDDLE"},
            {"summonerSpellIds": [4, 12], "position": "JUNGLE"},
        )
        self.assertEqual(server.evaluate_active_penalties(duo, game), 2)

    def test_unknown_position_does_not_complete_autofill(self):
        requirements = {"mainRoles": {"player1": "TOP", "player2": "JUNGLE"}}
        duo = {"activeDebuffs": [penalty("autofill", requirements=requirements)]}
        game = match({"position": "UNKNOWN"}, {"position": "JUNGLE"})
        self.assertEqual(server.evaluate_active_penalties(duo, game), 0)

    def test_match_before_assignment_is_ignored(self):
        duo = {"activeDebuffs": [penalty("no_flash", assigned_ms=3000)]}
        game = match({"summonerSpellIds": [14, 12]}, {"summonerSpellIds": [14, 12]}, end_ms=2000)
        self.assertEqual(server.evaluate_active_penalties(duo, game), 0)
        self.assertEqual(duo["activeDebuffs"][0]["status"], "ACTIVE")

    def test_weighted_picker_respects_only_enabled_result(self):
        weights = {item["id"]: 0 for item in server.PENALTY_CATALOG}
        weights["return_shell"] = 100
        for _ in range(10):
            self.assertEqual(server.weighted_penalty(weights)["id"], "return_shell")

    def test_favorite_snapshot_preserves_ties(self):
        duo = {"history": [
            {"player1Stats": {"championName": "Ahri"}, "player2Stats": {"championName": "Lux"}},
            {"player1Stats": {"championName": "Lux"}, "player2Stats": {"championName": "Lux"}},
        ]}
        snapshot = server.favorite_snapshot(duo)
        self.assertEqual(snapshot["player1"], ["Ahri", "Lux"])
        self.assertEqual(snapshot["player2"], ["Lux"])

    def test_player_insights_include_totals_and_ignore_test_matches(self):
        duo = {"history": [
            {"player1Stats": {"championName": "Ahri", "kills": 5, "deaths": 2, "assists": 7, "win": True},
             "player2Stats": {"championName": "Lux", "kills": 2, "deaths": 3, "assists": 10, "win": True}},
            {"isTest": True,
             "player1Stats": {"championName": "Ahri", "kills": 999, "deaths": 999, "assists": 999}},
        ]}
        insights = server.calculate_player_insights(duo)
        self.assertEqual(insights["player1"]["totals"], {"kills": 5, "deaths": 2, "assists": 7})
        self.assertEqual(insights["player2"]["totals"], {"kills": 2, "deaths": 3, "assists": 10})


class ShellEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_file = server.DB_FILE
        self.old_secrets_file = server.SECRETS_FILE
        server.SECRETS_FILE = str(Path(self.temp_dir.name) / "secrets.json")
        server.DB_FILE = str(Path(self.temp_dir.name) / "db.json")
        weights = {item["id"]: 0 for item in server.PENALTY_CATALOG}
        weights["no_flash_one"] = 100
        database = {
            "config": {"adminPinHash": server.hash_secret("9999"), "penaltyWeights": weights},
            "events": [], "shellAttacks": [],
            "duos": [
                {"id": "a", "teamName": "Atacante", "passwordHash": server.hash_secret("a-pass"), "blueShells": 1,
                 "player1": {"name": "A1", "mainRole": "TOP"}, "player2": {"name": "A2", "mainRole": "TOP"}, "history": []},
                {"id": "b", "teamName": "Receptor", "passwordHash": server.hash_secret("b-pass"), "blueShells": 0,
                 "player1": {"name": "B1", "mainRole": "TOP"}, "player2": {"name": "B2", "mainRole": "TOP"}, "history": []},
            ],
        }
        Path(server.DB_FILE).write_text(json.dumps(database), encoding="utf-8")
        server.player_sessions.clear()
        self.httpd = server.ReusableServer(("127.0.0.1", 0), server.CustomHandler)
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        server.DB_FILE = self.old_db_file
        server.SECRETS_FILE = self.old_secrets_file
        self.temp_dir.cleanup()

    def post(self, path, payload, expected=200):
        request = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, expected)
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, expected)
            return json.loads(error.read())

    def test_launch_receiver_spin_once_and_admin_completion(self):
        attacker_login = self.post("/api/player/login", {"teamId": "a", "password": "a-pass"})
        receiver_login = self.post("/api/player/login", {"teamId": "b", "password": "b-pass"})
        launched = self.post("/api/player/launch-shell", {"targetId": "b", "sessionToken": attacker_login["sessionToken"]})
        self.assertEqual(launched["attack"]["status"], "PENDING_SPIN")
        self.assertNotIn("penalty", launched)
        receiver_state = self.post("/api/player/state", {"sessionToken": receiver_login["sessionToken"]})
        self.assertEqual(len(receiver_state["duo"]["pendingShellAttacks"]), 1)

        spun = self.post("/api/player/spin-shell", {"attackId": launched["attack"]["id"], "sessionToken": receiver_login["sessionToken"]})
        self.assertEqual(spun["penalty"]["id"], "no_flash_one")
        instance = spun["duo"]["activeDebuffs"][0]
        self.assertEqual(instance["status"], "ACTIVE")
        self.post("/api/player/spin-shell", {"attackId": launched["attack"]["id"], "sessionToken": receiver_login["sessionToken"]}, expected=409)

        corrected = self.post("/api/admin/resolve-penalty", {
            "authPin": "9999", "penaltyInstanceId": instance["id"], "action": "COMPLETE", "note": "Prueba administrativa"
        })
        completed = next(d for d in corrected["duos"] if d["id"] == "b")["activeDebuffs"][0]
        self.assertEqual(completed["status"], "COMPLETED")
        self.assertEqual(completed["manualResolution"]["by"], "ADMIN")

    def test_credentials_are_not_returned_by_admin_login(self):
        response = self.post("/api/admin/login", {"pin": "9999"})
        self.assertNotIn("adminPinHash", response["config"])
        self.assertNotIn("passwordHash", response["duos"][0])


if __name__ == "__main__":
    unittest.main()
