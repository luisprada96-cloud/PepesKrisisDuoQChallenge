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
                      'player1': {'name': 'A1'}, 'player2': {'name': 'A2'}, 'history': []},
                     {'id': 'b', 'teamName': 'Equipo B', 'player1': {'name': 'B1'},
                      'player2': {'name': 'B2'}, 'history': []}], 'events': []}


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

    def test_late_imported_matches_count_and_two_winners_can_exceed_inventory_cap(self):
        self.submit()
        self.submit('browser2')
        self.submit('browser3', team='b', option='20-29')
        self.db['duos'][0]['history'] = [game()]
        self.settle()
        self.assertEqual(self.db['duos'][0]['blueShells'], 7)
        self.assertEqual(self.db['duos'][0]['pickemShellsEarnedTotal'], 2)
        self.assertEqual(len(self.db['events']), 2)
        restored = json.loads(json.dumps(self.db))
        self.settle(restored)
        self.assertFalse(pickem.maintain(restored, NOW+86400*30))
        self.assertEqual(restored['duos'][0]['blueShells'], 7)
        self.assertEqual(len(restored['events']), 2)

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
        self.assertEqual(len(self.board['categories']), 3)
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
        self.assertEqual(len(result['winners']), 1)
        self.assertEqual(self.db['duos'][0]['blueShells'], 6)
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
        self.assertEqual(self.db['duos'][0]['blueShells'],7)
        self.assertEqual(len(self.board['results']['best_game_kda']['winners']),2)
        self.settle()
        self.assertEqual(self.db['duos'][0]['blueShells'],7)

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


class PickemEndpointTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.object(server, 'remote_backend', None).start()
        patch.object(server.CustomHandler, 'log_message', return_value=None).start()
        patch.object(pickem.time, 'time', return_value=NOW).start()
        fixtures.ShellEndpointTests.setUp(self)
        db = server.load_db()
        db['config'].update(database()['config'])
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

    def test_all_registered_choices_are_available_and_three_answers_use_one_ballot(self):
        client, _ = self.client()
        auth = self.login(client)
        board, _ = self.call(client, headers=auth)
        categories = {c['id']:c for c in board['categories']}
        self.assertEqual({o['id'] for o in categories['weekly_leader']['options']}, {'a','b'})
        self.assertEqual(len(categories['best_game_kda']['options']), 4)
        for c in board['categories']:
            result, _ = self.call(client, {'week':WEEK,'categoryId':c['id'],'optionId':c['options'][0]['id']}, auth)
            self.assertEqual(result['entries'], 1)
        self.assertEqual(len(result['myBallot']['answers']), 3)
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

    def test_full_riot_import_awards_after_close_but_failed_scan_cannot_settle(self):
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
                self.assertEqual(len(settled['winners']), 1)
                self.assertEqual(db['duos'][0]['blueShells'], 2)
                self.assertEqual(sum(e['type']=='PICKEM_REWARD' for e in db['events']), 1)
                self.assertEqual(sum('/ids?' in url for url in calls), 1)


if __name__ == '__main__': unittest.main()
