"""Pick'em weekly quotas, private ballots and settlement from completed Riot scans."""
import copy
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pickem_service as pickem
import server
import test_shell_penalties as fixtures
from storage import StorageError
import test_tierlists as tierlist_tests
import test_riot_incremental as riot_tests


NOW = pickem.weeks.timestamp('2026-10-15T19:00')
WEEK = '2026-10-12'
CATEGORY = 'unique_champions'


def database():
    return {'config': {'startDate': '2026-10-15T18:00', 'endDate': '2026-11-15T23:59'},
            'duos': [{'id': 'a', 'teamName': 'Equipo A', 'blueShells': 5,
                      'player1': {'name': 'A1', 'displayName':'Joji'}, 'player2': {'name': 'A2'}, 'history': []},
                     {'id': 'b', 'teamName': 'Equipo B', 'player1': {'name': 'B1'},
                      'player2': {'name': 'B2', 'displayName':'Parradise'}, 'history': []}], 'events': []}


def game(mid='EUW1_1', first='Ahri', second='Lux', at=NOW):
    return {'matchId': mid, 'gameEndTimestamp': at*1000, 'statsVersion': 2, 'queueId': 420,
            'participantsChecked': {'player1': True, 'player2': True},
            'player1Stats': {'puuid': 'p1', 'championName': first},
            'player2Stats': {'puuid': 'p2', 'championName': second}}


class PickemServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = database()
        pickem.ensure_week(self.db, NOW)
        self.board = self.db['pickem']['weeks'][WEEK]

    def submit(self, browser='browser1', team='a', option='0-19', now=NOW):
        return pickem.submit(self.db, team, browser, CATEGORY, option, now=now)

    def settle(self, db=None):
        db = db or self.db
        at = pickem.period(db, WEEK)['endsAt'] + pickem.SETTLEMENT_GRACE
        return pickem.record_complete_sync(db, copy.deepcopy(db), at, now=at+60)

    def test_ranges_have_no_holes_or_overlap_at_every_boundary(self):
        for value in range(201):
            matches = [o for o in pickem.OPTIONS if o['min'] <= value and (o['max'] is None or value <= o['max'])]
            self.assertEqual(len(matches), 1, value)
        self.assertEqual(len(pickem.OPTIONS), 12)

    def test_two_ballots_per_team_and_one_per_browser_with_idempotent_retries(self):
        first, changed = self.submit()
        self.assertTrue(changed)
        again, changed = self.submit()
        self.assertFalse(changed)
        self.assertEqual(first['id'], again['id'])
        with self.assertRaises(FileExistsError): self.submit(option='20-29')
        with self.assertRaises(FileExistsError): self.submit(team='b')
        self.submit('browser2')
        with self.assertRaises(FileExistsError): self.submit('browser3')
        self.assertEqual(len(self.board['ballots']), 2)

    def test_each_new_category_reuses_the_same_ballot(self):
        self.submit()
        self.board['categories'].append({**copy.deepcopy(pickem.CATEGORIES[0]), 'id': 'future'})
        pickem.submit(self.db, 'a', 'browser1', 'future', '20-29', now=NOW)
        self.assertEqual(len(self.board['ballots']), 1)
        self.assertEqual(len(self.board['ballots'][0]['answers']), 2)

    def test_invalid_inputs_and_missing_auth_do_not_spend_attempts(self):
        for team, browser, category, option, author, error in [
            (None, 'browser', CATEGORY, '0-19', '', PermissionError),
            ('a', '', CATEGORY, '0-19', '', ValueError),
            ('a', 'browser', 'unknown', '0-19', '', ValueError),
            ('a', 'browser', CATEGORY, 'bogus', '', ValueError),
            ('a', 'browser', CATEGORY, '0-19', [], ValueError),
            ('a', 'browser', CATEGORY, '0-19', 'a'*61, ValueError),
            ('a', 'browser', CATEGORY, '0-19', 'a\nb', ValueError),
        ]:
            with self.subTest(option=option, author=author), self.assertRaises(error):
                pickem.submit(self.db, team, browser, category, option, author, now=NOW)
        self.assertEqual(self.board['ballots'], [])

    def test_sunday_2359_madrid_closes_and_monday_resets_both_quotas(self):
        closing = pickem.weeks.timestamp('2026-10-18T23:59')
        self.assertEqual(pickem.period(self.db, WEEK)['closesAt'], closing)
        self.submit(now=closing-.01)
        with self.assertRaises(FileExistsError): self.submit('browser2', now=closing)
        self.submit(now=pickem.weeks.timestamp('2026-10-19T00:00'))
        self.assertEqual(len(self.db['pickem']['weeks']), 2)
        self.assertEqual(len(self.board['ballots']), 1)
        dst = pickem.period(self.db, '2026-10-19')
        self.assertEqual(dst['closesAt'], pickem.weeks.timestamp('2026-10-25T23:59'))
        self.assertEqual(dst['endsAt']-dst['startsAt'], 7*86400+3600)

    def test_preseason_and_postseason_target_first_and_last_competition_week(self):
        self.assertEqual(pickem.ensure_week(self.db, NOW-86400*30)[0], WEEK)
        self.assertEqual(pickem.ensure_week(self.db, NOW+86400*50)[0], '2026-11-09')
        with self.assertRaises(FileExistsError): self.submit(now=NOW+86400*50)
        self.assertEqual(pickem.period(self.db, WEEK)['startsAt'], pickem.weeks.timestamp('2026-10-15T18:00'))

    def test_count_only_participants_with_unique_champions_games_and_time_bounds(self):
        outsider = {'puuid': 'outsider', 'championName': 'Teemo'}
        valid = game()
        valid['participants'] = [outsider]
        self.db['duos'][0]['history'] = [valid, game('2', 'Wukong', 'MonkeyKing'),
            {**game('3'), 'isTest': True}, {**game('4'), 'queueId': 450},
            game('5', at=pickem.weeks.timestamp('2026-10-15T17:59')),
            game('6', at=pickem.period(self.db, WEEK)['endsAt'])]
        self.db['duos'][1]['history'] = [copy.deepcopy(valid)]
        self.assertEqual(pickem.champion_count(self.db, self.board), {'value': 3, 'games': 2, 'pending': False})

    def test_known_absent_participant_is_allowed_but_incomplete_stats_block(self):
        match = game()
        match['player2Stats'] = None
        self.db['duos'][0]['history'] = [match]
        self.assertFalse(pickem.champion_count(self.db, self.board)['pending'])
        match['participantsChecked']['player2'] = False
        self.assertTrue(pickem.champion_count(self.db, self.board)['pending'])
        match['participantsChecked']['player2'] = True
        match['statsVersion'] = 1
        self.assertTrue(pickem.champion_count(self.db, self.board)['pending'])

    def test_settlement_requires_post_week_complete_scan_and_stable_roster(self):
        self.submit()
        self.db['duos'][0]['history'] = [game()]
        end = pickem.period(self.db, WEEK)['endsAt']
        self.assertFalse(pickem.maintain(self.db, end+900))
        pickem.record_complete_sync(self.db, copy.deepcopy(self.db), end+299, now=end+900)
        self.assertEqual(self.board['results'], {})
        original = copy.deepcopy(self.db)
        self.db['duos'][0]['player1']['name'] = 'Changed'
        self.assertFalse(pickem.record_complete_sync(self.db, original, end+300, now=end+900))
        self.assertEqual(self.board['results'], {})
        self.settle()
        self.assertEqual(self.board['results'][CATEGORY]['status'], 'SETTLED')

    def test_pending_imports_and_unknown_champions_delay_settlement(self):
        match = game(first='Unknown')
        self.db['duos'][0]['history'] = [match]
        self.settle()
        self.assertNotIn(CATEGORY, self.board['results'])
        match['player1Stats']['championName'] = 'Ahri'
        self.db['duos'][0]['riotMatchDiscovery'] = {'pendingMatchIds': ['EUW1_MISSING']}
        self.settle()
        self.assertNotIn(CATEGORY, self.board['results'])
        self.db['duos'][0]['riotMatchDiscovery']['pendingMatchIds'] = []
        self.settle()
        self.assertEqual(self.board['results'][CATEGORY]['value'], 2)

    def test_one_correct_category_does_not_pay_either_ballot(self):
        self.submit()
        self.submit('browser2')
        self.submit('browser3', team='b', option='20-29')
        self.db['duos'][0]['history'] = [game()]
        self.settle()
        self.assertEqual(self.db['duos'][0]['blueShells'], 5)
        self.assertEqual(self.db['duos'][0].get('pickemShellsEarnedTotal', 0), 0)
        self.assertEqual(len(self.db['events']), 0)
        restored = json.loads(json.dumps(self.db))
        self.settle(restored)
        self.assertFalse(pickem.maintain(restored, NOW+86400*30))
        self.assertEqual(restored['duos'][0]['blueShells'], 5)
        self.assertEqual(len(restored['events']), 0)

    def test_no_games_no_prize(self):
        self.submit()
        self.settle()
        self.assertEqual(self.board['results'][CATEGORY]['status'], 'NO_GAMES')
        self.assertEqual(self.db['duos'][0]['blueShells'], 5)

    def test_other_answers_are_hidden_until_close_and_browser_ids_never_exposed(self):
        self.submit('private-browser')
        before = pickem.public_board(self.db, now=NOW)
        self.assertEqual(before['predictions'], [])
        mine = pickem.public_board(self.db, 'a', 'private-browser', now=NOW)
        self.assertEqual(mine['myBallot']['answers'][CATEGORY], '0-19')
        after = pickem.public_board(self.db, now=pickem.period(self.db, WEEK)['closesAt'])
        self.assertEqual(len(after['predictions']), 1)
        for board in (before, mine, after):
            self.assertNotIn('private-browser', json.dumps(board))
            self.assertNotIn('visitor', json.dumps(board))

    def test_open_week_gets_new_categories_and_teams_without_resetting_existing_ballots(self):
        self.submit()
        self.board['categories'] = self.board['categories'][:1]
        self.db['duos'].append({'id':'new','teamName':'Nuevo','player1':{'name':'Nuevo1'},'player2':{'name':'Nuevo2'}})
        _, changed = pickem.ensure_week(self.db, NOW)
        self.assertTrue(changed)
        self.assertEqual(len(self.board['categories']), 6)
        self.assertEqual(len(self.board['ballots']), 1)
        team_category = next(c for c in self.board['categories'] if c['id']=='weekly_leader')
        player_category = next(c for c in self.board['categories'] if c['id']=='best_game_kda')
        self.assertEqual(len(team_category['options']), 3)
        self.assertEqual(len(player_category['options']), 6)
        pickem.submit(self.db,'a','browser1','weekly_leader','new',now=NOW)
        pickem.submit(self.db,'a','browser1','best_game_kda',player_category['options'][0]['id'],now=NOW)
        self.assertEqual(len(self.board['ballots']), 1)
        self.assertEqual(len(self.board['ballots'][0]['answers']), 3)
        self.board['categories'] = self.board['categories'][:1]
        pickem.ensure_week(self.db, pickem.period(self.db,WEEK)['closesAt'])
        self.assertEqual(len(self.board['categories']), 1, 'closed archives do not gain new categories')

    def test_team_leader_uses_preclose_elo_and_winrate_never_net_lp_or_monday_rank(self):
        a,b = self.db['duos']
        a.update(tier='Gold',division='II',lp=55,wins=1,losses=9,netLp=9999,rankObservedAt=NOW)
        b.update(tier='Emerald',division='IV',lp=0,wins=1,losses=9,netLp=-9999,rankObservedAt=NOW)
        pickem.ensure_week(self.db,NOW)
        pickem.submit(self.db,'a','browser1','weekly_leader','b',now=NOW)
        end = pickem.period(self.db,WEEK)['endsAt']
        a.update(tier='Challenger',lp=999,rankObservedAt=end+1)
        b.update(tier='Iron',lp=0,rankObservedAt=end+1)
        pickem.capture_rankings(self.db)
        self.settle()
        result = self.board['results']['weekly_leader']
        self.assertEqual(result['optionIds'], ['b'])
        self.assertNotIn('winners', result)
        self.assertEqual(self.db['duos'][0]['blueShells'], 5)
        self.assertLess(result['observedAt'], end)

    def test_leader_winrate_tiebreak_and_exact_ties_accept_both_teams(self):
        category = next(c for c in self.board['categories'] if c['id']=='weekly_leader')
        for d in self.db['duos']: d.update(tier='Gold',division='IV',lp=50,wins=5,losses=5,rankObservedAt=NOW)
        pickem.capture_rankings(self.db)
        self.assertEqual(set(pickem.weekly_leader(self.db,self.board,category)['optionIds']), {'a','b'})
        self.db['duos'][1].update(wins=6,rankObservedAt=NOW+1)
        pickem.capture_rankings(self.db)
        self.assertEqual(pickem.weekly_leader(self.db,self.board,category)['optionIds'], ['b'])

    def test_leader_missing_observation_voids_category_instead_of_using_postclose_elo(self):
        for d in self.db['duos']: d.update(tier='Gold',division='IV',lp=50,rankObservedAt=NOW+86400*6)
        pickem.capture_rankings(self.db)
        self.settle()
        self.assertEqual(self.board['results']['weekly_leader']['status'],'NO_DATA')
        self.assertEqual(self.db['duos'][0]['blueShells'], 5)

    def test_leader_snapshots_survive_daily_history_overwrite_and_exclude_initial_or_test_points(self):
        d = self.db['duos'][0]
        d['eloHistoryAccount'] = ['a1','']
        d['eloHistory'] = [{'tier':'Gold','lp':10,'observedAt':NOW,'source':'initial'},
                           {'tier':'Challenger','lp':99,'observedAt':NOW,'source':'test'}]
        self.assertFalse(pickem.capture_rankings(self.db))
        d['eloHistory'] = [{'tier':'Gold','division':'IV','lp':44,'observedAt':NOW,'source':'riot'}]
        self.assertTrue(pickem.capture_rankings(self.db))
        d['eloHistory'] = [{'tier':'Challenger','lp':99,'observedAt':NOW+86400*6,'source':'riot'}]
        pickem.capture_rankings(self.db)
        self.assertEqual(self.board['rankObservations']['a']['lp'],44)

    def test_replaced_first_account_cannot_reuse_legacy_team_rank(self):
        d = self.db['duos'][0]
        d.update(tier='Gold',division='IV',lp=50,rankObservedAt=NOW)
        pickem.capture_rankings(self.db)
        d['player1'].update(name='Other',rank=None)
        pickem.capture_rankings(self.db)
        self.assertNotEqual(self.board['rankObservations']['a']['account'],pickem.account(d['player1']))

    def first_five_category(self):
        return next(c for c in self.board['categories'] if c['id']=='first_five_negative')

    def first_games(self, duo, wins, start=NOW):
        # Stored newest-first, as real Riot imports are. The fifth result is still chronological.
        duo['history'] = [{**game(f"{duo['id']}-{i}",at=start+i*100),
                           'result':'WIN' if i<wins else 'LOSS'} for i in reversed(range(5))]
        return duo['history']

    def test_first_five_options_cover_zero_through_nine_and_only_opening_week_has_category(self):
        self.assertEqual([o['id'] for o in self.first_five_category()['options']],[str(i) for i in range(10)])
        pickem.submit(self.db,'a','browser','first_five_negative','0',now=NOW)
        self.assertEqual(self.board['ballots'][0]['answers']['first_five_negative'],'0')
        for value in ('10','-1',0,True):
            with self.subTest(value=value),self.assertRaises(ValueError):
                pickem.submit(self.db,'b','other','first_five_negative',value,now=NOW)
        next_week,_ = pickem.ensure_week(self.db,pickem.weeks.timestamp('2026-10-19T00:00'))
        self.assertNotIn('first_five_negative',[c['id'] for c in self.db['pickem']['weeks'][next_week]['categories']])

    def test_first_five_negative_means_at_most_two_wins_not_overall_winrate(self):
        for wins in range(6):
            with self.subTest(wins=wins):
                for duo in self.db['duos']: self.first_games(duo,wins)
                # Later wins must not change the first five.
                self.db['duos'][0]['history'] += [{**game('later',at=NOW+1000),'result':'WIN'}]
                metric = pickem.first_five_negative(self.db,self.first_five_category(),now=NOW+2000)
                self.assertEqual(metric['value'],2 if wins<3 else 0)
                self.assertEqual(metric['evidence'][0]['wins'],wins)
                self.assertEqual(metric['evidence'][0]['winrate'],wins*20)

    def test_first_five_orders_deduplicates_and_filters_test_nonranked_outside_tournament(self):
        for duo in self.db['duos']: self.first_games(duo,2)
        duo = self.db['duos'][0]
        duo['history'] += [copy.deepcopy(duo['history'][0]),
                          {**game('before',at=NOW-86400),'result':'WIN'},
                          {**game('test',at=NOW-1),'result':'WIN','isTest':True},
                          {**game('aram',at=NOW-1),'result':'WIN','queueId':450},
                          {**game('after',at=pickem.weeks.timestamp(self.db['config']['endDate'])),'result':'WIN'}]
        metric=pickem.first_five_negative(self.db,self.first_five_category(),now=NOW+2000)
        self.assertEqual(metric['value'],2)
        self.assertEqual(metric['evidence'][0]['matchIds'],[f'a-{i}' for i in range(5)])

    def test_first_five_waits_for_incomplete_teams_and_can_finish_in_a_later_week(self):
        self.first_games(self.db['duos'][0],2)
        self.first_games(self.db['duos'][1],3)
        last=self.db['duos'][1]['history'].pop(0)
        category=self.first_five_category()
        self.assertTrue(pickem.first_five_negative(self.db,category,now=NOW+86400*6)['pending'])
        last['gameEndTimestamp']=(NOW+86400*6)*1000
        self.db['duos'][1]['history'].append(last)
        metric=pickem.first_five_negative(self.db,category,now=NOW+86400*6+1)
        self.assertEqual(metric['value'],1)

    def test_first_five_unknown_result_or_pending_import_cannot_be_skipped(self):
        for duo in self.db['duos']: self.first_games(duo,2)
        missing=self.db['duos'][0]['history'][0]
        missing.pop('result')
        category=self.first_five_category()
        self.db['duos'][0]['history'].insert(0,{**game('sixth',at=NOW+1000),'result':'WIN'})
        self.assertTrue(pickem.first_five_negative(self.db,category,now=NOW+2000)['pending'])
        missing['result']='LOSS'
        self.db['duos'][1]['riotMatchDiscovery']={'pendingMatchIds':['earlier-missing']}
        self.assertTrue(pickem.first_five_negative(self.db,category,now=NOW+2000)['pending'])

    def test_first_five_incomplete_teams_excluded_only_after_final_tournament_scan(self):
        self.first_games(self.db['duos'][0],2)
        self.first_games(self.db['duos'][1],0)
        self.db['duos'][1]['history'].pop()
        category=self.first_five_category()
        end=pickem.weeks.timestamp(self.db['config']['endDate'])
        self.assertTrue(pickem.first_five_negative(self.db,category,now=end+600)['pending'])
        self.db['pickem']['lastCompleteSync']={'startedAt':end+300}
        metric=pickem.first_five_negative(self.db,category,now=end+600)
        self.assertEqual(metric['value'],1)
        self.assertFalse(metric['evidence'][1]['completed'])
        self.assertNotIn('negative',metric['evidence'][1])

    def test_first_five_alone_does_not_reward_either_ballot(self):
        for duo in self.db['duos']: self.first_games(duo,2)
        for browser in ('one','two'):
            pickem.submit(self.db,'a',browser,'first_five_negative','2',now=NOW)
        self.settle()
        result=self.board['results']['first_five_negative']
        self.assertEqual(result['value'],2)
        self.assertNotIn('winners', result)
        self.assertEqual(self.db['duos'][0]['blueShells'],5)
        self.settle()
        self.assertEqual(self.db['duos'][0]['blueShells'],5)

    def test_first_five_can_count_all_nine_teams(self):
        self.db['duos']=[{'id':str(i),'teamName':f'Equipo {i}'} for i in range(9)]
        for duo in self.db['duos']: self.first_games(duo,0)
        pickem.ensure_week(self.db,NOW)
        metric=pickem.first_five_negative(self.db,self.first_five_category(),now=NOW+2000)
        self.assertEqual(metric['value'],9)
        self.assertEqual(metric['optionIds'],['9'])

    def add_kda_game(self, mid, first, second, at=NOW):
        match = game(mid,at=at)
        for key, totals in zip(('player1','player2'),(first,second)):
            match[key+'Stats'].update(zip(('kills','deaths','assists'),totals))
            self.db['duos'][0][key]['puuid'] = match[key+'Stats']['puuid']
        self.db['duos'][0]['history'].append(match)
        pickem.ensure_week(self.db,NOW)
        return match

    def test_best_kda_is_single_player_single_game_with_safe_zero_deaths_and_exact_ties(self):
        self.add_kda_game('1',(0,1,9),(10,0,0))  # P2 10 KDA; not infinity.
        self.add_kda_game('2',(1,1,9),(0,5,0))  # P1 also 10 in one game.
        self.add_kda_game('3',(0,1,0),(1,1,0),at=NOW-86400*30)  # Excluded.
        category = next(c for c in self.board['categories'] if c['id']=='best_game_kda')
        metric = pickem.best_game_kda(self.db,self.board,category)
        self.assertEqual(metric['value'],10)
        self.assertEqual(len(metric['optionIds']),2)
        self.assertEqual({e['matchId'] for e in metric['evidence']},{'1','2'})
        for i,option in enumerate(metric['optionIds']):
            pickem.submit(self.db,'a',f'browser{i}','best_game_kda',option,now=NOW)
        self.settle()
        self.assertEqual(self.db['duos'][0]['blueShells'],5)
        self.assertNotIn('winners', self.board['results']['best_game_kda'])
        self.settle()
        self.assertEqual(self.db['duos'][0]['blueShells'],5)

    def test_best_kda_compares_exact_ratios_not_rounded_values_or_combined_duo_scores(self):
        self.add_kda_game('1',(1,3,0),(1,4,0))
        self.add_kda_game('2',(1,3,0),(334,1000,0))
        category = next(c for c in self.board['categories'] if c['id']=='best_game_kda')
        metric = pickem.best_game_kda(self.db,self.board,category)
        self.assertEqual(len(metric['optionIds']),1)
        self.assertEqual(metric['evidence'][0]['kills'],334)
        self.assertEqual(metric['evidence'][0]['matchId'],'2')

    def test_best_kda_missing_stats_waits_and_account_replacement_cannot_inherit_prediction(self):
        match = self.add_kda_game('1',(1,1,0),(1,2,0))
        category = next(c for c in self.board['categories'] if c['id']=='best_game_kda')
        old = next(o for o in category['options'] if o['teamId']=='a' and o['playerKey']=='player1')
        pickem.submit(self.db,'a','browser1','best_game_kda',old['id'],now=NOW)
        match['player2Stats'].pop('kills')
        self.settle()
        self.assertNotIn('best_game_kda',self.board['results'])
        match['player2Stats']['kills'] = 1
        self.db['duos'][0]['player1'].update(name='Replacement',puuid='new-puuid')
        pickem.ensure_week(self.db,NOW)
        category = next(c for c in self.board['categories'] if c['id']=='best_game_kda')
        retired = next(o for o in category['options'] if o['id']==old['id'])
        self.assertTrue(retired['disabled'])
        with self.assertRaises(ValueError): pickem.submit(self.db,'b','browser2','best_game_kda',old['id'],now=NOW)
        metric = pickem.best_game_kda(self.db,self.board,category)
        self.assertEqual(metric['optionIds'],[old['id']])  # Previous account's real game stays with its original option.
        public = pickem.public_board(self.db,'a','browser1',now=NOW)
        for c in public['categories']:
            for option in c['options']:
                self.assertFalse({'account','puuid','playerKey'} & option.keys())


