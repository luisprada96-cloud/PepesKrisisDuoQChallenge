import copy
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import server
import storage
import test_shell_penalties as fixtures
from sync_jobs import SyncJobs


class StorageTests(unittest.TestCase):
    def test_failed_replace_preserves_live_file_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "db.json"
            storage.write_json(path, {"value": 1})
            replace = os.replace
            def fail_live(source, target):
                if Path(target) == path:
                    raise OSError("simulated disk failure")
                replace(source, target)
            with patch("storage.os.replace", side_effect=fail_live):
                with self.assertRaises(storage.StorageError):
                    storage.write_json(path, {"value": 2})
            self.assertEqual(storage.read_json(path), {"value": 1})
            self.assertEqual(storage.read_json(str(path) + ".previous.bak"), {"value": 1})
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_corrupt_file_is_not_replaced_by_empty_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "db.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(storage.StorageError):
                storage.write_json(path, {"duos": []})
            self.assertEqual(path.read_text(), "{broken")

    def test_riot_retry_respects_retry_after(self):
        request = urllib.request.Request('https://example.invalid/test')
        response = io.BytesIO(b'{}')
        error = urllib.error.HTTPError(request.full_url, 429, 'limit', {'Retry-After': '2'}, None)
        with patch.object(server.urllib.request, 'urlopen', side_effect=[error, response]), patch.object(server.time, 'sleep') as sleep:
            self.assertIs(server.riot_open(request), response)
            sleep.assert_called_once_with(2.0)



class PenaltyRegressionTests(unittest.TestCase):
    def test_match_started_before_assignment_and_missing_start_are_ignored(self):
        for start in (None, 900):
            duo = {"activeDebuffs": [fixtures.penalty("no_flash")]}
            game = fixtures.match({"summonerSpellIds": [14, 12]}, {"summonerSpellIds": [14, 12]})
            game["gameStartTimestamp"] = start
            self.assertEqual(server.evaluate_active_penalties(duo, game), 0)

    def test_missing_spells_are_not_proof(self):
        duo = {"activeDebuffs": [fixtures.penalty("no_flash", "BOTH")]}
        game = fixtures.match({"summonerSpellIds": []}, {"summonerSpellIds": [0, 0]})
        self.assertEqual(server.evaluate_active_penalties(duo, game), 0)

class EndpointRegressionTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def get(self, path, expected=200):
        try:
            with urllib.request.urlopen(self.base + path, timeout=3) as response:
                self.assertEqual(response.status, expected)
                return response.read()
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, expected)
            return error.read()

    def test_private_paths_and_traversal_are_not_served(self):
        for path in ("/db.json", "/secrets.json", "/db.json.before-role-recreate.bak", "/server.py", "/.git/config", "/../db.json", "/%64b.json", "/%2e%2e/secrets.json", "/storage.py"):
            with self.subTest(path=path):
                self.get(path, 404)
        self.assertIn(b"<!DOCTYPE html>", self.get("/"))

    def test_manual_operations_require_admin_auth(self):
        with patch.object(server.sync_jobs, "start") as start:
            for endpoint in ("/api/sync", "/api/calculate-shells", "/api/twitch/sync"):
                self.post(endpoint, {}, expected=401)
            start.assert_not_called()

    def test_invalid_json_returns_400_and_server_remains_healthy(self):
        req = urllib.request.Request(self.base + "/api/player/login", data=b"{bad", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(req, timeout=3)
        self.assertEqual(context.exception.code, 400)
        self.get("/api/duos")

    def test_public_reads_do_not_grant_shells_or_expose_credentials(self):
        db = server.load_db()
        db["duos"][0]["history"] = [{"matchId": str(i), "result": "WIN"} for i in range(4)]
        server.save_db(db)
        before = Path(server.DB_FILE).read_bytes()
        summary = json.loads(self.get("/api/duos"))[0]
        self.assertEqual(summary["blueShells"], 1)
        self.assertEqual(summary["historyCount"], 4)
        self.assertNotIn("history", summary)
        self.assertNotIn("passwordHash", summary)
        self.assertEqual(before, Path(server.DB_FILE).read_bytes())
        result = self.post("/api/calculate-shells", {"authPin": "9999"})
        self.assertNotIn("passwordHash", result["duos"][0])
        self.assertEqual(result["newShells"], 1)
        self.assertEqual(result["duos"][0]["blueShells"], 2)

    def test_history_pagination_and_full_event_storage(self):
        db = server.load_db()
        db["duos"][0]["history"] = [{"matchId": f"EUW1_{i}", "gameEndTimestamp": i} for i in range(250)]
        db["events"] = [{"id": str(i)} for i in range(90)]
        server.save_db(db)
        result = json.loads(self.get("/api/duos/a/history?offset=30&limit=30"))
        self.assertEqual(result["total"], 250)
        self.assertEqual(result["matches"][0]["matchId"], "EUW1_219")
        self.assertEqual(len(json.loads(self.get("/api/events?offset=30&limit=30"))), 30)
        login = self.post("/api/player/login", {"teamId": "a", "password": "a-pass"})
        self.post("/api/player/launch-shell", {"sessionToken": login["sessionToken"], "targetId": "b"})
        self.assertEqual(len(server.load_db()["events"]), 91)

    def test_concurrent_launch_cannot_spend_same_shell_twice(self):
        login = self.post("/api/player/login", {"teamId": "a", "password": "a-pass"})
        def launch():
            req = urllib.request.Request(self.base + "/api/player/launch-shell", data=json.dumps({"sessionToken": login["sessionToken"], "targetId": "b"}).encode(), method="POST")
            try:
                with urllib.request.urlopen(req, timeout=3) as response:
                    return response.status
            except urllib.error.HTTPError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(lambda _: launch(), range(2)))
        self.assertEqual(sorted(codes), [200, 400])
        self.assertEqual(len(server.load_db()["shellAttacks"]), 1)

    def test_stale_admin_edit_preserves_inventory_and_history(self):
        stale = server.safe_duo_for_player(server.load_db()["duos"][0])
        db = server.load_db()
        db["duos"][0]["blueShells"] = 3
        db["duos"][0]["history"] = [{"matchId": "new"}]
        server.save_db(db)
        stale["player1"]["mainRole"] = "MIDDLE"
        self.post("/api/duos", {"authPin": "9999", "duo": stale})
        duo = server.load_db()["duos"][0]
        self.assertEqual(duo["blueShells"], 3)
        self.assertEqual(duo["history"], [{"matchId": "new"}])
        self.assertEqual(duo["player1"]["mainRole"], "MIDDLE")

    def test_sync_merge_preserves_attack_and_is_idempotent(self):
        original = server.load_db()
        scanned = copy.deepcopy(original)
        scanned["duos"][0]["history"] = [{"matchId": f"EUW1_{i}", "result": "WIN"} for i in range(4)]
        login = self.post("/api/player/login", {"teamId": "a", "password": "a-pass"})
        self.post("/api/player/launch-shell", {"sessionToken": login["sessionToken"], "targetId": "b"})
        server.merge_riot_result(original, scanned)
        server.merge_riot_result(original, scanned)
        db = server.load_db()
        self.assertEqual(len(db["shellAttacks"]), 1)
        self.assertEqual(db["duos"][0]["blueShells"], 1)
        self.assertEqual(db["duos"][0]["shellsUsed"], 1)
        self.assertEqual(db["duos"][0]["shellsEarnedTotal"], 1)

    def test_returned_shell_creates_pending_attack_even_at_inventory_cap(self):
        db = server.load_db()
        db["duos"][0]["blueShells"] = 5
        db["shellAttacks"] = [{"id": "return", "targetTeamId": "b", "attackerTeamId": "a", "status": "PENDING_SPIN", "wheelSnapshot": {"return_shell": 100}}]
        server.save_db(db)
        login = self.post("/api/player/login", {"teamId": "b", "password": "b-pass"})
        self.post("/api/player/spin-shell", {"sessionToken": login["sessionToken"], "attackId": "return"})
        self.assertEqual(server.load_db()["duos"][0]["blueShells"], 5)
        pending = [attack for attack in server.load_db()["shellAttacks"] if attack["status"] == "PENDING_SPIN"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["targetTeamId"], "a")
        self.assertEqual(pending[0]["returnedFromAttackId"], "return")

    def test_sync_endpoint_queues_without_blocking_and_keeps_last_success(self):
        jobs = SyncJobs()
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def slow():
            entered.set()
            release.wait(3)
            finished.set()
            return {"success": True}
        with patch.object(server, "sync_jobs", jobs), patch.object(server, "sync_riot_data", slow):
            try:
                self.post("/api/sync", {"authPin": "9999"}, expected=202)
                self.assertTrue(entered.wait(1))
                self.get("/api/duos")
                second = self.post("/api/sync", {"authPin": "9999"}, expected=202)
                self.assertTrue(second["alreadyRunning"])
            finally:
                release.set()
        self.assertTrue(finished.wait(1))
        jobs = SyncJobs()
        jobs.states["riot"] = {}
        # Deterministic synchronous status verification with no waiting loop.
        jobs._run("riot", lambda: {"success": True})
        success = jobs.snapshot()["riot"]["lastSuccessAt"]
        jobs._run("riot", lambda: {"success": False, "error": "Riot unavailable"})
        self.assertEqual(jobs.snapshot()["riot"]["lastSuccessAt"], success)

    def test_storage_failure_returns_503_not_success(self):
        with patch.object(server, "save_db", side_effect=storage.StorageError("Unavailable")):
            self.post("/api/calculate-shells", {"authPin": "9999"}, expected=503)

    def test_discovery_pages_beyond_first_hundred_without_truncating_history(self):
        db = server.load_db()
        duo = db["duos"][0]
        db["duos"] = [duo]
        duo.update(tier="Iron", division="IV", lp=0, wins=0, losses=0)
        for key in ("player1", "player2"):
            duo[key]["avatar"] = "custom.png"
        duo["history"] = [{"matchId": f"EUW1_{i}", "statsVersion": 2, "gameStartTimestamp": 1800000000000} for i in range(250)]
        server.save_db(db)
        pages = []
        def response(request, **kwargs):
            url = request.full_url
            if '/accounts/' in url:
                payload = {"puuid": "p1" if 'A1' in url else 'p2'}
            elif '/entries/' in url:
                payload = []
            elif '/ids?' in url:
                offset = int(server.urllib.parse.parse_qs(server.urllib.parse.urlparse(url).query)['start'][0])
                pages.append(offset)
                payload = [f"EUW1_{i}" for i in range(100)] if offset == 0 else ['EUW1_999']
            else:
                payload = {"info": {"participants": [{"puuid": "p1", "championName": "Ahri", "win": True}], "gameStartTimestamp": 1800000000000, "gameEndTimestamp": 1800000100000, "gameDuration": 100}}
            return io.BytesIO(json.dumps(payload).encode())
        with patch.object(server, 'get_riot_api_key', return_value='fake'), patch.object(server.urllib.request, 'urlopen', side_effect=response), patch.object(server.time, 'sleep'):
            server.sync_riot_data()
        self.assertEqual(pages, [0, 100])
        history = server.load_db()['duos'][0]['history']
        self.assertEqual(len(history), 251)
        self.assertIn('EUW1_999', [m['matchId'] for m in history])

    def test_admin_reopen_preserves_audit_and_rejects_previous_evidence(self):
        db = server.load_db()
        game = fixtures.match({'summonerSpellIds': [14, 12]}, {'summonerSpellIds': [14, 12]})
        debuff = fixtures.penalty('no_flash')
        duo = db['duos'][0]
        duo['activeDebuffs'] = [debuff]
        duo['history'] = [game]
        server.evaluate_active_penalties(duo, game)
        server.save_db(db)
        self.post('/api/admin/resolve-penalty', {'authPin': '9999', 'penaltyInstanceId': debuff['id'], 'action': 'REOPEN', 'note': 'Revisión'})
        current = server.load_db()
        self.assertEqual(server.evaluate_active_penalties(current['duos'][0], game), 0)
        self.assertEqual(current['duos'][0]['activeDebuffs'][0]['resolutionHistory'][0]['note'], 'Revisión')
        self.assertEqual(current['events'][0]['penaltyInstanceId'], debuff['id'])


if __name__ == "__main__":
    unittest.main()
