import copy
import json
import http.cookiejar
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import clips_service as clips
import server
import test_shell_penalties as fixtures
from storage import StorageError


class WeeklyClipsTests(unittest.TestCase):
    def test_week_changes_at_madrid_midnight_in_both_dst_transitions(self):
        for month, sunday, monday in ((3, 29, 30), (10, 25, 26)):
            before = datetime(2026, month, sunday, 23, 58, 59, tzinfo=clips.MADRID).timestamp()
            after = datetime(2026, month, monday, 0, 0, 0, tzinfo=clips.MADRID).timestamp()
            db = {'duos': [{'id': 'winner', 'teamName': 'Ganador', 'blueShells': 5}]}
            board, _ = clips.board_for(db, now=before)
            clips.publish(board, 'Clip', 'https://clips.twitch.tv/TestClip', now=before, team=db['duos'][0])
            clips.set_like(board, board['posts'][0]['id'], 'winner', 'voter', True, now=before)
            old_week = board['week']
            board, changed = clips.board_for(db, now=after)
            self.assertTrue(changed)
            self.assertNotEqual(old_week, board['week'])
            self.assertEqual(board['posts'], [])
            self.assertEqual(db['duos'][0]['blueShells'], 8)
            self.assertEqual(board['previousWeeklyAward']['teamId'], 'winner')

    def test_preview_is_opt_in_and_never_invents_like_counts(self):
        board, _ = clips.board_for({})
        self.assertEqual(board['posts'], [])
        board, _ = clips.board_for({}, preview=True)
        self.assertEqual(len(board['posts']), 3)
        self.assertTrue(all(post['votes'] == 0 for post in clips.public_board(board, 'visitor')['clips']))

    def test_only_twitch_clip_urls_are_accepted(self):
        self.assertEqual(clips.parse_url('https://www.twitch.tv/player/clip/TestClip-abc?tt_medium=web'), 'TestClip-abc')
        for value in ('http://clips.twitch.tv/Test', 'https://clips.twitch.tv.evil.test/Test', 'https://evil.test/Test', 'https://clips.twitch.tv/embed', 'https://clips.twitch.tv/%22evil', 'https://user:password@clips.twitch.tv/Test'):
            with self.subTest(value=value), self.assertRaises(ValueError): clips.parse_url(value)


class SharedLikesTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.object(server, 'remote_backend', None).start()
        patch.object(server, 'CLIPS_PREVIEW', False).start()
        patch.object(server.CustomHandler, 'log_message', return_value=None).start()
        fixtures.ShellEndpointTests.setUp(self)

    tearDown = fixtures.ShellEndpointTests.tearDown

    def client(self):
        jar = http.cookiejar.CookieJar()
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), jar

    def call(self, client, path='/api/clips', data=None, status=200, headers=None):
        request = urllib.request.Request(self.base + path, data=None if data is None else json.dumps(data).encode(), headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            response = client.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, status)
            return json.load(response), response.headers

    def setup_post(self):
        owner, jar = self.client()
        self.call(owner)
        result, _ = self.call(owner, data={'title': 'Una jugada', 'url': 'https://clips.twitch.tv/ExampleClip', 'teamId': 'a'})
        return owner, jar, result['clips'][0]['id']

    def login(self, client, team='a'):
        self.call(client)
        result, _ = self.call(client, '/api/player/login', {'teamId': team, 'password': team + '-pass'})
        return {'Authorization': 'Bearer ' + result['sessionToken']}

    def test_browser_votes_are_shared_idempotent_reversible_and_persistent(self):
        owner, jar, clip_id = self.setup_post()
        auth = self.login(owner)
        other, _ = self.client()
        other_auth = self.login(other)
        for _ in range(2):
            result, _ = self.call(owner, '/api/clips/like', {'clipId': clip_id, 'liked': True}, headers=auth)
            self.assertEqual(result['clips'][0]['votes'], 1)
            self.assertTrue(result['clips'][0]['liked'])
        result, _ = self.call(other, headers=other_auth)
        self.assertFalse(result['clips'][0]['liked'])
        self.assertEqual(result['clips'][0]['votes'], 1)
        self.assertNotIn('teamVotes', result['clips'][0])
        self.assertNotIn('likedBy', result['clips'][0])
        self.call(other, '/api/clips/like', {'clipId': clip_id, 'liked': True}, headers=other_auth)
        self.assertEqual(self.call(owner, headers=auth)[0]['clips'][0]['votes'], 2)
        restored = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.assertTrue(self.call(restored, headers=auth)[0]['clips'][0]['liked'])
        persisted = json.loads(Path(server.DB_FILE).read_text(encoding='utf-8'))
        voters = persisted['clips']['posts'][0]['teamVotes']['a']
        self.assertEqual(len(voters), 2)
        self.assertTrue(all(len(value) == 64 for value in voters))
        for _ in range(2):
            self.call(owner, '/api/clips/like', {'clipId': clip_id, 'liked': False}, headers=auth)
        self.assertEqual(self.call(other, headers=other_auth)[0]['clips'][0]['votes'], 1)
        self.assertTrue(self.call(other, headers=other_auth)[0]['clips'][0]['liked'])

    def test_restart_requires_login_but_keeps_browser_count(self):
        owner, jar, clip_id = self.setup_post()
        auth = self.login(owner)
        self.call(owner, '/api/clips/like', {'clipId': clip_id, 'liked': True}, headers=auth)
        server.player_sessions.clear()
        self.call(owner, '/api/clips/like', {'clipId': clip_id, 'liked': False}, headers=auth, status=401)
        self.assertEqual(self.call(owner)[0]['clips'][0]['votes'], 1)
        auth = self.login(owner)
        self.assertTrue(self.call(owner, headers=auth)[0]['clips'][0]['liked'])

    def test_concurrent_retries_do_not_duplicate_and_other_browsers_respect_team_cap(self):
        owner, jar, clip_id = self.setup_post()
        auth = self.login(owner)
        cookies = '; '.join(f'{item.name}={item.value}' for item in jar)
        def like(_):
            result, _ = self.call(urllib.request.build_opener(), '/api/clips/like', {'clipId': clip_id, 'liked': True}, headers={**auth,'Cookie':cookies})
            return result['clips'][0]['votes']
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(like, range(8))), [1] * 8)
        second, _ = self.client()
        second_auth = self.login(second)
        self.call(second, '/api/clips/like', {'clipId': clip_id, 'liked': True}, headers=second_auth)
        third, _ = self.client()
        third_auth = self.login(third)
        self.call(third, '/api/clips/like', {'clipId': clip_id, 'liked': True}, headers=third_auth, status=409)
        self.call(third, '/api/clips/like', {'clipId': clip_id, 'liked': False}, headers=third_auth)
        self.assertEqual(self.call(owner)[0]['clips'][0]['votes'], 2)
        self.call(owner, '/api/clips/like', {'clipId': clip_id, 'liked': False}, headers=auth)
        self.call(third, '/api/clips/like', {'clipId': clip_id, 'liked': True}, headers=third_auth)
        self.assertEqual(self.call(owner)[0]['clips'][0]['votes'], 2)

    def test_simultaneous_distinct_browsers_accept_only_two_per_team(self):
        owner, jar, clip_id = self.setup_post()
        clients = [self.client()[0] for _ in range(6)]
        auths = [self.login(client) for client in clients]
        def like(pair):
            client, auth = pair
            request = urllib.request.Request(self.base+'/api/clips/like', data=json.dumps({'clipId':clip_id,'liked':True}).encode(), headers={'Content-Type':'application/json',**auth})
            try:
                with client.open(request, timeout=5) as response: return response.status
            except urllib.error.HTTPError as error:
                error.close()
                return error.code
        with ThreadPoolExecutor(max_workers=6) as pool:
            statuses = list(pool.map(like, zip(clients,auths)))
        self.assertEqual(statuses.count(200), 2)
        self.assertEqual(statuses.count(409), 4)
        self.assertEqual(self.call(owner)[0]['clips'][0]['votes'], 2)

    def test_switching_team_cannot_add_second_browser_vote_or_spoof_team(self):
        owner, jar, clip_id = self.setup_post()
        a = self.login(owner)
        self.call(owner, '/api/clips/like', {'clipId':clip_id,'liked':True}, headers=a)
        b = self.login(owner, 'b')
        self.call(owner, '/api/clips/like', {'clipId':clip_id,'liked':True,'teamId':'b'}, headers=b)
        self.assertEqual(self.call(owner, headers=b)[0]['clips'][0]['votes'], 1)
        self.call(owner, '/api/clips/like', {'clipId':clip_id,'liked':False}, headers=b)
        self.call(owner, '/api/clips/like', {'clipId':clip_id,'liked':True,'teamId':'a'}, headers=b)
        self.assertEqual(list(server.load_db()['clips']['posts'][0]['teamVotes']), ['b'])

    def test_previous_shared_counts_migrate_without_losing_votes(self):
        owner, jar, clip_id = self.setup_post()
        db=server.load_db()
        db['clips']['posts'][0]['teamVotes']={'a':2}
        server.save_db(db)
        for client in (owner, self.client()[0]):
            auth=self.login(client)
            result,_=self.call(client,'/api/clips/like',{'clipId':clip_id,'liked':True},headers=auth)
            self.assertEqual(result['clips'][0]['votes'],2)
            self.assertTrue(result['clips'][0]['liked'])
        third,_=self.client()
        self.call(third,'/api/clips/like',{'clipId':clip_id,'liked':True},headers=self.login(third),status=409)

    def test_anonymous_missing_cookie_expired_deleted_team_bad_origin_and_invalid_likes_rejected(self):
        owner, jar, clip_id = self.setup_post()
        payload = {'clipId': clip_id, 'liked': True}
        self.call(owner, '/api/clips/like', payload, status=401)
        self.call(owner, '/api/clips/like', {**payload, 'teamId': 'a', 'sessionToken': 'invented'}, status=401)
        auth = self.login(owner)
        self.call(urllib.request.build_opener(), '/api/clips/like', payload, status=401, headers=auth)
        self.call(owner, '/api/clips/like', payload, status=403, headers={**auth, 'Origin': 'https://elsewhere.test'})
        for value in (-1, 0, 1, 2, 1.0, 'true', None):
            with self.subTest(value=value):
                self.call(owner, '/api/clips/like', {**payload, 'liked': value}, status=400, headers=auth)
        self.call(owner, '/api/clips/like', {'clipId':'missing','liked':True}, status=404, headers=auth)
        self.assertEqual(self.call(owner)[0]['clips'][0]['votes'],0)
        token=auth['Authorization'][7:]
        server.player_sessions[token]['expiresAt']=0
        self.call(owner,'/api/clips/like',payload,status=401,headers=auth)
        self.assertIsNone(self.call(owner,headers=auth)[0]['voting'])
        auth=self.login(owner)
        db=server.load_db()
        db['duos']=[duo for duo in db['duos'] if duo['id']!='a']
        server.save_db(db)
        self.call(owner,'/api/clips/like',payload,status=401,headers=auth)

    def test_storage_failure_does_not_report_success_or_increment_twice(self):
        owner, jar, clip_id = self.setup_post()
        auth=self.login(owner)
        with patch.object(server,'save_db',side_effect=StorageError('offline')):
            self.call(owner,'/api/clips/like',{'clipId':clip_id,'liked':True},status=503,headers=auth)
        self.assertEqual(self.call(owner)[0]['clips'][0]['votes'],0)
        self.call(owner,'/api/clips/like',{'clipId':clip_id,'liked':True},headers=auth)
        self.assertEqual(self.call(owner)[0]['clips'][0]['votes'],1)

    def test_publications_survive_reads_and_duplicates_are_rejected(self):
        owner, jar, clip_id = self.setup_post()
        other, _ = self.client()
        self.assertEqual(self.call(other)[0]['clips'][0]['id'], clip_id)
        self.call(owner, data={'title': 'Duplicado', 'url': 'https://www.twitch.tv/another/clip/ExampleClip', 'teamId': 'a'}, status=409)
        self.call(owner, data={'title': 'Malo', 'url': 'https://example.test/video', 'teamId': 'a'}, status=400)
        self.assertEqual(len(self.call(other)[0]['clips']), 1)

    def test_expired_week_is_pruned_and_old_like_cannot_be_reapplied(self):
        owner, jar, clip_id = self.setup_post()
        auth = self.login(owner)
        self.call(owner, '/api/clips/like', {'clipId': clip_id, 'liked': True}, headers=auth)
        db = server.load_db()
        db['clips']['week'] = '2020-01-06'
        duos = copy.deepcopy(db['duos'])
        server.save_db(db)
        self.assertEqual(self.call(owner)[0]['clips'], [])
        self.call(owner, '/api/clips/like', {'clipId': clip_id, 'liked': True}, status=404, headers=auth)
        self.assertEqual(server.load_db()['duos'], duos)

    def test_proxied_https_uses_secure_cookie(self):
        viewer, _ = self.client()
        _, headers = self.call(viewer, headers={'X-Forwarded-Proto': 'https'})
        self.assertIn('; Secure', headers['Set-Cookie'])


if __name__ == '__main__':
    unittest.main()
