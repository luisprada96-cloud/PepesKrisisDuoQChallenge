"""Regressions for team means, source selection and historical Pick'em evidence."""
import copy
import unittest
from unittest.mock import patch

import competition_ranking as ranking
import pickem_service as pickem
import player_accounts as accounts
import server
import test_pickem
import test_shell_penalties as endpoint_fixtures
from trophies import build_trophies


def rank(tier='Gold', division='IV', lp=0, **extra):
    return dict(tier=tier, division=division, lp=lp, wins=5, losses=5, **extra)


def team(identifier, first, second):
    return {'id':identifier, 'teamName':identifier, 'tier':'Challenger', 'lp':999,
            'player1':{'name':identifier+'1', 'rank':first}, 'player2':{'name':identifier+'2', 'rank':second}, 'history':[]}


class CompetitionRankingTests(unittest.TestCase):
    def test_mean_instead_of_first_player_and_no_persistent_rewrite(self):
        a = team('a', rank(), rank('Diamond'))
        b = team('b', rank('Platinum'), rank('Platinum'))
        before = copy.deepcopy(a)
        self.assertEqual(ranking.team_rank(a)['totalLp'], 1800)
        self.assertEqual(ranking.team_rank(a)['label'], 'Platinum II · 0 LP')
        self.assertGreater(ranking.team_rank_key(a), ranking.team_rank_key(b))
        self.assertEqual(build_trophies([b,a],None)['cards'][0]['entries'][0]['id'],'a')
        self.assertEqual(server.duo_summary(a)['competitionRank']['totalLp'],1800)
        self.assertEqual(a,before)

    def test_selected_secondary_accounts_of_both_players_override_stale_projection(self):
        duo = team('a',rank('Challenger',lp=900),rank('Challenger',lp=900))
        for key in ('player1','player2'):
            duo[key].update(accounts=[{'id':'main','name':key+'Main','rank':rank('Diamond')},
                                      {'id':'alt','name':key+'Alt','rank':rank('Silver',lp=51)}],eloAccountId='alt')
        self.assertEqual(ranking.team_rank(duo)['totalLp'],851)
        duo['player2']['eloAccountId']='main'
        self.assertEqual(ranking.team_rank(duo)['totalLp'],1625.5)
        duo['player1']['accounts'][1]['rank']=None
        self.assertFalse(ranking.team_rank(duo)['ready'])

    def test_master_shared_scale_and_fractional_mean(self):
        self.assertEqual(ranking.rank_points(rank('Grandmaster','I',500)),3300)
        self.assertEqual(ranking.rank_points(rank('Challenger','I',400)),3200)
        self.assertEqual(ranking.rank_label(3300),'Master · 500 LP')
        self.assertEqual(ranking.average_rank(rank(lp=1),rank())['totalLp'],1200.5)
        self.assertEqual(ranking.average_rank(rank('Iron'),rank('Iron'))['totalLp'],0)

    def test_missing_unranked_invalid_and_explicitly_reset_rank_are_pending(self):
        for missing in (None,{},rank('Unranked'),rank(lp=float('nan')),rank(division='bad')):
            duo=team('a',rank(),missing)
            self.assertFalse(ranking.team_rank(duo)['ready'])
            self.assertIsNone(ranking.team_rank(duo)['totalLp'])
        duo=team('a',None,rank())
        self.assertFalse(ranking.team_rank(duo)['ready'])
        del duo['player1']['rank']
        self.assertTrue(ranking.team_rank(duo)['ready'])  # Legacy P1 fields only.

    def test_equal_mean_uses_both_selected_accounts_winrate(self):
        a=team('a',rank(),rank('Diamond'))
        b=team('b',rank('Platinum','II'),rank('Platinum','II'))
        self.assertEqual(ranking.team_rank_key(a),ranking.team_rank_key(b))
        b['player2']['rank'].update(wins=6,losses=4)
        self.assertGreater(ranking.team_rank_key(b),ranking.team_rank_key(a))

    def test_weekly_mean_captures_both_sources_and_preserves_closed_results(self):
        db=test_pickem.database()
        a,b=db['duos']
        for duo, first, second in ((a,rank(),rank('Diamond')),(b,rank('Platinum'),rank('Platinum'))):
            for key,value in (('player1',first),('player2',second)):
                duo[key]['rank']={**value,'observedAt':test_pickem.NOW}
        pickem.ensure_week(db,test_pickem.NOW)
        board=db['pickem']['weeks'][test_pickem.WEEK]
        category=next(c for c in board['categories'] if c['id']=='weekly_leader')
        self.assertEqual(pickem.weekly_rank_result(db,board,category)['optionIds'],['a'])
        before=copy.deepcopy(board['rankObservations']['a'])
        end=pickem.period(db,board['week'])['endsAt']
        with patch.object(accounts.time,'time',return_value=end+1):
            accounts.update_accounts(a['player2'],{'accounts':[{'id':'main','name':'A2'}, {'id':'alt','name':'New'}],'eloAccountId':'alt'})
        a['player2']['accounts'][1]['rank']=rank('Iron',observedAt=test_pickem.NOW)
        pickem.capture_rankings(db)
        self.assertEqual(board['rankObservations']['a'],before)
        self.assertEqual(pickem.weekly_rank_result(db,board,category)['optionIds'],['a'])
        saved={'status':'SETTLED','optionIds':['b'],'settledAt':end+100}
        board['results']['weekly_leader']=copy.deepcopy(saved)
        pickem.capture_rankings(db)
        self.assertEqual(board['results']['weekly_leader'],saved)

    def test_weekly_legacy_p1_observation_requires_real_p2_evidence(self):
        db=test_pickem.database()
        for duo in db['duos']:
            duo['player2'].pop('rank',None)
        pickem.ensure_week(db,test_pickem.NOW)
        board=db['pickem']['weeks'][test_pickem.WEEK]
        board['rankObservations']={'a':{**rank(observedAt=test_pickem.NOW),'account':['a1','euw']}}
        pickem.capture_rankings(db)
        self.assertFalse(board['rankObservations']['a']['ready'])
        self.assertEqual(board['rankObservations']['a']['players']['player1']['tier'],'Gold')
        db['duos'][0]['player2']['rank']=rank('Diamond',observedAt=test_pickem.NOW)
        pickem.capture_rankings(db)
        self.assertEqual(board['rankObservations']['a']['totalLp'],1800)

    def test_weekly_selection_changes_before_close_use_the_selected_alt_for_each_player(self):
        db=test_pickem.database()
        a,b=db['duos']
        for duo in (a,b):
            for key in ('player1','player2'):
                player=duo[key]
                with patch.object(accounts.time,'time',return_value=test_pickem.NOW-10):
                    accounts.update_accounts(player, {'accounts':[{'id':'main','name':player['name']},
                        {'id':'alt','name':player['name']+'Alt'}],'eloAccountId':'main'})
                player['accounts'][0]['rank']=rank('Gold',observedAt=test_pickem.NOW)
                player['accounts'][1]['rank']=rank('Diamond',observedAt=test_pickem.NOW)
        pickem.ensure_week(db,test_pickem.NOW)
        board=db['pickem']['weeks'][test_pickem.WEEK]
        for key in ('player1','player2'):
            with patch.object(accounts.time,'time',return_value=test_pickem.NOW+1):
                accounts.update_accounts(a[key], {'eloAccountId':a[key]['accounts'][1]['id']})
        pickem.capture_rankings(db)
        self.assertEqual(board['rankObservations']['a']['totalLp'],2400)
        for key in ('player1','player2'):
            self.assertEqual(board['rankObservations']['a']['players'][key]['account'][0],a[key]['name'].lower()+'alt')
        category=next(c for c in board['categories'] if c['id']=='weekly_leader')
        self.assertEqual(pickem.weekly_rank_result(db,board,category)['optionIds'],['a'])

    def test_pending_mean_cannot_freeze_final_trophies_or_final_predictions(self):
        import tempfile
        from pathlib import Path
        duo=team('a',rank(),None)
        with tempfile.TemporaryDirectory() as directory, patch.object(server,'DB_FILE',str(Path(directory)/'db.json')), patch.object(server,'remote_backend',None):
            server.save_db({'config':{'endDate':'2026-11-15T23:59:00+01:00'},'duos':[duo]})
            with patch.object(server.time,'time',return_value=2000000000):
                self.assertFalse(server.public_trophies()['standingsReady'])
                self.assertNotIn('awardedTrophies',server.load_db())


