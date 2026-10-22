"""Uploader identity is separate from the team a clip represents."""
import copy
import unittest
from unittest.mock import patch

import clips_service as clips
import server
import test_clips as fixtures
from storage import StorageError


class ClipDeleteTests(unittest.TestCase):
    setUp = fixtures.SharedLikesTests.setUp
    tearDown = fixtures.SharedLikesTests.tearDown
    client = fixtures.SharedLikesTests.client
    call = fixtures.SharedLikesTests.call
    login = fixtures.SharedLikesTests.login
    setup_post = fixtures.SharedLikesTests.setup_post

    def test_guest_owner_can_delete_but_not_a_voter_or_represented_team(self):
        owner, _, clip_id = self.setup_post()
        payload = self.call(owner)[0]
        week = payload['week']
        self.assertTrue(payload['clips'][0]['canDelete'])
        self.assertNotIn('uploaderVisitor', str(payload))
        other, _ = self.client()
        self.call(other)
        auth = self.login(other, 'a')  # Represents A, but A did not upload it.
        self.assertFalse(self.call(other, headers=auth)[0]['clips'][0]['canDelete'])
        body = {'week': week, 'clipId': clip_id}
        self.call(other, '/api/clips/delete', {**body, 'admin': True, 'uploaderTeamId': 'a'}, status=403, headers=auth)
        result, _ = self.call(owner, '/api/clips/delete', body)
        self.assertEqual(result['clips'], [])
        self.call(owner, '/api/clips/delete', body)  # Lost-response retry.
        db = server.load_db()
        self.assertEqual(len(db['deletedClips']), 1)
        self.assertEqual(db['deletedClips'][clip_id]['post']['title'], 'Una jugada')
        self.call(other, '/api/clips/delete', body, status=403, headers=auth)

    def test_authenticated_uploader_team_can_delete_from_another_device(self):
        owner, _ = self.client()
        auth = self.login(owner, 'a')
        payload, _ = self.call(owner, data={'title': 'Representa B', 'url': 'https://clips.twitch.tv/UploadedByA', 'teamId': 'b'}, headers=auth)
        other, _ = self.client()
        other_auth = self.login(other, 'a')
        self.assertTrue(self.call(other, headers=other_auth)[0]['clips'][0]['canDelete'])
        self.call(other, '/api/clips/delete', {'week': payload['week'], 'clipId': payload['clips'][0]['id']}, headers=other_auth)

    def test_legacy_clips_are_admin_only_and_pin_never_goes_public(self):
        owner, _, clip_id = self.setup_post()
        db = server.load_db()
        db['clips']['posts'][0].pop('uploaderVisitor')
        server.save_db(db)
        payload, _ = self.call(owner)
        body = {'week': payload['week'], 'clipId': clip_id}
        self.assertFalse(payload['clips'][0]['canDelete'])
        self.call(owner, '/api/clips/delete', body, status=403)
        self.call(owner, '/api/clips/moderate', {'authPin': 'wrong'}, status=401)
        admin, _ = self.call(owner, '/api/clips/moderate', {'authPin': '9999'})
        self.assertTrue(admin['clips'][0]['canDelete'])
        self.assertNotIn('9999', str(admin))
        self.call(owner, '/api/clips/delete', {**body, 'authPin': 'wrong'}, status=401)
        self.call(owner, '/api/clips/delete', {**body, 'authPin': '9999'})
        self.assertEqual(server.load_db()['deletedClips'][clip_id]['deletedBy'], 'admin')

    def test_delete_archived_winner_keeps_award_inventory_and_comments_in_recovery(self):
        owner, _, clip_id = self.setup_post()
        db = server.load_db()
        old = copy.deepcopy(db['clips'])
        old.update(week='2026-09-28', archived=True, weeklyAward={'clipId': clip_id, 'status': 'AWARDED', 'shells': 3})
        old['posts'][0].update(comments=[{'id': 'comment', 'text': 'test', 'name': 'A', 'createdAt': 1}], teamVotes={'a': ['hash']})
        db.setdefault('clipArchives', {})[old['week']] = old
        db['clips']['posts'] = []
        db['clipWeeklyRewards'] = {old['week']: copy.deepcopy(old['weeklyAward'])}
        server.save_db(db)
        before = server.load_db()
        self.call(owner, '/api/clips/delete', {'week': old['week'], 'clipId': clip_id})
        after = server.load_db()
        self.assertEqual(after['duos'], before['duos'])
        self.assertEqual(after['clipWeeklyRewards'], before['clipWeeklyRewards'])
        self.assertEqual(after['clipArchives'][old['week']]['weeklyAward'], old['weeklyAward'])
        self.assertEqual(after['deletedClips'][clip_id]['post']['comments'], old['posts'][0]['comments'])
        self.call(owner, f"/api/clips/comments?week={old['week']}&clipId={clip_id}", status=404)

    def test_csrf_cannot_delete_or_enable_moderation(self):
        owner, _, clip_id = self.setup_post()
        week = self.call(owner)[0]['week']
        for headers in ({'Origin': 'https://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}, {'Content-Type': 'text/plain'}):
            self.call(owner, '/api/clips/delete', {'week': week, 'clipId': clip_id}, status=403, headers=headers)
            self.call(owner, '/api/clips/moderate', {'authPin': '9999'}, status=403, headers=headers)
        self.assertEqual(len(self.call(owner)[0]['clips']), 1)

    def test_failed_save_does_not_report_success_or_lose_the_clip(self):
        owner, _, clip_id = self.setup_post()
        week = self.call(owner)[0]['week']
        with patch.object(server, 'save_db', side_effect=StorageError('test failure')):
            self.call(owner, '/api/clips/delete', {'week': week, 'clipId': clip_id}, status=503)
        self.assertEqual(self.call(owner)[0]['clips'][0]['id'], clip_id)

    def test_wrong_week_and_missing_cookie_do_not_remove_anything(self):
        owner, _, clip_id = self.setup_post()
        week = self.call(owner)[0]['week']
        self.call(owner, '/api/clips/delete', {'week': '2000-01-03', 'clipId': clip_id}, status=404)
        no_cookie, _ = self.client()
        self.call(no_cookie, '/api/clips/delete', {'week': week, 'clipId': clip_id}, status=401)
        self.assertEqual(len(self.call(owner)[0]['clips']), 1)


if __name__ == '__main__':
    unittest.main()
