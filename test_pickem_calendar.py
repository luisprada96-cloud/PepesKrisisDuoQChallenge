"""Madrid calendar, server deadlines, private team review and admin-only ballot access."""
import copy
import json
import unittest
import urllib.request
from unittest.mock import patch

import pickem_service as pickem
import server
import test_pickem as old
import test_shell_penalties as fixtures

FRIDAY = pickem.weeks.timestamp('2026-10-16T18:00:00+02:00')
FIRST = '2026-10-16'


def database():
    db = old.database()
    db['config']['startDate'] = '2026-10-15T18:00:00+02:00'
    db['config']['endDate'] = '2026-11-15T23:59:00+01:00'
    pickem.reset_calendar(db)
    pickem.ensure_week(db, FRIDAY)
    return db


class PickemCalendarTests(unittest.TestCase):
    def setUp(self):
        self.db = database()

    def test_opening_period_includes_dst_and_two_sundays_without_resetting_attempts(self):
        bounds = pickem.period(self.db, FIRST)
        self.assertEqual(bounds['startsAt'], pickem.weeks.timestamp('2026-10-16T00:00:00+02:00'))
        self.assertEqual(bounds['endsAt'], pickem.weeks.timestamp('2026-10-26T00:00:00+01:00'))
        self.assertEqual(bounds['endsAt'] - bounds['startsAt'], 10*86400 + 3600)
        self.assertEqual(bounds['closesAt'], pickem.weeks.timestamp('2026-10-17T00:00:00+02:00'))
        pickem.submit(self.db, 'a', 'browser', 'unique_champions', '0-19', now=FRIDAY)
        for date in ('2026-10-18T23:59', '2026-10-19T00:00', '2026-10-25T23:59:59'):
            key, _ = pickem.ensure_week(self.db, pickem.weeks.timestamp(date))
            self.assertEqual(key, FIRST)
            self.assertEqual(len(self.db['pickem']['weeks'][key]['ballots']), 1)

    def test_friday_deadline_includes_last_minute_and_blocks_forged_late_posts(self):
        deadline = pickem.period(self.db, FIRST)['closesAt']
        pickem.submit(self.db, 'a', 'browser', 'unique_champions', '0-19', now=deadline-.001)
        before = copy.deepcopy(self.db)
        for at in (deadline, deadline+86400, pickem.weeks.timestamp('2026-10-25T23:59')):
            with self.assertRaises(FileExistsError):
                pickem.submit(self.db, 'a', 'browser2', 'unique_champions', '20-29', now=at)
        self.assertEqual(self.db, before)

    def test_next_period_opens_monday_and_closes_tuesday_midnight_in_madrid(self):
        monday = pickem.weeks.timestamp('2026-10-26T00:00:00+01:00')
        key, _ = pickem.ensure_week(self.db, monday)
        self.assertEqual(key, '2026-10-26')
        bounds = pickem.period(self.db, key)
        self.assertEqual(bounds['endsAt'], pickem.weeks.timestamp('2026-11-02T00:00:00+01:00'))
        self.assertEqual(bounds['closesAt'], pickem.weeks.timestamp('2026-10-27T00:00:00+01:00'))
        pickem.submit(self.db, 'a', 'browser', 'unique_champions', '0-19', now=bounds['closesAt']-.001)
        with self.assertRaises(FileExistsError):
            pickem.submit(self.db, 'a', 'browser2', 'unique_champions', '0-19', now=bounds['closesAt'])
        categories = self.db['pickem']['weeks'][key]['categories']
        self.assertFalse(any(c['id'] in pickem.OPENING_CATEGORIES for c in categories))
        self.assertTrue(any(c['id'] in pickem.OPENING_CATEGORIES for c in self.db['pickem']['weeks'][FIRST]['categories']))

    def test_votes_close_friday_but_games_keep_counting_until_the_25th(self):
        end = pickem.period(self.db, FIRST)['endsAt']
        self.db['duos'][0]['history'] = [
            old.game('before', first='Garen', at=pickem.weeks.timestamp('2026-10-15T23:59')),
            old.game('saturday', at=FRIDAY+86400),
            old.game('last-minute', first='Jinx', second='Thresh', at=end-.001),
            old.game('after', first='Vi', at=end)]
        board = self.db['pickem']['weeks'][FIRST]
        self.assertEqual(pickem.champion_count(self.db, board)['value'], 4)
        self.assertEqual(pickem.champion_count(self.db, board)['games'], 2)
        self.db['pickem']['lastCompleteSync'] = {'startedAt': FRIDAY+86400, 'roster':pickem.roster_key(self.db)}
        pickem.maintain(self.db, FRIDAY+86400)
        self.assertEqual(board['results'], {})
        self.db['pickem']['lastCompleteSync']['startedAt'] = end + pickem.SETTLEMENT_GRACE
        pickem.maintain(self.db, end + pickem.SETTLEMENT_GRACE)
        self.assertEqual(board['results']['unique_champions']['value'], 4)

    def test_team_sees_both_own_ballots_admin_sees_all_and_guests_see_no_hashes(self):
        for team, browser in (('a', 'private-one'), ('a', 'private-two'), ('b', 'private-three')):
            pickem.submit(self.db, team, browser, 'unique_champions', '0-19', author=browser, now=FRIDAY)
        for at in (FRIDAY, FRIDAY+86400):
            with self.subTest(at=at):
                team = pickem.public_board(self.db, 'a', 'another-browser', now=at)
                self.assertEqual(len(team['teamBallots']), 2)
                self.assertTrue(all(b['teamId']=='a' for b in team['teamBallots']))
                self.assertIsNone(team['myBallot'])
                self.assertEqual(team['predictions'], [])
                guest = pickem.public_board(self.db, visitor='private-one', now=at)
                self.assertEqual(guest['teamBallots'], [])
                self.assertIsNone(guest['myBallot'])
                admin = pickem.admin_board(self.db, now=at)
                self.assertEqual(len(admin['predictions']), 3)
                for response in (team, guest, admin):
                    self.assertNotIn('"visitor"', json.dumps(response))
                    self.assertNotIn('"puuid"', json.dumps(response))
        public = pickem.public_board(self.db, now=pickem.period(self.db, FIRST)['endsAt'])
        self.assertEqual(len(public['predictions']), 3)

    def test_reset_preserves_games_teams_inventory_and_other_features(self):
        db = old.database()
        db.update(pickem={'weeks':{'old':{'ballots':[{'id':'old'}]}}}, clips={'keep':True}, tierlists={'keep':True})
        db['events'] = [{'type':'PICKEM_REWARD'}, {'type':'SHELL_LAUNCHED'}]
        db['duos'][0]['pickemShellsEarnedTotal'] = 0
        before = copy.deepcopy(db)
        pickem.reset_calendar(db)
        self.assertEqual(db['pickem'], {'weeks':{}})
        self.assertEqual(db['events'], [{'type':'SHELL_LAUNCHED'}])
        before['duos'][0].pop('pickemShellsEarnedTotal')
        self.assertEqual(db['duos'], before['duos'])
        self.assertEqual(db['clips'], before['clips'])
        self.assertEqual(db['tierlists'], before['tierlists'])


