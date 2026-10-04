"""Isolated Twitch polling and Discord delivery tests; no real messages."""
import copy
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import discord_live
import server
import test_shell_penalties as fixtures


URL = 'https://discord.com/api/webhooks/123456/test_token_not_real'


class DiscordLiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(server, 'DB_FILE', str(Path(self.temp.name) / 'db.json'))
        self.remote_patch = patch.object(server, 'remote_backend', None)
        self.env_patch = patch.dict(os.environ, {'DISCORD_LIVE_WEBHOOK_URL': URL})
        for context in (self.db_patch, self.remote_patch, self.env_patch):
            context.start()
            self.addCleanup(context.stop)
        self.addCleanup(self.temp.cleanup)
        self.database = {'config': {}, 'duos': [{'id': 'a', 'teamName': 'Equipo',
            'player1': {'name': 'Uno', 'displayName': 'Luis', 'twitchUrl': 'https://twitch.tv/channel_one'},
            'player2': {'name': 'Dos', 'displayName': 'Pepe', 'twitchUrl': 'https://twitch.tv/channel_two'},
            'history': []}]}
        server.save_db(copy.deepcopy(self.database))

    def sync(self, streams=(), delivery=None, callback=None, twitch_failure=False):
        def reply(request, **kwargs):
            if callback:
                callback()
            if twitch_failure:
                raise urllib.error.URLError('failed')
            return io.BytesIO(json.dumps({'data': list(streams)}).encode())
        with patch.object(server, 'get_twitch_credentials', return_value=('client', 'secret')), \
             patch.object(server, 'get_twitch_app_token', return_value='token'), \
             patch.object(server.urllib.request, 'urlopen', side_effect=reply) as twitch, \
             patch.object(discord_live, 'send', return_value=delivery or {'success': True, 'messageId': 'message'}) as send:
            result = server.sync_twitch_live_status()
        return result, send, twitch

    def stream(self, channel='channel_one', stream_id='stream1'):
        return {'user_login': channel, 'id': stream_id, 'type': 'live', 'title': 'Jugando LoL'}

    def test_two_participants_and_persistent_deduplication(self):
        streams = [self.stream(), self.stream('channel_two', 'stream2')]
        result, send, twitch = self.sync(streams)
        self.assertTrue(result['success'])
        self.assertEqual(result['discord']['sent'], 2)
        self.assertEqual(twitch.call_count, 1)
        self.assertEqual(send.call_args_list[0].args[1]['name'], 'Luis')
        self.assertEqual(send.call_args_list[1].args[1]['name'], 'Pepe')
        self.assertEqual(server.load_db()['discordLiveNotifications']['channel_one']['status'], 'sent')
        # Nothing in the in-memory job status is needed to suppress a duplicate.
        result, send, _ = self.sync(streams)
        send.assert_not_called()
        self.assertEqual(result['discord']['sent'], 0)
        self.assertTrue(server.load_db()['discordLiveStatus']['lastSentAt'])

    def test_offline_then_same_id_is_not_resent_but_new_stream_is(self):
        self.sync([self.stream()])
        self.sync([])
        _, send, _ = self.sync([self.stream()])
        send.assert_not_called()
        _, send, _ = self.sync([self.stream(stream_id='new')])
        self.assertEqual(send.call_count, 1)

    def test_disabled_or_invalid_webhook_never_sends(self):
        for url in ('', 'https://example.com/api/webhooks/123/token'):
            with patch.dict(os.environ, {'DISCORD_LIVE_WEBHOOK_URL': url}):
                result, send, _ = self.sync([self.stream()])
            self.assertTrue(result['success'])
            send.assert_not_called()
        self.assertNotIn('discordLiveNotifications', server.load_db())

    def test_failed_delivery_retries_after_cooldown_without_breaking_twitch(self):
        failure = {'success': False, 'error': 'Discord respondió HTTP 429.', 'retryAfter': 600}
        result, _, _ = self.sync([self.stream()], delivery=failure)
        self.assertTrue(result['success'])
        self.assertEqual(result['discord']['pending'], 1)
        self.assertTrue(server.load_db()['duos'][0]['player1']['twitchIsLive'])
        _, send, _ = self.sync([self.stream()])
        send.assert_not_called()
        db = server.load_db()
        db['discordLiveStatus']['retryAt'] = 0
        server.save_db(db)
        _, send, _ = self.sync([self.stream()])
        self.assertEqual(send.call_count, 1)
        self.assertIsNone(server.load_db()['discordLiveStatus']['error'])

    def test_pending_offline_or_deleted_channel_does_not_send(self):
        failure = {'success': False, 'error': 'network', 'retryAfter': 0}
        self.sync([self.stream()], delivery=failure)
        _, send, _ = self.sync([])
        send.assert_not_called()
        db = server.load_db()
        db['duos'][0]['player1']['twitchUrl'] = ''
        server.save_db(db)
        _, send, _ = self.sync([self.stream()])
        send.assert_not_called()
        self.assertNotIn('channel_one', server.load_db()['discordLiveNotifications'])

    def test_twitch_failure_and_profile_edits_do_not_send_false_alerts(self):
        result, send, _ = self.sync([self.stream()], twitch_failure=True)
        self.assertFalse(result['success'])
        send.assert_not_called()
        def edit():
            db = server.load_db()
            db['duos'][0]['player1']['twitchUrl'] = 'https://twitch.tv/edited_channel'
            server.save_db(db)
        _, send, _ = self.sync([self.stream()], callback=edit)
        send.assert_not_called()

    def test_duplicate_channel_across_teams_only_notifies_once(self):
        db = server.load_db()
        duo = copy.deepcopy(db['duos'][0])
        duo['id'] = 'other'
        db['duos'].append(duo)
        server.save_db(db)
        _, send, _ = self.sync([self.stream()])
        self.assertEqual(send.call_count, 1)

    def test_message_no_mentions_and_confirmed_delivery(self):
        alert = {'channel': 'channel_one', 'name': '*Luis*', 'teamName': '@everyone', 'title': 'LoL'}
        opener = unittest.mock.Mock()
        opener.open.return_value = io.BytesIO(b'{"id":"123"}')
        with patch.object(discord_live.urllib.request, 'build_opener', return_value=opener):
            result = discord_live.send(URL, alert)
        self.assertEqual(result, {'success': True, 'messageId': '123'})
        request = opener.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, URL + '?wait=true')
        self.assertEqual(payload['allowed_mentions'], {'parse': []})
        self.assertEqual(payload['flags'], 4)
        self.assertIn('\\*Luis\\*', payload['content'])
        self.assertIn('https://www.twitch.tv/channel_one', payload['content'])

    def test_http_and_network_errors_hide_secret_and_honor_rate_limit(self):
        for error, delay in ((urllib.error.HTTPError(URL, 429, 'limited', {}, io.BytesIO(b'{"retry_after":720}')), 720),
                             (urllib.error.URLError(URL), 300)):
            opener = unittest.mock.Mock()
            opener.open.side_effect = error
            with patch.object(discord_live.urllib.request, 'build_opener', return_value=opener):
                result = discord_live.send(URL, {'channel': 'channel_one'})
            self.assertFalse(result['success'])
            self.assertEqual(result['retryAfter'], delay)
            self.assertNotIn('test_token', result['error'])


class DiscordTestEndpointTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def test_requires_admin_before_calling_discord(self):
        with patch.dict(os.environ, {'DISCORD_LIVE_WEBHOOK_URL': URL}), patch.object(discord_live, 'send_payload') as send:
            self.post('/api/discord/test', {'authPin': 'wrong'}, expected=401)
        send.assert_not_called()

    def test_missing_webhook_does_not_send(self):
        with patch.dict(os.environ, {'DISCORD_LIVE_WEBHOOK_URL': ''}), patch.object(discord_live, 'send_payload') as send:
            self.post('/api/discord/test', {'authPin': '9999'}, expected=400)
        send.assert_not_called()

    def test_one_fixed_test_message_without_changing_tournament(self):
        before = copy.deepcopy(server.load_db())
        with patch.dict(os.environ, {'DISCORD_LIVE_WEBHOOK_URL': URL}), patch.object(discord_live, 'send_payload', return_value={'success': True, 'messageId': 'test'}) as send:
            result = self.post('/api/discord/test', {'authPin': '9999', 'content': '@everyone fake'}, expected=200)
        self.assertTrue(result['success'])
        send.assert_called_once()
        payload = send.call_args.args[1]
        self.assertIn('Mensaje de prueba', payload['content'])
        self.assertNotIn('fake', payload['content'])
        self.assertEqual(payload['allowed_mentions'], {'parse': []})
        self.assertEqual(server.load_db(), before)

    def test_failed_delivery_reports_safe_error(self):
        with patch.dict(os.environ, {'DISCORD_LIVE_WEBHOOK_URL': URL}), patch.object(discord_live, 'send_payload', return_value={'success': False, 'error': 'Discord respondió HTTP 404.'}):
            result = self.post('/api/discord/test', {'authPin': '9999'}, expected=502)
        self.assertEqual(result['error'], 'Discord respondió HTTP 404.')


if __name__ == '__main__':
    unittest.main()
