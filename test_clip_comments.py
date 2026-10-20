"""Guest clip discussions: bounds, private identifiers, retries and archives."""
import copy
import json
import unittest
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import clips_service as clips
import server
import test_clips
from storage import StorageError

NOW = clips.weekly_summary.timestamp('2026-10-20T12:00:00+02:00')


def database():
    db={'config':{'startDate':'2026-10-15T18:00:00+02:00'},'duos':[{'id':'a','teamName':'Equipo A','blueShells':0}]}
    board,_=clips.board_for(db,now=NOW)
    post=clips.publish(board,'Una jugada','https://clips.twitch.tv/GuestCommentClip',now=NOW,team=db['duos'][0])
    return db,board['week'],post['id']


class ClipCommentRulesTests(unittest.TestCase):
    def setUp(self):
        self.db,self.week,self.id=database()

    def add(self, name='', text='Buena jugada', request_id='comment-request-0001', visitor='guest', now=NOW):
        return clips.add_comment(self.db,self.week,self.id,visitor,name,text,request_id,now)

    def test_guest_name_optional_and_exact_bounds_and_unicode(self):
        comment,changed=self.add(name='N'*15,text='C'*200)
        self.assertTrue(changed)
        self.assertEqual((len(comment['name']),len(comment['text'])),(15,200))
        anonymous,_=self.add(name='   ',text='  ¡Qué jugada!\n🎉  ',request_id='comment-request-0002',now=NOW+15)
        self.assertEqual(anonymous['name'],'')
        self.assertEqual(anonymous['text'],'¡Qué jugada!\n🎉')

    def test_invalid_texts_names_types_and_requests_never_mutate(self):
        before=copy.deepcopy(self.db)
        for edits in ({'name':'x'*16},{'name':None},{'name':{}},{'text':'x'*201},{'text':''},{'text':' \n '},
                      {'text':None},{'text':[]},{'name':'a\nb'},{'text':'a\x00b'},{'text':'\ud800'},
                      {'request_id':'short'},{'visitor':''}):
            with self.subTest(edits=repr(edits)),self.assertRaises(ValueError):self.add(**edits)
        self.assertEqual(self.db,before)

    def test_retry_is_idempotent_and_cannot_change_a_saved_request(self):
        first,_=self.add()
        again,changed=self.add(now=NOW+1)
        self.assertEqual(first,again)
        self.assertFalse(changed)
        self.assertEqual(len(self.db['clipCommentLimits']['guest']),1)
        with self.assertRaises(ValueError):self.add(text='Otro texto')
        self.assertEqual(clips.comment_page(self.db,self.week,self.id)['total'],1)

    def test_cooldown_and_hourly_limit_are_persistent_and_shared_across_clips(self):
        self.add()
        with self.assertRaises(clips.CommentRateLimit):self.add(request_id='comment-request-0002',now=NOW+14)
        self.db=json.loads(json.dumps(self.db))
        for index in range(1,20):self.add(request_id=f'comment-request-{index:04d}-next',now=NOW+index*15)
        with self.assertRaises(clips.CommentRateLimit):self.add(request_id='comment-request-over-hour',now=NOW+3500)
        self.add(request_id='comment-request-next-hour',now=NOW+3600)
        other=clips.publish(self.db['clips'],'Otro','https://clips.twitch.tv/AnotherClip',now=NOW,team=self.db['duos'][0])
        with self.assertRaises(clips.CommentRateLimit):
            clips.add_comment(self.db,self.week,other['id'],'guest','','Otro comentario','comment-other-clip-0001',NOW+3601)

    def test_paginated_public_comments_never_expose_private_browser_identifiers(self):
        for index in range(25):self.add(text=str(index),visitor=f'guest-{index}',now=NOW+index)
        first=clips.comment_page(self.db,self.week,self.id)
        second=clips.comment_page(self.db,self.week,self.id,10)
        self.assertEqual((first['total'],len(first['comments']),first['hasMore']),(25,10,True))
        self.assertEqual(first['comments'][0]['text'],'24')
        self.assertEqual(second['comments'][0]['text'],'14')
        self.assertFalse(clips.comment_page(self.db,self.week,self.id,20)['hasMore'])
        for comment in first['comments']:self.assertEqual(set(comment),{'id','name','text','createdAt'})
        public=clips.public_board(self.db['clips'])['clips'][0]
        self.assertEqual(public['commentCount'],25)
        self.assertNotIn('comments',public)

    def test_fiftieth_comment_is_allowed_but_next_is_blocked_without_exposing_the_cap(self):
        for index in range(50):self.add(text=str(index),visitor=f'guest-{index}',now=NOW+index)
        self.assertEqual(clips.comment_page(self.db,self.week,self.id)['total'],50)
        before=copy.deepcopy(self.db)
        with self.assertRaises(OverflowError) as failure:self.add(visitor='guest-51',now=NOW+100)
        self.assertNotIn('50',str(failure.exception))
        self.assertEqual(self.db,before)
        _,changed=self.add(text='49',visitor='guest-49',now=NOW+100)
        self.assertFalse(changed,'retry of the accepted fiftieth comment remains idempotent')
        self.assertEqual(clips.comment_page(self.db,self.week,self.id)['total'],50)

    def test_archives_keep_discussions_without_changing_votes_or_prizes(self):
        self.add()
        clips.board_for(self.db,now=NOW+14*86400)
        self.assertEqual(clips.comment_page(self.db,self.week,self.id)['total'],1)
        before=copy.deepcopy({k:self.db.get(k) for k in ('duos','events','clipWeeklyRewards')})
        self.add(visitor='another-guest',now=NOW+14*86400)
        self.assertEqual(clips.comment_page(self.db,self.week,self.id)['total'],2)
        self.assertEqual(before,{k:self.db.get(k) for k in before})

    def test_unknown_clip_wrong_week_and_preview_examples_reject_comments(self):
        with self.assertRaises(LookupError):clips.comment_page(self.db,'2020-01-06',self.id)
        with self.assertRaises(LookupError):clips.comment_page(self.db,self.week,'missing')
        self.db['clips']['posts'][0]['example']=True
        with self.assertRaises(LookupError):self.add()


