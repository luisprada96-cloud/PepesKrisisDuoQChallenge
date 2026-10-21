"""Remembered team cookies use isolated fixtures, never the live database."""
import json
import unittest
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from unittest.mock import patch

import remembered_sessions as sessions
import server
import test_shell_penalties as fixtures


class RememberedSessionTests(unittest.TestCase):
    def test_expiry_credentials_and_removed_team(self):
        duo = {'id': 'a', 'passwordHash': 'test-hash'}
        db = {'duos': [duo]}
        token = sessions.create(db, duo, now=100)
        self.assertEqual(sessions.team(db, token, now=100 + sessions.LIFETIME - 1), 'a')
        self.assertIsNone(sessions.team(db, token, now=100 + sessions.LIFETIME))
        self.assertIsNone(sessions.team(db, 'forged', now=101))
        duo['passwordHash'] = 'changed'
        self.assertIsNone(sessions.team(db, token, now=101))
        token = sessions.create(db, duo, now=102)
        self.assertEqual(len(db['rememberedTeamSessions']), 1)
        db['duos'] = []
        self.assertIsNone(sessions.team(db, token, now=103))

    def test_device_limit_and_pruning(self):
        duo = {'id': 'a', 'passwordHash': 'test-hash'}
        db = {'duos': [duo]}
        first = sessions.create(db, duo, now=100)
        for i in range(sessions.MAX_DEVICES):
            last = sessions.create(db, duo, now=101 + i)
        self.assertEqual(len(db['rememberedTeamSessions']), sessions.MAX_DEVICES)
        self.assertIsNone(sessions.team(db, first, now=200))
        self.assertEqual(sessions.team(db, last, now=200), 'a')
        self.assertNotIn(last, json.dumps(db))


