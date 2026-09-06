import json
import urllib.request
import unittest

import server
import test_shell_penalties as fixtures


class NotificationTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def open_stream(self, token):
        request = urllib.request.Request(self.base + '/api/player/events', headers={'Authorization': 'Bearer ' + token})
        return urllib.request.urlopen(request, timeout=3)

    def frame(self, response):
        lines = []
        while True:
            line = response.readline().decode()
            if not line or line == '\n':
                return ''.join(lines)
            lines.append(line)

    def test_notifications_are_private_immediate_and_session_bound(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.open_stream('invalid')
        self.assertEqual(error.exception.code, 401)
        attacker = self.post('/api/player/login', {'teamId': 'a', 'password': 'a-pass'})['sessionToken']
        receiver = self.post('/api/player/login', {'teamId': 'b', 'password': 'b-pass'})['sessionToken']
        own_stream = self.open_stream(attacker)
        target_stream = self.open_stream(receiver)
        try:
            self.assertEqual(json.loads(self.frame(own_stream).removeprefix('data: '))['attacks'], [])
            baseline = json.loads(self.frame(target_stream).removeprefix('data: '))
            self.assertEqual(baseline['team']['id'], 'b')
            self.assertEqual(baseline['attacks'], [])
            result = self.post('/api/player/launch-shell', {'targetId': 'b', 'sessionToken': attacker})
            frame = self.frame(target_stream)
            message = json.loads(frame.removeprefix('data: '))
            self.assertEqual(message['attacks'][0]['id'], result['attack']['id'])
            self.assertNotIn('password', frame)
            self.assertNotIn('sessionToken', frame)
            self.assertTrue(self.frame(own_stream).startswith(': heartbeat'))
            self.post('/api/player/logout', {'sessionToken': receiver})
            self.assertIn('event: expired', self.frame(target_stream))
            self.post('/api/player/state', {'sessionToken': receiver}, expected=401)
        finally:
            server.player_sessions.clear()
            server.notify_shell_receivers()
            own_stream.close()
            target_stream.close()


if __name__ == '__main__':
    unittest.main()
