import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server
from trophies import build_trophies


def duo(id="a", role="TOP", tier="Gold", lp=10):
    return {"id":id,"teamName":id,"tier":tier,"division":"IV","lp":lp,"player1":{"name":id,"mainRole":role},"history":[]}


def match(role="TOP", kills=10, deaths=2, assists=0, **extra):
    return {"player1Stats":{"position":role,"kills":kills,"deaths":deaths,"assists":assists},**extra}


class TrophyTests(unittest.TestCase):
    def test_only_main_role_matches_count(self):
        a=duo()
        a["history"]=[match(),match("MIDDLE",100),match("UNKNOWN",100),match(kills=100,isTest=True)]
        result=build_trophies([a],None)
        self.assertEqual(len(result["cards"]),7)
        top=result["cards"][1]["entries"]
        self.assertEqual((top[0]["games"],top[0]["kda"]),(1,5))
        self.assertEqual(result["cards"][3]["entries"],[])

    def test_accumulated_kda_zero_deaths_and_tie(self):
        a,b=duo("a"),duo("b")
        a["history"]=[match(kills=10,deaths=0),match(kills=0,deaths=10)]
        b["history"]=[match(kills=1,deaths=1),match(kills=1,deaths=1)]
        entries=build_trophies([a,b],None)["cards"][1]["entries"]
        self.assertEqual(entries[0]["kda"],1)
        self.assertTrue(all(e["tied"] for e in entries))
        a["history"]=[match(kills=10,deaths=0)]
        self.assertEqual(build_trophies([a],None)["cards"][1]["entries"][0]["kda"],10)

    def test_rank_ignores_net_lp_and_empty_role_has_no_winner(self):
        a,b=duo("a",tier="Silver"),duo("b",tier="Gold")
        a["netLp"]=99999
        result=build_trophies([a,b],None)
        self.assertEqual(result["cards"][0]["entries"][0]["id"],"b")
        self.assertEqual(result["cards"][-1]["entries"][0]["id"],"a")
        self.assertEqual(result["cards"][1]["entries"],[])

    def test_second_player_and_main_role_eligibility(self):
        a=duo()
        a["player2"]={"name":"support","mainRole":"UTILITY"}
        a["history"]=[{"player2Stats":{"position":"UTILITY","kills":0,"assists":20,"deaths":2}}]
        cards=build_trophies([a],None)["cards"]
        self.assertEqual(cards[5]["entries"][0]["kda"],10)
        self.assertEqual(cards[1]["entries"],[])

    def test_freezes_at_deadline_and_survives_data_changes(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server,"DB_FILE",str(Path(directory)/"db.json")), patch.object(server,"migrate_credentials",return_value=False):
            server.save_db({"config":{"endDate":"2030-01-01T00:00:00+00:00"},"duos":[duo()]})
            with patch.object(server.time,"time",return_value=1):
                self.assertEqual(server.public_trophies()["status"],"provisional")
                self.assertNotIn("awardedTrophies",server.load_db())
            with patch.object(server.time,"time",return_value=2000000000):
                frozen=server.public_trophies()
                self.assertEqual(frozen["status"],"awarded")
                db=server.load_db()
                db["duos"].append(duo("new",tier="Challenger"))
                server.save_db(db)
                self.assertEqual(server.public_trophies(),frozen)

    def test_invalid_deadline_does_not_award(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server,"DB_FILE",str(Path(directory)/"db.json")), patch.object(server,"migrate_credentials",return_value=False):
            server.save_db({"config":{"endDate":""},"duos":[]})
            self.assertEqual(server.public_trophies()["status"],"provisional")
