"""A tournament game must contain one registered account of each teammate."""
import copy
import io
import json
import unittest
import urllib.error
from collections import Counter
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse, unquote

import player_accounts as accounts
import riot_match_policy as policy
import server
import test_player_accounts as multi


def game(first='p1', second='p2', team1=100, team2=100, queue=420):
    participants = []
    for i, (uid, team) in enumerate(((first, team1), (second, team2)), 1):
        if uid:
            participants.append({'puuid': uid, 'participantId': i, 'teamId': team,
                'championName': 'Ahri' if i == 1 else 'Lux', 'kills': 2, 'deaths': 1,
                'assists': 3, 'win': True, 'summoner1Id': 4, 'summoner2Id': 12})
    return {'info': {'queueId': queue, 'gameStartTimestamp': policy.MIN_START_TIMESTAMP * 1000 + 1000,
                    'gameEndTimestamp': policy.MIN_START_TIMESTAMP * 1000 + 1201000,
                    'gameDuration': 1200, 'participants': participants}}


class PairPolicyTests(unittest.TestCase):
    def test_elo_selection_never_restricts_cartesian_account_pairs(self):
        duo = {'player1': {'accounts': [{'id': 'a', 'name': 'A', 'puuid': 'a'}, {'id': 'aa', 'name': 'AA', 'puuid': 'aa'}]},
               'player2': {'accounts': [{'id': 'b', 'name': 'B', 'puuid': 'b'}, {'id': 'bb', 'name': 'BB', 'puuid': 'bb'}]}}
        signature = policy.account_sources(duo)
        duo['player1']['eloAccountId'] = 'aa'
        self.assertEqual(policy.account_sources(duo), signature)
        for first in ('a', 'aa'):
            for second in ('b', 'bb'):
                found = {key: value for key, value in zip(('player1', 'player2'), game(first, second)['info']['participants'])}
                self.assertIsNone(policy.validate_pair(duo, found, {'player1': True, 'player2': True}))
        self.assertEqual(policy.validate_pair(duo, {'player1': {'puuid': 'a'}}, {'player2': True}), 'not_duo')
        with self.assertRaises(ValueError):
            policy.validate_pair(duo, {'player1': {'puuid': 'a'}}, {'player2': False})


