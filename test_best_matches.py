"""Best individual games must be selected independently from combined results."""
import unittest

import server


class BestMatchesTests(unittest.TestCase):
    def test_independent_games_and_no_deaths(self):
        duo = {"history": [
            {"matchId": "pair", "player1Stats": {"kills": 2, "deaths": 2, "assists": 2},
             "player2Stats": {"kills": 8, "deaths": 1, "assists": 2}},
            {"matchId": "alone", "date": "22/10/2026", "player1Stats": {
                "kills": 12, "deaths": 0, "assists": 5, "championName": "Ahri", "position": "MIDDLE", "win": True}},
            {"matchId": "test", "isTest": True, "player2Stats": {"kills": 999}},
        ]}
        insights = server.calculate_player_insights(duo)
        self.assertEqual(insights["player1"]["bestMatch"]["matchId"], "alone")
        self.assertEqual(insights["player1"]["bestMatch"]["kda"], 17)
        self.assertEqual(insights["player1"]["bestMatch"]["result"], "WIN")
        self.assertEqual(insights["player2"]["bestMatch"]["matchId"], "pair")
        self.assertEqual(server.calculate_duo_best_match(duo)["matchId"], "pair")

    def test_ties_legacy_data_and_missing_player(self):
        duo = {"history": [
            {"matchId": "legacy", "championP1": "Ahri", "kda1": "10/2/0", "result": "LOSS"},
            {"matchId": "fewer", "player1Stats": {"kills": 5, "deaths": 1, "assists": 0}},
        ]}
        insights = server.calculate_player_insights(duo)
        self.assertEqual(insights["player1"]["bestMatch"]["matchId"], "legacy")
        self.assertEqual(insights["player1"]["bestMatch"]["result"], "LOSS")
        self.assertIsNone(insights["player2"]["bestMatch"])
        self.assertIsNone(server.calculate_duo_best_match(duo))


if __name__ == "__main__":
    unittest.main()
