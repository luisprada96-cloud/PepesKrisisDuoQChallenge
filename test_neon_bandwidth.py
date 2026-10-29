"""Real HTTP with a disposable Neon substitute; never uses production credentials."""
import copy
import json
import unittest
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import server
import test_shell_penalties as fixtures
from test_postgres_storage import CountingPostgres


class NeonBandwidthEndpointTests(unittest.TestCase):
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def setUp(self):
        fixtures.ShellEndpointTests.setUp(self)
        initial = server.load_db()  # Normalise the isolated fixture, not real data.
        self.backend = CountingPostgres()
        self.backend.remote = copy.deepcopy(initial)
        replacement = patch.object(server, 'remote_backend', self.backend)
        replacement.start()
        self.addCleanup(replacement.stop)

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as response:
            return json.load(response)

    def test_public_reads_check_revisions_without_repeated_document_downloads(self):
        self.assertEqual(len(self.get('/api/duos')), 2)
        for _ in range(12):
            self.backend.checked_at -= 61
            self.assertIn('penaltyWeights', self.get('/api/config'))
        self.assertEqual(self.backend.payload_reads, 1)
        self.assertEqual(len(self.backend.queries), 13)
        self.backend.remote['duos'][0]['teamName'] = 'Equipo actualizado fuera del proceso'
        self.backend.version += 1
        self.backend.checked_at -= 61
        teams = self.get('/api/duos')
        self.assertEqual(next(t for t in teams if t['id'] == 'a')['teamName'], 'Equipo actualizado fuera del proceso')
        self.assertEqual(self.backend.payload_reads, 2)

    def test_concurrent_public_reads_share_the_periodic_check(self):
        self.get('/api/duos')
        self.backend.checked_at -= 61
        with ThreadPoolExecutor(max_workers=4) as pool:
            listings = list(pool.map(lambda _: self.get('/api/duos'), range(8)))
        self.assertTrue(all(len(teams) == 2 for teams in listings))
        self.assertEqual(len(self.backend.queries), 2)
        self.assertEqual(self.backend.payload_reads, 1)

    def test_launch_and_receiver_state_use_confirmed_cached_writes_immediately(self):
        sender = self.post('/api/player/login', {'teamId': 'a', 'password': 'a-pass'})['sessionToken']
        receiver = self.post('/api/player/login', {'teamId': 'b', 'password': 'b-pass'})['sessionToken']
        launched = self.post('/api/player/launch-shell', {'sessionToken': sender, 'targetId': 'b'})
        state = self.post('/api/player/state', {'sessionToken': receiver})['duo']
        self.assertEqual(state['pendingShellAttacks'][0]['id'], launched['attack']['id'])
        self.assertEqual(self.backend.remote['duos'][0]['blueShells'], 0)
        self.assertEqual(self.backend.payload_reads, 1)
        self.backend.checked_at -= 61
        state = self.post('/api/player/state', {'sessionToken': receiver})['duo']
        self.assertEqual(state['pendingShellAttacks'][0]['id'], launched['attack']['id'])
        self.assertEqual(self.backend.payload_reads, 1)


if __name__ == '__main__':
    unittest.main()
