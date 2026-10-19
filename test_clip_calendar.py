"""Opening round, permanent archives and the audited premature reward repair."""
import copy
import json
import unittest
from datetime import datetime
from unittest.mock import patch

import clips_service as clips
import repair_clip_calendar as repair
import server
import test_clips as endpoints
import weekly_summary


def at(value): return datetime.fromisoformat(value).timestamp()
NOW = at('2026-10-19T12:00:00+02:00')
CLOSE = at('2026-10-25T23:59:00+01:00')
MONDAY = at('2026-10-26T00:00:00+01:00')


def database():
    return {'config':{'startDate':'2026-10-15T18:00:00+02:00'},
            'duos':[{'id':'a','teamName':'A','blueShells':3,'clipShellsEarnedTotal':3,'keep':{'inventory':True}}],
            'clips':{'week':'2026-10-19','posts':[]}, 'pickem':{'preserved':True}}


def opening(db):
    board,_=clips.board_for(db,now=NOW)
    post=clips.publish(board,'Una jugada','https://clips.twitch.tv/Opening',now=NOW,team=db['duos'][0])
    clips.set_like(board,post['id'],'a','private-voter',True,now=NOW)
    return board,post


class CalendarTests(unittest.TestCase):
    def test_opening_continues_past_the_first_sunday_and_closes_once_at_correct_dst(self):
        db=database();board,post=opening(db)
        self.assertEqual(board['week'],'2026-10-15')
        self.assertEqual(board['startsAt'],at('2026-10-15T18:00:00+02:00'))
        self.assertEqual(clips.board_closes_at(board),CLOSE)
        self.assertFalse(clips.settle_weekly_reward(db,CLOSE-.01))
        self.assertTrue(clips.settle_weekly_reward(db,CLOSE))
        self.assertEqual(db['duos'][0]['blueShells'],6)
        self.assertFalse(clips.settle_weekly_reward(db,CLOSE+1))
        archived=copy.deepcopy(board)
        with self.assertRaises(FileExistsError): clips.set_like(board,post['id'],'a','private-voter',False,now=CLOSE)
        current,_=clips.board_for(db,now=MONDAY)
        self.assertEqual(current['week'],'2026-10-26')
        self.assertEqual(clips.board_closes_at(current),at('2026-11-01T23:59:00+01:00'))
        saved=db['clipArchives']['2026-10-15']
        self.assertEqual(saved['posts'],archived['posts'])
        self.assertTrue(saved['archived'])
        for mutation in (lambda:clips.publish(saved,'X','https://clips.twitch.tv/Archive',now=MONDAY,team=db['duos'][0]),
                         lambda:clips.set_like(saved,post['id'],'a','private-voter',False,now=NOW)):
            with self.assertRaises(FileExistsError): mutation()
        public,_=clips.public_payload(db,'a',visitor='private-voter',week='2026-10-15',now=MONDAY)
        self.assertTrue(public['archived']);self.assertTrue(public['weeklyReward']['closed'])
        self.assertEqual(public['clips'][0]['votes'],1)
        self.assertNotIn('private-voter',json.dumps(public))
        self.assertEqual([p['week'] for p in public['weeks']],['2026-10-26','2026-10-15'])
        with self.assertRaises(LookupError): clips.public_payload(db,week='2099-01-01',now=MONDAY)
        # A stale archived board cannot grant another copy of the same reward.
        db['clips']=copy.deepcopy(saved)
        clips.board_for(db,now=MONDAY+60)
        self.assertEqual(db['duos'][0]['blueShells'],6)

    def test_migration_merges_sources_preserves_votes_and_active_evidence(self):
        db=database()
        old={'id':'old','title':'Old','slug':'Old','createdAt':NOW-86400,'teamId':'a','teamVotes':{'a':['v1']}}
        db['clipArchives']={'2026-10-12':{'week':'2026-10-12','posts':[old]}}
        db['clips']['posts']=[dict(old,title='Current evidence'),dict(old,id='new',slug='New')]
        before=copy.deepcopy(db['duos'])
        board,_=clips.board_for(db,now=NOW)
        self.assertEqual(len(board['posts']),2)
        self.assertEqual(board['posts'][0]['title'],'Current evidence')
        self.assertEqual(board['posts'][0]['teamVotes'],old['teamVotes'])
        self.assertNotIn('2026-10-12',db['clipArchives'])
        self.assertEqual(db['duos'],before)
        snapshot=copy.deepcopy(db)
        clips.board_for(db,now=NOW+5)
        self.assertEqual(db,snapshot)

    def test_recaps_count_their_own_calendar_week_and_skip_the_revoked_prize(self):
        db=database();board,post=opening(db)
        board['posts'][0]['createdAt']=at('2026-10-18T12:00:00+02:00')
        db['clipWeeklyRewards']={'2026-10-12':{'status':'REVOKED','shells':0}}
        self.assertEqual(weekly_summary.clips_for_week(db,'2026-10-12')['posts'],1)
        self.assertIsNone(weekly_summary.clips_for_week(db,'2026-10-12')['winner'])
        self.assertEqual(weekly_summary.clips_for_week(db,'2026-10-19')['posts'],0)
        clips.board_for(db,now=MONDAY)
        self.assertEqual(weekly_summary.clips_for_week(db,'2026-10-12')['posts'],1)
        self.assertEqual(weekly_summary.clips_for_week(db,'2026-10-19')['winner']['teamId'],'a')


