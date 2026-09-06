import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server


def game(i=1, result="LOSS", **extra):
    return {"matchId": f"EUW1_{i}", "gameEndTimestamp": i * 1000, "result": result, **extra}


class RewardTests(unittest.TestCase):
    def reward(self, **extra):
        duo = {"history": [game(**extra)], "blueShells": 0}
        server.update_duo_shells(duo)
        return duo

    def test_thresholds_and_individual_stats(self):
        for field, threshold in (("kills", 20), ("assists", 30)):
            for player in ("player1Stats", "player2Stats"):
                with self.subTest(field=field, player=player):
                    self.assertEqual(self.reward(**{player: {field: threshold-1, "deaths": 1}})["blueShells"], 0)
                    self.assertEqual(self.reward(**{player: {field: threshold, "deaths": 1}})["blueShells"], 1)
            self.assertEqual(self.reward(player1Stats={field: threshold//2}, player2Stats={field: threshold//2})["blueShells"], 0)
        duo = self.reward(player1Stats={"assists": 30}, player2Stats={"assists": 30})
        self.assertEqual(duo["blueShells"], 1)

    def test_perfect_requires_zero_deaths_and_strictly_above_twenty(self):
        for kills, assists, deaths, expected in [(10,10,0,0),(10,11,0,1),(10,11,1,0)]:
            self.assertEqual(self.reward(player1Stats={"kills":kills,"assists":assists,"deaths":deaths})["blueShells"], expected)
        self.assertEqual(self.reward(player1Stats={"kills":10,"assists":11})["blueShells"], 0)

    def test_streak_and_other_rewards_share_cap_and_are_idempotent(self):
        duo = {"history": [game(1,"WIN"),game(2,"WIN"),game(3,"WIN",pentaKill=True,player1Stats={"kills":20,"assists":30,"deaths":0})]}
        server.update_duo_shells(duo)
        self.assertEqual(duo["blueShells"], 2)
        self.assertEqual(duo["history"][0]["shellRewardIds"], ["streak","penta"])
        snapshot = copy.deepcopy(duo)
        server.update_duo_shells(duo)
        self.assertEqual(duo, snapshot)

    def test_inventory_full_does_not_bank_rewards(self):
        duo = {"blueShells":4,"history":[game(pentaKill=True,player1Stats={"kills":20})]}
        server.update_duo_shells(duo)
        self.assertEqual(duo["blueShells"],5)
        duo["blueShells"] = 0
        server.update_duo_shells(duo)
        self.assertEqual(duo["blueShells"],0)

    def test_backfill_awards_only_new_criteria_up_to_match_cap(self):
        duo = self.reward(pentaKill=True)
        duo["history"][0]["player2Stats"] = {"kills":20,"assists":30,"deaths":0}
        server.update_duo_shells(duo)
        self.assertEqual(duo["blueShells"],2)
        server.update_duo_shells(duo)
        self.assertEqual(duo["blueShells"],2)

    def test_legacy_processed_rewards_and_new_import(self):
        duo = {"blueShells":2,"history":[game(i,"WIN",processedForShell=True,legacyShellRewards=True,processedForPenta=(i==3),pentaKill=(i==3),player1Stats={"kills":20}) for i in range(1,4)]}
        server.update_duo_shells(duo)
        self.assertEqual(duo["blueShells"],2)
        duo["history"].append(game(4,player2Stats={"assists":30}))
        server.update_duo_shells(duo)
        self.assertEqual(duo["blueShells"],3)

    def test_streak_blocks_and_loss_reset(self):
        duo = {"history":[game(i,"LOSS" if i==3 else "WIN") for i in range(1,10)]}
        server.update_duo_shells(duo)
        self.assertEqual(duo["blueShells"],2)
        server.update_duo_shells(duo)
        self.assertEqual(duo["blueShells"],2)

    def test_migration_is_persistent_without_retroactive_new_rewards(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server,"DB_FILE",str(Path(directory)/"db.json")), patch.object(server,"migrate_credentials",return_value=False):
            server.save_db({"config":{},"duos":[{"history":[game(player1Stats={"kills":20})]}]})
            db = server.load_db()
            self.assertTrue(db["duos"][0]["history"][0]["legacyShellRewards"])
            server.update_duo_shells(db["duos"][0])
            self.assertEqual(db["duos"][0].get("blueShells",0),0)
            db["duos"][0]["history"].append(game(2,player1Stats={"kills":20}))
            server.save_db(db)
            db = server.load_db()
            server.update_duo_shells(db["duos"][0])
            self.assertEqual(db["duos"][0]["blueShells"],1)
