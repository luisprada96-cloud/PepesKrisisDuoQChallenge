"""Favorite references become available as Riot history arrives, then stay fixed."""
import copy
import io
import json
import unittest
from unittest.mock import patch

import server
import test_shell_penalties as fixtures


def penalty(scope="ONE", assigned=None, favorites=None):
    req = {"favoriteChampions": favorites or {"player1": [], "player2": []}}
    if assigned:
        req.update(assignmentVersion=2, assignedPlayer=assigned,
                   assignedAccount={"name": "A2" if assigned == "player2" else "A1", "tag": "EUW", "puuid": "p2" if assigned == "player2" else "p1"})
    return fixtures.penalty("no_main_champion", scope, requirements=req)


def game(mid="FIRST", p1="Ahri", p2="Lux", start=1800000000000, **extra):
    stats = lambda name, i: {"championName": name, "puuid": f"p{i}", "participantId": i}
    return {"matchId": mid, "statsVersion": 2, "gameStartTimestamp": start,
            "gameEndTimestamp": start + 100000, "player1Stats": stats(p1, 1),
            "player2Stats": stats(p2, 2), **extra}


class FavoriteReferenceTests(unittest.TestCase):
    def test_no_history_tests_and_unknown_champions_keep_reference_pending(self):
        d = {"activeDebuffs": [penalty(assigned="player2")], "history": [game(isTest=True), game(p1="Unknown", p2="Unknown")]}
        self.assertEqual(server.fill_pending_penalty_favorites(d), [])
        self.assertEqual(d["activeDebuffs"][0]["requirements"]["favoriteChampions"]["player2"], [])
        d["history"].append(game("REAL"))
        self.assertEqual(len(server.fill_pending_penalty_favorites(d)), 1)
        req = d["activeDebuffs"][0]["requirements"]
        self.assertEqual(req["favoriteChampions"], {"player1": [], "player2": ["Lux"]})
        self.assertEqual(req["assignedPlayer"], "player2")

    def test_counted_favorites_include_ties(self):
        d = {"activeDebuffs": [penalty("BOTH")], "history": [game(p1="Ahri"), game("SECOND", p1="Ashe")]}
        server.fill_pending_penalty_favorites(d)
        self.assertEqual(d["activeDebuffs"][0]["requirements"]["favoriteChampions"], {"player1": ["Ahri", "Ashe"], "player2": ["Lux"]})

    def test_both_references_fill_independently_without_moving_existing_one(self):
        d = {"activeDebuffs": [penalty("BOTH")], "history": [game(player2Stats=None)]}
        server.fill_pending_penalty_favorites(d)
        req = d["activeDebuffs"][0]["requirements"]
        self.assertEqual(req["favoriteChampions"], {"player1": ["Ahri"], "player2": []})
        d["history"].extend([game("SECOND", p1="Ashe"), game("THIRD", p1="Ashe")])
        server.fill_pending_penalty_favorites(d)
        self.assertEqual(req["favoriteChampions"], {"player1": ["Ahri"], "player2": ["Lux"]})
        self.assertEqual(server.fill_pending_penalty_favorites(d), [])

    def test_completed_penalties_and_other_types_are_untouched(self):
        completed = penalty()
        completed.update(status="COMPLETED", resolved=True)
        other = fixtures.penalty("no_flash")
        d = {"activeDebuffs": [completed, other], "history": [game()]}
        before = copy.deepcopy(d)
        self.assertEqual(server.fill_pending_penalty_favorites(d), [])
        self.assertEqual(d, before)

    def test_existing_favorite_and_recipient_are_never_redrawn(self):
        p = penalty(assigned="player2", favorites={"player1": [], "player2": ["Ahri"]})
        d = {"activeDebuffs": [p], "history": [game()]}
        before = copy.deepcopy(p)
        with patch.object(server.secrets, "choice", side_effect=AssertionError("No redraw")):
            self.assertEqual(server.fill_pending_penalty_favorites(d), [])
        self.assertEqual(p, before)

    def test_legacy_any_player_rule_stays_unassigned(self):
        p = penalty()
        d = {"activeDebuffs": [p], "history": [game()]}
        server.fill_pending_penalty_favorites(d)
        self.assertNotIn("assignedPlayer", p["requirements"])
        good = game("GOOD", p1="Ashe", p2="Lux")
        self.assertEqual(server.evaluate_active_penalties(d, good), 1)


class FavoriteImportTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown

    def prepare(self, scope="ONE", legacy=False):
        db = server.load_db()
        d = db["duos"][0]
        db["duos"] = [d]
        d.update(tier="Iron", division="IV", lp=0, wins=0, losses=0)
        for i, key in enumerate(("player1", "player2"), 1):
            d[key].update(puuid=f"p{i}", tag="EUW", avatar="custom.png")
        p = penalty(scope, assigned="player2" if scope == "ONE" and not legacy else None)
        p.update(sourceShellId="source", id="favorite-penalty")
        d["activeDebuffs"] = [p]
        db["shellAttacks"] = [{"id": "source", "requirements": copy.deepcopy(p["requirements"])}]
        db["events"] = [{"type": "SHELL_SPUN", "shellAttackId": "source", "requirements": copy.deepcopy(p["requirements"])}]
        server.save_db(db)

    def sync(self, matches):
        def reply(request, **kwargs):
            url = request.full_url
            if "/accounts/" in url:
                payload = {"puuid": "p1" if "A1" in url else "p2"}
            elif "/entries/" in url:
                payload = []
            elif "/ids?" in url:
                payload = [m["matchId"] for m in reversed(matches)]
            else:
                m = next(m for m in matches if url.endswith("/" + m["matchId"]))
                participants = [{**m[key + "Stats"], "summoner1Id": 14, "summoner2Id": 12} for key in ("player1", "player2")]
                payload = {"info": {"participants": participants, "gameStartTimestamp": m["gameStartTimestamp"], "gameEndTimestamp": m["gameEndTimestamp"], "gameDuration": 1200}}
            return io.BytesIO(json.dumps(payload).encode())
        with patch.object(server, "get_riot_api_key", return_value="fake"), patch.object(server, "riot_open", side_effect=reply), patch.object(server.time, "sleep"):
            self.assertTrue(server.sync_riot_data()["success"])
        return server.load_db()

    def test_empty_reference_is_saved_then_next_different_champion_completes(self):
        self.prepare()
        first = game()
        db = self.sync([first])
        p = db["duos"][0]["activeDebuffs"][0]
        self.assertEqual(p["status"], "ACTIVE")
        self.assertEqual(p["requirements"]["favoriteChampions"]["player2"], ["Lux"])
        self.assertEqual(db["shellAttacks"][0]["requirements"], p["requirements"])
        self.assertEqual(db["events"][0]["requirements"], p["requirements"])
        # Reload/migrate persisted data as after a restart, with no new recipient draw.
        with patch.object(server.secrets, "choice", side_effect=AssertionError("No redraw")):
            server.migrate_legacy_penalties(db)
        server.save_db(db)
        good = game("GOOD", p2="Ashe", start=1800000200000)
        db = self.sync([first, good])
        p = db["duos"][0]["activeDebuffs"][0]
        self.assertEqual(p["status"], "COMPLETED")
        self.assertEqual(p["resolvedByMatchId"], "GOOD")
        self.assertEqual(p["requirements"]["favoriteChampions"]["player2"], ["Lux"])
        self.assertEqual(p["requirements"]["assignedPlayer"], "player2")

    def test_both_requires_both_to_avoid_their_fixed_favorites(self):
        self.prepare("BOTH")
        first = game()
        self.sync([first])
        one = game("ONE", p1="Ashe", start=1800000200000)
        db = self.sync([first, one])
        self.assertEqual(db["duos"][0]["activeDebuffs"][0]["status"], "ACTIVE")
        both = game("BOTH", p1="Ashe", p2="Garen", start=1800000400000)
        db = self.sync([first, one, both])
        p = db["duos"][0]["activeDebuffs"][0]
        self.assertEqual(p["status"], "COMPLETED")
        self.assertEqual(p["resolvedByMatchId"], "BOTH")
        self.assertEqual(p["requirements"]["favoriteChampions"], {"player1": ["Ahri"], "player2": ["Lux"]})

    def test_old_blocked_reference_recovers_from_existing_history_without_reassignment(self):
        self.prepare(legacy=True)
        db = server.load_db()
        d = db["duos"][0]
        # Keep the historical reference before assignment, within the tournament window.
        reference_start = server.riot_match_policy.MIN_START_TIMESTAMP * 1000 + 100
        d["history"] = [game(f"OLD{i}", start=reference_start) for i in range(3)]
        d["activeDebuffs"][0]["assignedAtEpochMs"] = reference_start + 1000
        server.save_db(db)
        original = server.load_db()
        scanned = copy.deepcopy(original)
        scanned["duos"][0]["history"].append(game("GOOD", p1="Ashe"))
        with patch.object(server.secrets, "choice", side_effect=AssertionError("No redraw")):
            server.merge_riot_result(original, scanned)
        p = server.load_db()["duos"][0]["activeDebuffs"][0]
        self.assertEqual(p["status"], "COMPLETED")
        self.assertEqual(p["resolvedByMatchId"], "GOOD")
        self.assertNotIn("assignedPlayer", p["requirements"])


if __name__ == "__main__":
    unittest.main()
