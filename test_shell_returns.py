"""A reverse shell is a pending attack for the original sender, not inventory."""
import copy
import json
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import server
import test_shell_penalties as fixtures


def result(base):
    return dict(next(item for item in server.PENALTY_CATALOG if item['baseId'] == base and item['scope'] in ('ONE','SPECIAL')))


class ShellReturnTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def prepare(self):
        db = server.load_db()
        db['config']['penaltyWeights'] = {item['id']:0 for item in server.PENALTY_CATALOG}
        db['config']['penaltyWeights'].update(return_shell=50,no_flash_one=50)
        server.save_db(db)
        self.sender = self.post('/api/player/login', {'teamId':'a','password':'a-pass'})['sessionToken']
        self.receiver = self.post('/api/player/login', {'teamId':'b','password':'b-pass'})['sessionToken']
        return self.post('/api/player/launch-shell', {'targetId':'b','sessionToken':self.sender})['attack']

    def spin(self, token, attack_id, base='return_shell', expected=200):
        with patch.object(server, 'weighted_penalty', return_value=result(base)):
            return self.post('/api/player/spin-shell', {'sessionToken':token,'attackId':attack_id},expected=expected)

    def test_reverse_creates_exactly_one_pending_inbox_attack_and_keeps_inventory(self):
        original = self.prepare()
        before = copy.deepcopy(server.load_db()['duos'])
        with patch.object(server, 'notify_shell_receivers') as notify:
            spun = self.spin(self.receiver, original['id'])
        notify.assert_called_once()
        returned = spun['returnedAttack']
        self.assertEqual(spun['attack']['status'], 'RETURNED')
        self.assertEqual(spun['attack']['returnedAttackId'], returned['id'])
        self.assertNotEqual(original['id'], returned['id'])
        self.assertEqual((returned['attackerTeamId'],returned['targetTeamId'],returned['status']), ('b','a','PENDING_SPIN'))
        self.assertEqual(returned['returnedFromAttackId'], original['id'])
        self.assertEqual(returned['rootShellId'], original['id'])
        self.assertEqual(returned['reflectionCount'], 1)
        self.assertEqual(returned['wheelSnapshot'], original['wheelSnapshot'])
        self.assertIsNone(spun['penaltyInstance'])
        self.assertEqual(spun['duo']['pendingShellAttacks'], [])
        self.assertFalse(spun['duo'].get('activeDebuffs'))
        saved = server.load_db()
        self.assertEqual(saved['duos'], before)
        self.assertEqual(len(saved['shellAttacks']), 2)
        state = self.post('/api/player/state', {'sessionToken':self.sender})['duo']
        self.assertEqual(state['pendingShellAttacks'], [returned])
        self.assertEqual(state['blueShells'], 0)
        self.assertEqual(server.receiver_notification_state(self.sender)['attacks'][0]['id'], returned['id'])
        self.assertEqual(server.receiver_notification_state(self.receiver)['attacks'], [])
        self.assertEqual([e['type'] for e in saved['events']], ['SHELL_SPUN','SHELL_RETURNED','SHELL_LAUNCHED'])
        self.spin(self.receiver, original['id'], expected=409)
        self.assertEqual(len(server.load_db()['shellAttacks']), 2)

    def test_original_sender_can_spin_the_returned_attack_for_their_own_penalty(self):
        original = self.prepare()
        returned = self.spin(self.receiver, original['id'])['returnedAttack']
        # Only the new receptor is allowed to spin the returned shell.
        self.spin(self.receiver, returned['id'], base='no_flash', expected=404)
        with patch.object(server.secrets, 'choice', return_value='player2'):
            spun = self.spin(self.sender, returned['id'], base='no_flash')
        penalty = spun['penaltyInstance']
        self.assertEqual(spun['attack']['status'], 'PENALTY_ASSIGNED')
        self.assertEqual(penalty['sourceShellId'], returned['id'])
        self.assertEqual(penalty['attackerTeamId'], 'b')
        self.assertEqual(penalty['requirements']['assignedPlayer'], 'player2')
        self.assertEqual(penalty['requirements']['assignedAccount']['name'], 'A2')
        self.assertEqual(spun['duo']['id'], 'a')
        self.assertEqual(spun['duo']['pendingShellAttacks'], [])
        self.assertEqual(spun['duo']['blueShells'], 0)
        self.assertFalse(server.load_db()['duos'][1].get('activeDebuffs'))

    def test_return_does_not_depend_on_inventory_and_uses_original_probabilities(self):
        original = self.prepare()
        db = server.load_db()
        db['duos'][0]['blueShells'] = 5
        db['config']['penaltyWeights'] = {item['id']:0 for item in server.PENALTY_CATALOG}
        db['config']['penaltyWeights']['autofill_both'] = 100
        server.save_db(db)
        returned = self.spin(self.receiver, original['id'])['returnedAttack']
        self.assertEqual(returned['wheelSnapshot'], original['wheelSnapshot'])
        self.assertEqual(server.load_db()['duos'][0]['blueShells'], 5)
        self.assertEqual(server.load_db()['duos'][1]['blueShells'], 0)
        self.assertEqual(server.load_db()['duos'][0]['shellsUsed'], 1)
        self.assertEqual(server.load_db()['duos'][1].get('shellsUsed',0), 0)

    def test_second_reverse_bounces_back_with_same_root_and_unique_attack(self):
        original = self.prepare()
        first = self.spin(self.receiver, original['id'])['returnedAttack']
        second = self.spin(self.sender, first['id'])['returnedAttack']
        self.assertEqual(second['targetTeamId'], 'b')
        self.assertEqual(second['returnedFromAttackId'], first['id'])
        self.assertEqual(second['rootShellId'], original['id'])
        self.assertEqual(second['reflectionCount'], 2)
        self.assertEqual(second['wheelSnapshot'], original['wheelSnapshot'])
        self.assertEqual(len({a['id'] for a in server.load_db()['shellAttacks']}), 3)
        self.assertEqual(len(self.post('/api/player/state', {'sessionToken':self.receiver})['duo']['pendingShellAttacks']), 1)
        self.assertEqual(self.post('/api/player/state', {'sessionToken':self.sender})['duo']['pendingShellAttacks'], [])

    def test_concurrent_spins_cannot_duplicate_a_return(self):
        original = self.prepare()
        def request(_):
            req = urllib.request.Request(self.base+'/api/player/spin-shell', data=json.dumps({'sessionToken':self.receiver,'attackId':original['id']}).encode(), headers={'Content-Type':'application/json'}, method='POST')
            try:
                with urllib.request.urlopen(req, timeout=3) as response:
                    return response.status
            except urllib.error.HTTPError as error:
                return error.code
        with patch.object(server, 'weighted_penalty', return_value=result('return_shell')), ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(request, range(2)))
        self.assertEqual(sorted(statuses), [200,409])
        saved = server.load_db()
        self.assertEqual(len(saved['shellAttacks']), 2)
        self.assertEqual(sum(a['status']=='PENDING_SPIN' for a in saved['shellAttacks']), 1)

    def test_missing_sender_does_not_consume_the_shell_or_create_an_orphan(self):
        original = self.prepare()
        db = server.load_db()
        db['duos'] = [d for d in db['duos'] if d['id'] != 'a']
        server.save_db(db)
        before = copy.deepcopy(server.load_db())
        self.spin(self.receiver, original['id'], expected=409)
        self.assertEqual(server.load_db(), before)


if __name__ == '__main__':
    unittest.main()
