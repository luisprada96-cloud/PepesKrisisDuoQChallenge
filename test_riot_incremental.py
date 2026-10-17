"""Incremental Riot discovery preserves gaps and deduplicates per-job requests."""
import copy
import io
import json
import unittest
import urllib.error
import urllib.request
from collections import Counter
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import server
import test_shell_penalties as fixtures

MIN_TIMESTAMP = 1767225600


def discovery(latest, pending=(), account=None):
    return {"version": 1, "account": account or ["a1", "euw"],
            "latestMatchId": latest, "pendingMatchIds": list(pending)}


def game(mid):
    return {"matchId": mid, "statsVersion": 2, "matchDetailsVersion": 1, "gameStartTimestamp": 1800000000000,
            "gameEndTimestamp": 1800000100000, "result": "WIN",
            "player1Stats": {"puuid": "p1", "participantId": 1, "championName": "Ahri", "win": True},
            "player2Stats": {"puuid": "p2", "participantId": 2, "championName": "Lux", "win": True}}


def detail():
    return {"info": {"gameStartTimestamp": 1800000000000, "gameEndTimestamp": 1800001200000,
            "gameDuration": 1200, "participants": [
                {"puuid": "p1", "participantId": 1, "championName": "Ahri", "win": True,
                 "profileIcon": 30, "summoner1Id": 14, "summoner2Id": 12},
                {"puuid": "p2", "participantId": 2, "championName": "Lux", "win": True,
                 "profileIcon": 31, "summoner1Id": 14, "summoner2Id": 12}]}}


