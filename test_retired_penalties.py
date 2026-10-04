"""Retiring boots preserves history and keeps already-launched wheels usable."""
import copy
import unittest

import server
import test_shell_penalties as fixtures


class RetiredPenaltyTests(unittest.TestCase):
    def test_catalog_and_picker_exclude_both_boots_variants(self):
        self.assertFalse(any(server.is_retired_penalty(p) for p in server.PENALTY_CATALOG))
        weights = {"no_flash_one": 7, "basic_boots_15_one": 900, "basic_boots_15_both": 900}
        for _ in range(20):
            self.assertEqual(server.weighted_penalty(weights)["id"], "no_flash_one")

    def test_retirement_preserves_completed_evidence_and_is_idempotent(self):
        pending = [fixtures.penalty("basic_boots_15", scope) for scope in ("ONE", "BOTH")]
        pending.append({"penalty": {"id": "no_boots"}, "resolved": False})
        completed = fixtures.penalty("basic_boots_15")
        completed.update(status="COMPLETED", resolved=True, resolvedByMatchId="REAL_GAME", evidence={"matchId": "REAL_GAME"})
        other = fixtures.penalty("no_flash")
        db = {"duos": [{"activeDebuffs": pending + [completed, other]}]}
        self.assertTrue(server.retire_removed_penalties(db))
        for item in pending:
            self.assertEqual(item["status"], "CANCELLED")
            self.assertFalse(item.get("resolved"))
            self.assertNotIn("resolvedByMatchId", item)
        self.assertEqual(completed["status"], "COMPLETED")
        self.assertEqual(completed["evidence"], {"matchId": "REAL_GAME"})
        self.assertEqual(other["status"], "ACTIVE")
        snapshot = copy.deepcopy(db)
        self.assertFalse(server.retire_removed_penalties(db))
        self.assertEqual(db, snapshot)
        game = fixtures.match({"summonerSpellIds": [14, 12]}, {"summonerSpellIds": [14, 12]})
        game["bootsCompliance"] = {"player1": True, "player2": True}
        self.assertEqual(server.evaluate_active_penalties(db["duos"][0], game), 1)
        self.assertTrue(all(item["status"] == "CANCELLED" for item in pending))

    def test_config_pending_and_reflected_wheels_keep_other_odds(self):
        weights = {"no_flash_one": 7, "return_shell": 3, "basic_boots_15_both": 6}
        historical = {"status": "OPENED", "wheelSnapshot": copy.deepcopy(weights)}
        db = {"config": {"penaltyWeights": weights}, "shellAttacks": [
            {"status": "PENDING_SPIN", "wheelSnapshot": copy.deepcopy(weights)}, historical]}
        server.retire_removed_penalties(db)
        expected = {"no_flash_one": 7, "return_shell": 3}
        self.assertEqual(db["config"]["penaltyWeights"], expected)
        self.assertEqual(db["shellAttacks"][0]["wheelSnapshot"], expected)
        self.assertIn("basic_boots_15_both", historical["wheelSnapshot"])
        attack = server.create_pending_shell(db, {"id": "a", "teamName": "A"}, {"id": "b", "teamName": "B"}, historical["wheelSnapshot"])
        self.assertEqual(attack["wheelSnapshot"], expected)

    def test_old_boots_only_wheel_recovers_but_empty_wheel_stays_invalid(self):
        weights = {key: 0 for key in server.default_penalty_weights()}
        weights["basic_boots_15_one"] = 100
        db = {"config": {"penaltyWeights": copy.deepcopy(weights)}, "shellAttacks": [
            {"status": "PENDING_SPIN", "wheelSnapshot": weights}]}
        server.retire_removed_penalties(db)
        self.assertEqual(db["config"]["penaltyWeights"], server.default_penalty_weights())
        self.assertFalse(server.is_retired_penalty(server.weighted_penalty(db["shellAttacks"][0]["wheelSnapshot"])))
        with self.assertRaises(ValueError):
            server.weighted_penalty(server.without_retired_weights({key: 0 for key in server.default_penalty_weights()}))


class RetiredPenaltyEndpointTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def test_load_persists_retirement_and_admin_cannot_reactivate(self):
        db = server.load_db()
        debuff = fixtures.penalty("basic_boots_15")
        db["duos"][0]["activeDebuffs"] = [debuff]
        server.save_db(db)
        loaded = server.load_db()
        self.assertEqual(loaded["duos"][0]["activeDebuffs"][0]["status"], "CANCELLED")
        for action in ("REOPEN", "COMPLETE"):
            self.post("/api/admin/resolve-penalty", {"authPin": "9999", "penaltyInstanceId": debuff["id"], "action": action}, expected=409)
        self.assertEqual(server.load_db()["duos"][0]["activeDebuffs"][0]["status"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
