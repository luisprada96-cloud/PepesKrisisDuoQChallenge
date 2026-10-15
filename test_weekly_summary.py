"""Archive lifecycle and evidence-derived weekly statistics."""
import copy
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import urllib.request
import urllib.error

import weekly_summary as weekly
import clips_service as clips
import server
import test_shell_penalties as fixtures
from storage import StorageError

WEEK = '2026-09-28'
START, END = weekly.bounds(WEEK)


def iso(seconds):
    return datetime.fromtimestamp(seconds, weekly.MADRID).isoformat()


def database():
    p1 = {'name':'Uno','tag':'EUW','displayName':'Ana','puuid':'p1','mainRole':'TOP',
          'eloHistory':[{'observedAt':START-60,'totalLp':2000,'tier':'Emerald','division':'IV','lp':0},
                        {'observedAt':END-60,'totalLp':2100,'tier':'Emerald','division':'III','lp':0}]}
    p2 = {'name':'Dos','tag':'EUW','displayName':'Luis','puuid':'p2',
          'eloHistory':[{'observedAt':START+60,'totalLp':1000,'tier':'Gold','division':'IV','lp':0},
                        {'observedAt':END-60,'totalLp':950,'tier':'Silver','division':'I','lp':50}]}
    games = [game('one', START+100, 'WIN'), game('two', START+200, 'WIN'), game('three', START+300, 'LOSS')]
    games[0].update(shellRewardIds=['kills','penta'], shellRewardCredits={'kills':True,'penta':False})
    games[1]['shellRewardIds'] = ['streak']
    duo = {'id':'a','teamName':'Equipo A','player1':p1,'player2':p2,'history':games,'blueShells':5,
           'activeDebuffs':[{'id':'penalty','scope':'ONE','status':'COMPLETED','resolved':True,
                            'assignedAt':iso(START+50),'resolvedAt':iso(END+10),'resolvedByMatchId':'one',
                            'requirements':{'assignedPlayer':'player1'}}]}
    return {'duos':[duo], 'weeklySummaryFirstWeek':WEEK, 'shellAttacks':[
        {'id':'attack','attackerTeamId':'a','targetTeamId':'b','launchedAt':iso(START+100)},
        {'id':'return','attackerTeamId':'b','targetTeamId':'a','launchedAt':iso(START+200),'returnedFromAttackId':'attack'}],
        'clips':{'week':WEEK,'posts':[{'id':'clip','slug':'Winner','url':'https://clips.twitch.tv/Winner',
            'title':'Gran jugada','teamId':'a','createdAt':START+100,'likedBy':['secret1','secret1','secret2']}]}}


def game(mid, at, result='WIN', **extra):
    return {'matchId':mid,'gameEndTimestamp':at*1000,'result':result,
            'player1Stats':{'puuid':'p1','kills':10,'deaths':2,'assists':8,'championName':'Gnar','win':result=='WIN'},
            'player2Stats':{'puuid':'p2','kills':2,'deaths':1,'assists':12,'championName':'Lulu','win':result=='WIN'}, **extra}