class ClipCommentEndpointTests(unittest.TestCase):
    setUp=test_clips.SharedLikesTests.setUp
    tearDown=test_clips.SharedLikesTests.tearDown
    client=test_clips.SharedLikesTests.client
    call=test_clips.SharedLikesTests.call
    setup_post=test_clips.SharedLikesTests.setup_post

    def payload(self, client, clip_id, **extra):
        board=self.call(client)[0]
        return {'week':board['week'],'clipId':clip_id,'name':'','text':'Sin iniciar sesión','requestId':'endpoint-request-0001',**extra}

    def test_anonymous_post_shared_reload_limits_and_private_data(self):
        owner,_,clip_id=self.setup_post()
        body=self.payload(owner,clip_id)
        result,_=self.call(owner,'/api/clips/comments',body)
        self.assertEqual(result['total'],1)
        self.assertEqual(result['comment']['name'],'')
        other,_=self.client()
        shared,_=self.call(other,f"/api/clips/comments?week={body['week']}&clipId={clip_id}")
        self.assertEqual(shared['comments'],result['comments'])
        self.assertEqual(self.call(other)[0]['clips'][0]['commentCount'],1)
        self.assertNotIn('visitor',shared['comments'][0])
        self.assertEqual(self.call(owner,'/api/clips/comments',body)[0]['total'],1)
        self.call(owner,'/api/clips/comments',{**body,'requestId':'endpoint-request-0002'},status=429)
        self.call(owner,'/api/clips/comments',{**body,'name':'x'*16},status=400)
        self.call(owner,'/api/clips/comments',{**body,'text':'x'*201},status=400)

    def test_cross_origin_missing_cookie_invalid_clip_and_failed_save(self):
        owner,_,clip_id=self.setup_post()
        body=self.payload(owner,clip_id)
        self.call(owner,'/api/clips/comments',body,status=403,headers={'Origin':'https://evil.test'})
        self.call(urllib.request.build_opener(),'/api/clips/comments',body,status=401)
        self.call(owner,'/api/clips/comments',{**body,'clipId':'missing'},status=404)
        with patch.object(server,'save_db',side_effect=StorageError('offline')):
            self.call(owner,'/api/clips/comments',body,status=503)
        self.assertEqual(self.call(owner)[0]['clips'][0]['commentCount'],0)
        self.assertEqual(self.call(owner,'/api/clips/comments',body)[0]['total'],1)

    def test_concurrent_retries_only_store_one_comment(self):
        owner,jar,clip_id=self.setup_post()
        body=self.payload(owner,clip_id)
        headers={'Cookie':'; '.join(f'{c.name}={c.value}' for c in jar)}
        def submit(_):return self.call(urllib.request.build_opener(),'/api/clips/comments',body,headers=headers)[0]['total']
        with ThreadPoolExecutor(max_workers=4) as pool:self.assertEqual(list(pool.map(submit,range(8))),[1]*8)
        self.assertEqual(len(server.load_db()['clips']['posts'][0]['comments']),1)


if __name__ == '__main__':unittest.main()
