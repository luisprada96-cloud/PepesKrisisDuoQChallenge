"""Independent participant rank synchronization and preservation of confirmed data."""
import copy
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

import server
import test_shell_penalties as fixtures


class PlayerRankTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def prepare(self):
        db = server.load_db()
        duo = db['duos'][0]
        db['duos'] = [duo]
        duo.update(tier='Iron', division='IV', lp=0, wins=0, losses=0)
        for key in ('player1', 'player2'):
            duo[key]['avatar'] = 'custom.png'
        server.save_db(db)
        return db

    @staticmethod
    def entries(tier='EMERALD', division='IV', lp=55):
        return [{'queueType': 'RANKED_FLEX_SR', 'tier': 'CHALLENGER', 'rank': 'I', 'leaguePoints': 1000},
                {'queueType': 'RANKED_SOLO_5x5', 'tier': tier, 'rank': division, 'leaguePoints': lp, 'wins': 12, 'losses': 8}]

    def sync(self, second=None, fail_second=False, fail_first_account=False):
        calls = []
        def response(request, **kwargs):
            url = request.full_url
            calls.append(url)
            if '/accounts/' in url:
                if 'A1' in url and fail_first_account:
                    raise urllib.error.URLError('Account unavailable')
                payload = {'puuid': 'p1' if 'A1' in url else 'p2'}
            elif '/entries/' in url:
                if url.endswith('/p2') and fail_second:
                    raise urllib.error.URLError('League unavailable')
                payload = self.entries() if url.endswith('/p1') else (self.entries('DIAMOND', 'II', 22) if second is None else second)
            elif '/ids?' in url:
                payload = []
            else:
                raise AssertionError('Unexpected request: ' + url)
            return io.BytesIO(json.dumps(payload).encode())
        with patch.object(server, 'get_riot_api_key', return_value='fake'), patch.object(server, 'riot_open', side_effect=response):
            result = server.sync_riot_data()
        return result, calls

    def test_distinct_solo_ranks_are_saved_and_team_rank_stays_player_one(self):
        self.prepare()
        result, calls = self.sync()
        self.assertTrue(result['success'])
        duo = server.load_db()['duos'][0]
        self.assertEqual((duo['tier'], duo['division'], duo['lp']), ('Emerald', 'IV', 55))
        self.assertEqual(duo['player1']['rank']['lp'], 55)
        self.assertEqual(duo['player2']['rank']['tier'], 'Diamond')
        self.assertEqual(duo['player2']['rank']['division'], 'II')
        self.assertEqual(duo['player2']['rank']['lp'], 22)
        self.assertGreater(duo['player2']['rank']['observedAt'], 0)
        self.assertEqual(sum('/entries/' in url for url in calls), 2)
        self.assertEqual(server.public_duo_summaries()[0]['player2']['rank'], duo['player2']['rank'])
        self.assertEqual(duo['player1']['eloHistory'][-1]['totalLp'], 2055)
        self.assertEqual(duo['player2']['eloHistory'][-1]['totalLp'], 2622)
        self.assertEqual(duo['player2']['eloHistory'][-1]['wins'], 12)
        self.assertEqual(duo['player2']['eloHistory'][-1]['losses'], 8)
        first_history = copy.deepcopy(duo['player1']['eloHistory'])
        self.sync(second=self.entries('DIAMOND', 'II', 33))
        duo = server.load_db()['duos'][0]
        self.assertEqual(len(duo['player1']['eloHistory']), len(first_history))
        self.assertEqual(len(duo['player2']['eloHistory']), 1)
        self.assertEqual(duo['player2']['eloHistory'][-1]['totalLp'], 2633)

    def test_failed_second_rank_keeps_previous_confirmed_rank(self):
        db = self.prepare()
        previous = {'tier': 'Gold', 'division': 'III', 'lp': 20, 'observedAt': 1}
        db['duos'][0]['player2']['rank'] = previous
        server.save_db(db)
        result, _ = self.sync(fail_second=True)
        self.assertFalse(result['success'])
        duo = server.load_db()['duos'][0]
        self.assertEqual(duo['player2']['rank'], previous)
        self.assertEqual(duo['player2']['eloHistory'][-1]['totalLp'], 1320)
        self.assertEqual(duo['player1']['rank']['tier'], 'Emerald')

    def test_successful_response_without_solo_rank_is_unranked(self):
        self.prepare()
        result, _ = self.sync(second=[self.entries()[0]])
        self.assertTrue(result['success'])
        rank = server.load_db()['duos'][0]['player2']['rank']
        self.assertEqual((rank['tier'], rank['division'], rank['lp']), ('Unranked', '', 0))

    def test_second_rank_can_sync_when_first_account_is_unavailable(self):
        self.prepare()
        result, _ = self.sync(fail_first_account=True)
        self.assertFalse(result['success'])
        duo = server.load_db()['duos'][0]
        self.assertEqual(duo['player2']['rank']['tier'], 'Diamond')
        self.assertNotIn('rank', duo['player1'])

    def test_merge_does_not_overwrite_newer_rank_or_changed_account(self):
        self.prepare()
        original = server.load_db()
        scanned = copy.deepcopy(original)
        scanned['duos'][0]['player2']['rank'] = {'tier': 'Diamond', 'division': 'II', 'lp': 22, 'observedAt': 2}
        current = server.load_db()
        newer = {'tier': 'Master', 'division': 'I', 'lp': 100, 'observedAt': 3}
        current['duos'][0]['player2']['rank'] = newer
        server.save_db(current)
        server.merge_riot_result(original, scanned)
        self.assertEqual(server.load_db()['duos'][0]['player2']['rank'], newer)
        self.assertEqual(server.load_db()['duos'][0]['player2']['eloHistory'][-1]['totalLp'], 2900)
        current = server.load_db()
        current['duos'][0]['player2']['name'] = 'Replacement'
        current['duos'][0]['player2']['rank'] = None
        server.save_db(current)
        server.merge_riot_result(original, scanned)
        self.assertIsNone(server.load_db()['duos'][0]['player2']['rank'])
        self.assertEqual(server.load_db()['duos'][0]['player2']['eloHistory'], [])

    def test_admin_account_change_invalidates_rank_but_role_change_does_not(self):
        db = self.prepare()
        previous = {'tier': 'Gold', 'division': 'III', 'lp': 20, 'observedAt': 1}
        db['duos'][0]['player2']['rank'] = previous
        server.save_db(db)
        self.post('/api/duos', {'authPin': '9999', 'duo': {'id': 'a', 'player2': {'mainRole': 'MIDDLE'}}})
        self.assertEqual(server.load_db()['duos'][0]['player2']['rank'], previous)
        self.post('/api/duos', {'authPin': '9999', 'duo': {'id': 'a', 'player2': {'name': 'Replacement'}}})
        self.assertIsNone(server.load_db()['duos'][0]['player2']['rank'])
        self.assertEqual(server.load_db()['duos'][0]['player2']['eloHistory'], [])


if __name__ == '__main__':
    unittest.main()
