"""Participant profile persistence and independent Twitch live status."""
import copy
import io
import json
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

import server
import test_shell_penalties as fixtures


class ParticipantProfileTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def configure(self):
        db = server.load_db()
        duo = db['duos'][0]
        duo['twitchUrl'] = 'https://www.twitch.tv/legacy_channel'
        duo['twitchIsLive'] = True
        duo['player1']['rank'] = {'tier': 'Gold', 'division': 'II', 'lp': 30}
        duo['player1']['eloHistory'] = [{'date': '2026-10-01', 'totalLp': 1430}]
        duo['activeDebuffs'] = [{'id': 'keep-me', 'status': 'ACTIVE'}]
        server.save_db(db)
        return copy.deepcopy(server.load_db()['duos'][0])

    def sync(self, live=(), callback=None, fail=False, malformed=False):
        calls = []
        def reply(request, **kwargs):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
            calls.append(query)
            if callback:
                callback()
            if fail:
                raise urllib.error.URLError('unavailable')
            payload = {} if malformed else {'data': [{'user_login': ch, 'type': 'live'} for ch in live if ch in query['user_login']]}
            return io.BytesIO(json.dumps(payload).encode())
        with patch.object(server, 'get_twitch_credentials', return_value=('client', 'secret')), patch.object(server, 'get_twitch_app_token', return_value='token'), patch.object(server.urllib.request, 'urlopen', side_effect=reply):
            result = server.sync_twitch_live_status()
        return result, calls

    def test_edit_profiles_preserves_rank_history_and_inventory(self):
        before = self.configure()
        result = self.post('/api/duos', {'authPin': '9999', 'duo': {'id': 'a',
            'player1': {'displayName': '  Luis  ', 'twitchUrl': 'https://twitch.tv/LEGACY_CHANNEL/', 'twitchIsLive': False},
            'player2': {'displayName': 'Pepe', 'twitchUrl': 'https://twitch.tv/Second_Channel', 'twitchIsLive': True}}})
        duo = result['duo']
        self.assertEqual(duo['player1']['displayName'], 'Luis')
        self.assertEqual(duo['player2']['twitchUrl'], 'https://www.twitch.tv/second_channel')
        self.assertTrue(duo['player1']['twitchIsLive'])
        self.assertFalse(duo['player2']['twitchIsLive'])
        for field in ('history', 'blueShells', 'activeDebuffs'):
            self.assertEqual(duo[field], before[field])
        for field in ('name', 'rank', 'eloHistory', 'mainRole'):
            self.assertEqual(duo['player1'][field], before['player1'][field])
        self.post('/api/duos', {'authPin': '9999', 'duo': {'id': 'a', 'player2': {'mainRole': 'UTILITY'}}})
        duo = server.load_db()['duos'][0]
        self.assertEqual(duo['player2']['displayName'], 'Pepe')
        self.assertEqual(duo['player2']['twitchUrl'], 'https://www.twitch.tv/second_channel')

    def test_create_profiles_and_legacy_client_name_fallback(self):
        result = self.post('/api/duos', {'authPin': '9999', 'duo': {'id': 'new', 'teamName': 'Nuevo',
            'player1': {'name': 'RiotOne', 'mainRole': 'TOP', 'displayName': 'Nombre Uno', 'twitchUrl': 'https://twitch.tv/channel_one', 'twitchIsLive': True},
            'player2': {'name': 'RiotTwo', 'mainRole': 'JUNGLE'}}})
        self.assertEqual(result['duo']['player1']['displayName'], 'Nombre Uno')
        self.assertEqual(result['duo']['player2']['displayName'], 'RiotTwo')
        self.assertFalse(result['duo']['player1']['twitchIsLive'])
        self.assertFalse(result['duo']['twitchIsLive'])

    def test_invalid_profiles_are_rejected_without_saving(self):
        before = self.configure()
        for profile in ({'displayName': ''}, {'displayName': 'a'*61},
                        {'twitchUrl': 'http://twitch.tv/channel'}, {'twitchUrl': 'https://example.com/channel'},
                        {'twitchUrl': 'https://user@twitch.tv/channel'}, {'twitchUrl': 'https://twitch.tv/channel/videos'}):
            with self.subTest(profile=profile):
                self.post('/api/duos', {'authPin': '9999', 'duo': {'id': 'a', 'player1': profile}}, expected=400)
                self.assertEqual(server.load_db()['duos'][0], before)

    def test_opgg_links_can_be_added_preserved_and_removed(self):
        before = self.configure()
        url = 'https://www.op.gg/lol/summoners/euw/Prueba-EUW'
        result = self.post('/api/duos', {'authPin':'9999','duo':{'id':'a',
            'player1':{'opggUrl':'  '+url+'  '},'player2':{'opggUrl':'https://op.gg/summoners/euw/Dos-EUW'}}})
        self.assertEqual(result['duo']['player1']['opggUrl'],url)
        self.assertEqual(server.load_db()['duos'][0]['player1']['opggUrl'],url)
        with urllib.request.urlopen(self.base+'/api/duos',timeout=3) as response:
            public=next(team for team in json.load(response) if team['id']=='a')
        self.assertEqual(public['player1']['opggUrl'],url)
        for field in ('history','blueShells','activeDebuffs'):
            self.assertEqual(result['duo'][field],before[field])
        self.post('/api/duos',{'authPin':'9999','duo':{'id':'a','player1':{'displayName':'Editado'}}})
        self.assertEqual(server.load_db()['duos'][0]['player1']['opggUrl'],url)
        result = self.post('/api/duos',{'authPin':'9999','duo':{'id':'a','player1':{'opggUrl':''}}})
        self.assertEqual(result['duo']['player1']['opggUrl'],'')
        self.assertTrue(result['duo']['player2']['opggUrl'])
        self.post('/api/duos',{'authPin':'wrong','duo':{'id':'a','player1':{'opggUrl':url}}},expected=401)
        self.assertEqual(server.load_db()['duos'][0]['player1']['opggUrl'],'')

    def test_invalid_opgg_links_are_rejected_without_saving(self):
        before=self.configure()
        for url in ('javascript:alert(1)','http://op.gg/summoners/euw/Test',
                    'https://example.com/user','https://op.gg.evil.com/user',
                    'https://evilop.gg/user','https://user@op.gg/user',
                    'https://op.gg:8443/user','https://op.gg/user\n<script>',
                    'https://op.gg/\\evil','https://op.gg/'+('a'*2048)):
            with self.subTest(url=url):
                self.post('/api/duos',{'authPin':'9999','duo':{'id':'a','player1':{'opggUrl':url}}},expected=400)
                self.assertEqual(server.load_db()['duos'][0],before)
        created=self.post('/api/duos',{'authPin':'9999','duo':{'id':'new-opgg','teamName':'Nuevo',
            'player1':{'name':'Uno','mainRole':'TOP','opggUrl':'https://op.gg/lol/summoners/euw/Uno-EUW'},
            'player2':{'name':'Dos','mainRole':'JUNGLE'}}})
        self.assertEqual(created['duo']['player1']['opggUrl'],'https://op.gg/lol/summoners/euw/Uno-EUW')
        self.assertNotIn('opggUrl',created['duo']['player2'])

    def test_explicit_empty_link_disables_legacy_fallback(self):
        self.configure()
        duo = self.post('/api/duos', {'authPin': '9999', 'duo': {'id': 'a', 'player1': {'twitchUrl': ''}}})['duo']
        self.assertEqual(server.participant_twitch_channel(duo, 'player1'), '')
        self.assertFalse(duo['twitchIsLive'])
        self.assertFalse(duo['player1']['twitchIsLive'])

    def test_independent_live_states_and_deduplication(self):
        self.configure()
        db = server.load_db()
        db['duos'][0]['player2']['twitchUrl'] = 'https://twitch.tv/second_channel'
        db['duos'][1]['player1']['twitchUrl'] = 'https://twitch.tv/second_channel'
        server.save_db(db)
        result, calls = self.sync(live=['second_channel'])
        self.assertTrue(result['success'])
        self.assertEqual(result['checked'], 2)
        self.assertEqual(calls[0]['first'], ['100'])
        duo = server.load_db()['duos'][0]
        self.assertFalse(duo['player1']['twitchIsLive'])
        self.assertTrue(duo['player2']['twitchIsLive'])
        self.assertTrue(duo['twitchIsLive'])
        self.assertFalse(server.load_db()['duos'][1]['player2']['twitchIsLive'])

    def test_legacy_first_participant_only_and_no_channel_flags(self):
        self.configure()
        self.sync(live=['legacy_channel'])
        duo = server.load_db()['duos'][0]
        self.assertTrue(duo['player1']['twitchIsLive'])
        self.assertFalse(duo['player2']['twitchIsLive'])
        self.assertTrue(duo['twitchIsLive'])
        db = server.load_db()
        db['duos'][0]['twitchUrl'] = ''
        server.save_db(db)
        result, calls = self.sync()
        self.assertTrue(result['success'])
        self.assertEqual(calls, [])
        self.assertFalse(server.load_db()['duos'][0]['twitchIsLive'])

    def test_failure_or_malformed_response_preserves_confirmed_states(self):
        before = self.configure()
        for kwargs in ({'fail': True}, {'malformed': True}):
            result, _ = self.sync(**kwargs)
            self.assertFalse(result['success'])
            self.assertEqual(server.load_db()['duos'][0], before)

    def test_channel_edit_during_response_does_not_apply_stale_result(self):
        self.configure()
        def edit():
            db = server.load_db()
            duo = db['duos'][0]
            duo['player1'].update(displayName='Edited', twitchUrl='https://twitch.tv/new_channel', twitchIsLive=False)
            duo['blueShells'] = 5
            server.save_db(db)
        result, _ = self.sync(live=['legacy_channel'], callback=edit)
        self.assertTrue(result['success'])
        duo = server.load_db()['duos'][0]
        self.assertEqual(duo['player1']['displayName'], 'Edited')
        self.assertFalse(duo['player1']['twitchIsLive'])
        self.assertFalse(duo['twitchIsLive'])
        self.assertEqual(duo['blueShells'], 5)

    def test_more_than_one_hundred_channels_are_batched(self):
        db = server.load_db()
        db['duos'] = [{'id': str(i), 'player1': {'name': 'One', 'twitchUrl': f'https://twitch.tv/channel_{2*i}'},
                       'player2': {'name': 'Two', 'twitchUrl': f'https://twitch.tv/channel_{2*i+1}'}} for i in range(51)]
        server.save_db(db)
        live = [f'channel_{i}' for i in range(102)]
        result, calls = self.sync(live=live)
        self.assertEqual(result['checked'], 102)
        self.assertEqual(result['live'], 102)
        self.assertEqual([len(query['user_login']) for query in calls], [100, 2])
        self.assertTrue(all(duo['twitchIsLive'] for duo in server.load_db()['duos']))


if __name__ == '__main__':
    unittest.main()