class PairImportTests(unittest.TestCase):
    setUp = multi.MultiAccountEndpointTests.setUp
    tearDown = multi.MultiAccountEndpointTests.tearDown
    post = multi.MultiAccountEndpointTests.post
    configure = multi.MultiAccountEndpointTests.configure

    def sync_games(self, games, unresolved=(), during_detail=None, listed=None):
        calls = []
        identities = {'A1': 'p1', 'A2': 'p2', 'Alternate': 'alt', 'SecondAlt': 'alt2'}
        def reply(request, **kwargs):
            url = request.full_url
            calls.append(url)
            if '/accounts/' in url:
                name = unquote(url.rsplit('/', 2)[-2])
                if name in unresolved:
                    raise urllib.error.URLError('Temporary account lookup failure')
                payload = {'puuid': identities[name]}
            elif '/entries/' in url:
                payload = [{'queueType': 'RANKED_SOLO_5x5', 'tier': 'GOLD', 'rank': 'IV',
                            'leaguePoints': 10, 'wins': 120, 'losses': 80}]
            elif '/ids?' in url:
                uid = url.split('/by-puuid/')[1].split('/')[0]
                ids = list(listed) if listed is not None else [mid for mid, detail in games.items()
                        if any(p['puuid'] == uid for p in detail['info']['participants'])]
                offset = int(parse_qs(urlparse(url).query)['start'][0])
                payload = ids[offset:offset + 100]
            else:
                mid = url.rsplit('/', 1)[-1]
                if during_detail:
                    during_detail(mid)
                payload = games[mid]
            return io.BytesIO(json.dumps(payload).encode())
        with patch.object(server, 'get_riot_api_key', return_value='fake'), patch.object(server, 'riot_open', side_effect=reply), patch.object(server.time, 'sleep'):
            result = server.sync_riot_data()
        return result, calls

    def test_two_plus_one_counts_both_combinations_but_not_solo_enemy_or_flex(self):
        self.configure()
        games = {'MAIN': game(), 'ALT': game('alt'), 'SOLO1': game('p1', 'stranger'),
                 'SOLO2': game('stranger', 'p2'), 'ENEMY': game('alt', 'p2', team2=200),
                 'FLEX': game(queue=440)}
        result, calls = self.sync_games(games)
        self.assertTrue(result['success'], result)
        duo = server.load_db()['duos'][0]
        self.assertEqual({m['matchId'] for m in duo['history']}, {'MAIN', 'ALT'})
        self.assertEqual(policy.history_record(duo), {'wins': 2, 'losses': 0, 'games': 2})
        self.assertEqual(duo['playerInsights']['player1']['gamesAnalyzed'], 2)
        self.assertEqual(duo['playerInsights']['player1']['totals']['kills'], 4)
        self.assertEqual(duo['excludedRiotMatches']['ENEMY']['reason'], 'not_same_team')
        self.assertEqual(duo['excludedRiotMatches']['FLEX']['reason'], 'wrong_queue')
        self.assertEqual(result['pending'], 0)
        self.assertEqual(duo['blueShells'], 1)
        _, calls = self.sync_games(games)
        self.assertFalse(any('/matches/' in url and '/ids?' not in url for url in calls))

    def test_both_players_alternates_are_supported_once_per_match(self):
        self.configure()
        self.post('/api/duos', {'authPin': '9999', 'duo': {'id': 'a', 'player2': {'accounts': [
            {'name': 'A2', 'tag': 'EUW'}, {'name': 'SecondAlt', 'tag': 'EUW'}]}}})
        games = {'AA': game(), 'AB': game('p1', 'alt2'), 'BA': game('alt', 'p2'), 'BB': game('alt', 'alt2')}
        result, calls = self.sync_games(games)
        self.assertTrue(result['success'], result)
        duo = server.load_db()['duos'][0]
        self.assertEqual(len(duo['history']), 4)
        for mid in games:
            self.assertEqual(Counter(url.rsplit('/', 1)[-1] for url in calls)[mid], 1)
        self.assertEqual(duo['playerInsights']['player2']['totals']['kills'], 8)

    def test_account_lookup_failure_does_not_count_or_permanently_exclude(self):
        self.configure()
        games = {'WAIT': game('alt')}
        result, _ = self.sync_games(games, unresolved={'Alternate'})
        self.assertFalse(result['success'])
        duo = server.load_db()['duos'][0]
        self.assertEqual(duo['history'], [])
        self.assertIn('WAIT', duo['riotMatchDiscovery']['pendingMatchIds'])
        self.assertNotIn('WAIT', duo.get('excludedRiotMatches', {}))
        result, _ = self.sync_games(games)
        self.assertTrue(result['success'], result)
        self.assertEqual([m['matchId'] for m in server.load_db()['duos'][0]['history']], ['WAIT'])

    def test_known_valid_pair_can_count_even_if_an_unused_account_lookup_fails(self):
        self.configure()
        result, _ = self.sync_games({'MAIN': game()}, unresolved={'Alternate'})
        self.assertFalse(result['success'])  # Diagnostic failure, not a false rejection.
        self.assertEqual([m['matchId'] for m in server.load_db()['duos'][0]['history']], ['MAIN'])

    def test_legacy_missing_stats_are_rechecked_against_new_accounts_before_exclusion(self):
        self.configure()
        games = {'LEGACY': game('alt')}
        db = server.load_db()
        old = {'matchId': 'LEGACY', 'gameStartTimestamp': games['LEGACY']['info']['gameStartTimestamp']}
        server.enrich_match_record(old, games['LEGACY']['info'], 'p1', 'p2')
        db['duos'][0]['history'] = [old]
        server.save_db(db)
        result, _ = self.sync_games(games)
        self.assertTrue(result['success'], result)
        duo = server.load_db()['duos'][0]
        self.assertEqual([m['matchId'] for m in duo['history']], ['LEGACY'])
        self.assertEqual(duo['history'][0]['player1Stats']['puuid'], 'alt')
        self.assertNotIn('LEGACY', duo['excludedRiotMatches'])

    def test_any_same_team_combination_is_preferred_over_another_registered_account(self):
        self.configure()
        info = game('alt', team1=200)
        info['info']['participants'].append(game()['info']['participants'][0])
        result, _ = self.sync_games({'PAIR': info})
        self.assertTrue(result['success'], result)
        match = server.load_db()['duos'][0]['history'][0]
        self.assertEqual(match['player1Stats']['puuid'], 'p1')
        self.assertEqual(match['player1Stats']['teamId'], match['player2Stats']['teamId'])

    def test_empty_participants_are_retried_instead_of_becoming_an_exclusion(self):
        self.configure()
        detail = game()
        detail['info']['participants'] = []
        result, _ = self.sync_games({'BAD': detail}, listed=['BAD'])
        self.assertFalse(result['success'])
        duo = server.load_db()['duos'][0]
        self.assertEqual(duo['history'], [])
        self.assertNotIn('BAD', duo.get('excludedRiotMatches', {}))
        self.assertIn('BAD', duo['riotMatchDiscovery']['pendingMatchIds'])

    def test_missing_team_evidence_is_retried_not_guessed(self):
        self.configure()
        result, _ = self.sync_games({'WAIT': game('alt', team2=None)})
        self.assertFalse(result['success'])
        duo = server.load_db()['duos'][0]
        self.assertEqual(duo['history'], [])
        self.assertIn('WAIT', duo['riotMatchDiscovery']['pendingMatchIds'])
        result, _ = self.sync_games({'WAIT': game('alt')})
        self.assertTrue(result['success'])
        self.assertEqual(len(server.load_db()['duos'][0]['history']), 1)

    def test_new_partner_account_rechecks_old_exclusion_and_preserves_reward_ledger(self):
        self.configure()
        games = {'LATER': game('alt', 'alt2')}
        db = server.load_db()
        duo = db['duos'][0]
        # The old importer admitted this game with only one teammate present.
        old = {'matchId': 'LATER', 'gameStartTimestamp': games['LATER']['info']['gameStartTimestamp'],
               'gameEndTimestamp': games['LATER']['info']['gameEndTimestamp'], 'result': 'WIN'}
        server.enrich_match_record(old, games['LATER']['info'], 'alt', 'p2')
        duo['player1']['accounts'][1]['puuid'] = 'alt'
        old.update(shellRewardIds=['kills'], shellRewardsEvaluated=['kills'], shellRewardCredits={'kills': True}, processedForShell=True)
        duo.update(history=[old], blueShells=3, shellsEarnedTotal=7)
        server.save_db(db)
        result, _ = self.sync_games(games)
        self.assertTrue(result['success'], result)
        duo = server.load_db()['duos'][0]
        self.assertEqual(duo['history'], [])
        self.assertEqual(duo['excludedRiotMatches']['LATER']['match']['shellRewardIds'], ['kills'])
        self.assertEqual((duo['blueShells'], duo['shellsEarnedTotal']), (3, 7))
        self.post('/api/duos', {'authPin': '9999', 'duo': {'id': 'a', 'player2': {'accounts': [
            {'name': 'A2', 'tag': 'EUW'}, {'name': 'SecondAlt', 'tag': 'EUW'}]}}})
        result, calls = self.sync_games(games)
        self.assertTrue(result['success'], result)
        duo = server.load_db()['duos'][0]
        self.assertEqual([m['matchId'] for m in duo['history']], ['LATER'])
        self.assertNotIn('LATER', duo['excludedRiotMatches'])
        self.assertEqual(duo['history'][0]['shellRewardIds'], ['kills'])
        self.assertEqual((duo['blueShells'], duo['shellsEarnedTotal']), (3, 7))
        self.assertEqual(sum(url.endswith('/LATER') for url in calls), 1)
        self.assertNotIn('excludedRiotMatches', server.safe_duo_for_player(duo))

    def test_changing_elo_selection_does_not_reopen_pair_exclusions(self):
        self.configure()
        self.sync_games({'SOLO': game('alt', 'stranger')})
        duo = server.load_db()['duos'][0]
        self.post('/api/duos', {'authPin': '9999', 'duo': {'id': 'a', 'player1': {'eloAccountId': duo['player1']['accounts'][0]['id']}}})
        result, calls = self.sync_games({'SOLO': game('alt', 'stranger')})
        self.assertTrue(result['success'], result)
        self.assertFalse(any(url.endswith('/SOLO') for url in calls))

    def test_manual_exclusion_during_scan_wins_over_a_valid_api_result(self):
        self.configure()
        def exclude(mid):
            with server.db_lock:
                db = server.load_db()
                db['duos'][0].setdefault('excludedRiotMatches', {})[mid] = {'reason': 'manual_review'}
                server.save_db(db)
        result, _ = self.sync_games({'REMOVED': game('alt')}, during_detail=exclude)
        self.assertTrue(result['success'], result)
        duo = server.load_db()['duos'][0]
        self.assertEqual(duo['history'], [])
        self.assertEqual(duo['excludedRiotMatches']['REMOVED']['reason'], 'manual_review')


if __name__ == '__main__':
    unittest.main()
