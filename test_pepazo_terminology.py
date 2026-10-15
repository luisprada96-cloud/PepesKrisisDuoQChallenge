"""Pepazo wording and legacy presentation compatibility; never touches production."""
import copy
import json
import unittest
import urllib.request
from unittest.mock import patch

import discord_shells
import server
import test_shell_penalties as fixtures
from terminology import pepazo_payload, pepazo_text


class PepazoTextTests(unittest.TestCase):
    def test_legacy_forms_case_and_plural(self):
        for before, after in [
            ('caparazón', 'pepazo'), ('caparazon', 'pepazo'), ('Caparazón Azul', 'Pepazo'),
            ('CAPARAZÓN AZUL', 'PEPAZO'), ('caparazones azules', 'pepazos'),
            ('Caparazones Azules', 'Pepazos'), ('CAPARAZONES', 'PEPAZOS'),
            ('caparazón(es) azul(es)', 'pepazo(s)'),
            ('Devuelve el caparazón', 'Devuelve el pepazo'),
            ('Caparazoneros', 'Caparazoneros'), ('pepazos', 'pepazos')]:
            with self.subTest(before=before):
                self.assertEqual(pepazo_text(before), after)
        self.assertEqual(pepazo_text(3), 3)
        self.assertIsNone(pepazo_text(None))

    def test_payload_preserves_identity_keys_user_content_and_original_data(self):
        payload = {
            'teamName':'Caparazón Azul', 'player1':{'name':'Caparazón', 'displayName':'Caparazón'},
            'blueShells':5, 'shellsReceived':3,
            'shellAttacks':[{'id':'shell-legacy', 'status':'RETURNED', 'targetName':'Caparazón Azul',
                'result':{'id':'return_shell', 'name':'Devuelve el caparazón', 'desc':'El caparazón vuelve al atacante.'}}],
            'activeDebuffs':[{'penalty':{'name':'Devuelve el caparazón', 'desc':'Un caparazón.'}}],
            'categories':[{'id':'first_individual_shell', 'title':'¿Quién conseguirá el primer caparazón?',
                'options':[{'id':'player-a', 'label':'Caparazón · Equipo A'}]}],
            'events':[{'type':'SHELL_LAUNCHED', 'message':'Se ha lanzado un Caparazón Azul.'}],
            'clips':[{'id':'clip-user', 'title':'Mi caparazón favorito'}],
            'answers':{'first_individual_shell':'player-a'}}
        original = copy.deepcopy(payload)
        result = pepazo_payload(payload)
        self.assertEqual(payload, original)
        self.assertEqual(result['teamName'], payload['teamName'])
        self.assertEqual(result['player1'], payload['player1'])
        self.assertEqual(result['blueShells'], 5)
        self.assertEqual(result['shellsReceived'], 3)
        self.assertEqual(result['shellAttacks'][0]['id'], 'shell-legacy')
        self.assertEqual(result['shellAttacks'][0]['status'], 'RETURNED')
        self.assertEqual(result['shellAttacks'][0]['result']['id'], 'return_shell')
        self.assertEqual(result['shellAttacks'][0]['result']['name'], 'Devuelve el pepazo')
        self.assertEqual(result['activeDebuffs'][0]['penalty']['desc'], 'Un pepazo.')
        self.assertEqual(result['categories'][0]['title'], '¿Quién conseguirá el primer pepazo?')
        self.assertEqual(result['categories'][0]['options'], payload['categories'][0]['options'])
        self.assertEqual(result['events'][0]['message'], 'Se ha lanzado un Pepazo.')
        self.assertEqual(result['clips'], payload['clips'])
        self.assertEqual(result['answers'], payload['answers'])

    def test_discord_normalizes_old_penalties_without_changing_team_names(self):
        penalty = {'name':'Devuelve el caparazón', 'desc':'El caparazón vuelve al atacante.'}
        original = copy.deepcopy(penalty)
        message = discord_shells.message_shell_spun('Caparazón Azul', 'Otro equipo', penalty)['content']
        self.assertIn('**Caparazón Azul**', message)
        self.assertIn('Devuelve el pepazo', message)
        self.assertIn('El pepazo vuelve al atacante.', message)
        self.assertEqual(penalty, original)


class PepazoEndpointTests(unittest.TestCase):
    def setUp(self):
        self.remote_patch = patch.object(server, 'remote_backend', None)
        self.remote_patch.start()
        self.addCleanup(self.remote_patch.stop)
        fixtures.ShellEndpointTests.setUp(self)

    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=3) as response:
            return json.load(response)

    def test_api_translates_old_penalties_and_events_without_rewriting_the_database(self):
        db = server.load_db()
        penalty = {'id':'return_shell', 'baseId':'return_shell', 'name':'Devuelve el caparazón',
                   'desc':'El caparazón vuelve al atacante.', 'scope':'SPECIAL'}
        db['duos'][0]['activeDebuffs'] = [{'id':'legacy-penalty', 'status':'COMPLETED', 'penalty':penalty}]
        db['events'] = [{'id':'legacy-event', 'type':'SHELL_SPUN', 'penalty':penalty,
                         'message':'Se ha abierto un Caparazón Azul.'}]
        server.save_db(db)
        duo = next(d for d in self.get('/api/duos') if d['id']=='a')
        self.assertEqual(duo['activeDebuffs'][0]['penalty']['name'], 'Devuelve el pepazo')
        event = self.get('/api/events?type=SHELL_SPUN')[0]
        self.assertEqual(event['id'], 'legacy-event')
        self.assertEqual(event['message'], 'Se ha abierto un Pepazo.')
        self.assertEqual(server.load_db()['duos'][0]['activeDebuffs'][0]['penalty'], penalty)
        self.assertEqual(server.load_db()['events'][0]['message'], db['events'][0]['message'])

    def test_current_catalog_and_existing_launch_routes_use_pepazo(self):
        catalog = self.get('/api/config')['penaltyCatalog']
        self.assertEqual(next(p for p in catalog if p['id']=='return_shell')['name'], 'Devuelve el pepazo')
        login = self.post('/api/player/login', {'teamId':'a', 'password':'a-pass'})
        token = login['sessionToken']
        launched = self.post('/api/player/launch-shell', {'targetId':'b', 'sessionToken':token})
        self.assertIn('Pepazo', launched['event']['message'])
        self.assertEqual(launched['attack']['status'], 'PENDING_SPIN')
        self.assertTrue(launched['attack']['id'].startswith('shell-'))
        self.assertEqual(launched['attacker']['blueShells'], 0)
        self.assertEqual(len(server.load_db()['shellAttacks']), 1)


if __name__ == '__main__':
    unittest.main()
