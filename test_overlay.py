import unittest
import urllib.request
import server
import overlay_sessions

import test_shell_penalties as fixtures


class OverlayFilesTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def test_persistent_login_survives_memory_loss_and_is_read_only(self):
        login = self.post('/api/overlay/login', {'teamId': 'b', 'password': 'b-pass'})
        token = login['sessionToken']
        server.player_sessions.clear()  # Simulate a server restart: only stored data remains.
        state = self.post('/api/overlay/state', {'sessionToken': token})
        self.assertEqual(state['duo']['id'], 'b')
        self.assertNotIn('passwordHash', state['duo'])
        self.assertNotIn(token, str(server.load_db()))
        self.assertEqual(server.receiver_notification_state(token)['team']['id'], 'b')
        for path in ('/api/player/state', '/api/player/launch-shell', '/api/player/spin-shell'):
            with self.subTest(path=path):
                self.post(path, {'sessionToken': token, 'targetId': 'a', 'attackId': 'fake'}, expected=401)
        self.post('/api/overlay/logout', {'sessionToken': token})
        self.post('/api/overlay/state', {'sessionToken': token}, expected=401)
        self.assertIsNone(server.receiver_notification_state(token))

    def test_password_change_revokes_only_that_teams_devices(self):
        first = self.post('/api/overlay/login', {'teamId': 'b', 'password': 'b-pass'})['sessionToken']
        second = self.post('/api/overlay/login', {'teamId': 'b', 'password': 'b-pass'})['sessionToken']
        other = self.post('/api/overlay/login', {'teamId': 'a', 'password': 'a-pass'})['sessionToken']
        self.post('/api/overlay/logout', {'sessionToken': first})
        self.post('/api/overlay/state', {'sessionToken': second})
        with server.db_lock:
            db = server.load_db()
            db['duos'][1]['passwordHash'] = server.hash_secret('new-pass')
            server.save_db(db)
        self.post('/api/overlay/state', {'sessionToken': second}, expected=401)
        self.post('/api/overlay/state', {'sessionToken': other})

    def test_upgrade_existing_session_and_reject_invalid_credentials(self):
        self.post('/api/overlay/login', {'teamId': 'b', 'password': 'wrong'}, expected=401)
        self.post('/api/overlay/state', {'sessionToken': 'obs_forged'}, expected=401)
        self.post('/api/overlay/session', {'sessionToken': 'forged'}, expected=401)
        old = self.post('/api/player/login', {'teamId': 'b', 'password': 'b-pass'})['sessionToken']
        new = self.post('/api/overlay/session', {'sessionToken': old})['sessionToken']
        self.assertNotEqual(old, new)
        self.assertIsNone(server.session_team(new))
        self.assertEqual(overlay_sessions.team(server.load_db(), new), 'b')

    def test_overlay_assets_are_served_without_a_session(self):
        for filename, content_type in [('overlay.html', 'text/html'),
                                       ('overlay.js', 'javascript'),
                                       ('overlay.css', 'text/css'),
                                       ('overlay-pepazo.mp3', 'audio/mpeg')]:
            with self.subTest(filename=filename):
                with urllib.request.urlopen(self.base + '/' + filename) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(content_type, response.headers['Content-Type'])
                    self.assertGreater(len(response.read()), 100)


if __name__ == '__main__':
    unittest.main()