class RepairTests(unittest.TestCase):
    def fixture(self):
        db=database()
        post={'id':'winner','slug':'Winner','title':'Winner','createdAt':NOW-86400,'likedBy':['v1','v2']}
        recovered={'week':'2026-10-12','posts':[post]}
        award={'status':'AWARDED','week':'2026-10-12','teamId':'a','shells':3,'clipId':'winner','votes':2}
        db['clipWeeklyRewards']={'2026-10-12':award}
        db['weeklySummaries']={'2026-10-12':{'clips':{'posts':1,'votes':2,'winner':copy.deepcopy(award)}}}
        db['clips']['previousWeeklyAward']=copy.deepcopy(award)
        db['events']=[{'id':'clip-week-2026-10-12','type':'CLIP_WEEKLY_REWARD'},{'id':'unrelated'}]
        return db,recovered

    def test_repair_is_selective_idempotent_and_old_and_new_servers_cannot_reaward(self):
        db,recovered=self.fixture();before=copy.deepcopy(db)
        after,report=repair.prepare_repair(db,recovered,NOW)
        self.assertEqual(db,before)
        self.assertEqual(report['removedShells'],3)
        self.assertEqual(after['duos'][0]['blueShells'],0)
        self.assertEqual(after['duos'][0]['clipShellsEarnedTotal'],0)
        self.assertEqual(after['duos'][0]['keep'],before['duos'][0]['keep'])
        self.assertEqual(after['pickem'],before['pickem'])
        self.assertEqual(after['clips']['posts'],before['clips']['posts'])
        self.assertEqual(after['clipWeeklyRewards']['2026-10-12']['status'],'REVOKED')
        self.assertEqual(after['clipArchives']['2026-10-12']['posts'],recovered['posts'])
        repeated,report=repair.prepare_repair(after,recovered,NOW+5)
        self.assertFalse(report['changed']);self.assertEqual(repeated,after)
        board,_=clips.board_for(after,now=NOW)
        self.assertEqual(len(board['posts']),1)
        self.assertNotIn('weeklyAward',board)
        self.assertEqual(after['duos'][0]['blueShells'],0)

    def test_incomplete_recovery_or_spent_inventory_fails_without_changes(self):
        for bad in ('votes','posts','inventory'):
            db,recovered=self.fixture()
            if bad=='votes': recovered['posts'][0]['likedBy']=[]
            if bad=='posts': recovered['posts']=[]
            if bad=='inventory': db['duos'][0]['blueShells']=2
            before=copy.deepcopy(db)
            with self.assertRaises(ValueError): repair.prepare_repair(db,recovered,NOW)
            self.assertEqual(db,before)


class ArchiveEndpointTests(unittest.TestCase):
    setUp=endpoints.SharedLikesTests.setUp
    tearDown=endpoints.SharedLikesTests.tearDown
    client=endpoints.SharedLikesTests.client
    call=endpoints.SharedLikesTests.call
    login=endpoints.SharedLikesTests.login

    def test_archived_get_and_forged_writes_preserve_votes_and_round(self):
        with patch.object(clips.time,'time',return_value=NOW):
            client,_=self.client();auth=self.login(client)
            db=server.load_db();db['config']['startDate']='2026-10-15T18:00:00+02:00'
            db.pop('clipsCalendarVersion',None);board,post=opening(db);server.save_db(db)
        with patch.object(clips.time,'time',return_value=MONDAY):
            auth=self.login(client)
            result,_=self.call(client,'/api/clips?week=2026-10-15',headers=auth)
            self.assertEqual(result['clips'][0]['id'],post['id']);self.assertTrue(result['archived'])
            before=server.load_db()
            self.call(client,'/api/clips/like',{'week':'2026-10-15','clipId':post['id'],'liked':False},status=409,headers=auth)
            self.call(client,'/api/clips',{'week':'2026-10-15','title':'No','url':'https://clips.twitch.tv/No','teamId':'a'},status=409)
            self.call(client,'/api/clips?week=2099-01-01',status=404)
            self.assertEqual(server.load_db(),before)
            fresh,_=self.call(client)
            self.assertEqual(fresh['week'],'2026-10-26');self.assertEqual(fresh['clips'],[])


if __name__=='__main__': unittest.main()