class OpeningDeathsDuelTests(unittest.TestCase):
    setUp = PickemServiceTests.setUp
    settle = PickemServiceTests.settle

    def category(self):
        return next(c for c in self.board['categories'] if c['id']=='joji_parradise_deaths')

    def add_game(self, team='a', deaths=5, mid='one', at=NOW, **extra):
        duo=next(d for d in self.db['duos'] if d['id']==team)
        key='player1' if team=='a' else 'player2'
        match=game(mid,at=at)
        match[key+'Stats'].update(deaths=deaths,riotIdGameName=duo[key]['name'],riotIdTagline='EUW')
        match.update(extra)
        duo['history'].append(match)
        return match

    def result(self):
        return pickem.opening_deaths_duel(self.db,self.board,self.category())

    def test_only_two_named_options_bound_to_real_players_and_opening_week_only(self):
        c=self.category()
        self.assertEqual([(o['id'],o['label']) for o in c['options']],[('joji','Joji'),('parradise','Parradise')])
        self.assertEqual(c['options'][0]['playerKey'],'player1')
        self.assertEqual(c['options'][1]['playerKey'],'player2')
        public=pickem.public_board(self.db,now=NOW)
        self.assertEqual(next(c for c in public['categories'] if c['id']=='joji_parradise_deaths')['options'],
                         [{'id':'joji','label':'Joji'},{'id':'parradise','label':'Parradise'}])
        key,_=pickem.ensure_week(self.db,NOW+7*86400)
        self.assertNotIn('joji_parradise_deaths',[c['id'] for c in self.db['pickem']['weeks'][key]['categories']])

    def test_sums_individual_deaths_not_kda_average_or_team_deaths(self):
        self.add_game(deaths=6)
        first=self.add_game(deaths=7,mid='two')
        first['player2Stats']['deaths']=100  # Joji's teammate does not count.
        self.add_game(team='b',deaths=10)
        result=self.result()
        self.assertEqual(result['optionIds'],['joji'])
        self.assertEqual([(t['deaths'],t['games']) for t in result['totals']],[(13,2),(10,1)])
        self.assertEqual(len(result['evidence']),3)
        self.assertIn('Joji: 13 muertes',result['summary'])
        self.add_game(team='b',deaths=5,mid='three')
        self.assertEqual(self.result()['optionIds'],['parradise'])

    def test_tie_accepts_both_including_real_zero_death_games(self):
        for deaths in (0,8):
            with self.subTest(deaths=deaths):
                self.setUp()
                self.add_game(deaths=deaths)
                self.add_game(team='b',deaths=deaths)
                self.assertEqual(self.result()['optionIds'],['joji','parradise'])

    def test_no_games_does_not_manufacture_a_zero_death_tie(self):
        self.assertEqual(self.result()['status'],'NO_GAMES')
        self.assertEqual(self.result()['optionIds'],[])

    def test_filters_first_week_boundaries_duplicates_tests_and_other_queues(self):
        end=pickem.period(self.db,WEEK)['endsAt']
        self.add_game(mid='old',at=NOW-86400,deaths=100)
        self.add_game(mid='late',at=end,deaths=100)
        self.add_game(mid='test',deaths=100,isTest=True)
        self.add_game(mid='aram',deaths=100,queueId=450)
        valid=self.add_game(mid='valid',deaths=2,at=end-.001)
        self.db['duos'][0]['history'].append(copy.deepcopy(valid))
        self.add_game(team='b',deaths=3)
        self.assertEqual(self.result()['optionIds'],['parradise'])
        self.assertEqual(self.result()['totals'][0]['deaths'],2)

    def test_missing_stats_or_pending_imports_wait_instead_of_guessing(self):
        match=self.add_game()
        for value in (None,-1,True,'5'):
            with self.subTest(value=value):
                match['player1Stats']['deaths']=value
                self.assertTrue(self.result()['pending'])
        match['player1Stats']['deaths']=5
        match['participantsChecked']['player1']=False
        self.assertTrue(self.result()['pending'])
        match['participantsChecked']['player1']=True
        self.db['duos'][1]['riotMatchDiscovery']={'pendingMatchIds':['missing']}
        self.assertTrue(self.result()['pending'])
        self.db['duos'][1]['riotMatchDiscovery']['pendingMatchIds']=[]
        self.assertEqual(self.result()['optionIds'],['joji'])

    def test_resolved_absence_is_not_a_zero_stat_match(self):
        match=self.add_game()
        match['player1Stats']=None
        self.add_game(team='b',deaths=3)
        result=self.result()
        self.assertEqual(result['totals'][0]['games'],0)
        self.assertEqual(result['optionIds'],['parradise'])

    def test_account_replacement_and_display_name_edits_do_not_rebind_guesses(self):
        first=self.add_game(deaths=7)
        first['player1Stats']['puuid']='original'
        self.db['duos'][0]['player1']['puuid']='original'
        pickem.ensure_week(self.db,NOW)
        old=copy.deepcopy(self.category()['options'][0])
        self.db['duos'][0]['player1'].update(name='Replacement',puuid='other',displayName='Otro')
        self.db['duos'][0]['player2']['displayName']='Joji'
        pickem.ensure_week(self.db,NOW)
        self.assertEqual(self.category()['options'][0],old)
        other=self.add_game(mid='replacement',deaths=100)
        other['player1Stats']['puuid']='other'
        self.add_game(team='b',deaths=3)
        self.assertEqual(self.result()['totals'][0]['deaths'],7)

    def test_missing_or_ambiguous_named_players_are_disabled_until_identified(self):
        for duo in self.db['duos']:
            for key in ('player1','player2'): duo[key]['displayName']='Joji'
        self.board['categories']=pickem.category_definitions(self.db,WEEK)
        self.assertTrue(all(o['disabled'] for o in self.category()['options']))
        self.assertEqual(self.result()['status'],'NO_DATA')
        with self.assertRaises(ValueError):
            pickem.submit(self.db,'a','browser','joji_parradise_deaths','joji',now=NOW)
        self.db['duos'][0]['player1']['displayName']='Joji'
        self.db['duos'][0]['player2']['displayName']='A2'
        self.db['duos'][1]['player1']['displayName']='B1'
        self.db['duos'][1]['player2']['displayName']='Parradise'
        pickem.ensure_week(self.db,NOW)
        self.assertTrue(all('account' in o and not o.get('disabled') for o in self.category()['options']))

    def test_settlement_uses_weekly_checkpoint_then_freezes_totals(self):
        pickem.submit(self.db,'a','browser','joji_parradise_deaths','joji',now=NOW)
        self.add_game(deaths=10)
        self.add_game(team='b',deaths=5)
        end=pickem.period(self.db,WEEK)['endsAt']
        self.assertFalse(pickem.maintain(self.db,end+1000))
        self.settle()
        result=copy.deepcopy(self.board['results']['joji_parradise_deaths'])
        self.assertEqual(result['optionIds'],['joji'])
        self.assertEqual(pickem.ballot_score(self.board,self.board['ballots'][0])['correct'],1)
        self.assertEqual(self.db['duos'][0]['blueShells'],5,'one correct category is not a prize')
        self.add_game(team='b',deaths=50,mid='next-week',at=end+100)
        self.settle()
        self.assertEqual(self.board['results']['joji_parradise_deaths'],result)


