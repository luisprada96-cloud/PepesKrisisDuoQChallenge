"""Credential probes use real endpoints, with isolated responses in tests."""
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

import server
import test_shell_penalties as fixtures


class CredentialProbeTests(unittest.TestCase):
    def run_probe(self, reply):
        with patch.object(server, 'get_riot_api_key', return_value='private-riot-key'), \
             patch.object(server, 'get_twitch_credentials', return_value=('client', 'private-secret')), \
             patch.object(server, 'clear_twitch_token_cache') as clear, \
             patch.object(server, 'get_twitch_app_token', return_value='private-token'), \
             patch.object(server.urllib.request, 'urlopen', side_effect=reply) as calls:
            result = server.check_service_credentials({'config': {'server': 'EUW'}, 'duos': []})
        clear.assert_called()
        for secret in ('private-riot-key', 'private-secret', 'private-token'):
            self.assertNotIn(secret, json.dumps(result))
        return result, calls

    def test_no_teams_still_makes_authenticated_requests(self):
        def reply(request, **kwargs):
            payload = {'id': 'EUW1'} if 'riotgames.com' in request.full_url else {'data': []}
            return io.BytesIO(json.dumps(payload).encode())
        result, calls = self.run_probe(reply)
        self.assertTrue(result['riot']['success'])
        self.assertTrue(result['twitch']['success'])
        self.assertEqual(calls.call_count, 2)
        self.assertEqual(calls.call_args_list[0].args[0].get_header('X-riot-token'), 'private-riot-key')
        self.assertEqual(calls.call_args_list[1].args[0].get_header('Authorization'), 'Bearer private-token')

    def test_http_failure_is_independent_and_safe(self):
        def reply(request, **kwargs):
            if 'riotgames.com' in request.full_url:
                raise urllib.error.HTTPError(request.full_url, 401, 'private-riot-key', {}, None)
            return io.BytesIO(b'{"data":[]}')
        result, _ = self.run_probe(reply)
        self.assertFalse(result['riot']['success'])
        self.assertEqual(result['riot']['httpStatus'], 401)
        self.assertTrue(result['twitch']['success'])

    def test_missing_credentials_never_issue_requests(self):
        with patch.object(server, 'get_riot_api_key', return_value=''), \
             patch.object(server, 'get_twitch_credentials', return_value=('', '')), \
             patch.object(server.urllib.request, 'urlopen') as calls:
            result = server.check_service_credentials({})
        calls.assert_not_called()
        self.assertFalse(result['riot']['success'])
        self.assertFalse(result['twitch']['success'])

    def test_malformed_success_is_not_reported_as_ok(self):
        result, _ = self.run_probe(lambda *args, **kwargs: io.BytesIO(b'{}'))
        self.assertFalse(result['riot']['success'])
        self.assertFalse(result['twitch']['success'])


class CredentialEndpointTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def test_probe_requires_admin_auth(self):
        with patch.object(server, 'check_service_credentials') as probe:
            self.post('/api/admin/check-apis', {}, expected=401)
        probe.assert_not_called()

    def test_confirmed_riot_response_updates_timestamp_without_teams(self):
        db = server.load_db()
        db['duos'] = []
        server.save_db(db)
        checks = {'checkedAt': '2026-10-13T20:00:00Z', 'riot': {'success': True, 'httpStatus': 200}, 'twitch': {'success': True, 'httpStatus': 200}}
        with patch.object(server, 'check_service_credentials', return_value=checks):
            result = self.post('/api/admin/check-apis', {'authPin': '9999'})
        self.assertEqual(result['riot']['httpStatus'], 200)
        self.assertTrue(server.load_db()['lastRiotApiSuccessAt'])
        self.assertEqual(server.load_db()['duos'], [])


if __name__ == '__main__':
    unittest.main()
