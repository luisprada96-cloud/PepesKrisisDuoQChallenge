import unittest
from elo_history import record_elo, ensure_player_elo_histories, record_player_elo

class EloHistoryTests(unittest.TestCase):
    def test_daily_last_value_and_new_day(self):
        duo={"player1":{"name":"A","tag":"EUW"},"tier":"Gold","lp":20}
        record_elo(duo,1220,1800000000)
        record_elo(duo,1210,1800000010)
        self.assertEqual(len(duo["eloHistory"]),1)
        self.assertEqual(duo["eloHistory"][0]["totalLp"],1210)
        record_elo(duo,9999,1799999999)
        self.assertEqual(duo["eloHistory"][0]["totalLp"],1210)
        record_elo(duo,1240,1800086410)
        self.assertEqual(len(duo["eloHistory"]),2)

    def test_account_change_resets_history(self):
        duo={"player1":{"name":"A"}}
        record_elo(duo,100,1800000000)
        duo["player1"]["name"]="B"
        record_elo(duo,200,1800086400)
        self.assertEqual(len(duo["eloHistory"]),1)
        self.assertEqual(duo["eloHistory"][0]["totalLp"],200)

    def test_legacy_migration_only_belongs_to_first_player(self):
        duo = {"player1": {"name": "A", "tag": "EUW"}, "player2": {"name": "B", "tag": "EUW"}}
        record_elo(duo, 1200, 1800000000)
        self.assertTrue(ensure_player_elo_histories(duo))
        self.assertEqual(duo["player1"]["eloHistory"], duo["eloHistory"])
        self.assertEqual(duo["player2"]["eloHistory"], [])
        self.assertFalse(ensure_player_elo_histories(duo))
        duo["player1"]["eloHistory"][0]["totalLp"] = 1300
        self.assertEqual(duo["eloHistory"][0]["totalLp"], 1200)

    def test_participant_daily_updates_and_account_reset_are_independent(self):
        duo = {"player1": {"name": "A"}, "player2": {"name": "B"}}
        ensure_player_elo_histories(duo)
        for key, lp in (("player1", 1200), ("player2", 2200)):
            duo[key]["rank"] = {"tier": "Gold", "division": "IV", "lp": 0}
            record_player_elo(duo[key], lp, 1800000000)
        p2 = duo["player2"]
        record_player_elo(p2, 2250, 1800000010)
        record_player_elo(p2, 9999, 1799999999)
        self.assertEqual([p["totalLp"] for p in p2["eloHistory"]], [2250])
        record_player_elo(p2, 2300, 1800086410)
        self.assertEqual([p["totalLp"] for p in p2["eloHistory"]], [2250, 2300])
        p2["name"] = "Replacement"
        ensure_player_elo_histories(duo)
        self.assertEqual(p2["eloHistory"], [])
        self.assertEqual(duo["player1"]["eloHistory"][0]["totalLp"], 1200)
