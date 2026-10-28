"""Polivalente draws and freezes a specific non-primary position per recipient."""
import copy
import unittest
from unittest.mock import patch

import server
import test_participant_roles as roles
import test_shell_penalties as fixtures
from test_penalty_assignments import duo_fixture, catalog


class PolivalenteTests(unittest.TestCase):
    def test_both_queue_choices_exclude_both_main_roles(self):
        for scope in ('ONE', 'BOTH'):
            for primary in server.participant_roles.POSITIONS:
                duo = duo_fixture()
                duo['history'][0]['player1Stats']['position'] = primary
                def draw(options):
                    if options == ('player1', 'player2'):
                        return 'player1'
                    self.assertTrue(2 <= len(options) <= 4)
                    self.assertEqual(len(set(options)), len(options))
                    return options[0]
                with patch.object(server.secrets, 'choice', side_effect=draw) as choice:
                    req = server.penalty_requirements(duo, catalog('autofill', scope), [duo])
                keys = ['player1'] if scope == 'ONE' else ['player1', 'player2']
                self.assertEqual(set(req['randomPositions']), set(keys))
                for key in keys:
                    first,second=req['randomPositions'][key],req['randomSecondaryPositions'][key]
                    self.assertNotEqual(first,second)
                    self.assertNotIn(first,req['mainRoles'].values())
                    self.assertNotIn(second,req['mainRoles'].values())
                self.assertEqual(set(req['randomSecondaryPositions']),set(keys))
                if scope == 'BOTH':
                    self.assertNotEqual(req['randomPositions']['player1'],req['randomPositions']['player2'])

    def test_exact_assigned_role_required_and_saved_in_evidence(self):
        duo = duo_fixture()
        with patch.object(server.secrets, 'choice', side_effect=['player1', 'MIDDLE', 'BOTTOM']):
            req = server.penalty_requirements(duo, catalog('autofill'), [duo])
        duo['activeDebuffs'] = [fixtures.penalty('autofill', requirements=req)]
        game = fixtures.match({'puuid':'p1','position':'UTILITY'}, {'puuid':'p2','position':'MIDDLE'})
        self.assertEqual(server.evaluate_active_penalties(duo, game), 0)
        game['player1Stats']['position'] = 'BOTTOM'
        self.assertEqual(server.evaluate_active_penalties(duo, game), 1)
        self.assertEqual(duo['activeDebuffs'][0]['evidence']['randomPositions'], {'player1':'MIDDLE'})
        self.assertEqual(duo['activeDebuffs'][0]['evidence']['randomSecondaryPositions'], {'player1':'BOTTOM'})

    def test_pending_role_draws_once_and_existing_penalties_never_redraw(self):
        duo = roles.team()
        req = server.penalty_requirements(duo, catalog('autofill', 'BOTH'), [duo])
        self.assertEqual(req['randomPositions'], {})
        legacy = {'mainRoleMode':'most_played', 'mainRoles':{'player1':'TOP','player2':'JUNGLE'}}
        duo['activeDebuffs'] = [fixtures.penalty('autofill', 'BOTH', req), fixtures.penalty('autofill', 'BOTH', legacy)]
        duo['history'] = [roles.game(1)]
        with patch.object(server.secrets, 'choice', side_effect=['MIDDLE','BOTTOM','BOTTOM','UTILITY']) as draw:
            self.assertEqual(len(server.fill_pending_penalty_roles(duo)), 1)
            self.assertEqual(draw.call_count, 4)
        frozen = copy.deepcopy(req)
        duo['history'] += [roles.game(i, 'MIDDLE', 'BOTTOM') for i in range(2, 6)]
        with patch.object(server.secrets, 'choice', side_effect=AssertionError('must not redraw')):
            self.assertEqual(server.fill_pending_penalty_roles(duo), [])
        self.assertEqual(req, frozen)
        self.assertNotIn('randomPositions', legacy)

    def test_both_must_use_their_assigned_positions(self):
        duo = duo_fixture()
        with patch.object(server.secrets, 'choice', side_effect=['MIDDLE','BOTTOM','BOTTOM','UTILITY']):
            req = server.penalty_requirements(duo, catalog('autofill','BOTH'), [duo])
        duo['activeDebuffs'] = [fixtures.penalty('autofill', 'BOTH', req)]
        game = fixtures.match({'position':'MIDDLE'}, {'position':'TOP'})
        self.assertEqual(server.evaluate_active_penalties(duo, game), 0)
        game['player2Stats']['position'] = 'UTILITY'
        self.assertEqual(server.evaluate_active_penalties(duo, game), 1)

    def test_migration_keeps_old_polivalente_without_a_new_position(self):
        duo = duo_fixture()
        duo['activeDebuffs'] = [{'id':'old', 'penalty':{'id':'autofill'}, 'resolved':False}]
        with patch.object(server.secrets, 'choice', side_effect=AssertionError('legacy must not draw')):
            server.migrate_legacy_penalties({'duos':[duo]})
        self.assertNotIn('randomPositions', duo['activeDebuffs'][0]['requirements'])

    def test_single_recipient_waits_for_companions_main_role(self):
        duo=duo_fixture()
        duo['history'][0]['player2Stats']=None
        with patch.object(server.secrets,'choice',return_value='player1') as draw:
            req=server.penalty_requirements(duo,catalog('autofill'),[duo])
        self.assertEqual(draw.call_count,1)
        self.assertEqual(req['randomPositions'],{})
        self.assertEqual(req['randomSecondaryPositions'],{})
        duo['activeDebuffs']=[fixtures.penalty('autofill',requirements=req)]
        duo['history']=duo_fixture()['history']
        server.fill_pending_penalty_roles(duo)
        self.assertEqual(req['mainRoles']['player2'],'JUNGLE')
        self.assertNotIn(req['randomSecondaryPositions']['player1'],('TOP','JUNGLE'))

    def test_legacy_single_position_keeps_original_condition(self):
        duo=duo_fixture()
        req={'mainRoles':{'player1':'TOP','player2':'JUNGLE'},'randomPositions':{'player1':'JUNGLE'}}
        duo['activeDebuffs']=[fixtures.penalty('autofill',requirements=req)]
        self.assertEqual(server.evaluate_active_penalties(duo,fixtures.match({'position':'JUNGLE'},{'position':'TOP'})),1)


class PolivalenteEndpointTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def spin_and_check(self, scope):
        db = server.load_db()
        db['config']['penaltyWeights'] = {p['id']: 100 if p['id'] == f'autofill_{scope.lower()}' else 0 for p in server.PENALTY_CATALOG}
        target = db['duos'][1]
        target['player1']['puuid'] = 'p1'
        target['player2']['puuid'] = 'p2'
        target['history'] = [roles.game(1)]
        server.save_db(db)
        attacker = self.post('/api/player/login', {'teamId':'a','password':'a-pass'})['sessionToken']
        receiver = self.post('/api/player/login', {'teamId':'b','password':'b-pass'})['sessionToken']
        attack = self.post('/api/player/launch-shell', {'targetId':'b','sessionToken':attacker})['attack']
        spun = self.post('/api/player/spin-shell', {'attackId':attack['id'],'sessionToken':receiver})
        req = spun['penaltyInstance']['requirements']
        self.assertEqual(len(req['randomPositions']), 1 if scope == 'ONE' else 2)
        self.assertEqual(len(req['randomSecondaryPositions']), 1 if scope == 'ONE' else 2)
        self.assertEqual(spun['attack']['requirements'], req)
        stored = server.load_db()
        event = next(e for e in stored['events'] if e['type'] == 'SHELL_SPUN')
        self.assertEqual(event['requirements'], req)
        with patch.object(server.secrets, 'choice', side_effect=AssertionError('must not redraw')):
            state = self.post('/api/player/state', {'sessionToken':receiver})['duo']
            outgoing = self.post('/api/player/state', {'sessionToken':attacker})['duo']['outgoingShellAttacks'][0]
            self.post('/api/player/spin-shell', {'attackId':attack['id'],'sessionToken':receiver}, expected=409)
        self.assertEqual(state['activeDebuffs'][0]['requirements'], req)
        self.assertEqual(outgoing['requirements'], req)
        self.assertEqual(server.public_duo_summaries()[1]['activeDebuffs'][0]['requirements'], req)

    def test_one_persists_through_spin_reload_events_and_outgoing_attacks(self):
        self.spin_and_check('ONE')

    def test_both_persists_through_spin_reload_events_and_outgoing_attacks(self):
        self.spin_and_check('BOTH')


if __name__ == '__main__':
    unittest.main()