class WeeklySummaryTests(unittest.TestCase):
    def test_archive_at_monday_preserves_clip_and_awards_once(self):
        db = database()
        self.assertFalse(weekly.maintain(db, END-1))
        self.assertTrue(clips.settle_weekly_reward(db, END-60))
        self.assertNotIn(WEEK, db['weeklySummaries'])
        board, changed = clips.board_for(db, now=END)
        self.assertTrue(changed)
        self.assertEqual(board['posts'], [])
        recap = db['weeklySummaries'][WEEK]
        self.assertEqual(recap['clips']['posts'], 1)
        self.assertEqual(recap['clips']['votes'], 2)
        self.assertEqual(recap['clips']['winner']['title'], 'Gran jugada')
        self.assertEqual(recap['teams'][0]['shells']['clipPrize'], 3)
        self.assertEqual(db['duos'][0]['blueShells'], 8)
        restored = json.loads(json.dumps(db))
        self.assertFalse(clips.board_for(restored, now=END+2)[1])
        self.assertFalse(weekly.maintain(restored, END+2, refresh=True))
        self.assertEqual(restored['duos'][0]['blueShells'], 8)

    def test_counts_real_games_stats_and_manual_completions(self):
        db = database()
        duo = db['duos'][0]
        duo['history'] += [copy.deepcopy(duo['history'][0]), game('fake', START+350, isTest=True),
                           game('before', START-1), game('after', END), {'matchId':'undated','date':'invented'}]
        duo['activeDebuffs'] += [
            {'assignedAt':iso(START+60),'status':'COMPLETED','resolvedAt':iso(START+200),'manualResolution':{'by':'ADMIN'}},
            {'assignedAt':iso(START+60),'status':'COMPLETED','resolvedAt':iso(END+20)},
            {'assignedAt':iso(START+60),'status':'ACTIVE'},
            {'assignedAt':iso(START+60),'status':'CANCELLED','retiredAt':iso(START+200)}]
        summary = weekly.build_summary(db, WEEK)
        team = summary['teams'][0]
        self.assertEqual(summary['totals']['games'], 3)
        self.assertEqual((team['wins'],team['losses'],team['bestStreak']), (2,1,2))
        self.assertEqual(team['totals'], {'kills':36,'deaths':9,'assists':60})
        self.assertEqual(team['kda'], 10.67)
        self.assertEqual(team['penalties'], {'received':5,'completed':1,'manual':1,'pending':2})
        self.assertEqual(team['shells']['launched'], 1)
        self.assertEqual(team['shells']['received'], 1)
        self.assertEqual(team['shells']['credited'], 1)
        self.assertEqual(team['shells']['blocked'], 1)
        self.assertEqual(team['shells']['creditUnknown'], 1)
        self.assertEqual(team['players'][0]['favorite'], {'name':'Gnar','games':3})
        self.assertEqual(team['players'][0]['penaltiesCompleted'], 1)

    def test_global_dedup_and_no_invented_player_stats(self):
        db = database()
        second = copy.deepcopy(db['duos'][0]);second['id']='b';second['teamName']='Equipo B'
        second['history'][0]['player2Stats'] = None
        db['duos'].append(second)
        summary = weekly.build_summary(db, WEEK)
        self.assertEqual(summary['totals']['games'], 3)
        self.assertEqual(summary['teams'][1]['players'][1]['games'], 2)
        self.assertEqual(summary['teams'][1]['detailGames'], 2)

    def test_observed_elo_partial_and_missing_are_not_highlighted(self):
        summary = weekly.build_summary(database(), WEEK)
        self.assertEqual(summary['highlights']['rising']['elo']['delta'], 100)
        self.assertIsNone(summary['highlights']['falling'])
        elo = summary['teams'][0]['players'][1]['elo']
        self.assertTrue(elo['partial']);self.assertEqual(elo['delta'], -50)
        self.assertIsNone(weekly.elo_summary({}, START, END)['delta'])
        self.assertIsNone(weekly.elo_summary({'eloHistory':[{'observedAt':START+5,'totalLp':30,'tier':'Gold'}]},START,END)['delta'])

    def test_old_account_completion_does_not_credit_replacement_player(self):
        db=database()
        db['duos'][0]['activeDebuffs'][0]['requirements']['assignedAccount']={'name':'Previous','tag':'EUW'}
        summary=weekly.build_summary(db,WEEK)
        self.assertEqual(summary['teams'][0]['penalties']['completed'],1)
        self.assertEqual(summary['teams'][0]['players'][0]['penaltiesCompleted'],0)

    def test_inventory_credit_is_recorded_once_with_cap(self):
        duo={'blueShells':4,'history':[game('credits',START+100,pentaKill=True)]}
        server.update_duo_shells(duo)
        match=duo['history'][0]
        self.assertEqual(match['shellRewardCredits'],{'penta':True})
        duo['history'].append(game('blocked',START+200,pentaKill=True))
        server.update_duo_shells(duo)
        blocked=next(m for m in duo['history'] if m['matchId']=='blocked')
        self.assertEqual(blocked['shellRewardCredits'],{'penta':False})
        duo['blueShells']=0
        server.update_duo_shells(duo)
        self.assertEqual(duo['blueShells'],0)
        self.assertEqual(blocked['shellRewardCredits'],{'penta':False})

    def test_late_games_update_without_replacing_accounts_or_labels(self):
        db = database();clips.board_for(db,now=END)
        saved = copy.deepcopy(db['weeklySummaries'][WEEK])
        db['duos'][0]['teamName'] = 'Renamed'
        db['duos'][0]['history'].append(game('late',START+500))
        self.assertTrue(weekly.maintain(db,END+20,refresh=True))
        recap = db['weeklySummaries'][WEEK]
        self.assertEqual(recap['teams'][0]['games'],4)
        self.assertEqual(recap['teams'][0]['name'],'Equipo A')
        self.assertEqual(recap['clips'],saved['clips'])
        saved = copy.deepcopy(recap)
        db['duos'][0]['player1']['name']='Replacement'
        db['duos'][0]['history'].append(game('different',START+600))
        self.assertFalse(weekly.maintain(db,END+30,refresh=True))
        self.assertEqual(db['weeklySummaries'][WEEK],saved)
        db['duos']=[]
        self.assertFalse(weekly.maintain(db,END+40,refresh=True))

    def test_dst_and_downtime_archive_each_missing_week(self):
        for week, hours in [('2026-03-23',167),('2026-10-19',169)]:
            start,end=weekly.bounds(week)
            self.assertEqual((end-start)/3600,hours)
            db={'duos':[], 'weeklySummaryFirstWeek':week}
            weekly.maintain(db,end+8*86400)
            self.assertEqual(len(db['weeklySummaries']),2)

    def test_selector_hides_pre_tournament_archives_without_deleting_them(self):
        db=database()
        weekly.maintain(db,END)
        db['config']={'startDate':'2026-10-15T18:00:00+02:00'}
        before=copy.deepcopy(db['weeklySummaries'])
        result=weekly.public_payload(db,now=weekly.timestamp('2026-10-15T20:00'))
        self.assertEqual(result['weeks'],['2026-10-12'])
        self.assertEqual(result['currentWeek'],'2026-10-12')
        self.assertEqual(result['summary']['week'],'2026-10-12')
        self.assertEqual(result['summary']['status'],'CURRENT')
        self.assertEqual(db['weeklySummaries'],before)
        with self.assertRaises(LookupError):
            weekly.public_payload(db,WEEK,weekly.timestamp('2026-10-15T20:00'))

    def test_new_tournament_weeks_are_archived_normally_without_regenerating_test_weeks(self):
        db=database()
        weekly.maintain(db,END)
        before=copy.deepcopy(db['weeklySummaries'][WEEK])
        db['config']={'startDate':'2026-10-15T18:00:00+02:00'}
        now=weekly.timestamp('2026-10-26T12:00')
        weekly.maintain(db,now,refresh=True)
        self.assertNotIn('2026-10-05',db['weeklySummaries'])
        self.assertEqual(db['weeklySummaries'][WEEK],before)
        result=weekly.public_payload(db,now=now)
        self.assertEqual(result['weeks'],['2026-10-26','2026-10-19','2026-10-12'])
        archived=weekly.public_payload(db,'2026-10-12',now)
        self.assertEqual(archived['summary']['status'],'ARCHIVED')

    def test_first_archive_origin_uses_madrid_tournament_week_instead_of_old_clip_board(self):
        db=database()
        db.pop('weeklySummaryFirstWeek')
        # Sunday UTC is already Monday in Madrid.
        db['config']={'startDate':'2026-10-11T23:30:00Z'}
        now=weekly.timestamp('2026-10-19T00:01')
        weekly.maintain(db,now)
        self.assertEqual(db['weeklySummaryFirstWeek'],'2026-10-12')
        self.assertEqual(set(db['weeklySummaries']),{'2026-10-12'})

    def test_before_opening_week_previews_first_week_and_never_lists_preseason(self):
        db=database()
        db['config']={'startDate':'2026-10-15T18:00'}
        result=weekly.public_payload(db,now=START+100)
        self.assertEqual(result['weeks'],['2026-10-12'])
        self.assertEqual(result['summary']['status'],'UPCOMING')
        self.assertEqual(result['summary']['totals']['games'],0)

    def test_public_payload_has_no_credentials_or_votes_tokens(self):
        db=database();db['duos'][0]['passwordHash']='PRIVATE';db['config']={'riotApiKey':'PRIVATE'}
        clips.board_for(db,now=END)
        result=weekly.public_payload(db,WEEK,END)
        serialized=json.dumps(result)
        for secret in ('PRIVATE','secret1','secret2','puuid','likedBy','requirements'):
            self.assertNotIn(secret,serialized)
        self.assertEqual(result['summary']['status'],'ARCHIVED')
        with self.assertRaises(LookupError):weekly.public_payload(db,'2020-01-01',END)


