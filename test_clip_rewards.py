"""Weekly rewards survive pruning, restarts, concurrent reads and storage failures."""
import copy
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import clips_service as clips
import server
import test_clips as fixtures
from storage import StorageError


WEEK = '2026-09-28'
CLOSE = clips.week_closes_at(WEEK)


def database():
    return {'duos': [{'id':'a', 'teamName':'A', 'blueShells':5}, {'id':'b', 'teamName':'B', 'blueShells':1}],
            'clips': {'week':WEEK, 'posts':[]}}


def post(db, title='Ganador', slug='Winner', team=0, votes=('v1',), created=None):
    board = db['clips']
    created = CLOSE - 3600 if created is None else created
    item = clips.publish(board, title, f'https://clips.twitch.tv/{slug}', now=created, team=db['duos'][team])
    item['likedBy'] = list(votes)
    return item


class ClipRewardTests(unittest.TestCase):
    def test_team_votes_determine_winner_and_summary_before_pruning(self):
        db = database()
        loser = post(db, title='Uno', slug='One', votes=())
        winner = post(db, title='Dos', slug='Two', team=1, votes=())
        clips.set_like(db['clips'], loser['id'], 'a', 'browser1', True, now=CLOSE-1)
        clips.set_like(db['clips'], winner['id'], 'a', 'browser1', True, now=CLOSE-1)
        clips.set_like(db['clips'], winner['id'], 'a', 'browser2', True, now=CLOSE-1)
        clips.settle_weekly_reward(db, CLOSE)
        self.assertEqual(db['clipWeeklyRewards'][WEEK]['clipId'], winner['id'])
        self.assertEqual(db['clipWeeklyRewards'][WEEK]['votes'], 2)
        stats = clips.weekly_summary.clip_stats(db, db['clips'])
        self.assertEqual(stats['votes'], 3)
        self.assertEqual(stats['winner']['votes'], 2)
        self.assertNotIn('teamVotes', json.dumps(stats))

    def test_award_at_exact_close_once_and_can_exceed_inventory_cap(self):
        db = database()
        winner = post(db, votes=('v1','v2','v2'))
        post(db, slug='Second', team=1)
        self.assertFalse(clips.settle_weekly_reward(db, CLOSE - 0.001))
        self.assertTrue(clips.settle_weekly_reward(db, CLOSE))
        self.assertEqual(db['duos'][0]['blueShells'], 8)
        self.assertEqual(db['duos'][1]['blueShells'], 1)
        award = db['clipWeeklyRewards'][WEEK]
        self.assertEqual(award['clipId'], winner['id'])
        self.assertEqual(award['votes'], 2)
        self.assertEqual(len(db['events']), 1)
        restored = json.loads(json.dumps(db))
        self.assertFalse(clips.settle_weekly_reward(restored, CLOSE + 40))
        self.assertEqual(restored['duos'][0]['blueShells'], 8)
        server.update_duo_shells(restored['duos'][0])
        self.assertEqual(restored['duos'][0]['blueShells'], 8)

    def test_tie_goes_to_first_publication_then_stable_id(self):
        db = database()
        later = post(db, slug='Later', created=CLOSE-100)
        earlier = post(db, slug='Earlier', team=1, created=CLOSE-200)
        clips.settle_weekly_reward(db, CLOSE)
        self.assertEqual(db['clipWeeklyRewards'][WEEK]['clipId'], earlier['id'])
        self.assertEqual(db['duos'][1]['blueShells'], 4)
        db = database()
        p1, p2 = post(db, slug='One'), post(db, slug='Two', team=1)
        p1['id'], p2['id'] = 'b', 'a'
        clips.settle_weekly_reward(db, CLOSE)
        self.assertEqual(db['clipWeeklyRewards'][WEEK]['clipId'], 'a')

    def test_no_votes_and_legacy_unassigned_and_examples_never_win(self):
        for kind in ('empty', 'no-votes', 'unassigned', 'example', 'deleted-team', 'wrong-week'):
            db = database()
            if kind != 'empty':
                item = post(db)
                if kind == 'no-votes': item['likedBy'] = []
                if kind == 'unassigned': item.pop('teamId')
                if kind == 'example': item['example'] = True
                if kind == 'deleted-team': db['duos'] = db['duos'][1:]
                if kind == 'wrong-week': item['createdAt'] = CLOSE - 8*86400
            inventory = [team['blueShells'] for team in db['duos']]
            self.assertTrue(clips.settle_weekly_reward(db, CLOSE))
            self.assertEqual(db['clipWeeklyRewards'][WEEK]['status'], 'NO_WINNER')
            self.assertEqual([team['blueShells'] for team in db['duos']], inventory)
            self.assertFalse(clips.settle_weekly_reward(db, CLOSE+1))

    def test_downtime_awards_before_pruning_and_new_week_is_independent(self):
        db = database()
        winner = post(db)
        old = copy.deepcopy(db['clips'])
        board, changed = clips.board_for(db, now=CLOSE + 3*86400)
        self.assertTrue(changed)
        self.assertEqual(board['posts'], [])
        self.assertEqual(board['previousWeeklyAward']['clipId'], winner['id'])
        self.assertEqual(db['duos'][0]['blueShells'], 8)
        # Restoring an old weekly board must not recreate an already credited reward.
        db['clips'] = old
        clips.board_for(db, now=CLOSE + 3*86400)
        self.assertEqual(db['duos'][0]['blueShells'], 8)
        next_close = clips.week_closes_at(db['clips']['week'])
        post(db, slug='NextWeek', created=next_close-100)
        clips.settle_weekly_reward(db, next_close)
        self.assertEqual(db['duos'][0]['blueShells'], 11)
        self.assertEqual(len(db['clipWeeklyRewards']), 2)

    def test_final_minute_is_read_only_even_if_settlement_was_delayed(self):
        db = database()
        item = post(db)
        with self.assertRaises(FileExistsError):
            clips.publish(db['clips'], 'Late', 'https://clips.twitch.tv/Late', now=CLOSE, team=db['duos'][0])
        with self.assertRaises(FileExistsError):
            clips.set_like(db['clips'], item['id'], 'a', 'v2', True, now=CLOSE)
        self.assertEqual(item['likedBy'], ['v1'])
        db = {'duos':[]}
        board, _ = clips.board_for(db, now=CLOSE + 1)
        self.assertTrue(clips.public_board(board, 'visitor')['weeklyReward']['closed'])

    def test_closing_time_tracks_madrid_dst(self):
        for week, month, sunday, utc_hour in (('2026-03-23',3,29,21), ('2026-10-19',10,25,22)):
            expected = datetime(2026,month,sunday,23,59,tzinfo=clips.MADRID).timestamp()
            self.assertEqual(clips.week_closes_at(week), expected)
            self.assertEqual(datetime.fromtimestamp(expected, clips.MADRID).hour, 23)
            from datetime import timezone
            self.assertEqual(datetime.fromtimestamp(expected, timezone.utc).hour, utc_hour)


