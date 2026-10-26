import copy
import json
import unittest
from unittest.mock import patch

import server
import test_riot_incremental as incremental
import test_shell_penalties as fixtures
from match_details import needs_match_details, update_match_details_backfill


def rich_info():
    info = incremental.detail()["info"]
    info.update(gameDuration=1884, gameVersion="16.19.123.456", queueId=420)
    info["participants"][0].update(
        riotIdGameName="A1", riotIdTagline="EUW", champLevel=17, teamId=100,
        teamPosition="MIDDLE", kills=8, deaths=3, assists=11,
        totalMinionsKilled=230, neutralMinionsKilled=7,
        goldEarned=14860, visionScore=19,
        **{f"item{i}": item for i, item in enumerate([6655, 3020, 3089, 4645, 3135, 0, 3363])})
    info["participants"][1].update(
        riotIdGameName="A2", riotIdTagline="EUW", champLevel=16, teamId=100,
        teamPosition="UTILITY", kills=3, deaths=5, assists=16,
        totalMinionsKilled=38, neutralMinionsKilled=0,
        goldEarned=10120, visionScore=63,
        **{f"item{i}": item for i, item in enumerate([3116, 3151, 3009, 3135, 3157, 0, 3364])})
    info["participants"].extend([
        {"puuid":"ally", "teamId":100, "kills":16},
        {"puuid":"enemy", "teamId":200, "kills":30},
    ])
    return info


class MatchDetailsTests(unittest.TestCase):
    def test_locke_and_vex_keep_their_riot_names_and_ids(self):
        for actual in ('Locke','Vex'):
            match={'matchId':'ambiguous','matchDetailsVersion':1,'player1Stats':{'championName':'Vex'}}
            self.assertFalse(needs_match_details(match))
            info=rich_info()
            info['participants'][0].update(championName=actual,championId=9001)
            server.enrich_match_record(match,info,'p1','p2')
            self.assertEqual(match['player1Stats']['championName'],actual)
            self.assertEqual(match['championP1'],actual)
            self.assertEqual(match['player1Stats']['championId'],9001)
            self.assertFalse(needs_match_details(match))

    def test_keeps_both_players_and_only_their_own_team_totals(self):
        info = rich_info()
        before = copy.deepcopy(info)
        match = {}
        server.enrich_match_record(match, info, "p1", "p2")
        self.assertEqual(info, before)
        p1, p2 = match["player1Stats"], match["player2Stats"]
        self.assertEqual(p1["teamKills"], 27)
        self.assertEqual(p2["teamKills"], 27)
        self.assertEqual(p1["cs"], 237)
        self.assertEqual(p2["cs"], 38)
        self.assertEqual(p1["goldEarned"], 14860)
        self.assertEqual(p2["visionScore"], 63)
        self.assertEqual(p1["champLevel"], 17)
        self.assertEqual(p1["riotIdGameName"], "A1")
        self.assertEqual(p1["itemIds"], [6655,3020,3089,4645,3135,0,3363])
        self.assertEqual(match["durationSeconds"], 1884)
        self.assertEqual(match["gameVersion"], "16.19.123.456")
        self.assertEqual(match["duration"], "31m 24s")
        self.assertEqual(match["matchDetailsVersion"], 1)
        self.assertNotIn("participants", match)

    def test_opposing_players_have_separate_team_kills(self):
        info = rich_info()
        info["participants"][1]["teamId"] = 200
        match = {}
        server.enrich_match_record(match, info, "p1", "p2")
        self.assertEqual(match["player1Stats"]["teamKills"], 24)
        self.assertEqual(match["player2Stats"]["teamKills"], 33)

    def test_absent_fields_are_unknown_and_real_zero_is_preserved(self):
        match = {}
        info = {"participants":[{"puuid":"p1", "kills":0,"deaths":0,"assists":0,
                                  "teamId":100,"goldEarned":0,"visionScore":0,"item0":0}]}
        server.enrich_match_record(match, info, "p1", "p2")
        p = match["player1Stats"]
        self.assertEqual(p["goldEarned"], 0)
        self.assertEqual(p["visionScore"], 0)
        self.assertEqual(p["teamKills"], 0)
        self.assertIsNone(p["cs"])
        self.assertIsNone(p["champLevel"])
        self.assertEqual(p["itemIds"], [0,None,None,None,None,None,None])
        self.assertIsNone(match["player2Stats"])
        self.assertTrue(match["participantsChecked"]["player2"])
        self.assertIsNone(match["durationSeconds"])

    def test_backfill_excludes_test_and_unkeyed_records(self):
        duo = {"history":[{"matchId":"old","statsVersion":2},
                          {"matchId":"new","matchDetailsVersion":1},
                          {"matchId":"fake","isTest":True},{}]}
        self.assertEqual(update_match_details_backfill(duo), {"remaining":1,"complete":False})
        self.assertTrue(needs_match_details(duo["history"][0]))


class MatchDetailsSyncTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown
    prepare = incremental.IncrementalSyncTests.prepare
    responses = incremental.IncrementalSyncTests.responses
    sync = incremental.IncrementalSyncTests.sync

    def test_visual_backfill_runs_once_per_old_match_with_existing_batch_limit(self):
        ids = [f"EUW1_{i}" for i in range(3)]
        old = [incremental.game(mid) for mid in ids]
        for match in old:
            match.pop("matchDetailsVersion")
            match.update(processedForShell=True, shellRewardIds=["streak"],
                         shellRewardsEvaluated=["streak"], legacyShellRewards=True)
        self.prepare(old)
        db = server.load_db()
        db["duos"][0]["blueShells"] = 4
        completed = fixtures.penalty("no_flash")
        completed.update(status="COMPLETED", resolved=True, resolvedByMatchId="EUW1_EXISTING")
        db["duos"][0]["activeDebuffs"] = [completed]
        server.save_db(db)
        with patch.object(server,"RIOT_MATCH_DETAIL_BATCH_PER_DUO",1):
            for remaining in [2,1,0]:
                calls=[]
                self.assertTrue(self.sync(ids,calls)["success"])
                self.assertEqual(sum('/matches/EUW1_' in url for url in calls),1)
                duo = server.load_db()["duos"][0]
                self.assertEqual(duo["matchDetailsBackfill"]["remaining"], remaining)
                self.assertEqual(duo["blueShells"],4)
                self.assertEqual(duo["activeDebuffs"][0]["resolvedByMatchId"],"EUW1_EXISTING")
                self.assertTrue(all(m["shellRewardIds"]==["streak"] for m in duo["history"]))
        calls=[]
        self.sync(ids,calls)
        self.assertFalse(any('/matches/EUW1_' in url for url in calls))

    def test_details_survive_save_reload_and_history_endpoint(self):
        self.prepare()
        calls=[]
        normal = self.responses(["EUW1_RICH"],calls)
        def response(request, **kwargs):
            if request.full_url.endswith('/EUW1_RICH'):
                import io
                calls.append(request.full_url)
                return io.BytesIO(json.dumps({"info":rich_info()}).encode())
            return normal(request,**kwargs)
        with patch.object(server,'get_riot_api_key',return_value='fake'), patch.object(server,'riot_open',side_effect=response), patch.object(server.time,'sleep'):
            self.assertTrue(server.sync_riot_data()["success"])
        import urllib.request
        with urllib.request.urlopen(self.base+'/api/duos/a/history?offset=0&limit=30') as result:
            match = json.load(result)["matches"][0]
        self.assertEqual(match["player1Stats"]["teamKills"],27)
        self.assertEqual(match["player2Stats"]["itemIds"][-1],3364)
        self.assertEqual(match["durationSeconds"],1884)

    def test_failed_details_stay_pending_and_preserve_previous_stats(self):
        old=incremental.game('EUW1_RETRY'); old.pop('matchDetailsVersion')
        self.prepare([old])
        self.assertFalse(self.sync(['EUW1_RETRY'],[],fail_once={'EUW1_RETRY'})['success'])
        saved=server.load_db()['duos'][0]
        self.assertEqual(saved['history'][0]['player1Stats'],old['player1Stats'])
        self.assertEqual(saved['matchDetailsBackfill']['remaining'],1)
        self.assertTrue(self.sync(['EUW1_RETRY'],[])['success'])
        self.assertEqual(server.load_db()['duos'][0]['matchDetailsBackfill']['remaining'],0)

    def test_unidentified_second_account_is_retried_when_it_recovers(self):
        import urllib.error
        self.prepare()
        db = server.load_db()
        db['duos'][0]['player2'].pop('puuid', None)
        server.save_db(db)
        normal = self.responses(['EUW1_ACCOUNT'],[])
        def fail_second_account(request, **kwargs):
            if '/accounts/' in request.full_url and '/A2/' in request.full_url:
                raise urllib.error.URLError('Account unavailable')
            return normal(request,**kwargs)
        with patch.object(server,'get_riot_api_key',return_value='fake'), patch.object(server,'riot_open',side_effect=fail_second_account), patch.object(server.time,'sleep'):
            self.assertFalse(server.sync_riot_data()['success'])
        saved=server.load_db()['duos'][0]
        self.assertEqual(saved['history'], [], 'Unknown partner identity must not count a solo game.')
        self.assertIn('EUW1_ACCOUNT', saved['riotMatchDiscovery']['pendingMatchIds'])
        self.assertNotIn('EUW1_ACCOUNT', saved.get('excludedRiotMatches', {}))
        calls=[]
        self.assertTrue(self.sync(['EUW1_ACCOUNT'],calls)['success'])
        self.assertEqual(sum(url.endswith('/EUW1_ACCOUNT') for url in calls),1)
        match=server.load_db()['duos'][0]['history'][0]
        self.assertEqual(match['player2Stats']['championName'],'Lux')
        self.assertFalse(needs_match_details(match))


if __name__ == '__main__':
    unittest.main()