class DiscoveryTests(unittest.TestCase):
    def discover(self, duo, ids, puuid="p1"):
        offsets = []
        def fetch(url):
            query = parse_qs(urlparse(url).query)
            self.assertEqual(query["queue"], ["420"])
            self.assertEqual(query["startTime"], [str(MIN_TIMESTAMP)])
            offset = int(query["start"][0])
            offsets.append(offset)
            return ids[offset:offset + 100]
        with patch.object(server.time, "sleep"):
            result = server.discover_riot_matches(duo, puuid, fetch, MIN_TIMESTAMP)
        return result, offsets

    def test_initial_scan_keeps_holes_beyond_a_fully_known_first_page(self):
        ids = [f"EUW1_{i}" for i in range(205)]
        duo = {"player1": {"name": "A1"}, "history": [game(mid) for mid in ids if mid != ids[204]]}
        result, offsets = self.discover(duo, ids)
        self.assertEqual(offsets, [0, 100, 200])
        self.assertEqual(result["pendingMatchIds"], [ids[204]])
        self.assertEqual(result["latestMatchId"], ids[0])

    def test_incremental_scan_crosses_pages_until_previous_boundary(self):
        fresh = [f"EUW1_NEW{i}" for i in range(250)]
        duo = {"player1": {"name": "A1"}, "history": [game("OLD")],
               "riotMatchDiscovery": discovery("OLD")}
        result, offsets = self.discover(duo, fresh + ["OLD"])
        self.assertEqual(offsets, [0, 100, 200])
        self.assertEqual(result["pendingMatchIds"], fresh)
        self.assertEqual(result["latestMatchId"], fresh[0])

    def test_boundary_does_not_discard_old_pending_details_after_restart(self):
        ids = [f"EUW1_{i}" for i in range(250)]
        duo = {"player1": {"name": "A1"}, "history": [game(mid) for mid in ids[:40]],
               "riotMatchDiscovery": discovery(ids[0], ids[40:])}
        restored = json.loads(json.dumps(duo))
        result, offsets = self.discover(restored, ids)
        self.assertEqual(offsets, [0])
        self.assertEqual(set(result["pendingMatchIds"]), set(ids[40:]))

    def test_missing_boundary_falls_back_to_full_scan_and_keeps_pending(self):
        ids = [f"EUW1_{i}" for i in range(101)]
        duo = {"player1": {"name": "A1"}, "history": [],
               "riotMatchDiscovery": discovery("REMOVED", ["FAILED_DETAIL"])}
        result, offsets = self.discover(duo, ids)
        self.assertEqual(offsets, [0, 100])
        self.assertIn("FAILED_DETAIL", result["pendingMatchIds"])
        self.assertEqual(result["latestMatchId"], ids[0])

    def test_empty_api_response_preserves_boundary_and_pending(self):
        duo = {"player1": {"name": "A1"}, "history": [],
               "riotMatchDiscovery": discovery("OLD", ["FAILED_DETAIL"])}
        result, offsets = self.discover(duo, [])
        self.assertEqual(offsets, [0])
        self.assertEqual(result, duo["riotMatchDiscovery"])

    def test_changed_account_rescans_but_puuid_rotation_keeps_boundary(self):
        ids = [f"EUW1_{i}" for i in range(101)]
        duo = {"player1": {"name": "Replacement"}, "history": [],
               "riotMatchDiscovery": discovery(ids[0], ["OLD_ACCOUNT"])}
        result, offsets = self.discover(duo, ids)
        self.assertEqual(offsets, [0, 100])
        self.assertNotIn("OLD_ACCOUNT", result["pendingMatchIds"])
        duo["player1"]["name"] = "A1"
        result, offsets = self.discover(duo, ids, puuid="rotated-puuid")
        self.assertEqual(offsets, [0])
        self.assertIn("OLD_ACCOUNT", result["pendingMatchIds"])

    def test_failed_or_malformed_page_cannot_advance_saved_boundary(self):
        duo = {"player1": {"name": "A1"}, "history": [], "riotMatchDiscovery": discovery("OLD")}
        before = copy.deepcopy(duo)
        for invalid in ({"unexpected": []}, [None], [""]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                server.discover_riot_matches(duo, "p1", lambda url: invalid, MIN_TIMESTAMP)
            self.assertEqual(duo, before)
        def failing(url):
            if "start=0&" in url:
                return [f"NEW{i}" for i in range(100)]
            raise urllib.error.URLError("Page unavailable")
        with patch.object(server.time, "sleep"), self.assertRaises(urllib.error.URLError):
            server.discover_riot_matches(duo, "p1", failing, MIN_TIMESTAMP)
        self.assertEqual(duo, before)

    def test_repeated_full_page_cannot_loop_forever(self):
        duo = {"player1": {"name": "A1"}, "history": []}
        with patch.object(server.time, "sleep"), self.assertRaises(ValueError):
            server.discover_riot_matches(duo, "p1", lambda url: [str(i) for i in range(100)], MIN_TIMESTAMP)


class IncrementalSyncTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown

    def prepare(self, history=(), two_teams=False, avatars=True):
        db = server.load_db()
        duos = db["duos"] if two_teams else db["duos"][:1]
        for duo in duos:
            duo.update(tier="Iron", division="IV", lp=0, wins=0, losses=0)
            for i, key in enumerate(("player1", "player2"), 1):
                duo[key].update(name=f"A{i}", tag="EUW", puuid=f"p{i}")
                if avatars:
                    duo[key]["avatar"] = "custom.png"
            duo["history"] = copy.deepcopy(list(history))
        db["duos"] = duos
        server.save_db(db)

    def responses(self, ids, calls, fail_once=None, lp=10, durations=None):
        def respond(request, **kwargs):
            url = request.full_url
            calls.append(url)
            if "/accounts/" in url:
                payload = {"puuid": "p1" if "A1" in url else "p2"}
            elif "/entries/" in url:
                payload = [{"queueType": "RANKED_SOLO_5x5", "tier": "GOLD", "rank": "IV", "leaguePoints": lp, "wins": 12, "losses": 8}]
            elif "/ids?" in url:
                query = parse_qs(urlparse(url).query)
                offset = int(query.get("start", [0])[0])
                count = int(query["count"][0])
                payload = ids[offset:offset + count]
            elif url.endswith("/timeline"):
                self.fail("Retired boots must never request a timeline")
            else:
                mid = url.rsplit("/", 1)[-1]
                if fail_once is not None and mid in fail_once:
                    fail_once.remove(mid)
                    raise urllib.error.URLError("Temporary match error")
                payload = detail()
                if durations and mid in durations:
                    payload['info']['gameDuration'] = durations[mid]
                    payload['info']['gameEndTimestamp'] = payload['info']['gameStartTimestamp'] + durations[mid] * 1000
            return io.BytesIO(json.dumps(payload).encode())
        return respond

    def sync(self, ids, calls, **kwargs):
        with patch.object(server, "get_riot_api_key", return_value="fake"), patch.object(server, "riot_open", side_effect=self.responses(ids, calls, **kwargs)), patch.object(server.time, "sleep"):
            return server.sync_riot_data()

    def test_short_matches_are_excluded_once_and_ten_minutes_is_allowed(self):
        self.prepare()
        before = server.load_db()['duos'][0]['blueShells']
        calls = []
        durations = {'EUW1_REMAKE':76, 'EUW1_SHORT':599, 'EUW1_VALID':600}
        self.assertTrue(self.sync(list(durations), calls, durations=durations)['success'])
        duo = server.load_db()['duos'][0]
        self.assertEqual([m['matchId'] for m in duo['history']], ['EUW1_VALID'])
        self.assertEqual(set(duo['excludedRiotMatches']), {'EUW1_REMAKE','EUW1_SHORT'})
        self.assertEqual(duo['riotMatchDiscovery']['pendingMatchIds'], [])
        self.assertEqual(duo['blueShells'], before)
        self.assertEqual(duo['playerInsights']['player1']['gamesAnalyzed'], 1)
        calls = []
        self.assertTrue(self.sync(list(durations), calls, durations=durations)['success'])
        self.assertFalse(any(url.endswith('/EUW1_REMAKE') or url.endswith('/EUW1_SHORT') for url in calls))

    def test_exclusion_added_during_scan_prevents_stale_match_reimport(self):
        self.prepare()
        original = server.load_db()
        scanned = copy.deepcopy(original)
        scanned['duos'][0]['history'] = [game('EUW1_REMOVED')]
        current = server.load_db()
        current['duos'][0]['excludedRiotMatches'] = {'EUW1_REMOVED': {'reason':'duration_below_minimum','durationSeconds':76}}
        server.save_db(current)
        server.merge_riot_result(original, scanned)
        duo = server.load_db()['duos'][0]
        self.assertEqual(duo['history'], [])
        self.assertIn('EUW1_REMOVED',duo['excludedRiotMatches'])

    def test_real_api_success_is_persisted_and_exposed_after_job_restart(self):
        self.prepare()
        stamp = "2026-10-04T14:44:00+00:00"
        with patch.object(server, "utc_now", return_value=stamp):
            self.assertTrue(self.sync([], [])["success"])
        self.assertEqual(server.load_db()["lastRiotApiSuccessAt"], stamp)
        with patch.object(server, "sync_jobs", server.SyncJobs()):
            with urllib.request.urlopen(self.base + '/api/sync/status', timeout=3) as response:
                status = json.load(response)
        self.assertEqual(status["riot"]["lastApiSuccessAt"], stamp)
        self.assertNotIn("lastSuccessAt", status["riot"])

    def test_empty_job_does_not_invent_or_advance_api_success(self):
        db = server.load_db()
        db["duos"] = []
        server.save_db(db)
        with patch.object(server, "get_riot_api_key", return_value="fake"), patch.object(server, "riot_open") as request:
            self.assertTrue(server.sync_riot_data()["success"])
            request.assert_not_called()
        self.assertNotIn("lastRiotApiSuccessAt", server.load_db())
        db = server.load_db()
        db["lastRiotApiSuccessAt"] = "2026-10-03T14:44:00+00:00"
        server.save_db(db)
        self.sync([], [])
        self.assertEqual(server.load_db()["lastRiotApiSuccessAt"], db["lastRiotApiSuccessAt"])

    def test_failed_calls_keep_previous_real_api_success(self):
        self.prepare()
        db = server.load_db()
        db["lastRiotApiSuccessAt"] = "2026-10-03T14:44:00+00:00"
        server.save_db(db)
        error = urllib.error.HTTPError('https://riot.invalid', 403, 'Forbidden', {}, None)
        with patch.object(server, "get_riot_api_key", return_value="fake"), patch.object(server, "riot_open", side_effect=error):
            result = server.sync_riot_data()
            self.assertFalse(result["success"])
        self.assertIn("Sincronización fallida", result["error"])
        self.assertIn("HTTP 403:", result["error"])
        self.assertNotIn("riot.invalid", result["error"])
        self.assertEqual(server.load_db()["lastRiotApiSuccessAt"], db["lastRiotApiSuccessAt"])

    def test_partial_sync_still_records_successful_api_responses(self):
        self.prepare()
        stamp = "2026-10-04T14:44:00+00:00"
        with patch.object(server, "utc_now", return_value=stamp):
            result = self.sync(['EUW1_FAILED'], [], fail_once={'EUW1_FAILED'})
        self.assertFalse(result["success"])
        self.assertIn("Sincronización parcial", result["error"])
        self.assertIn("error de conexión: 1", result["error"])
        self.assertEqual(server.load_db()["lastRiotApiSuccessAt"], stamp)

    def test_500_game_history_needs_one_list_request_after_first_scan(self):
        ids = [f"EUW1_{i}" for i in range(500)]
        self.prepare([game(mid) for mid in ids])
        first = []
        self.assertTrue(self.sync(ids, first)["success"])
        self.assertEqual(sum("/ids?" in url for url in first), 6)
        second = []
        self.assertTrue(self.sync(ids, second)["success"])
        self.assertEqual(sum("/ids?" in url for url in second), 1)
        self.assertFalse(any("/matches/EUW1_" in url for url in second))
        third = []
        self.assertTrue(self.sync(["EUW1_NEW"] + ids, third)["success"])
        self.assertEqual(sum("/ids?" in url for url in third), 1)
        self.assertEqual(sum("/matches/EUW1_" in url for url in third), 1)
        duo = server.load_db()["duos"][0]
        self.assertEqual(len(duo["history"]), 501)
        self.assertEqual(duo["riotMatchDiscovery"]["pendingMatchIds"], [])
        self.assertNotIn("riotMatchDiscovery", server.public_duo_summaries()[0])

    def test_old_gaps_and_failed_details_survive_saved_boundary_and_batch_limit(self):
        ids = [f"EUW1_{i}" for i in range(205)]
        missing = {ids[100], ids[150], ids[200]}
        self.prepare([game(mid) for mid in ids if mid not in missing])
        fail_once = {ids[100]}
        page_counts = []
        with patch.object(server, "RIOT_MATCH_DETAIL_BATCH_PER_DUO", 1):
            for run in range(4):
                calls = []
                result = self.sync(ids, calls, fail_once=fail_once)
                self.assertEqual(result["success"], run != 0)
                page_counts.append(sum("/ids?" in url for url in calls))
        self.assertEqual(page_counts, [3, 1, 1, 1])
        duo = server.load_db()["duos"][0]
        self.assertEqual({m["matchId"] for m in duo["history"]}, set(ids))
        self.assertEqual(duo["riotMatchDiscovery"]["pendingMatchIds"], [])
        shells = duo["blueShells"]
        calls = []
        self.sync(ids, calls)
        self.assertFalse(any("/matches/EUW1_" in url for url in calls))
        self.assertEqual(server.load_db()["duos"][0]["blueShells"], shells)

    def test_shared_profiles_and_matches_are_requested_once_per_job(self):
        self.prepare(two_teams=True, avatars=False)
        db = server.load_db()
        for duo in db["duos"]:
            duo["activeDebuffs"] = [fixtures.penalty("no_flash", "BOTH")]
        server.save_db(db)
        calls = []
        self.assertTrue(self.sync(["EUW1_SHARED"], calls)["success"])
        counts = Counter(calls)
        self.assertTrue(all(count == 1 for count in counts.values()))
        self.assertEqual(sum(url.endswith("/EUW1_SHARED") for url in calls), 1)
        self.assertFalse(any(url.endswith("/timeline") for url in calls))
        for duo in server.load_db()["duos"]:
            self.assertEqual(len(duo["history"]), 1)
            self.assertEqual(duo["activeDebuffs"][0]["status"], "COMPLETED")
        next_calls = []
        self.sync(["EUW1_SHARED"], next_calls, lp=20)
        self.assertEqual(sum("/entries/" in url for url in next_calls), 2)
        self.assertEqual(server.load_db()["duos"][0]["player1"]["rank"]["lp"], 20)

    def test_retired_boots_do_not_redownload_complete_matches(self):
        self.prepare([game("EUW1_BOOTS")])
        db = server.load_db()
        db["duos"][0]["activeDebuffs"] = [fixtures.penalty("basic_boots_15", "BOTH")]
        server.save_db(db)
        calls = []
        self.assertTrue(self.sync(["EUW1_BOOTS"], calls)["success"])
        self.assertFalse(any(url.endswith("/timeline") for url in calls))
        self.assertFalse(any(url.endswith("/EUW1_BOOTS") for url in calls))
        self.assertEqual(server.load_db()["duos"][0]["activeDebuffs"][0]["status"], "CANCELLED")

    def test_failed_later_page_does_not_advance_persisted_discovery(self):
        self.prepare([game("ANCHOR")])
        db = server.load_db()
        previous = discovery("ANCHOR")
        db["duos"][0]["riotMatchDiscovery"] = copy.deepcopy(previous)
        server.save_db(db)
        ids = [f"EUW1_NEW{i}" for i in range(100)] + ["ANCHOR"]
        calls = []
        normal = self.responses(ids, calls)
        def fail_later_page(request, **kwargs):
            if "start=100&" in request.full_url:
                raise urllib.error.URLError("Second page unavailable")
            return normal(request, **kwargs)
        with patch.object(server, "get_riot_api_key", return_value="fake"), patch.object(server, "riot_open", side_effect=fail_later_page), patch.object(server.time, "sleep"):
            self.assertFalse(server.sync_riot_data()["success"])
        duo = server.load_db()["duos"][0]
        self.assertEqual(duo["riotMatchDiscovery"], previous)
        self.assertEqual(len(duo["history"]), 1)
        with patch.object(server, "RIOT_MATCH_DETAIL_BATCH_PER_DUO", 2):
            self.assertTrue(self.sync(ids, [])["success"])
        duo = server.load_db()["duos"][0]
        self.assertEqual(duo["riotMatchDiscovery"]["latestMatchId"], ids[0])
        self.assertEqual(len(duo["riotMatchDiscovery"]["pendingMatchIds"]), 98)
        self.assertEqual(len(duo["history"]), 3)

    def test_incremental_boundary_still_enriches_legacy_stats(self):
        old = game("EUW1_OLD")
        old["statsVersion"] = 1
        self.prepare([old])
        db = server.load_db()
        db["duos"][0]["riotMatchDiscovery"] = discovery("EUW1_OLD")
        server.save_db(db)
        calls = []
        self.assertTrue(self.sync(["EUW1_OLD"], calls)["success"])
        self.assertEqual(sum(url.endswith("/EUW1_OLD") for url in calls), 1)
        self.assertEqual(server.load_db()["duos"][0]["history"][0]["statsVersion"], 2)
        calls = []
        self.sync(["EUW1_OLD"], calls)
        self.assertFalse(any(url.endswith("/EUW1_OLD") for url in calls))

    def test_failed_response_is_not_cached_for_another_team(self):
        self.prepare(two_teams=True)
        calls = []
        result = self.sync(["EUW1_SHARED"], calls, fail_once={"EUW1_SHARED"})
        self.assertFalse(result["success"])
        self.assertEqual(sum(url.endswith("/EUW1_SHARED") for url in calls), 2)
        duos = server.load_db()["duos"]
        self.assertEqual(duos[0]["riotMatchDiscovery"]["pendingMatchIds"], ["EUW1_SHARED"])
        self.assertEqual(duos[1]["riotMatchDiscovery"]["pendingMatchIds"], [])
        calls = []
        self.assertTrue(self.sync(["EUW1_SHARED"], calls)["success"])
        self.assertTrue(all(len(d["history"]) == 1 for d in server.load_db()["duos"]))


if __name__ == "__main__":
    unittest.main()
