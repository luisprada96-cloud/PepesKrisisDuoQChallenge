"""Uniform recipient draws and Riot evidence tied to the selected participant."""
import io
import json
import unittest
from unittest.mock import patch

import server
import test_shell_penalties as fixtures


def duo_fixture():
    return {'player1': {'name': 'RiotOne', 'tag': 'EUW', 'displayName': 'Ana', 'puuid': 'p1', 'mainRole': 'TOP'},
            'player2': {'name': 'RiotTwo', 'tag': 'ZZZ', 'displayName': 'Luis', 'puuid': 'p2', 'mainRole': 'JUNGLE'},
            'history': [{'player1Stats': {'championName': 'Ahri'}, 'player2Stats': {'championName': 'LeeSin'}}]}


def catalog(base, scope='ONE'):
    return next(p for p in server.PENALTY_CATALOG if p['baseId'] == base and p['scope'] == scope)


def assigned_requirements(duo, base, key='player1'):
    def choice(options):
        return key if options == ('player1', 'player2') else options[0]
    with patch.object(server.secrets, 'choice', side_effect=choice), patch.object(server, 'champion_pool', return_value=['Ashe', 'Lux']):
        return server.penalty_requirements(duo, catalog(base), [duo])


class PenaltyAssignmentTests(unittest.TestCase):
    def test_every_individual_penalty_draws_once_from_equal_choices(self):
        duo = duo_fixture()
        for pen in server.PENALTY_CATALOG:
            if pen['scope'] != 'ONE':
                continue
            for key in ('player1', 'player2'):
                with self.subTest(penalty=pen['id'], player=key):
                    def draw(options):
                        return key if options == ('player1', 'player2') else options[0]
                    with patch.object(server.secrets, 'choice', side_effect=draw) as choice, patch.object(server, 'champion_pool', return_value=['Ashe', 'Lux']):
                        req = server.penalty_requirements(duo, pen, [duo])
                    self.assertEqual(req['assignedPlayer'], key)
                    self.assertEqual(req['assignedAccount']['name'], duo[key]['name'])
                    self.assertEqual(req['assignedAccount']['puuid'], duo[key]['puuid'])
                    self.assertEqual(sum(call.args[0] == ('player1', 'player2') for call in choice.call_args_list), 1)
                    if pen['baseId'] == 'random_champion':
                        self.assertEqual(req['randomChampions'], {key: 'Ashe'})

    def test_other_player_cannot_complete_any_individual_penalty(self):
        for base in ('autofill', 'no_main_champion', 'random_champion', 'no_flash'):
            for selected in ('player1', 'player2'):
                with self.subTest(base=base, selected=selected):
                    duo = duo_fixture()
                    req = assigned_requirements(duo, base, selected)
                    duo['activeDebuffs'] = [fixtures.penalty(base, requirements=req)]
                    game = fixtures.match({'puuid':'p1'}, {'puuid':'p2'})
                    def qualify(key, passed):
                        stats = game[f'{key}Stats']
                        if base == 'autofill':
                            stats['position'] = 'MIDDLE' if passed else duo[key]['mainRole']
                        elif base == 'no_main_champion':
                            stats['championName'] = 'Lux' if passed else req['favoriteChampions'][key][0]
                        elif base == 'random_champion':
                            stats['championName'] = 'Ashe' if passed else 'Lux'
                        elif base == 'no_flash':
                            stats['summonerSpellIds'] = [14,12] if passed else [4,12]
                    other = 'player2' if selected == 'player1' else 'player1'
                    qualify(selected, False)
                    qualify(other, True)
                    self.assertEqual(server.evaluate_active_penalties(duo, game), 0)
                    self.assertEqual(duo['activeDebuffs'][0]['status'], 'ACTIVE')
                    qualify(selected, True)
                    self.assertEqual(server.evaluate_active_penalties(duo, game), 1)
                    evidence = duo['activeDebuffs'][0]['evidence']
                    self.assertEqual(evidence['assignedPlayer'], selected)
                    self.assertEqual(evidence['assignedAccount']['puuid'], duo[selected]['puuid'])
                    self.assertEqual(evidence['matchId'], game['matchId'])
                    self.assertEqual(server.evaluate_active_penalties(duo, game), 0)

    def test_account_identity_rejects_other_account_or_missing_riot_proof(self):
        for puuid in ('wrong-account', None):
            duo = duo_fixture()
            req = assigned_requirements(duo, 'no_flash')
            duo['activeDebuffs'] = [fixtures.penalty('no_flash', requirements=req)]
            game = fixtures.match({'puuid':puuid,'summonerSpellIds':[14,12]}, {'puuid':'p2','summonerSpellIds':[14,12]})
            self.assertEqual(server.evaluate_active_penalties(duo, game), 0)
        duo = duo_fixture()
        req = assigned_requirements(duo, 'no_flash')
        duo['activeDebuffs'] = [fixtures.penalty('no_flash', requirements=req)]
        duo['player1']['displayName'] = 'Renamed display'
        game = fixtures.match({'puuid':'p1','summonerSpellIds':[14,12]}, {'puuid':'p2'})
        self.assertEqual(server.evaluate_active_penalties(duo, game), 1)

    def test_assignment_before_first_riot_sync_binds_configured_riot_id(self):
        duo = duo_fixture()
        duo['player1'].pop('puuid')
        req = assigned_requirements(duo, 'no_flash')
        duo['activeDebuffs'] = [fixtures.penalty('no_flash', requirements=req)]
        duo['player1']['puuid'] = 'p1'
        game = fixtures.match({'puuid':'p1','summonerSpellIds':[14,12]}, {'puuid':'p2'})
        self.assertEqual(server.evaluate_active_penalties(duo, game), 1)
        duo['activeDebuffs'] = [fixtures.penalty('no_flash', requirements=req)]
        duo['player1']['name'] = 'DifferentRiotAccount'
        self.assertEqual(server.evaluate_active_penalties(duo, game), 0)

    def test_legacy_unassigned_castigos_remain_either_participant(self):
        duo = duo_fixture()
        old = fixtures.penalty('no_flash')
        duo['activeDebuffs'] = [old]
        db = {'duos':[duo]}
        with patch.object(server.secrets, 'choice', side_effect=AssertionError('Existing penalties must never redraw')):
            server.migrate_legacy_penalties(db)
            server.migrate_legacy_penalties(db)
        self.assertNotIn('assignedPlayer', old['requirements'])
        game = fixtures.match({'summonerSpellIds':[4,12]}, {'summonerSpellIds':[14,12]})
        self.assertEqual(server.evaluate_active_penalties(duo, game), 1)

    def test_missing_assignment_fails_closed_and_test_or_early_games_are_ignored(self):
        duo = duo_fixture()
        req = assigned_requirements(duo, 'no_flash')
        good = fixtures.match({'puuid':'p1','summonerSpellIds':[14,12]}, {'puuid':'p2'})
        for changes in ({'isTest':True}, {'gameStartTimestamp':999}, {'player1Stats':None}):
            duo['activeDebuffs'] = [fixtures.penalty('no_flash', requirements=req)]
            self.assertEqual(server.evaluate_active_penalties(duo, {**good, **changes}), 0)
        for key in (None, 'player3'):
            duo['activeDebuffs'] = [fixtures.penalty('no_flash', requirements={**req, 'assignedPlayer':key})]
            self.assertEqual(server.evaluate_active_penalties(duo, good), 0)

    def test_both_scope_is_unchanged_and_does_not_draw_a_recipient(self):
        duo = duo_fixture()
        with patch.object(server.secrets, 'choice', side_effect=AssertionError('No recipient draw for BOTH')):
            req = server.penalty_requirements(duo, catalog('no_flash','BOTH'), [duo])
        self.assertNotIn('assignedPlayer', req)
        duo['activeDebuffs'] = [fixtures.penalty('no_flash','BOTH',requirements=req)]
        game = fixtures.match({'summonerSpellIds':[14,12]}, {'summonerSpellIds':[4,12]})
        self.assertEqual(server.evaluate_active_penalties(duo, game), 0)
        game['player2Stats']['summonerSpellIds'] = [14,12]
        self.assertEqual(server.evaluate_active_penalties(duo, game), 1)

    def test_riot_participant_enrichment_saves_puuid_for_each_player(self):
        game = {}
        info = {'participants':[{'puuid':'p1','championName':'Ahri'}, {'puuid':'p2','championName':'Lux'}]}
        server.enrich_match_record(game, info, 'p1', 'p2')
        self.assertEqual(game['player1Stats']['puuid'], 'p1')
        self.assertEqual(game['player2Stats']['puuid'], 'p2')


class PenaltyAssignmentEndpointTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def test_riot_sync_waits_until_the_selected_player_qualifies(self):
        db = server.load_db()
        duo = db['duos'][0]
        db['duos'] = [duo]
        duo.update(tier='Iron',division='IV',lp=0,wins=0,losses=0)
        for i, key in enumerate(('player1', 'player2'), 1):
            duo[key].update(puuid=f'p{i}', tag='EUW', avatar='custom.png')
        req = assigned_requirements(duo, 'no_flash', 'player2')
        duo['activeDebuffs'] = [fixtures.penalty('no_flash', requirements=req)]
        server.save_db(db)
        second_game = False
        def reply(request, **kwargs):
            url = request.full_url
            if '/accounts/' in url:
                payload = {'puuid': 'p1' if 'A1' in url else 'p2'}
            elif '/entries/' in url:
                payload = []
            elif '/ids?' in url:
                payload = ['EUW1_CORRECT','EUW1_WRONG'] if second_game else ['EUW1_WRONG']
            else:
                correct = url.endswith('EUW1_CORRECT')
                payload = {'info': {'gameStartTimestamp':1800000000000 + (200000 if correct else 0),
                    'gameEndTimestamp':1800001200000 + (200000 if correct else 0), 'gameDuration':1200,
                    'participants': [{'puuid':'p1','championName':'Ahri','summoner1Id':14,'summoner2Id':12},
                                     {'puuid':'p2','championName':'Lux','summoner1Id':14 if correct else 4,'summoner2Id':12}]}}
            return io.BytesIO(json.dumps(payload).encode())
        with patch.object(server, 'get_riot_api_key', return_value='fake'), patch.object(server, 'riot_open', side_effect=reply), patch.object(server.time, 'sleep'):
            self.assertTrue(server.sync_riot_data()['success'])
            self.assertEqual(server.load_db()['duos'][0]['activeDebuffs'][0]['status'], 'ACTIVE')
            second_game = True
            self.assertTrue(server.sync_riot_data()['success'])
        saved = server.load_db()['duos'][0]['activeDebuffs'][0]
        self.assertEqual(saved['status'], 'COMPLETED')
        self.assertEqual(saved['resolvedByMatchId'], 'EUW1_CORRECT')
        self.assertEqual(saved['requirements'], req)
        self.assertEqual(saved['evidence']['assignedPlayer'], 'player2')

    def test_spin_persists_one_assignment_in_result_attack_event_and_instance(self):
        db = server.load_db()
        db['duos'][1]['player2'].update(displayName='Receptor Dos',tag='EUW',puuid='p2')
        server.save_db(db)
        sender = self.post('/api/player/login', {'teamId':'a','password':'a-pass'})
        receiver = self.post('/api/player/login', {'teamId':'b','password':'b-pass'})
        attack = self.post('/api/player/launch-shell', {'targetId':'b','sessionToken':sender['sessionToken']})['attack']
        with patch.object(server.secrets, 'choice', return_value='player2') as draw:
            result = self.post('/api/player/spin-shell', {'attackId':attack['id'], 'sessionToken':receiver['sessionToken'], 'assignedPlayer':'player1'})
        draw.assert_called_once_with(('player1','player2'))
        req = result['penaltyInstance']['requirements']
        self.assertEqual(req['assignedPlayer'], 'player2')
        self.assertEqual(req['assignedAccount']['displayName'], 'Receptor Dos')
        self.assertEqual(req['assignedAccount']['name'], 'B2')
        self.assertEqual(result['attack']['requirements'], req)
        saved = server.load_db()
        self.assertEqual(saved['events'][0]['requirements'], req)
        self.assertEqual(saved['duos'][1]['activeDebuffs'][0]['requirements'], req)
        self.post('/api/player/spin-shell', {'attackId':attack['id'], 'sessionToken':receiver['sessionToken']}, expected=409)
        self.assertEqual(server.load_db()['duos'][1]['activeDebuffs'][0]['requirements'], req)
        with patch.object(server.secrets, 'choice', side_effect=AssertionError('No redraw during restart')):
            server.migrate_legacy_penalties(saved)
        self.assertEqual(saved['duos'][1]['activeDebuffs'][0]['requirements'], req)
        penalty_id = result['penaltyInstance']['id']
        self.post('/api/admin/resolve-penalty', {'penaltyInstanceId':penalty_id,'action':'COMPLETE','authPin':'9999'})
        self.post('/api/admin/resolve-penalty', {'penaltyInstanceId':penalty_id,'action':'REOPEN','authPin':'9999'})
        self.assertEqual(server.load_db()['duos'][1]['activeDebuffs'][0]['requirements'], req)


if __name__ == '__main__':
    unittest.main()