class PickemAdminEndpointTests(unittest.TestCase):
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def setUp(self):
        backend = patch.object(server, 'remote_backend', None)
        backend.start()
        self.addCleanup(backend.stop)
        fixtures.ShellEndpointTests.setUp(self)
        clock = patch.object(pickem.time, 'time', return_value=FRIDAY)
        clock.start()
        self.addCleanup(clock.stop)
        db = database()
        db['config']['adminPinHash'] = server.hash_secret('9999')
        pickem.submit(db, 'a', 'hash-browser-one', 'unique_champions', '0-19', now=FRIDAY)
        pickem.submit(db, 'b', 'hash-browser-two', 'unique_champions', '20-29', now=FRIDAY)
        server.save_db(db)

    def test_admin_ballots_require_pin_and_unknown_period_does_not_leak(self):
        before = server.load_db()
        for payload in ({}, {'authPin':'wrong'}, {'authPin':'wrong', 'week':FIRST}):
            self.post('/api/admin/pickem', payload, expected=401)
        self.assertEqual(server.load_db(), before)
        data = self.post('/api/admin/pickem', {'authPin':'9999'})
        self.assertEqual(data['week'], FIRST)
        self.assertEqual(len(data['predictions']), 2)
        self.assertNotIn('hash-browser', json.dumps(data))
        self.assertNotIn('adminPin', json.dumps(data))
        self.post('/api/admin/pickem', {'authPin':'9999','week':'bogus'}, expected=404)
        token = server.create_player_session('a')
        request = urllib.request.Request(self.base+'/api/pickem', headers={'Authorization':'Bearer '+token})
        with urllib.request.urlopen(request, timeout=5) as response:
            team = json.load(response)
        self.assertEqual(len(team['teamBallots']), 1)
        self.assertEqual(team['predictions'], [])


if __name__ == '__main__':
    unittest.main()
