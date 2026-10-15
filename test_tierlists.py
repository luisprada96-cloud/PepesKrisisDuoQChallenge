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


def player_arrangement():
    ids=[item['id'] for item in tierlists.PLAYER_ITEMS]
    return {tier:ids[i*4:(i+1)*4] for i,tier in enumerate(tierlists.TIERS)}


class ParticipantTierlistServiceTests(unittest.TestCase):
    def test_catalog_contains_eighteen_unique_names_and_exact_png_tiles(self):
        import struct
        self.assertEqual(len(tierlists.PLAYER_ITEMS),18)
        self.assertEqual(len({i['id'] for i in tierlists.ALL_ITEMS}),27)
        self.assertEqual(len({i['name'] for i in tierlists.PLAYER_ITEMS}),18)
        for item in tierlists.PLAYER_ITEMS:
            content=(Path(__file__).parent/item['image'].lstrip('/')).read_bytes()
            self.assertEqual(content[:8],b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('>II',content[16:24]),(400,400))
            self.assertTrue(item['teamName'])

    def test_same_browser_and_team_have_independent_quotas_per_kind(self):
        db={'duos':[{'id':'a','teamName':'Equipo'}]}
        tierlists.publish(db,'a','browser1','',arrangement())
        tierlists.publish(db,'a','browser2','',arrangement())
        self.assertFalse(tierlists.publication_status(db,'a','browser1')['canPublish'])
        self.assertTrue(tierlists.publication_status(db,'a','browser1','players')['canPublish'])
        tierlists.publish(db,'a','browser1','Autor',player_arrangement(),kind='players')
        tierlists.publish(db,'a','browser2','',player_arrangement(),kind='players')
        with self.assertRaises(FileExistsError):
            tierlists.publish(db,'a','browser3','',player_arrangement(),kind='players')
        self.assertEqual(len(db['tierlists']),4)
        for kind in ('teams','players'):
            board=tierlists.public_board(db,kind=kind)
            self.assertEqual(board['total'],2)
            self.assertNotIn('visitor',json.dumps(board))

    def test_legacy_posts_remain_team_posts_and_galleries_paginate_independently(self):
        db={'duos':[{'id':str(i),'teamName':str(i)} for i in range(7)]}
        legacy=tierlists.publish(db,'0','team-browser','Original',arrangement(),now=1)
        legacy.pop('kind')
        original=copy.deepcopy(legacy)
        for i in range(7):
            tierlists.publish(db,str(i),f'player-browser{i}',f'Autor {i}',player_arrangement(),now=i,kind='players')
        self.assertEqual(tierlists.public_board(db)['posts'],[{k:v for k,v in original.items() if k!='visitor'}])
        board=tierlists.public_board(db,offset=6,kind='players')
        self.assertEqual(board['total'],7)
        self.assertEqual(board['posts'][0]['author'],'Autor 0')
        self.assertEqual(db['tierlists'][0],original)

    def test_mixed_missing_duplicate_or_unknown_players_and_invalid_kind_rejected(self):
        for rows in (arrangement(),{**player_arrangement(),'S':[]},
                     {**player_arrangement(),'S':[tierlists.PLAYER_ITEMS[0]['id']]*4},
                     {**player_arrangement(),'S':['unknown']*4}):
            with self.subTest(rows=rows),self.assertRaises(ValueError):
                tierlists.validate_tiers(rows,'players')
        for kind in ('unknown',None,[],{}):
            with self.subTest(kind=kind),self.assertRaises(ValueError):tierlists.catalog(kind)


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
        for item in tierlists.ALL_ITEMS:
            with client.open(self.base+item['image'], timeout=3) as response:
                self.assertEqual(response.headers['Content-Type'], 'image/png')
                self.assertEqual(response.read(8), b'\x89PNG\r\n\x1a\n')
        for path in ('/tierlists_service.py', '/assets/tierlist/../../db.json', '/assets/tierlist/unknown.png'):
            self.call(client, path=path, status=404)


class ParticipantTierlistEndpointTests(unittest.TestCase):
    setUp=TierlistEndpointTests.setUp
    tearDown=TierlistEndpointTests.tearDown
    client=TierlistEndpointTests.client
    call=TierlistEndpointTests.call
    login=TierlistEndpointTests.login

    def test_authenticated_publication_kind_is_validated_and_team_gallery_stays_intact(self):
        client,_=self.client()
        self.call(client,{'kind':'players','tiers':player_arrangement()},status=401)
        auth=self.login(client)
        self.call(client,{'tiers':arrangement(),'author':'Equipos'},auth)
        board,_=self.call(client,headers=auth,path='/api/tierlists?kind=players')
        self.assertEqual(board['total'],0)
        self.assertEqual(len(board['items']),18)
        self.assertTrue(board['publishing']['canPublish'])
        self.call(client,{'kind':'players','tiers':arrangement()},auth,status=400)
        self.call(client,{'kind':'bad','tiers':player_arrangement()},auth,status=400)
        self.call(client,path='/api/tierlists?kind=bad',status=400)
        self.call(client,{'kind':'players','tiers':player_arrangement()},
                  {**auth,'Origin':'https://evil.test'},status=403)
        result,_=self.call(client,{'kind':'players','tiers':player_arrangement(),'author':'Integrantes'},auth)
        self.assertEqual(result['kind'],'players')
        self.assertEqual(result['total'],1)
        self.assertEqual(result['posts'][0]['author'],'Integrantes')
        self.assertFalse(result['publishing']['canPublish'])
        self.assertEqual(self.call(client)[0]['posts'][0]['author'],'Equipos')
        self.call(client,{'kind':'players','tiers':player_arrangement()},auth,status=409)
        self.assertEqual(len(server.load_db()['tierlists']),2)

    def test_failed_player_save_does_not_consume_either_quota(self):
        client,_=self.client();auth=self.login(client)
        with patch.object(server,'save_db',side_effect=StorageError('Storage unavailable')):
            self.call(client,{'kind':'players','tiers':player_arrangement()},auth,status=503)
        for path in ('/api/tierlists','/api/tierlists?kind=players'):
            board,_=self.call(client,headers=auth,path=path)
            self.assertTrue(board['publishing']['canPublish'])
            self.assertEqual(board['total'],0)

    def test_concurrent_player_publications_cannot_spend_third_team_slot(self):
        client,_=self.client();auth=self.login(client)
        self.call(client,{'kind':'players','tiers':player_arrangement()},auth)
        clients=[self.client()[0] for _ in range(2)]
        for client in clients:self.call(client,path='/api/tierlists?kind=players')
        barrier=threading.Barrier(2)
        def submit(client):
            barrier.wait()
            req=urllib.request.Request(self.base+'/api/tierlists',data=json.dumps({'kind':'players','tiers':player_arrangement()}).encode(),headers={'Content-Type':'application/json',**auth})
            try:
                with client.open(req,timeout=5) as response:return response.status
            except urllib.error.HTTPError as error:return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(submit,clients))
        self.assertEqual(sorted(codes),[200,409])
        self.assertEqual(self.call(clients[0])[0]['total'],0)
        self.assertEqual(self.call(clients[0],path='/api/tierlists?kind=players')[0]['total'],2)


if __name__ == '__main__': unittest.main()