class WeeklyEndpointTests(unittest.TestCase):
    tearDown = fixtures.ShellEndpointTests.tearDown
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.object(server,'remote_backend',None).start()
        patch.object(server.CustomHandler,'log_message',return_value=None).start()
        fixtures.ShellEndpointTests.setUp(self)

    def test_weekly_summary_endpoint_archive_retry_and_concurrent_reads(self):
        db=json.loads(Path(server.DB_FILE).read_text(encoding='utf-8'))
        data=database();db.update({k:v for k,v in data.items() if k!='duos'})
        db['duos'][0].update(data['duos'][0])
        Path(server.DB_FILE).write_text(json.dumps(db),encoding='utf-8')
        with patch.object(server.time,'time',return_value=END+5):
            with patch.object(server,'save_db',side_effect=StorageError('failure')):
                with self.assertRaises(urllib.error.HTTPError) as failed:
                    urllib.request.urlopen(self.base+'/api/weekly-summary',timeout=5)
                self.assertEqual(failed.exception.code,503)
            self.assertNotIn('weeklySummaries',json.loads(Path(server.DB_FILE).read_text(encoding='utf-8')))
            def get(_):
                with urllib.request.urlopen(self.base+'/api/weekly-summary?week='+WEEK,timeout=5) as response:
                    return json.load(response)
            with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(get,range(4)))
            self.assertTrue(all(result['summary']['clips']['winner']['votes']==2 for result in results))
            saved=json.loads(Path(server.DB_FILE).read_text(encoding='utf-8'))
            self.assertEqual(saved['duos'][0]['blueShells'],8)
            self.assertEqual(len(saved['weeklySummaries']),1)

if __name__ == '__main__':
    unittest.main()
