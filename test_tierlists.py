"""Permanent tierlists: team auth, browser quota, atomic limits and public assets."""
import copy
import http.cookiejar
import json
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import server
import tierlists_service as tierlists
import test_shell_penalties as fixtures
from storage import StorageError


def arrangement():
    ids = [item['id'] for item in tierlists.ITEMS]
    return {'S': ids[:2], 'A': ids[2:4], 'B': ids[4:6], 'C': ids[6:8], 'D': ids[8:]}


class TierlistServiceTests(unittest.TestCase):
    def test_optional_author_and_order_preserved_without_weekly_reset(self):
        db = {'duos': [{'id': 'a', 'teamName': 'Equipo'}]}
        rows = arrangement()
        rows['S'].reverse()
        tierlists.publish(db, 'a', 'private-browser', '', rows, now=1)
        with patch.object(tierlists.time, 'time', return_value=1999999999):
            board = tierlists.public_board(db)
        self.assertEqual(board['posts'][0]['author'], '')
        self.assertEqual(board['posts'][0]['tiers'], rows)
        self.assertNotIn('private-browser', json.dumps(board))
        self.assertNotIn('visitor', board['posts'][0])

    def test_cannot_forge_missing_repeated_or_unknown_teams(self):
        invalid = [None, [], {}, {**arrangement(), 'E': []}, {**arrangement(), 'S': []},
                   {**arrangement(), 'S': ['atodoflash', 'atodoflash']},
                   {**arrangement(), 'S': ['unknown', 'atodoflash']}, {**arrangement(), 'D': [1]},
                   {**arrangement(), 'D': 'atodoflash'}]
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(ValueError): tierlists.validate_tiers(rows)

    def test_pagination_is_recent_first_and_posts_keep_author_team_snapshot(self):
        db = {'duos': [{'id': str(i), 'teamName': f'Equipo {i}'} for i in range(7)]}
        for i in range(7): tierlists.publish(db, str(i), str(i), f'Autor {i}', arrangement(), now=i)
        db['duos'] = []
        page = tierlists.public_board(db, offset=6)
        self.assertEqual(page['total'], 7)
        self.assertEqual(page['posts'][0]['author'], 'Autor 0')
        self.assertEqual(page['posts'][0]['teamName'], 'Equipo 0')


class TierlistEndpointTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.object(server, 'remote_backend', None).start()
        patch.object(server.CustomHandler, 'log_message', return_value=None).start()
        fixtures.ShellEndpointTests.setUp(self)
        server.load_db()

    tearDown = fixtures.ShellEndpointTests.tearDown

    def client(self):
        jar = http.cookiejar.CookieJar()
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), jar

    def call(self, client, data=None, headers=None, status=200, path='/api/tierlists'):
        request = urllib.request.Request(self.base + path, data=None if data is None else json.dumps(data).encode(),
                                         headers={'Content-Type': 'application/json', **(headers or {})})
        try: response = client.open(request, timeout=5)
        except urllib.error.HTTPError as failure: response = failure
        with response:
            self.assertEqual(response.status, status)
            return json.load(response), response.headers

    def login(self, client, team='a'):
        self.call(client)
        login, _ = self.call(client, {'teamId': team, 'password': team + '-pass'}, path='/api/player/login')
        return {'Authorization': 'Bearer ' + login['sessionToken']}

    def test_two_distinct_browsers_can_publish_third_cannot_and_public_data_persists(self):
        for index in range(3):
            client, jar = self.client()
            auth = self.login(client)
            result, _ = self.call(client, {'author': f'Persona {index}', 'tiers': arrangement()}, auth, status=200 if index < 2 else 409)
            if index < 2:
                self.assertTrue(result['success'])
                self.assertFalse(result['publishing']['canPublish'])
                self.call(client, {'author': 'Otra', 'tiers': arrangement()}, auth, status=409)
                persisted_client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
                self.assertFalse(self.call(persisted_client, headers=auth)[0]['publishing']['canPublish'])
        reader, _ = self.client()
        board, _ = self.call(reader)
        self.assertEqual(board['total'], 2)
        self.assertEqual({p['author'] for p in board['posts']}, {'Persona 0', 'Persona 1'})
        raw = json.loads(Path(server.DB_FILE).read_text(encoding='utf-8'))
        self.assertEqual(len(raw['tierlists']), 2)
        for post in raw['tierlists']:
            self.assertEqual(len(post['visitor']), 64)
            self.assertNotIn(post['visitor'], json.dumps(board))

    def test_same_browser_cannot_publish_twice_even_after_switching_team(self):
        client, _ = self.client()
        auth = self.login(client)
        self.call(client, {'tiers': arrangement(), 'teamId': 'b'}, auth)
        self.assertEqual(server.load_db()['tierlists'][0]['teamId'], 'a')
        auth = self.login(client, 'b')
        self.call(client, {'tiers': arrangement()}, auth, status=409)

    def test_no_auth_expired_session_missing_cookie_and_cross_origin_are_blocked(self):
        client, _ = self.client()
        self.call(client, {'tiers': arrangement()}, status=401)
        auth = self.login(client)
        self.call(client, {'tiers': arrangement()}, {**auth, 'Origin': 'https://evil.test'}, status=403)
        fresh, _ = self.client()
        self.call(fresh, {'tiers': arrangement()}, auth, status=400)
        server.player_sessions.clear()
        self.call(client, {'tiers': arrangement()}, auth, status=401)
        self.assertFalse(server.load_db().get('tierlists'))

    def test_invalid_input_does_not_spend_attempt_and_optional_author_is_allowed(self):
        client, _ = self.client()
        auth = self.login(client)
        for body in ({'tiers': {}}, {'tiers': arrangement(), 'author': []}, {'tiers': arrangement(), 'author': 'a'*61}):
            self.call(client, body, auth, status=400)
        self.call(client, {'tiers': arrangement()}, auth)
        self.assertEqual(server.load_db()['tierlists'][0]['author'], '')

    def test_failed_save_does_not_spend_attempt(self):
        client, _ = self.client()
        auth = self.login(client)
        with patch.object(server, 'save_db', side_effect=StorageError('Storage unavailable')):
            self.call(client, {'tiers': arrangement()}, auth, status=503)
        self.assertFalse(server.load_db().get('tierlists'))
        self.assertTrue(self.call(client, headers=auth)[0]['publishing']['canPublish'])
        self.call(client, {'tiers': arrangement()}, auth)

    def test_concurrent_requests_share_last_team_slot_atomically(self):
        first, _ = self.client()
        auth = self.login(first)
        self.call(first, {'tiers': arrangement()}, auth)
        remaining = [self.client()[0] for _ in range(2)]
        for client in remaining: self.call(client)
        barrier = threading.Barrier(2)
        def submit(client):
            barrier.wait()
            request = urllib.request.Request(self.base+'/api/tierlists', data=json.dumps({'tiers':arrangement()}).encode(), headers={'Content-Type':'application/json', **auth})
            try:
                with client.open(request, timeout=5) as response: return response.status
            except urllib.error.HTTPError as error: return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(submit, remaining))
        self.assertEqual(sorted(codes), [200,409])
        self.assertEqual(len(server.load_db()['tierlists']), 2)

    def test_cookie_and_static_asset_allowlist(self):
        client, _ = self.client()
        _, headers = self.call(client, headers={'X-Forwarded-Proto': 'https'})
        cookie = headers['Set-Cookie']
        for value in ('pepes_tierlist_visitor=', 'HttpOnly', 'SameSite=Lax', 'Secure'): self.assertIn(value, cookie)
        for item in tierlists.ITEMS:
            with client.open(self.base+item['image'], timeout=3) as response:
                self.assertEqual(response.headers['Content-Type'], 'image/png')
                self.assertEqual(response.read(8), b'\x89PNG\r\n\x1a\n')
        for path in ('/tierlists_service.py', '/assets/tierlist/../../db.json', '/assets/tierlist/unknown.png'):
            self.call(client, path=path, status=404)


if __name__ == '__main__': unittest.main()
