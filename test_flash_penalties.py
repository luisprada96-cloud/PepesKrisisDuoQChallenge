"""Comfort slot is learned once; only later Riot games can prove the opposite slot."""
import copy
import unittest
from unittest.mock import patch

import server
import test_shell_penalties as fixtures
import test_riot_incremental as incremental


def duo_fixture():
    return {"player1": {"name": "A1", "tag": "EUW", "puuid": "p1"},
            "player2": {"name": "A2", "tag": "EUW", "puuid": "p2"}}


def game(mid="FIRST", start=2000, spells1=(4, 14), spells2=(12, 4)):
    return {"matchId": mid, "gameStartTimestamp": start,
            "player1Stats": {"puuid": "p1", "summonerSpellIds": list(spells1)},
            "player2Stats": {"puuid": "p2", "summonerSpellIds": list(spells2)}}


def add_penalty(duo, scope="ONE", selected="player1"):
    pen = next(p for p in server.PENALTY_CATALOG if p["baseId"] == "swap_flash" and p["scope"] == scope)
    with patch.object(server.secrets, "choice", return_value=selected):
        req = server.penalty_requirements(duo, pen, [duo])
    debuff = fixtures.penalty("swap_flash", scope, req)
    duo["activeDebuffs"] = [debuff]
    return debuff


class FlashPenaltyTests(unittest.TestCase):
    def test_weights_migration_totals_100_and_preserves_new_weights(self):
        weights = {key: 0 for key in server.default_penalty_weights()}
        weights.update(autofill_one=30, no_flash_one=55, swap_flash_one=12, swap_flash_both=6)
        db = {"config": {"penaltyWeights": weights}}
        self.assertTrue(server.migrate_flash_penalty_weights(db))
        self.assertEqual(sum(weights.values()), 100)
        self.assertEqual(weights["swap_flash_one"], 12)
        self.assertEqual(weights["swap_flash_both"], 6)
        self.assertEqual(weights["return_shell"], 0)
        saved = copy.deepcopy(db)
        self.assertFalse(server.migrate_flash_penalty_weights(db))
        self.assertEqual(db, saved)

    def test_weights_migration_preserves_valid_admin_configuration(self):
        weights = {key: 0 for key in server.default_penalty_weights()}
        weights.update(no_flash_one=75, swap_flash_one=25)
        db = {"config": {"penaltyWeights": copy.deepcopy(weights)}}
        server.migrate_flash_penalty_weights(db)
        self.assertEqual(db["config"]["penaltyWeights"], weights)

    def test_first_import_fixes_independent_slots_and_survives_restart(self):
        duo = duo_fixture()
        server.record_flash_baselines(duo, game())
        expected = copy.deepcopy(duo)
        server.record_flash_baselines(duo, game("LATER", 3000, (14, 4), (4, 12)))
        server.record_flash_baselines(duo, game("OLDER_IMPORTED_LATER", 1000, (14, 4), (4, 12)))
        self.assertEqual(duo, expected)
        self.assertEqual(duo["player1"]["flashBaseline"]["slot"], 1)
        self.assertEqual(duo["player2"]["flashBaseline"]["slot"], 2)
        self.assertEqual(duo["player1"]["flashBaseline"]["matchId"], "FIRST")

    def test_invalid_or_test_games_do_not_fix_reference(self):
        for spells in ((), (4,), (0, 4), (4, 4), (12, 14)):
            duo = duo_fixture()
            server.record_flash_baselines(duo, game(spells1=spells, spells2=spells))
            self.assertNotIn("flashBaseline", duo["player1"])
            self.assertNotIn("flashBaseline", duo["player2"])
        for change in ({"isTest": True}, {"gameStartTimestamp": 0}, {"matchId": ""}):
            duo = duo_fixture()
            server.record_flash_baselines(duo, {**game(), **change})
            self.assertNotIn("flashBaseline", duo["player1"])
        duo = duo_fixture()
        wrong = game()
        wrong["player1Stats"]["puuid"] = "wrong"
        server.record_flash_baselines(duo, wrong)
        self.assertNotIn("flashBaseline", duo["player1"])

    def test_one_requires_selected_player_and_allows_other_spell_to_change(self):
        for selected in ("player1", "player2"):
            duo = duo_fixture()
            server.record_flash_baselines(duo, game())
            debuff = add_penalty(duo, selected=selected)
            other_only = game("OTHER", 3000, (4, 7) if selected == "player1" else (7, 4), (4, 11) if selected == "player1" else (11, 4))
            self.assertEqual(server.evaluate_active_penalties(duo, other_only), 0)
            swapped = game("SWAPPED", 4000, (7, 4), (4, 11))
            self.assertEqual(server.evaluate_active_penalties(duo, swapped), 1)
            self.assertEqual(debuff["evidence"]["assignedPlayer"], selected)
            self.assertEqual(debuff["resolvedByMatchId"], "SWAPPED")
            self.assertIn(selected, debuff["evidence"]["flashBaselines"])

    def test_both_must_swap_in_same_game_using_their_own_reference(self):
        duo = duo_fixture()
        server.record_flash_baselines(duo, game())
        add_penalty(duo, "BOTH")
        self.assertEqual(server.evaluate_active_penalties(duo, game("P1_ONLY", 3000, (14, 4))), 0)
        self.assertEqual(server.evaluate_active_penalties(duo, game("P2_ONLY", 4000, spells2=(4, 12))), 0)
        self.assertEqual(server.evaluate_active_penalties(duo, game("BOTH", 5000, (11, 4), (4, 14))), 1)

    def test_pending_reference_fills_once_and_first_game_never_completes(self):
        duo = duo_fixture()
        debuff = add_penalty(duo, "BOTH")
        self.assertEqual(server.evaluate_active_penalties(duo, game()), 0)
        server.record_flash_baselines(duo, game())
        self.assertEqual(server.fill_pending_flash_baselines(duo), [debuff])
        req = copy.deepcopy(debuff["requirements"])
        self.assertEqual(server.evaluate_active_penalties(duo, game()), 0)
        # Even a malformed replay with inverted spells cannot credit the source match.
        self.assertEqual(server.evaluate_active_penalties(duo, game("FIRST", 3000, (14, 4), (4, 12))), 0)
        server.record_flash_baselines(duo, game("SECOND", 4000, (14, 4), (4, 12)))
        self.assertEqual(server.fill_pending_flash_baselines(duo), [])
        self.assertEqual(debuff["requirements"], req)
        self.assertEqual(server.evaluate_active_penalties(duo, game("SECOND", 4000, (14, 4), (4, 12))), 1)

    def test_missing_flash_wrong_account_old_game_and_bad_spells_cannot_complete(self):
        duo = duo_fixture()
        server.record_flash_baselines(duo, game())
        add_penalty(duo)
        for spells in ((), (4,), (4, 4), (0, 4), (11, 14), (4, 11)):
            self.assertEqual(server.evaluate_active_penalties(duo, game("BAD", 3000, spells)), 0)
        for start in (0, 1000, 2000):
            self.assertEqual(server.evaluate_active_penalties(duo, game("OLD", start, (14, 4))), 0)
        for scope in ("ONE", "BOTH"):
            add_penalty(duo, scope)
            wrong = game("WRONG", 3000, (14, 4), (4, 12))
            wrong["player1Stats"]["puuid"] = "other-account"
            self.assertEqual(server.evaluate_active_penalties(duo, wrong), 0)

    def test_changed_account_cannot_inherit_or_fill_old_pending_reference(self):
        duo = duo_fixture()
        debuff = add_penalty(duo)
        duo["player1"].update(name="NewAccount", puuid="new")
        new = game()
        new["player1Stats"]["puuid"] = "new"
        server.record_flash_baselines(duo, new)
        self.assertEqual(server.fill_pending_flash_baselines(duo), [])
        self.assertEqual(debuff["requirements"]["flashBaselines"], {})


class FlashSyncTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown
    prepare = incremental.IncrementalSyncTests.prepare
    responses = incremental.IncrementalSyncTests.responses
    post = fixtures.ShellEndpointTests.post

    def test_admin_account_change_clears_only_changed_players_reference(self):
        self.prepare()
        db = server.load_db()
        duo = db["duos"][0]
        server.record_flash_baselines(duo, game())
        other_reference = copy.deepcopy(duo["player2"]["flashBaseline"])
        server.save_db(db)
        self.post("/api/duos", {"authPin": "9999", "duo": {"id": duo["id"], "player1": {"name": "NewAccount", "tag": "EUW"}}})
        saved = server.load_db()["duos"][0]
        self.assertNotIn("flashBaseline", saved["player1"])
        self.assertNotIn("puuid", saved["player1"])
        self.assertEqual(saved["player2"]["flashBaseline"], other_reference)

    def test_sync_learns_slots_updates_attack_and_event_then_completes(self):
        self.prepare()
        db = server.load_db()
        debuff = add_penalty(db["duos"][0], "BOTH")
        debuff["sourceShellId"] = "source"
        db["shellAttacks"] = [{"id": "source", "status": "SPUN", "requirements": copy.deepcopy(debuff["requirements"])}]
        db["events"] = [{"type": "SHELL_SPUN", "shellAttackId": "source", "requirements": copy.deepcopy(debuff["requirements"])}]
        server.save_db(db)
        calls = []
        def run(ids, swapped=False):
            normal = self.responses(ids, calls)
            def reply(request, **kwargs):
                if "/matches/FIRST" in request.full_url or "/matches/SECOND" in request.full_url:
                    import io, json
                    payload = incremental.detail()
                    info = payload["info"]
                    is_second = request.full_url.endswith("SECOND")
                    info["gameStartTimestamp"] += 200000 if is_second else 0
                    info["gameEndTimestamp"] += 200000 if is_second else 0
                    for i, p in enumerate(info["participants"]):
                        spells = (14, 4) if i == 0 else (4, 12)
                        if swapped and is_second:
                            spells = spells[::-1]
                        p["summoner1Id"], p["summoner2Id"] = spells
                    return io.BytesIO(json.dumps(payload).encode())
                return normal(request, **kwargs)
            with patch.object(server, "get_riot_api_key", return_value="fake"), patch.object(server, "riot_open", side_effect=reply), patch.object(server.time, "sleep"):
                self.assertTrue(server.sync_riot_data()["success"])
        run(["FIRST"])
        saved = server.load_db()
        penalty = saved["duos"][0]["activeDebuffs"][0]
        self.assertEqual(penalty["status"], "ACTIVE")
        refs = copy.deepcopy(penalty["requirements"])
        self.assertEqual(saved["shellAttacks"][0]["requirements"], refs)
        self.assertEqual(saved["events"][0]["requirements"], refs)
        self.assertEqual(saved["duos"][0]["player1"]["flashBaseline"]["matchId"], "FIRST")
        run(["SECOND", "FIRST"], swapped=True)
        penalty = server.load_db()["duos"][0]["activeDebuffs"][0]
        self.assertEqual(penalty["status"], "COMPLETED")
        self.assertEqual(penalty["resolvedByMatchId"], "SECOND")
        self.assertEqual(penalty["requirements"], refs)
        self.assertFalse(any(url.endswith("/timeline") for url in calls))


if __name__ == "__main__":
    unittest.main()
