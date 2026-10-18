"""Cumulative curves preserve chronology, account ownership and tournament filters."""
import copy
import json
import unittest
import urllib.request
from unittest.mock import patch

import player_accounts
import riot_match_policy
import server
import stat_progression
import test_shell_penalties as fixtures

START = riot_match_policy.MIN_START_TIMESTAMP * 1000


def stats(uid='main', kills=3, deaths=1, assists=5, **extra):
    return {'puuid': uid, 'kills': kills, 'deaths': deaths, 'assists': assists, **extra}


def game(mid, at=1, p1=None, p2=None, **extra):
    return {'matchId':mid, 'gameStartTimestamp':START+at*2000000, 'gameEndTimestamp':START+at*2000000+1200000,
            'durationSeconds':1200, 'queueId':420, 'participantsChecked':{'player1':True,'player2':True},
            'player1Stats':p1, 'player2Stats':p2, **extra}


def database():
    p1={'name':'Main','displayName':'Markel','tag':'EUW','puuid':'main'}
    player_accounts.update_accounts(p1,{'accounts':[{'name':'Main','tag':'EUW'},{'name':'Alt','tag':'EUW'}]})
    p1['accounts'][1]['puuid']='alt'
    return {'config':{'endDate':'2026-11-15T23:59:00+01:00'},'duos':[{'id':'a','teamName':'ATodoFlash',
            'player1':p1, 'player2':{'name':'Second','displayName':'Guille','puuid':'second'}, 'history':[]}]}


class ProgressionTests(unittest.TestCase):
    def test_chronological_cumulative_values_merge_accounts_but_keep_people_separate(self):
        db=database();duo=db['duos'][0]
        duo['history']=[game('LAST',3,stats('alt',7,2,8)),game('FIRST',1,stats('main',2,1,4),stats('second',1,3,9)),game('MIDDLE',2,stats('alt',0,0,6),stats('second',3,2,10))]
        before=copy.deepcopy(db)
        payload=stat_progression.build_progression(db)
        markel,guille=payload['players']
        self.assertEqual(markel['name'],'Markel')
        self.assertEqual(markel['points'],[{'game':1,'kills':2,'deaths':1,'assists':4},{'game':2,'kills':2,'deaths':1,'assists':10},{'game':3,'kills':9,'deaths':3,'assists':18}])
        self.assertEqual(guille['games'],2)
        self.assertEqual(guille['totals'],{'kills':4,'deaths':5,'assists':19})
        self.assertEqual(payload['pendingMatches'],0)
        self.assertEqual(db,before)
        self.assertFalse(any(key in json.dumps(payload) for key in ('puuid','accounts','password','matchId')))

    def test_duplicate_rows_prefer_complete_evidence_and_do_not_double_count(self):
        db=database();duo=db['duos'][0]
        duo['history']=[game('SAME',1,{'puuid':'main','kills':30}),game('SAME',1,stats()),game('NEXT',2,stats('alt'))]
        payload=stat_progression.build_progression(db)
        self.assertEqual(payload['players'][0]['games'],2)
        self.assertEqual(payload['players'][0]['totals']['kills'],6)
        self.assertEqual(payload['pendingMatches'],0)

    def test_filter_cutoff_duration_queue_test_exclusion_and_end(self):
        db=database();duo=db['duos'][0]
        duo['history']=[game('VALID',0,stats(),durationSeconds=600),
            game('OLD',0,stats(),gameStartTimestamp=START-1),game('SHORT',1,stats(),durationSeconds=599),
            game('FLEX',1,stats(),queueId=440),game('TEST',1,stats(),isTest=True),game('EXCLUDED',1,stats()),
            game('LATE',1,stats(),gameEndTimestamp=stat_progression.timestamp(db['config']['endDate'])*1000)]
        duo['excludedRiotMatches']={'EXCLUDED':{'reason':'manual'}}
        payload=stat_progression.build_progression(db)
        self.assertEqual(payload['players'][0]['games'],1)
        self.assertEqual(payload['players'][0]['totals']['kills'],3)

    def test_missing_numbers_are_pending_and_absence_is_not_a_zero_game(self):
        db=database();duo=db['duos'][0]
        duo['history']=[game('PARTIAL',1,{'puuid':'main','kills':3,'deaths':1}),game('ABSENT',2,None,stats('second')),
                        game('UNKNOWN',3,None,None,participantsChecked={'player1':False,'player2':True}),game('NAN',4,stats(kills=float('nan')))]
        duo['riotMatchDiscovery']={'pendingMatchIds':['IMPORT_GAP']}
        payload=stat_progression.build_progression(db)
        self.assertEqual(payload['pendingMatches'],4)
        self.assertEqual(payload['players'][0]['games'],0)
        self.assertEqual(payload['players'][1]['games'],1)

    def test_foreign_accounts_are_not_attributed_to_a_reused_slot(self):
        db=database();db['duos'][0]['history']=[game('OTHER',1,stats('someone-else'))]
        self.assertEqual(stat_progression.build_progression(db)['players'][0]['points'],[])

    def test_roster_is_dynamic_and_empty_players_are_retained(self):
        db={'config':{},'duos':[{'id':f't{i}','teamName':f'Team {i}','player1':{'name':f'A{i}'},'player2':{'name':f'B{i}'},'history':[]} for i in range(9)]}
        people=stat_progression.build_progression(db)['players']
        self.assertEqual(len(people),18)
        self.assertEqual(len({p['id'] for p in people}),18)
        self.assertTrue(all(p['games']==0 and p['points']==[] for p in people))


class ProgressionEndpointTests(unittest.TestCase):
    setUp=fixtures.ShellEndpointTests.setUp
    tearDown=fixtures.ShellEndpointTests.tearDown

    def test_public_endpoint_reads_stored_data_without_network_or_state_changes(self):
        db=server.load_db();duo=db['duos'][0]
        duo['history']=[game('ONE',1,stats('main'))]
        duo['player1']['puuid']='main'
        server.save_db(db)
        before=server.load_db()
        with patch.object(server,'riot_open') as riot:
            with urllib.request.urlopen(self.base+'/api/stats/progression',timeout=3) as response:
                self.assertEqual(response.status,200)
                payload=json.load(response)
            riot.assert_not_called()
        self.assertEqual(payload['players'][0]['points'][0]['kills'],3)
        self.assertEqual(server.load_db(),before)
        with urllib.request.urlopen(self.base+'/stat-progression.js',timeout=3) as response:
            self.assertIn(b'window.StatProgression',response.read())


if __name__=='__main__': unittest.main()
