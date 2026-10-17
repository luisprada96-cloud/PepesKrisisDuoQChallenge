"""Multiple sources keep one participant, one match and one selected rank."""
import copy
import io
import json
import time
import unittest
import urllib.error
from collections import Counter
from unittest.mock import patch
from urllib.parse import urlparse

import player_accounts as pa
import server
import pickem_service
import weekly_summary
import test_shell_penalties as fixtures
from test_shell_penalties import penalty


class AccountRulesTests(unittest.TestCase):
    def test_default_and_projection_keep_original_identity_and_separate_histories(self):
        player = {'name':'Markel','tag':'EUW','rank':{'tier':'Gold','lp':10},'eloHistory':[{'totalLp':1210}]}
        pa.update_accounts(player, {'accounts':[{'id':'original','name':'Markel','tag':'EUW'}, {'id':'alt','name':'MarkelAlt','tag':'EUW'}], 'eloAccountId':'original'})
        original = copy.deepcopy(player['accounts'][0])
        self.assertEqual(pa.elo_account(player)['name'], 'Markel')
        player['accounts'][1].update(rank={'tier':'Diamond','lp':20},eloHistory=[{'totalLp':2420}])
        pa.update_accounts(player, {'eloAccountId':player['accounts'][1]['id']})
        self.assertEqual(player['name'], 'Markel')
        self.assertEqual(player['rank']['tier'], 'Diamond')
        self.assertEqual(player['eloHistory'], [{'totalLp':2420}])
        self.assertEqual(player['accounts'][0], original)
        pa.update_accounts(player, {'eloAccountId':original['id']})
        self.assertEqual(player['eloHistory'], [{'totalLp':1210}])

    def test_client_cannot_inject_rank_or_puuid_and_duplicate_accounts_fail(self):
        player = {'name':'Markel','tag':'EUW'}
        pa.update_accounts(player, {'accounts':[{'name':'Markel','tag':'EUW'}, {'name':'Otra','tag':'EUW','puuid':'fake','rank':{'tier':'Challenger'}}]})
        self.assertNotIn('puuid',player['accounts'][1])
        self.assertNotIn('rank',player['accounts'][1])
        with self.assertRaises(ValueError):
            pa.update_accounts(player, {'eloAccountId':'missing'})
        with self.assertRaises(ValueError):
            pa.update_accounts({'name':'A','tag':'EUW'}, {'accounts':[{'name':'A','tag':'EUW'},{'name':' a ','tag':'euw'}]})

    def test_elo_selection_after_close_does_not_replace_the_weeks_observation(self):
        import test_pickem
        db = test_pickem.database()
        pickem_service.ensure_week(db, test_pickem.NOW)
        board = db['pickem']['weeks'][test_pickem.WEEK]
        for i, duo in enumerate(db['duos']):
            duo.update(tier='Gold' if i == 0 else 'Platinum', division='IV', lp=20, rankObservedAt=test_pickem.NOW)
        pickem_service.capture_rankings(db)
        before = copy.deepcopy(board['rankObservations']['a'])
        player = db['duos'][0]['player1']
        with patch.object(pa.time, 'time', return_value=pickem_service.period(db,board['week'])['endsAt']+1):
            pa.update_accounts(player, {'accounts':[{'id':'main','name':'A1','tag':'EUW'}, {'id':'alt','name':'Otra','tag':'EUW'}], 'eloAccountId':'alt'})
        player['accounts'][1]['rank'] = {'tier':'Challenger','division':'I','lp':900,'observedAt':test_pickem.NOW}
        pa.project_elo(player)
        db['duos'][0].update(tier='Challenger',lp=900)
        pickem_service.capture_rankings(db)
        self.assertEqual(board['rankObservations']['a'], before)
        category = next(c for c in board['categories'] if c['id']=='weekly_leader')
        result = pickem_service.weekly_rank_result(db,board,category)
        self.assertEqual(result['optionIds'],['b'])

    def test_unicode_riot_ids_are_kept_without_losing_the_accent(self):
        player = {'name':'Markel','tag':'EUW'}
        pa.update_accounts(player, {'accounts':[{'name':'Markel','tag':'EUW'}, {'name':'Unlucky Lemür','tag':'EUW'}]})
        self.assertEqual(player['accounts'][1]['name'],'Unlucky Lemür')
        self.assertEqual(pa.identity(player['accounts'][1]),['unlucky lemür','euw'])

    def test_rotation_retains_historical_account_evidence(self):
        player = {'name':'Markel','tag':'EUW'}
        pa.update_accounts(player, {})
        pa.remember_puuid(player['accounts'][0],'old')
        pa.remember_puuid(player['accounts'][0],'rotated')
        self.assertTrue(pa.owns_stats(player,{'puuid':'old'}))
        self.assertTrue(pa.owns_stats(player,{'puuid':'rotated'}))
        self.assertFalse(pa.owns_stats(player,{'puuid':'someone-else'}))


class MultiAccountEndpointTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def configure(self, player_key='player1'):
        db = server.load_db()
        db['duos'] = db['duos'][:1]
        now = time.time()
        db['config'].update(startDate='2026-10-01',endDate='2026-11-01')
        duo = db['duos'][0]
        duo.update(tier='Gold',division='IV',lp=10,wins=2,losses=1)
        for key, name, uid in [('player1','A1','p1'),('player2','A2','p2')]:
            duo[key].update(name=name,tag='EUW',puuid=uid,avatar='custom.png')
        server.save_db(db)
        owner = duo[player_key]
        edits = {'accounts':[{'id':'main','name':owner['name'],'tag':'EUW'}, {'id':'alt','name':'Alternate','tag':'EUW'}], 'eloAccountId':'alt'}
        result = self.post('/api/duos',{'authPin':'9999','duo':{'id':'a',player_key:edits}})
        self.assertTrue(result['success'])
        return server.load_db()['duos'][0]

    def sync(self, fail_detail=False, callback=None):
        calls=[]
        now_ms=int(time.time()*1000)
        def reply(request,**kwargs):
            url=request.full_url
            calls.append(url)
            if callback:
                callback(url)
            if '/accounts/' in url:
                payload={'puuid':'alt' if '/Alternate/' in url else ('p1' if '/A1/' in url else 'p2')}
            elif '/entries/' in url:
                uid=url.rsplit('/',1)[-1]
                payload=[{'queueType':'RANKED_SOLO_5x5','tier':'DIAMOND' if uid=='alt' else 'GOLD','rank':'IV','leaguePoints':55 if uid=='alt' else 10,'wins':20,'losses':10}]
            elif '/ids?' in url:
                payload=['EUW1_ALT','EUW1_SHARED'] if '/alt/' in url else ['EUW1_SHARED']
            else:
                mid=url.rsplit('/',1)[-1]
                if mid=='EUW1_ALT' and fail_detail:
                    raise urllib.error.URLError('temporary')
                first='alt' if mid=='EUW1_ALT' else 'p1'
                payload={'info':{'queueId':420,'gameStartTimestamp':now_ms-1500000,'gameEndTimestamp':now_ms-300000,'gameDuration':1200,'participants':[
                    {'puuid':first,'participantId':1,'teamId':100,'riotIdGameName':'Alternate' if first=='alt' else 'A1','riotIdTagline':'EUW','championName':'Ahri','kills':21,'deaths':2,'assists':10,'win':True,'summoner1Id':14,'summoner2Id':12},
                    {'puuid':'p2','participantId':2,'teamId':100,'riotIdGameName':'A2','riotIdTagline':'EUW','championName':'Lux','kills':4,'deaths':1,'assists':20,'win':True,'summoner1Id':4,'summoner2Id':12}]}}
            return io.BytesIO(json.dumps(payload).encode())
        with patch.object(server,'get_riot_api_key',return_value='fake'),patch.object(server,'riot_open',side_effect=reply),patch.object(server.time,'sleep'):
            result=server.sync_riot_data()
        return result,calls

    def test_union_deduplicates_and_selected_elo_does_not_change_identity(self):
        self.configure()
        result,calls=self.sync()
        self.assertTrue(result['success'], result)
        duo=server.load_db()['duos'][0]
        self.assertEqual(len(duo['history']),2)
        self.assertEqual(duo['player1']['name'],'A1')
        self.assertEqual(duo['player1']['rank']['tier'],'Diamond')
        self.assertEqual(duo['tier'],'Diamond')
        self.assertEqual(duo['netLp'],0)
        self.assertEqual(duo['player1']['eloHistory'][-1]['totalLp'],2455)
        self.assertEqual(duo['playerInsights']['player1']['totals']['kills'],42)
        self.assertEqual(duo['shellsEarnedTotal'],2)
        self.assertEqual(sum(u.endswith('/EUW1_SHARED') for u in calls),1)
        source_ids={m['player1Stats']['sourceAccountId'] for m in duo['history']}
        self.assertEqual(len(source_ids),2)
        public=server.safe_duo_for_player(duo)
        self.assertTrue(all('matchDiscovery' not in a for a in public['player1']['accounts']))
        before=copy.deepcopy(duo)
        self.sync()
        after=server.load_db()['duos'][0]
        self.assertEqual(after['shellsEarnedTotal'],before['shellsEarnedTotal'])
        self.assertEqual(len(after['history']),2)

    def test_failed_details_survive_restart_and_are_retried(self):
        self.configure()
        result,_=self.sync(fail_detail=True)
        self.assertFalse(result['success'])
        duo=server.load_db()['duos'][0]
        self.assertIn('EUW1_ALT',duo['riotMatchDiscovery']['pendingMatchIds'])
        self.sync()
        duo=server.load_db()['duos'][0]
        self.assertEqual(duo['riotMatchDiscovery']['pendingMatchIds'],[])
        self.assertEqual(len(duo['history']),2)

    def test_switch_elo_restores_the_correct_account_history(self):
        self.configure()
        self.sync()
        duo=server.load_db()['duos'][0]
        main=duo['player1']['accounts'][0]
        result=self.post('/api/duos',{'authPin':'9999','duo':{'id':'a','player1':{'eloAccountId':main['id']}}})
        current=result['duo']
        self.assertEqual(current['tier'],'Gold')
        self.assertEqual(current['player1']['rank']['lp'],10)
        self.assertEqual(current['player1']['eloHistory'],main['eloHistory'])
        self.assertEqual(current['history'],duo['history'])
        self.assertEqual(current['blueShells'],duo['blueShells'])

    def test_second_participant_selects_own_rank_without_changing_team_rank(self):
        self.configure('player2')
        self.sync()
        duo=server.load_db()['duos'][0]
        self.assertEqual(duo['tier'],'Gold')
        self.assertEqual(duo['player2']['rank']['tier'],'Diamond')

    def test_duplicate_other_player_and_invalid_selection_rejected_atomically(self):
        duo=self.configure()
        before=copy.deepcopy(duo)
        self.post('/api/duos',{'authPin':'9999','duo':{'id':'a','player2':{'accounts':[{'name':'A2','tag':'EUW'},{'name':'Alternate','tag':'EUW'}]}}},expected=400)
        self.post('/api/duos',{'authPin':'9999','duo':{'id':'a','player1':{'eloAccountId':'unknown'}}},expected=400)
        self.assertEqual(server.load_db()['duos'][0],before)

    def test_existing_penalty_and_saved_pickem_identity_recognize_alternate(self):
        self.configure()
        db=server.load_db();duo=db['duos'][0]
        options=pickem_service.category_definitions(db,'2026-10-12')
        category=next(c for c in options if c['kind']=='player')
        original=next(o for o in category['options'] if o['playerKey']=='player1')
        duo['activeDebuffs']=[penalty('no_flash','ONE',{'assignmentVersion':2,'assignedPlayer':'player1','assignedAccount':{'name':'A1','tag':'EUW','puuid':'p1'}},assigned_ms=1)]
        server.save_db(db)
        self.sync()
        duo=server.load_db()['duos'][0]
        self.assertEqual(duo['activeDebuffs'][0]['status'],'COMPLETED')
        alternate=next(m for m in duo['history'] if m['matchId']=='EUW1_ALT')['player1Stats']
        bound={(o['teamId'],o['playerKey'],tuple(o['account'])):o for o in category['options']}
        self.assertEqual(pickem_service.player_option(bound,duo,'player1',alternate)['id'],original['id'])
        summary=weekly_summary.build_summary(server.load_db(),weekly_summary.week_key(time.time()))
        self.assertEqual(summary['teams'][0]['players'][0]['totals']['kills'],42)

    def test_new_sources_backfill_existing_matches_before_declaring_complete(self):
        self.configure()
        self.sync()
        db=server.load_db();duo=db['duos'][0]
        template=copy.deepcopy(duo['history'][0])
        duo['history']=[{**copy.deepcopy(template),'matchId':f'EUW1_OLD{i}'} for i in range(45)]
        for game in duo['history']: game.pop('accountSources',None)
        server.save_db(db)
        result,_=self.sync()
        self.assertGreater(result['pending'],0)
        duo=server.load_db()['duos'][0]
        self.assertTrue(any(m.get('matchDetailsVersion')==0 for m in duo['history']))
        result,_=self.sync()
        self.assertEqual(result['pending'],0)
        self.assertTrue(all(m.get('matchDetailsVersion')==1 for m in server.load_db()['duos'][0]['history']))

    def test_archived_summaries_remain_unchanged(self):
        self.configure()
        self.sync()
        db=server.load_db()
        week=weekly_summary.week_key(time.time()-7*86400)
        old=weekly_summary.build_summary(db,week)
        before=copy.deepcopy(old)
        db['duos'][0]['history'][0]['gameEndTimestamp']=int((time.time()-7*86400)*1000)
        archived=weekly_summary.build_summary(db,week,previous=old)
        self.assertEqual(archived['teams'],before['teams'])

    def test_swap_flash_uses_each_accounts_own_reference(self):
        self.configure()
        self.sync()
        duo=server.load_db()['duos'][0]
        alternate=duo['player1']['accounts'][1]
        alternate['flashBaseline']={'slot':1,'matchId':'FIRST','gameStartTimestamp':1,'account':{'puuid':'alt','name':'Alternate','tag':'EUW'}}
        duo['activeDebuffs']=[penalty('swap_flash','ONE',{'assignmentVersion':2,'assignedPlayer':'player1',
            'assignedAccount':{'name':'A1','tag':'EUW','puuid':'p1'},'flashAccounts':{'player1':{'name':'A1','tag':'EUW','puuid':'p1'}},
            'flashBaselines':{'player1':{'slot':2,'matchId':'OTHER','gameStartTimestamp':1,'account':{'puuid':'p1'}}}},assigned_ms=1)]
        game=copy.deepcopy(next(m for m in duo['history'] if m['matchId']=='EUW1_ALT'))
        game['player1Stats']['summonerSpellIds']=[12,4]
        self.assertEqual(server.evaluate_active_penalties(duo,game),1)
        self.assertEqual(duo['activeDebuffs'][0]['evidence']['flashBaselines']['player1']['slot'],1)

    def test_saving_one_account_preserves_rank_graph_and_flash_reference(self):
        db=server.load_db();duo=db['duos'][0]
        duo.update(tier='Gold',division='IV',lp=10)
        duo['player1'].update(name='A1',tag='EUW',puuid='p1',rank={'tier':'Gold','division':'IV','lp':10,'observedAt':time.time()})
        server.save_db(db)
        result=self.post('/api/duos',{'authPin':'9999','duo':{'id':'a','player1':{'accounts':[{'name':'A1','tag':'EUW'}]}}})
        owner=result['duo']['player1']
        self.assertEqual(owner['rank']['lp'],10)
        self.assertEqual(len(owner['accounts']),1)
        game={'matchId':'FLASH','gameStartTimestamp':1,'player1Stats':{'puuid':'p1','summonerSpellIds':[4,12]}}
        server.record_flash_baselines(result['duo'],game)
        self.assertEqual(owner['flashBaseline'],owner['accounts'][0]['flashBaseline'])

    def test_mid_sync_selection_change_rejects_stale_results(self):
        duo=self.configure();changed=[]
        def change(url):
            if changed: return
            changed.append(True)
            db=server.load_db();p=db['duos'][0]['player1']
            pa.update_accounts(p,{'eloAccountId':p['accounts'][0]['id']})
            server.save_db(db)
        self.sync(callback=change)
        duo=server.load_db()['duos'][0]
        self.assertEqual(duo['player1']['eloAccountId'],duo['player1']['accounts'][0]['id'])
        self.assertEqual(duo['history'],[])


if __name__ == '__main__':
    unittest.main()
