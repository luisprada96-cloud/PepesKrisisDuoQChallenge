"""Final porra: permanent posts, authenticated quotas, durable official comparisons."""
import copy
import json
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import final_predictions as predictions
import server
import test_shell_penalties as fixtures
import test_tierlists as tierlist_tests
from storage import StorageError
from trophies import build_trophies


def database():
    return {'config': {'startDate':'2026-10-15T18:00','endDate':'2026-11-15T23:59'},
            'duos':[{'id':str(i),'teamName':item['name'],'tier':'Gold','division':'IV','lp':i,
                     'blueShells':3} for i,item in enumerate(predictions.ITEMS)], 'events':[]}


class FinalPredictionTests(unittest.TestCase):
    def setUp(self):
        self.db = database()
        predictions.ensure_board(self.db)
        self.board = self.db['finalPredictions']
        self.order = [i['id'] for i in self.board['items']]

    def publish(self, visitor='one', team='0', **kwargs):
        return predictions.publish(self.db,team,visitor,kwargs.pop('author',''),kwargs.pop('order',self.order),**kwargs)

    def finalize(self):
        trophies = build_trophies(self.db['duos'],self.db['config']['endDate'])
        trophies['status']='awarded'
        self.db['awardedTrophies']=trophies
        return predictions.maintain(self.db,now=predictions.timestamp(trophies['endDate'])+10)

    def test_roster_uses_real_team_ids_and_existing_images(self):
        self.assertEqual(len(self.board['items']),9)
        self.assertEqual({i['id'] for i in self.board['items']},{d['id'] for d in self.db['duos']})
        self.assertTrue(all(i['image'].startswith('/assets/tierlist/') for i in self.board['items']))

    def test_no_time_limit_and_explicit_publication_timestamp(self):
        for now in (1,1900000000):
            with self.subTest(now=now):
                self.setUp()
                post,_=self.publish(now=now)
                self.assertEqual(post['createdAt'],now)
                self.assertEqual(post['author'],'')

    def test_order_is_exactly_one_of_each_team(self):
        for order in (None,{},[],self.order[:-1],self.order+self.order[:1],['unknown']+self.order[1:],
                      [1]+self.order[1:],self.order[:1]*9):
            with self.subTest(order=order),self.assertRaises(ValueError): self.publish(order=order)
        self.assertEqual(self.board['posts'],[])

    def test_author_validation_and_optional_trimmed_author(self):
        for author in ([],{},True,'x'*61,'bad\nname'):
            with self.subTest(author=author),self.assertRaises(ValueError): self.publish(author=author)
        post,_=self.publish(author='  Participante  ')
        self.assertEqual(post['author'],'Participante')

    def test_team_auth_cookie_and_two_separate_browser_limits(self):
        with self.assertRaises(PermissionError): self.publish(team='unknown')
        with self.assertRaises(ValueError): self.publish(visitor='')
        self.publish()
        with self.assertRaises(FileExistsError): self.publish(order=list(reversed(self.order)))
        with self.assertRaises(FileExistsError): self.publish(team='1')
        self.publish(visitor='two')
        with self.assertRaises(FileExistsError): self.publish(visitor='three')
        self.assertEqual(len(self.board['posts']),2)

    def test_retry_is_idempotent_and_cannot_edit_published_author_or_order(self):
        first,changed=self.publish(author='Persona')
        self.assertTrue(changed)
        retried,changed=self.publish(author='Persona')
        self.assertFalse(changed)
        self.assertEqual(first['id'],retried['id'])
        with self.assertRaises(FileExistsError): self.publish(author='Otra')

    def test_roster_and_author_team_snapshots_survive_edits_and_deletion(self):
        before=copy.deepcopy(self.board['items'])
        post,_=self.publish(author='Persona')
        name=post['teamName']
        self.db['duos'][0]['teamName']='Nuevo nombre'
        self.db['duos'].pop()
        predictions.ensure_board(self.db)
        self.assertEqual(self.board['items'],before)
        self.assertEqual(predictions.public_board(self.db)['posts'][0]['teamName'],name)

    def test_unpublished_roster_can_refresh_and_unknown_images_have_safe_fallback(self):
        self.db['duos'][0]['teamName']='Equipo nuevo'
        self.assertTrue(predictions.ensure_board(self.db))
        item=next(i for i in self.board['items'] if i['id']=='0')
        self.assertEqual(item['image'],'')

    def test_private_browser_identity_never_leaves_service(self):
        self.publish(visitor='private-token')
        public=predictions.public_board(self.db,'0','private-token')
        self.assertNotIn('private-token',json.dumps(public))
        self.assertNotIn('visitor',public['posts'][0])

    def test_public_feed_recent_first_and_paginated_without_weekly_prune(self):
        for index in range(9): self.publish(visitor=str(index),team=str(index),now=index)
        page=predictions.public_board(self.db,offset=6,limit=6)
        self.assertEqual(page['total'],9)
        self.assertEqual([p['createdAt'] for p in page['posts']],[2,1,0])
        self.assertEqual(len(self.board['posts']),9)

    def test_no_result_until_official_final_trophies_are_awarded(self):
        self.publish()
        self.db['awardedTrophies']=build_trophies(self.db['duos'],self.db['config']['endDate'])
        self.assertFalse(predictions.maintain(self.db,now=2000000000))
        self.assertIsNone(predictions.public_board(self.db)['posts'][0]['comparison'])
        self.db['awardedTrophies']['status']='awarded'
        self.assertFalse(predictions.maintain(self.db,now=1))

    def test_official_order_and_scores_are_frozen_without_shell_rewards(self):
        official=[d['id'] for d in sorted(self.db['duos'],key=lambda d:d['lp'],reverse=True)]
        self.publish(order=official)
        before=copy.deepcopy(self.db['duos'])
        self.assertTrue(self.finalize())
        result=copy.deepcopy(self.board['result'])
        comparison=predictions.public_board(self.db)['posts'][0]['comparison']
        self.assertEqual(comparison['exact'],9)
        self.assertTrue(all(p['correct'] for p in comparison['positions']))
        self.assertEqual(self.db['duos'],before)
        self.assertEqual(self.db['events'],[])
        self.db['duos'].reverse()
        self.db['awardedTrophies']['cards'][0]['entries'].reverse()
        self.assertFalse(predictions.maintain(self.db,now=2000000000))
        self.assertEqual(self.board['result'],result)

    def test_partial_correct_positions_not_merely_correct_podium_members(self):
        actual=list(self.order)
        swapped=[actual[1],actual[0],*actual[2:]]
        c=predictions.comparison({'order':swapped},{'order':actual})
        self.assertEqual(c['exact'],7)
        self.assertEqual(c['positions'][0]['actual'],2)

    def test_roster_mismatch_is_unavailable_instead_of_an_invented_score(self):
        c=predictions.comparison({'order':self.order},{'order':self.order[:-1]})
        self.assertEqual(c['status'],'UNAVAILABLE')
        self.assertIsNone(c['exact'])

    def test_new_prediction_after_tournament_is_allowed_and_compared_immediately(self):
        self.finalize()
        self.publish(now=2000000000)
        public=predictions.public_board(self.db)
        self.assertEqual(public['posts'][0]['createdAt'],2000000000)
        self.assertEqual(public['posts'][0]['comparison']['status'],'SETTLED')


class FinalPredictionEndpointTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.object(server,'remote_backend',None).start()
        patch.object(server.CustomHandler,'log_message',return_value=None).start()
        fixtures.ShellEndpointTests.setUp(self)
        server.load_db()

    tearDown = fixtures.ShellEndpointTests.tearDown
    client = tierlist_tests.TierlistEndpointTests.client
    login = tierlist_tests.TierlistEndpointTests.login

    def call(self,client,data=None,headers=None,status=200,path='/api/final-predictions'):
        return tierlist_tests.TierlistEndpointTests.call(self,client,data,headers,status,path)

    def payload(self):
        return {'order':['a','b'],'author':'Persona','teamId':'b'}

    def test_auth_cookie_origin_validation_and_no_team_spoofing(self):
        client,_=self.client()
        self.call(client,self.payload(),status=401)
        auth=self.login(client)
        self.call(client,self.payload(),{**auth,'Origin':'https://evil.test'},status=403)
        fresh,_=self.client()
        self.call(fresh,self.payload(),auth,status=400)
        self.call(client,{'order':['a','a']},auth,status=400)
        result,_=self.call(client,self.payload(),auth)
        self.assertEqual(result['posts'][0]['teamId'],'a')
        self.assertNotIn('visitor',result['posts'][0])
        self.call(client,self.payload(),auth)
        self.assertEqual(self.call(client)[0]['total'],1)
        server.player_sessions.clear()
        self.call(client,self.payload(),auth,status=401)

    def test_http_only_secure_cookie_and_allowlisted_assets(self):
        client,_=self.client()
        _,headers=self.call(client,headers={'X-Forwarded-Proto':'https'})
        for flag in ('pepes_porra_visitor=','HttpOnly','SameSite=Lax','Secure'): self.assertIn(flag,headers['Set-Cookie'])
        for asset in ('porra.html','porra.js','porra.css'):
            with client.open(self.base+'/'+asset) as response: self.assertEqual(response.status,200)
        self.call(client,path='/final_predictions.py',status=404)

    def test_storage_failure_does_not_spend_browser_or_team_quota(self):
        client,_=self.client()
        auth=self.login(client)
        with patch.object(server,'save_db',side_effect=StorageError('Unavailable')):
            self.call(client,self.payload(),auth,status=503)
        self.assertEqual(self.call(client)[0]['total'],0)
        self.call(client,self.payload(),auth)
        self.assertEqual(self.call(client)[0]['total'],1)

    def test_concurrent_requests_cannot_take_three_team_slots(self):
        first,_=self.client()
        auth=self.login(first)
        self.call(first,self.payload(),auth)
        clients=[self.client()[0] for _ in range(2)]
        for client in clients: self.call(client)
        barrier=threading.Barrier(2)
        def submit(client):
            barrier.wait()
            request=urllib.request.Request(self.base+'/api/final-predictions',data=json.dumps(self.payload()).encode(),headers={'Content-Type':'application/json',**auth})
            try:
                with client.open(request,timeout=5) as response: return response.status
            except urllib.error.HTTPError as error: return error.code
        with ThreadPoolExecutor(max_workers=2) as pool: self.assertEqual(sorted(pool.map(submit,clients)),[200,409])
        self.assertEqual(self.call(first)[0]['total'],2)

    def test_tierlist_and_final_prediction_use_independent_quotas(self):
        client,_=self.client()
        auth=self.login(client)
        self.call(client,self.payload(),auth)
        self.call(client,path='/api/tierlists')
        self.call(client,{'tiers':tierlist_tests.arrangement()},auth,path='/api/tierlists')
        self.assertEqual(len(server.load_db()['tierlists']),1)
        self.assertEqual(len(server.load_db()['finalPredictions']['posts']),1)

    def test_trophy_finalization_also_persists_official_prediction_comparison(self):
        client,_=self.client()
        auth=self.login(client)
        self.call(client,self.payload(),auth)
        db=server.load_db()
        db['config']['endDate']='2020-01-01T00:00:00+00:00'
        server.save_db(db)
        official=server.public_trophies()
        board=self.call(client)[0]
        self.assertEqual(board['result']['source'],'awardedTrophies')
        self.assertEqual(board['result']['order'],[e['id'] for e in official['cards'][0]['entries']])
        self.assertEqual(board['posts'][0]['comparison']['status'],'SETTLED')


if __name__ == '__main__': unittest.main()