class RememberedEndpointTests(unittest.TestCase):
    def setUp(self):
        self.backend = patch.object(server, 'remote_backend', None)
        self.backend.start()
        fixtures.ShellEndpointTests.setUp(self)

    def tearDown(self):
        fixtures.ShellEndpointTests.tearDown(self)
        self.backend.stop()

    def request(self, path, payload=None, cookie=None, headers=None, expected=200):
        request = urllib.request.Request(self.base + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Content-Type': 'application/json', **({'Cookie': cookie} if cookie else {}), **(headers or {})})
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, expected)
            return json.load(response), response.headers

    def login(self, team='a', cookie=None, headers=None):
        result, response_headers = self.request('/api/player/login', {'teamId': team, 'password': team + '-pass'}, cookie, headers)
        return result, response_headers['Set-Cookie'].split(';')[0]

    def test_remembers_default_and_restores_after_restart_without_tab_token(self):
        result, cookie = self.login()
        self.assertTrue(result['remembered'])
        token = cookie.split('=', 1)[1]
        self.assertNotIn(token, json.dumps(server.load_db()))
        self.assertNotIn(token, json.dumps(result))
        server.player_sessions.clear()
        state, _ = self.request('/api/player/state', {}, cookie)
        self.assertEqual(state['duo']['id'], 'a')
        self.assertNotIn('passwordHash', state['duo'])
        self.request('/api/player/state', {'sessionToken': result['sessionToken']}, cookie, expected=401)
        self.request('/api/player/state', {}, cookie, {'Authorization': 'Bearer forged'}, expected=401)

    def test_cookie_flags_for_local_and_https_proxy(self):
        _, headers = self.request('/api/player/login', {'teamId': 'a', 'password': 'a-pass'})
        cookie = SimpleCookie(headers['Set-Cookie'])[sessions.COOKIE]
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax')
        self.assertEqual(cookie['path'], '/')
        self.assertEqual(int(cookie['max-age']), sessions.LIFETIME)
        self.assertFalse(cookie['domain'])
        self.assertFalse(cookie['secure'])
        for extra in ({'X-Forwarded-Proto': 'https'}, {'Host': 'duoqchallenge.luisjourney.xyz'}):
            _, headers = self.request('/api/player/login', {'teamId': 'a', 'password': 'a-pass'}, headers=extra)
            self.assertTrue(SimpleCookie(headers['Set-Cookie'])[sessions.COOKIE]['secure'])

    def test_logout_revokes_only_this_device_and_survives_copied_cookie(self):
        first, cookie1 = self.login()
        _, cookie2 = self.login()
        _, cookie_b = self.login('b')
        _, headers = self.request('/api/player/logout', {}, cookie1)
        self.assertIn('Max-Age=0', headers['Set-Cookie'])
        self.request('/api/player/state', {}, cookie1, expected=401)
        self.request('/api/player/state', {'sessionToken': first['sessionToken']}, expected=401)
        self.request('/api/player/state', {}, cookie2)
        self.request('/api/player/state', {}, cookie_b)

    def test_password_change_revokes_cookies_and_legacy_aliases(self):
        first, cookie = self.login()
        _, other_device = self.login()
        _, other_team = self.login('b')
        with server.db_lock:
            db = server.load_db()
            db['duos'][0]['passwordHash'] = server.hash_secret('changed')
            server.save_db(db)
        self.request('/api/player/state', {}, cookie, expected=401)
        self.request('/api/player/state', {}, other_device, expected=401)
        self.request('/api/player/state', {'sessionToken': first['sessionToken']}, expected=401)
        self.request('/api/player/state', {}, other_team)
        self.assertIsNone(server.receiver_notification_state(cookie.split('=', 1)[1], remembered=True))

    def test_switching_teams_rotates_cookie_and_revokes_previous_device(self):
        old, cookie1 = self.login()
        _, cookie2 = self.login('b', cookie1)
        state, _ = self.request('/api/player/state', {}, cookie2)
        self.assertEqual(state['duo']['id'], 'b')
        self.request('/api/player/state', {}, cookie1, expected=401)
        self.request('/api/player/state', {'sessionToken': old['sessionToken']}, expected=401)

    def test_cookie_auth_for_other_features_and_no_obs_escalation(self):
        _, cookie = self.login()
        result, _ = self.request('/api/shop', cookie=cookie)
        self.assertEqual(result['wallet']['teamId'], 'a')
        overlay, _ = self.request('/api/overlay/session', {}, cookie)
        self.request('/api/player/state', {'sessionToken': overlay['sessionToken']}, cookie, expected=401)
        self.request('/api/admin/login', {'pin': 'wrong'}, cookie, expected=401)
        self.request('/api/player/logout', {}, cookie)
        self.request('/api/overlay/state', {'sessionToken': overlay['sessionToken']})

    def test_cookie_can_launch_and_receive_live_notifications(self):
        _, sender = self.login()
        _, receiver = self.login('b')
        request = urllib.request.Request(self.base + '/api/player/events', headers={'Cookie': receiver})
        with urllib.request.urlopen(request, timeout=5) as response:
            def frame():
                lines = []
                while True:
                    line = response.readline().decode()
                    if not line or line == '\n': return ''.join(lines)
                    lines.append(line)
            self.assertEqual(json.loads(frame()[6:])['team']['id'], 'b')
            attack, _ = self.request('/api/player/launch-shell', {'targetId': 'b'}, sender)
            self.assertEqual(json.loads(frame()[6:])['attacks'][0]['id'], attack['attack']['id'])
            self.request('/api/player/logout', {}, receiver)
            self.assertIn('event: expired', frame())

    def test_csrf_rejects_login_logout_and_actions_without_mutating(self):
        _, cookie = self.login()
        for path, payload in [('/api/player/login', {'teamId': 'b', 'password': 'b-pass'}),
                              ('/api/player/logout', {}), ('/api/player/launch-shell', {'targetId': 'b'})]:
            for headers, expected in [({'Origin': 'https://evil.example'}, 403),
                                      ({'Sec-Fetch-Site': 'cross-site'}, 403),
                                      ({'Content-Type': 'text/plain'}, 415)]:
                with self.subTest(path=path, headers=headers):
                    self.request(path, payload, cookie, headers, expected)
        self.request('/api/player/state', {}, cookie, {'Origin': self.base})
        self.assertFalse(server.load_db()['shellAttacks'])

    def test_expired_session_and_failed_save_do_not_issue_cookies(self):
        _, cookie = self.login()
        with server.db_lock:
            db = server.load_db()
            for record in db['rememberedTeamSessions'].values(): record['expiresAt'] = 0
            server.save_db(db)
        self.request('/api/player/state', {}, cookie, expected=401)
        with patch.object(server, 'save_db', side_effect=server.StorageError('test failure')):
            _, headers = self.request('/api/player/login', {'teamId': 'b', 'password': 'b-pass'}, expected=503)
        self.assertIsNone(headers.get('Set-Cookie'))


if __name__ == '__main__':
    unittest.main()