class ClipRewardEndpointTests(unittest.TestCase):
    setUp = fixtures.SharedLikesTests.setUp
    tearDown = fixtures.SharedLikesTests.tearDown
    client = fixtures.SharedLikesTests.client
    call = fixtures.SharedLikesTests.call
    def test_post_requires_valid_team_and_ignores_forged_team_name(self):
        client, _ = self.client()
        listing, _ = self.call(client)
        self.assertEqual(listing['teams'], [{'id':'a','name':'Atacante'}, {'id':'b','name':'Receptor'}])
        self.assertNotIn('passwordHash', json.dumps(listing))
        for team_id in (None, 'missing'):
            self.call(client, data={'title':'Clip','url':'https://clips.twitch.tv/TeamClip','teamId':team_id}, status=400)
        result, _ = self.call(client, data={'title':'Clip','url':'https://clips.twitch.tv/TeamClip','teamId':'b','team':'Forged'})
        self.assertEqual(result['clips'][0]['teamId'], 'b')
        self.assertEqual(result['clips'][0]['team'], 'Receptor')

    def seed_due_reward(self):
        db = server.load_db()
        db['duos'][0]['blueShells'] = 5
        db['clips'] = {'week':WEEK, 'posts':[]}
        post(db)
        server.save_db(db)

    def test_concurrent_due_requests_credit_once_and_block_late_votes(self):
        self.seed_due_reward()
        with patch.object(clips.time, 'time', return_value=CLOSE+1):
            def read(_):
                client, _ = self.client()
                return self.call(client)[0]
            with ThreadPoolExecutor(max_workers=4) as pool:
                listings = list(pool.map(read, range(8)))
            db = server.load_db()
            self.assertEqual(db['duos'][0]['blueShells'], 8)
            self.assertEqual(len(db['clipWeeklyRewards']), 1)
            client, _ = self.client()
            listing, _ = self.call(client)
            clip_id = listing['clips'][0]['id']
            self.call(client, '/api/clips/like', {'clipId':clip_id,'liked':True}, status=409, headers=fixtures.SharedLikesTests.login(self, client))
            self.call(client, data={'title':'Late','url':'https://clips.twitch.tv/Late','teamId':'a'}, status=409)
            self.assertTrue(all(result['weeklyReward']['closed'] for result in listings))

    def test_failed_reward_save_can_retry_without_duplicate_credit(self):
        self.seed_due_reward()
        client, _ = self.client()
        with patch.object(clips.time, 'time', return_value=CLOSE+1):
            with patch.object(server, 'save_db', side_effect=StorageError('offline')):
                self.call(client, status=503)
            persisted = json.loads(Path(server.DB_FILE).read_text(encoding='utf-8'))
            self.assertEqual(persisted['duos'][0]['blueShells'], 5)
            self.assertNotIn('clipWeeklyRewards', persisted)
            self.call(client)
            self.call(client)
            self.assertEqual(server.load_db()['duos'][0]['blueShells'], 8)


if __name__ == '__main__':
    unittest.main()
