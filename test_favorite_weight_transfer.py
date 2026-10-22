"""Favorite roulette outcomes move to random champions, not assigned obligations."""
import copy
import json
import unittest
import urllib.request
from unittest.mock import patch

import server
import test_shell_penalties as fixtures


def old_weights():
    return dict(autofill_one=30, autofill_both=10,
                no_main_champion_one=8, no_main_champion_both=8,
                random_champion_one=14, random_champion_both=5,
                no_flash_one=5, no_flash_both=5,
                swap_flash_one=5, swap_flash_both=5, return_shell=5)


class FavoriteWeightTransferTests(unittest.TestCase):
    def test_current_odds_transfer_by_scope_once_without_changing_other_odds(self):
        original = old_weights()
        transferred = server.without_retired_weights(original)
        self.assertEqual(transferred['random_champion_one'], 22)
        self.assertEqual(transferred['random_champion_both'], 13)
        self.assertEqual(sum(transferred.values()), 100)
        for key, value in original.items():
            if key not in server.REPLACED_PENALTY_WEIGHTS and not key.startswith('random_champion'):
                self.assertEqual(transferred[key], value)
        self.assertFalse(server.REPLACED_PENALTY_WEIGHTS.keys() & transferred.keys())
        self.assertEqual(server.without_retired_weights(transferred), transferred)
        self.assertEqual(original, old_weights())

    def test_defaults_and_new_catalog_have_no_favorite_outcomes(self):
        weights = server.default_penalty_weights()
        self.assertEqual(sum(weights.values()), 100)
        self.assertEqual(weights['random_champion_one'], 28)
        self.assertEqual(weights['random_champion_both'], 12)
        self.assertFalse(any(p['baseId'] == 'no_main_champion' for p in server.PENALTY_CATALOG))
        db = {'config': {'penaltyWeights': old_weights()}}
        server.ensure_shell_schema(db)
        self.assertEqual(db['config']['penaltyWeights']['random_champion_one'], 22)

    def test_pending_and_returned_wheels_transfer_but_history_and_assignments_stay(self):
        active = fixtures.penalty('no_main_champion')
        completed = fixtures.penalty('no_main_champion', 'BOTH')
        completed.update(status='COMPLETED', resolved=True, evidence={'matchId': 'REAL'})
        historical = {'status': 'OPENED', 'wheelSnapshot': old_weights()}
        db = {'config': {'penaltyWeights': old_weights()},
              'duos': [{'activeDebuffs': [active, completed]}],
              'shellAttacks': [{'status': 'PENDING_SPIN', 'wheelSnapshot': old_weights()}, historical]}
        assignments = copy.deepcopy(db['duos'])
        self.assertTrue(server.retire_removed_penalties(db))
        expected = server.without_retired_weights(old_weights())
        self.assertEqual(db['config']['penaltyWeights'], expected)
        self.assertEqual(db['shellAttacks'][0]['wheelSnapshot'], expected)
        self.assertEqual(historical['wheelSnapshot'], old_weights())
        self.assertEqual(db['duos'], assignments)
        self.assertFalse(server.retire_removed_penalties(db))
        reflected = server.create_pending_shell(db, {'id': 'b', 'teamName': 'B'}, {'id': 'a', 'teamName': 'A'}, historical['wheelSnapshot'])
        self.assertEqual(reflected['wheelSnapshot'], expected)

    def test_zero_weights_are_not_enabled_and_favorite_only_wheel_remains_drawable(self):
        self.assertEqual(server.without_retired_weights({'no_main_champion_one': 0}), {'random_champion_one': 0})
        with self.assertRaises(ValueError):
            server.weighted_penalty({'no_main_champion_one': 0})
        for scope in ('one', 'both'):
            old = {f'no_main_champion_{scope}': 100}
            self.assertEqual(server.weighted_penalty(old)['id'], f'random_champion_{scope}')

    def test_picker_preserves_every_weight_boundary(self):
        weights = server.without_retired_weights(old_weights())
        draws = []
        for index in range(100):
            with patch.object(server.secrets, 'randbelow', return_value=index) as draw:
                draws.append(server.weighted_penalty(old_weights())['id'])
            draw.assert_called_once_with(100)
        for key, weight in weights.items():
            self.assertEqual(draws.count(key), weight)


class FavoriteWeightEndpointTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def test_reload_persists_transfer_and_public_admin_catalogs_exclude_favorites(self):
        db = server.load_db()
        db['config']['penaltyWeights'] = old_weights()
        db['shellAttacks'] = [{'id': 'pending', 'status': 'PENDING_SPIN', 'wheelSnapshot': old_weights()}]
        server.save_db(db)
        expected = server.without_retired_weights(old_weights())
        for _ in range(2):
            loaded = server.load_db()
            self.assertEqual(loaded['config']['penaltyWeights'], expected)
            self.assertEqual(loaded['shellAttacks'][0]['wheelSnapshot'], expected)
        with open(server.DB_FILE, encoding='utf-8') as source:
            self.assertEqual(json.load(source)['config']['penaltyWeights'], expected)
        with urllib.request.urlopen(self.base + '/api/config', timeout=3) as response:
            public = json.load(response)
        admin = self.post('/api/admin/login', {'pin': '9999'})
        for result in (public, admin):
            self.assertFalse(any('no_main_champion' in p['id'] for p in result['penaltyCatalog']))
        self.assertEqual(public['penaltyWeights'], expected)
        self.assertEqual(admin['config']['penaltyWeights'], expected)

    def test_stale_admin_tab_cannot_restore_favorite_outcomes(self):
        result = self.post('/api/config', {'authPin': '9999', 'config': {'penaltyWeights': old_weights()}})
        self.assertTrue(result['success'])
        self.assertEqual(result['config']['penaltyWeights'], server.without_retired_weights(old_weights()))
        self.assertEqual(server.load_db()['config']['penaltyWeights'], result['config']['penaltyWeights'])

    def test_old_pending_favorite_wheel_now_assigns_a_random_champion(self):
        db = server.load_db()
        server.create_pending_shell(db, db['duos'][0], db['duos'][1], {'no_main_champion_one': 100})
        attack_id = db['shellAttacks'][0]['id']
        server.save_db(db)
        token = self.post('/api/player/login', {'teamId': 'b', 'password': 'b-pass'})['sessionToken']
        with patch.object(server, 'champion_pool', return_value=['Ashe']):
            result = self.post('/api/player/spin-shell', {'sessionToken': token, 'attackId': attack_id})
        self.assertEqual(result['penalty']['id'], 'random_champion_one')
        requirements = result['penaltyInstance']['requirements']
        self.assertEqual(requirements['randomChampions'], {requirements['assignedPlayer']: 'Ashe'})
        self.assertEqual(server.load_db()['shellAttacks'][0]['wheelSnapshot'], {'random_champion_one': 100})


if __name__ == '__main__':
    unittest.main()