class FirstIndividualShellTests(unittest.TestCase):
    setUp = PickemServiceTests.setUp
    settle = PickemServiceTests.settle

    def category(self):
        return next(c for c in self.board['categories'] if c['id']=='first_individual_shell')

    def player(self, key='player1', team='a'):
        return next(o for o in self.category()['options'] if o['teamId']==team and o['playerKey']==key)

    def add_game(self, mid='first', at=NOW, team='a', first=None, second=None, **extra):
        duo=next(d for d in self.db['duos'] if d['id']==team)
        match=game(mid,at=at)
        match.update(pentaKill=False,result='LOSS')
        for key,totals in [('player1',first),('player2',second)]:
            stats=match[key+'Stats']
            stats.update(kills=1,deaths=1,assists=1,pentaKills=0,largestMultiKill=1)
            stats['puuid']=team+'-'+key
            if totals: stats.update(totals)
            duo[key]['puuid']=stats['puuid']
        match.update(extra)
        duo['history'].append(match)
        pickem.ensure_week(self.db,NOW)
        return match

    def result(self, at=NOW+86400*5):
        return pickem.first_individual_shell(self.db,self.category(),now=at)

    def test_opening_week_only_and_dropdown_contains_all_eighteen_people(self):
        self.db['duos']=[{'id':str(i),'teamName':f'Equipo {i}',
            'player1':{'name':f'Account{i}A','displayName':f'Persona {i}A'},
            'player2':{'name':f'Account{i}B','displayName':f'Persona {i}B'}} for i in range(9)]
        self.board['categories']=pickem.category_definitions(self.db,WEEK)
        pickem.ensure_week(self.db,NOW)
        self.assertEqual(len(self.category()['options']),18)
        self.assertEqual(len({o['id'] for o in self.category()['options']}),18)
        self.assertTrue(all(o['label'].startswith('Persona') for o in self.category()['options']))
        public=pickem.public_board(self.db,now=NOW)
        c=next(c for c in public['categories'] if c['id']=='first_individual_shell')
        self.assertTrue(all(set(o)=={'id','label'} for o in c['options']))
        key,_=pickem.ensure_week(self.db,NOW+7*86400)
        self.assertNotIn('first_individual_shell',[c['id'] for c in self.db['pickem']['weeks'][key]['categories']])

    def test_each_exact_threshold_and_pentakill_fallback_for_either_member(self):
        cases=[({'pentaKills':1},'penta'),({'largestMultiKill':5},'penta'),
               ({'kills':20},'kills'),({'assists':30},'assists'),
               ({'kills':10,'assists':11,'deaths':0},'perfect')]
        for key in ('player1','player2'):
            for stats,criterion in cases:
                with self.subTest(key=key,stats=stats):
                    self.setUp()
                    self.add_game(**{'first' if key=='player1' else 'second':stats})
                    result=self.result()
                    self.assertEqual(result['optionIds'],[self.player(key)['id']])
                    self.assertIn(criterion,result['evidence'][0]['criteria'])
                    self.assertEqual(result['evidence'][0]['matchId'],'first')

    def test_not_combined_stats_no_streak_clips_or_pickem_and_no_win_requirement(self):
        self.add_game(first={'kills':10,'assists':15,'deaths':1},second={'kills':10,'assists':15,'deaths':1},
                      shellRewardIds=['streak'],shellRewardCredits={'streak':True})
        self.db['events']=[{'type':'PICKEM_REWARD','teamId':'a'}, {'type':'CLIP_REWARD','teamId':'a'}]
        self.assertTrue(self.result()['pending'])
        self.db['duos'][0]['history'][0]['player2Stats']['kills']=20
        self.assertEqual(self.result()['optionIds'],[self.player('player2')['id']])

    def test_perfect_requires_strictly_more_than_twenty_and_zero_deaths(self):
        for stats in ({'kills':10,'assists':10,'deaths':0},{'kills':10,'assists':11,'deaths':1},
                      {'kills':19,'assists':29,'deaths':1}):
            with self.subTest(stats=stats):
                self.setUp()
                self.add_game(first=stats)
                self.assertTrue(self.result()['pending'])

    def test_earliest_game_end_wins_regardless_of_import_order_inventory_or_ledger(self):
        self.add_game('late',at=NOW+100,first={'kills':25})
        self.add_game('early',at=NOW,team='b',second={'assists':30},shellRewardIds=[],shellRewardCredits={})
        self.db['duos'][1]['blueShells']=99
        result=self.result()
        self.assertEqual(result['optionIds'],[self.player('player2','b')['id']])
        self.assertEqual(result['firstAt'],NOW)
        self.assertEqual(result['evidence'][0]['matchId'],'early')

    def test_tied_members_and_same_end_time_in_other_games_are_all_valid(self):
        self.add_game(first={'kills':20},second={'assists':30})
        self.add_game('same',team='b',first={'pentaKills':1})
        # Duplicate imports must not duplicate the evidence or the number of aciertos.
        self.db['duos'][0]['history']*=2
        result=self.result()
        self.assertEqual(set(result['optionIds']),{self.player()['id'],self.player('player2')['id'],self.player(team='b')['id']})
        self.assertEqual(len(result['evidence']),3)

    def test_test_other_queue_outside_tournament_and_future_matches_are_ignored(self):
        for mid,extra in [('test',{'isTest':True}),('aram',{'queueId':450}),
                          ('old',{'at':NOW-86400}),('future',{'at':NOW+86400*6}),
                          ('post',{'at':pickem.weeks.timestamp(self.db['config']['endDate'])})]:
            self.add_game(mid,first={'pentaKills':1},**extra)
        self.assertTrue(self.result()['pending'])
        self.add_game('valid',second={'kills':20})
        self.assertEqual(self.result()['optionIds'],[self.player('player2')['id']])

    def test_incomplete_earlier_game_or_pending_discovery_blocks_premature_winner(self):
        early=self.add_game('early',first={'kills':2})
        self.add_game('later',at=NOW+100,second={'assists':30})
        del early['player1Stats']['deaths']
        self.assertTrue(self.result()['pending'])
        early['player1Stats']['deaths']=1
        self.db['duos'][1]['riotMatchDiscovery']={'pendingMatchIds':['missing']}
        self.assertTrue(self.result()['pending'])
        self.db['duos'][1]['riotMatchDiscovery']['pendingMatchIds']=[]
        self.assertEqual(self.result()['optionIds'],[self.player('player2')['id']])

    def test_team_penta_flag_waits_for_personal_evidence_then_names_correct_member(self):
        match=self.add_game(pentaKill=True)
        for key in ('player1Stats','player2Stats'):
            del match[key]['pentaKills'];del match[key]['largestMultiKill']
        self.assertTrue(self.result()['pending'])
        self.assertTrue(server.needs_match_details({**match,'matchDetailsVersion':1}))
        match['player1Stats'].update(pentaKills=0,largestMultiKill=2)
        match['player2Stats'].update(pentaKills=1,largestMultiKill=5)
        self.assertFalse(server.needs_match_details({**match,'matchDetailsVersion':1}))
        self.assertEqual(self.result()['optionIds'],[self.player('player2')['id']])

    def test_legacy_no_penta_flag_false_is_enough_to_rule_out_pentakills(self):
        match=self.add_game(first={'kills':20})
        for key in ('player1Stats','player2Stats'):
            del match[key]['pentaKills'];del match[key]['largestMultiKill']
        self.assertEqual(self.result()['optionIds'],[self.player()['id']])
        self.assertFalse(server.needs_match_details({**match,'matchDetailsVersion':1}))

    def test_absent_second_member_is_allowed_but_unchecked_presence_is_pending(self):
        match=self.add_game(first={'kills':20})
        match['player2Stats']=None
        self.assertEqual(self.result()['optionIds'],[self.player()['id']])
        match['participantsChecked']['player2']=False
        self.assertTrue(self.result()['pending'])

    def test_replaced_account_cannot_inherit_old_participants_first_shell(self):
        match=self.add_game(first={'kills':20})
        original=self.player()['id']
        self.db['duos'][0]['player1'].update(name='Replacement',puuid='new')
        pickem.ensure_week(self.db,NOW)
        self.assertTrue(next(o for o in self.category()['options'] if o['id']==original)['disabled'])
        self.assertEqual(self.result()['optionIds'],[original])

    def test_no_achievement_stays_pending_then_resolves_once_in_a_later_week(self):
        pickem.submit(self.db,'a','browser','first_individual_shell',self.player('player2')['id'],now=NOW)
        self.settle()
        self.assertNotIn('first_individual_shell',self.board['results'])
        later=NOW+86400*8
        self.add_game('next-week',at=later,second={'kills':20})
        pickem.record_complete_sync(self.db,copy.deepcopy(self.db),later+1,now=later+10)
        self.assertEqual(self.board['results']['first_individual_shell']['optionIds'],[self.player('player2')['id']])
        self.assertEqual(self.db['duos'][0]['blueShells'],5,'one correct category alone does not pay')
        before=copy.deepcopy(self.board['results']['first_individual_shell'])
        self.settle()
        self.assertEqual(self.board['results']['first_individual_shell'],before)

    def test_no_one_qualifies_only_voids_after_complete_post_tournament_scan(self):
        self.add_game()
        end=pickem.weeks.timestamp(self.db['config']['endDate'])
        self.assertTrue(self.result(at=end+1000)['pending'])
        self.db['pickem']['lastCompleteSync']={'startedAt':end+pickem.SETTLEMENT_GRACE}
        self.assertEqual(self.result(at=end+1000)['status'],'NO_GAMES')

    def test_enriched_penta_is_third_correct_answer_and_gives_one_prize(self):
        match=self.add_game(pentaKill=True)
        for key in ('player1Stats','player2Stats'):
            match[key].pop('pentaKills');match[key].pop('largestMultiKill')
        self.assertTrue(server.needs_match_details({**match,'matchDetailsVersion':1}))
        info={'queueId':420,'participants':[
            {'puuid':'a-player1','kills':1,'deaths':2,'assists':1,'pentaKills':0,'largestMultiKill':1},
            {'puuid':'a-player2','kills':8,'deaths':2,'assists':1,'pentaKills':1,'largestMultiKill':5}]}
        server.enrich_match_record(match,info,'a-player1','a-player2')
        self.assertFalse(server.needs_match_details(match))
        for d in self.db['duos']:
            d.update(tier='Gold',division='IV',lp=50,wins=5,losses=5,rankObservedAt=NOW)
        pickem.ensure_week(self.db,NOW)
        for category,option in [('unique_champions','0-19'),('weekly_leader','a'),
                                ('first_individual_shell',self.player('player2')['id'])]:
            pickem.submit(self.db,'a','browser',category,option,now=NOW)
        # Champion names are present on real Match-V5 participants.
        match['player1Stats']['championName']='Ahri'
        match['player2Stats']['championName']='Lux'
        self.settle()
        self.assertEqual(self.board['results']['first_individual_shell']['optionIds'],[self.player('player2')['id']])
        self.assertEqual(self.db['duos'][0]['blueShells'],6)
        self.assertEqual(len(self.db['events']),1)
        self.assertEqual(self.db['events'][0]['correct'],3)

    def test_riot_parser_keeps_individual_pentakill_and_multikill_fields(self):
        first=server.participant_stats({'pentaKills':1,'largestMultiKill':5})
        second=server.participant_stats({'pentaKills':0,'largestMultiKill':3})
        self.assertEqual((first['pentaKills'],first['largestMultiKill']),(1,5))
        self.assertEqual((second['pentaKills'],second['largestMultiKill']),(0,3))


