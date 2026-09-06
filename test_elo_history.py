import unittest
from elo_history import record_elo

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