class SelectedAccountRankingEndpointTests(unittest.TestCase):
    setUp = endpoint_fixtures.ShellEndpointTests.setUp
    tearDown = endpoint_fixtures.ShellEndpointTests.tearDown
    post = endpoint_fixtures.ShellEndpointTests.post

    def test_admin_selection_for_each_participant_updates_public_mean_without_a_sync(self):
        db=server.load_db()
        duo=db['duos'][0]
        for key in ('player1','player2'):
            player=duo[key]
            accounts.update_accounts(player, {'accounts':[{'id':'main','name':player['name'],'tag':player.get('tag','EUW')},
                {'id':'alt','name':key+'Alternate','tag':'EUW'}],'eloAccountId':'main'})
            player['accounts'][0]['rank']=rank('Diamond')
            player['accounts'][1]['rank']=rank('Silver',lp=51)
            accounts.project_elo(player)
        server.save_db(db)
        self.assertEqual(server.public_duo_summaries()[0]['competitionRank']['totalLp'],2400)
        for key,expected in (('player1',1625.5),('player2',851)):
            self.post('/api/duos',{'authPin':'9999','duo':{'id':duo['id'],key:{'eloAccountId':duo[key]['accounts'][1]['id']}}})
            self.assertEqual(server.public_duo_summaries()[0]['competitionRank']['totalLp'],expected)


if __name__ == '__main__':
    unittest.main()