class PickemWeeklyRewardTests(unittest.TestCase):
    setUp = PickemServiceTests.setUp
    settle = PickemServiceTests.settle
    add_kda_game = PickemServiceTests.add_kda_game
    def prepare_scores(self, count=6, correct=3, browser='one', team='a'):
        self.board['categories'] = [{'id':f'cat{i}', 'options':[{'id':'yes','label':'Sí'},{'id':'no','label':'No'}]} for i in range(count)]
        ballot = {'id':browser, 'visitor':browser, 'teamId':team, 'teamName':'Equipo '+team.upper(),
                  'author':'Autor', 'createdAt':NOW, 'answers':{f'cat{i}':'yes' if i<correct else 'no' for i in range(count)}}
        self.board['ballots'].append(ballot)
        return ballot

    def resolve(self, pending=(), void=()):
        def result(db, board, category, now):
            if category['id'] in pending: return {'pending':True}
            return {'status':'NO_DATA' if category['id'] in void else 'SETTLED',
                    'optionIds':[] if category['id'] in void else ['yes'], 'summary':'Resultado'}
        with patch.object(pickem, 'category_result', side_effect=result):
            self.settle()

    def test_zero_through_six_correct_answers_give_at_most_one_shell(self):
        for correct in range(7):
            with self.subTest(correct=correct):
                self.setUp()
                self.prepare_scores(correct=correct)
                self.resolve()
                amount = int(correct>=3)
                self.assertEqual(self.db['duos'][0]['blueShells'],5+amount)
                self.assertEqual(self.db['duos'][0].get('pickemShellsEarnedTotal',0),amount)
                self.assertEqual(len(self.db['events']),amount)
                reward = self.board['ballotRewards']['one']
                self.assertEqual(reward['correct'],correct)
                self.assertEqual(reward['shells'],amount)
                self.assertEqual(reward['status'],'AWARDED' if amount else 'NO_REWARD')
                self.resolve()
                restored = json.loads(json.dumps(self.db))
                self.settle(restored)
                self.assertEqual(restored['duos'][0]['blueShells'],5+amount)
                self.assertEqual(len(restored['events']),amount)

    def test_team_ballots_are_independent_and_cannot_pool_answers(self):
        for scores,expected in [((2,2),0),((3,2),1),((3,6),2)]:
            with self.subTest(scores=scores):
                self.setUp()
                for i,correct in enumerate(scores): self.prepare_scores(correct=correct,browser=str(i))
                self.resolve()
                self.assertEqual(self.db['duos'][0]['blueShells'],5+expected)
                self.assertEqual(len({e['id'] for e in self.db['events']}),expected)

    def test_pending_third_correct_waits_then_rewards_once_in_later_week(self):
        self.prepare_scores(correct=3)
        self.resolve(pending=('cat2',))
        self.assertEqual(self.db['duos'][0]['blueShells'],5)
        self.assertNotIn('one',self.board['ballotRewards'])
        self.resolve()
        self.assertEqual(self.db['duos'][0]['blueShells'],6)
        self.resolve()
        self.assertEqual(len(self.db['events']),1)

    def test_three_confirmed_correct_pay_even_with_other_categories_pending(self):
        self.prepare_scores(correct=6)
        self.resolve(pending=('cat3','cat4','cat5'))
        self.assertEqual(self.db['duos'][0]['blueShells'],6)
        self.resolve()
        self.assertEqual(self.db['duos'][0]['blueShells'],6)
        self.assertEqual(len(self.db['events']),1)
        public=pickem.public_board(self.db,'a','one',now=NOW+86400*5)
        self.assertEqual(public['predictions'][0]['correct'],6)
        self.assertEqual(public['predictions'][0]['reward']['shells'],1)

    def test_no_data_and_unanswered_categories_do_not_count_as_correct(self):
        ballot=self.prepare_scores(correct=6)
        del ballot['answers']['cat0']
        self.resolve(void=('cat1','cat2','cat3'))
        self.assertEqual(self.board['ballotRewards']['one']['correct'],2)
        self.assertEqual(self.db['duos'][0]['blueShells'],5)

    def test_removed_team_does_not_receive_reward(self):
        self.prepare_scores(correct=6)
        self.db['duos']=self.db['duos'][1:]
        self.resolve()
        self.assertEqual(self.board['ballotRewards']['one']['shells'],0)
        self.assertEqual(self.db['events'],[])

    def test_existing_open_week_migrates_without_losing_ballots(self):
        ballot=self.prepare_scores(correct=3)
        del self.board['rewardRule']
        del self.board['ballotRewards']
        for c in self.board['categories']: c['reward']=1
        self.resolve()
        self.assertEqual(self.board['rewardRule'],{'minCorrect':3,'shells':1})
        self.assertEqual(self.board['ballots'][0],ballot)
        self.assertEqual(self.db['duos'][0]['blueShells'],6)
        public=pickem.public_board(self.db,now=NOW+86400*5)
        self.assertEqual(public['rewardRule'],pickem.REWARD_RULE)
        self.assertTrue(all('reward' not in c for c in public['categories']))

    def test_legacy_paid_prizes_are_preserved_without_extra_payment(self):
        self.prepare_scores(correct=6)
        del self.board['rewardRule']
        del self.board['ballotRewards']
        self.board['results']['cat0']={'status':'SETTLED','optionIds':['yes'],'settledAt':NOW,
            'winners':[{'ballotId':'one','shells':1}]}
        self.db['duos'][0]['blueShells']=6
        self.resolve()
        self.assertEqual(self.db['duos'][0]['blueShells'],6)
        self.assertTrue(self.board['ballotRewards']['one']['legacy'])
        self.assertEqual(self.db['events'],[])

    def test_real_three_categories_give_one_prize_not_three(self):
        for d in self.db['duos']: d.update(tier='Gold',division='IV',lp=50,wins=5,losses=5,rankObservedAt=NOW)
        self.add_kda_game('real',(10,1,10),(1,5,0))
        c=next(c for c in self.board['categories'] if c['id']=='best_game_kda')
        player=next(o for o in c['options'] if o['teamId']=='a' and o['playerKey']=='player1')
        for category,option in [('unique_champions','0-19'),('weekly_leader','a'),('best_game_kda',player['id'])]:
            pickem.submit(self.db,'a','browser',category,option,now=NOW)
        self.settle()
        self.assertEqual(self.db['duos'][0]['blueShells'],6)
        self.assertEqual(len(self.db['events']),1)
        self.assertEqual(self.db['events'][0]['correct'],3)
        self.assertNotIn('first_five_negative',self.board['results'])


class PickemEndpointTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.object(server, 'remote_backend', None).start()
        patch.object(server.CustomHandler, 'log_message', return_value=None).start()
        patch.object(pickem.time, 'time', return_value=NOW).start()
        fixtures.ShellEndpointTests.setUp(self)
        db = server.load_db()
        db['config'].update(database()['config'])
        db['duos'][0]['player1']['displayName']='Joji'
        db['duos'][1]['player2']['displayName']='Parradise'
        server.save_db(db)

    tearDown = fixtures.ShellEndpointTests.tearDown
    client = tierlist_tests.TierlistEndpointTests.client
    login = tierlist_tests.TierlistEndpointTests.login

    def call(self, client, data=None, headers=None, status=200, path='/api/pickem'):
        return tierlist_tests.TierlistEndpointTests.call(self, client, data, headers, status, path)

    def payload(self):
        return {'week': WEEK, 'categoryId': CATEGORY, 'optionId': '0-19', 'teamId': 'b'}

    def test_cookie_team_auth_csrf_and_week_restrictions(self):
        client, _ = self.client()
        board, headers = self.call(client, headers={'X-Forwarded-Proto': 'https'})
        for part in ('pepes_pickem_visitor=', 'HttpOnly', 'SameSite=Lax', 'Secure'):
            self.assertIn(part, headers['Set-Cookie'])
        # Secure cookie is correctly unavailable over HTTP; use a fresh ordinary local client.
        client, _ = self.client()
        self.call(client, self.payload(), status=401)
        auth = self.login(client)
        self.call(client, self.payload(), {**auth, 'Origin': 'https://evil.test'}, status=403)
        fresh, _ = self.client()
        self.call(fresh, self.payload(), auth, status=400)
        self.call(client, {**self.payload(), 'week': '2026-10-05'}, auth, status=409)
        result, _ = self.call(client, self.payload(), auth)
        self.assertEqual(result['participation']['teamId'], 'a')
        server.player_sessions.clear()
        self.call(client, self.payload(), auth, status=401)
        for path in ('/pickem.html', '/pickem.js', '/pickem.css'):
            with client.open(self.base+path) as response: self.assertEqual(response.status, 200)
        self.call(client, path='/pickem_service.py', status=404)

    def test_failed_save_does_not_consume_attempt_and_retries_are_idempotent(self):
        client, _ = self.client()
        auth = self.login(client)
        with patch.object(server, 'save_db', side_effect=StorageError('Unavailable')):
            self.call(client, self.payload(), auth, status=503)
        self.assertEqual(self.call(client, headers=auth)[0]['entries'], 0)
        self.call(client, self.payload(), auth)
        self.call(client, self.payload(), auth)
        self.assertEqual(self.call(client)[0]['entries'], 1)
        self.call(client, {**self.payload(), 'optionId': '20-29'}, auth, status=409)
        raw = json.loads(Path(server.DB_FILE).read_text(encoding='utf-8'))
        self.assertEqual(len(raw['pickem']['weeks'][WEEK]['ballots'][0]['visitor']), 64)

    def test_all_registered_choices_are_available_and_six_answers_use_one_ballot(self):
        client, _ = self.client()
        auth = self.login(client)
        board, _ = self.call(client, headers=auth)
        categories = {c['id']:c for c in board['categories']}
        self.assertEqual({o['id'] for o in categories['weekly_leader']['options']}, {'a','b'})
        self.assertEqual(len(categories['best_game_kda']['options']), 4)
        for c in board['categories']:
            result, _ = self.call(client, {'week':WEEK,'categoryId':c['id'],'optionId':c['options'][0]['id']}, auth)
            self.assertEqual(result['entries'], 1)
        self.assertEqual(len(result['myBallot']['answers']), 6)
        self.assertEqual(self.call(client)[0]['predictions'], [])

    def test_concurrent_requests_cannot_spend_a_third_team_ballot(self):
        client, _ = self.client()
        auth = self.login(client)
        self.call(client, self.payload(), auth)
        clients = [self.client()[0] for _ in range(2)]
        for client in clients: self.call(client)
        barrier = threading.Barrier(2)
        # Inspect statuses without an assertion tied to request order.
        def request(client):
            import urllib.request
            import urllib.error
            barrier.wait()
            req = urllib.request.Request(self.base+'/api/pickem', data=json.dumps(self.payload()).encode(),
                                         headers={'Content-Type':'application/json', **auth})
            try:
                with client.open(req, timeout=5) as response: return response.status
            except urllib.error.HTTPError as error: return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(request, clients)), [200, 409])
        self.assertEqual(self.call(client)[0]['entries'], 2)

    def test_full_riot_import_resolves_after_close_but_one_correct_does_not_pay(self):
        client, _ = self.client()
        auth = self.login(client)
        self.call(client, self.payload(), auth)
        riot_tests.IncrementalSyncTests.prepare(self)
        end = pickem.period(server.load_db(), WEEK)['endsAt']
        payload = riot_tests.detail()
        payload['info']['gameStartTimestamp'] = (NOW-600)*1000
        payload['info']['gameEndTimestamp'] = NOW*1000
        for failure in ({'EUW1_NEW'}, set()):
            calls = []
            responder = riot_tests.IncrementalSyncTests.responses(self, ['EUW1_NEW'], calls, fail_once=failure)
            with patch.object(pickem.time, 'time', return_value=end+600), \
                 patch.object(server, 'get_riot_api_key', return_value='fake'), \
                 patch.object(server, 'riot_open', side_effect=responder), \
                 patch.object(riot_tests, 'detail', return_value=payload), patch.object(server.time, 'sleep'):
                result = server.sync_riot_data()
            db = server.load_db()
            settled = db['pickem']['weeks'][WEEK]['results'].get(CATEGORY)
            if not result['success']:
                self.assertIsNone(settled)
                self.assertNotIn('lastCompleteSync', db['pickem'])
            else:
                self.assertEqual(settled['value'], 2)
                self.assertNotIn('winners', settled)
                self.assertEqual(db['duos'][0]['blueShells'], 1)
                self.assertEqual(sum(e['type']=='PICKEM_REWARD' for e in db['events']), 0)
                self.assertEqual(sum('/ids?' in url for url in calls), 1)


if __name__ == '__main__': unittest.main()
