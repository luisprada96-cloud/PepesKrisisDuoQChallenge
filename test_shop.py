"""Purchases debit shared gold and credit real inventory atomically, even on retry."""
import copy
import json
import unittest
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import betting_service
import server
import shop_service as shop
import test_clips as fixtures
from storage import StorageError


def payload(quantity=1, request_id='shop-purchase-request-1234'):
    return {'quantity': quantity, 'requestId': request_id}


class ShopTests(unittest.TestCase):
    def setUp(self):
        self.db = {'config': {}, 'duos': [{'id': 'a', 'teamName': 'A', 'blueShells': 4},
                                         {'id': 'b', 'teamName': 'B', 'blueShells': 0}]}
        betting_service.ensure(self.db, 1792576800)
        self.db['betting']['wallets']['a']['balance'] = 210

    def test_fixed_price_multiple_items_and_retries_survive_serialization(self):
        result = shop.purchase(self.db, 'a', {**payload(2), 'price': 1, 'teamId': 'b'})
        self.assertEqual((result['unitPrice'], result['total']), (70, 140))
        self.assertEqual(self.db['betting']['wallets']['a']['balance'], 70)
        self.assertEqual([d['blueShells'] for d in self.db['duos']], [6, 0])
        self.assertEqual(self.db['duos'][0]['shellsPurchasedTotal'], 2)
        self.assertNotIn('shellsEarnedTotal', self.db['duos'][0])
        restored = json.loads(json.dumps(self.db))
        self.assertEqual(shop.purchase(restored, 'a', payload(2)), result)
        self.assertEqual(restored, self.db)
        self.assertEqual(restored['betting']['ledger'][-1]['amount'], -140)

    def test_invalid_quantity_request_reuse_and_insufficient_gold_do_not_mutate(self):
        for quantity in (True, False, 0, -1, 1.5, '1', None, 1000001):
            before = copy.deepcopy(self.db)
            with self.assertRaises(ValueError): shop.purchase(self.db, 'a', payload(quantity))
            self.assertEqual(before, self.db)
        for body in ({'quantity': 1}, payload(1, 'short'), payload(1, ['invalid'])):
            before = copy.deepcopy(self.db)
            with self.assertRaises(ValueError): shop.purchase(self.db, 'a', body)
            self.assertEqual(before, self.db)
        shop.purchase(self.db, 'a', payload(3))
        before = copy.deepcopy(self.db)
        with self.assertRaises(FileExistsError): shop.purchase(self.db, 'a', payload(2))
        with self.assertRaises(FileExistsError): shop.purchase(self.db, 'a', payload(1, 'another-purchase-request-123'))
        with self.assertRaises(PermissionError): shop.purchase(self.db, 'missing', payload())
        self.assertEqual(before, self.db)

    def test_private_wallet_excludes_other_teams_and_reserved_bets_are_unspendable(self):
        self.db['betting']['wallets']['a']['balance'] = 69
        self.db['betting']['bets'] = [{'teamId': 'a', 'amount': 141, 'status': 'PENDING'},
                                      {'teamId': 'b', 'amount': 1000, 'status': 'PENDING'}]
        with self.assertRaises(FileExistsError): shop.purchase(self.db, 'a', payload())
        self.assertIsNone(shop.public_shop(self.db)['wallet'])
        own = shop.public_shop(self.db, 'a')
        self.assertEqual(own['wallet'], {'teamId': 'a', 'teamName': 'A', 'balance': 69, 'reserved': 141, 'inventory': 4})
        self.assertNotIn('purchases', json.dumps(own))
        self.assertEqual(shop.public_shop(self.db, 'b')['wallet']['balance'], 10)


class ShopEndpointTests(unittest.TestCase):
    setUp = fixtures.SharedLikesTests.setUp
    tearDown = fixtures.SharedLikesTests.tearDown
    client = fixtures.SharedLikesTests.client
    call = fixtures.SharedLikesTests.call
    login = fixtures.SharedLikesTests.login

    def fund(self, amount=140):
        db = server.load_db()
        db['betting']['wallets']['a']['balance'] = amount
        server.save_db(db)

    def test_auth_origin_privacy_and_forged_price_owner(self):
        client, _ = self.client()
        public, headers = self.call(client, '/api/shop')
        self.assertEqual(public, {'product': {'id': 'pepazo', 'name': 'Pepazo', 'unitPrice': 70}, 'wallet': None})
        self.assertIn('Authorization', headers['Vary'])
        self.call(client, '/api/shop', payload(), status=401)
        auth = self.login(client); self.fund()
        self.call(client, '/api/shop', payload(), status=403, headers={**auth, 'Origin': 'https://evil.test'})
        result, _ = self.call(client, '/api/shop', {**payload(), 'teamId': 'b', 'unitPrice': 1}, headers=auth)
        self.assertEqual(result['wallet']['balance'], 70)
        self.assertEqual(result['wallet']['inventory'], 2)
        self.assertEqual(result['purchase']['total'], 70)
        self.assertNotIn('requestId', json.dumps(result))
        self.assertNotIn('password', json.dumps(result))
        anonymous, _ = self.client()
        self.assertIsNone(self.call(anonymous, '/api/shop')[0]['wallet'])
        state, _ = self.call(client, '/api/player/state', {'sessionToken': auth['Authorization'][7:]})
        self.assertEqual(state['duo']['blueShells'], 2)
        launched, _ = self.call(client, '/api/player/launch-shell', {'sessionToken': auth['Authorization'][7:], 'targetId': 'b'})
        self.assertTrue(launched['success'])
        self.assertEqual(server.load_db()['duos'][0]['blueShells'], 1)

    def test_concurrent_same_receipt_and_distinct_requests_never_overdraw(self):
        client, _ = self.client(); auth = self.login(client); self.fund(70)
        def retry(_):
            connection, _ = self.client()
            return self.call(connection, '/api/shop', payload(), headers=auth)[0]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(retry, range(4)))
        self.assertEqual(len({r['purchase']['id'] for r in results}), 1)
        self.assertTrue(all(r['wallet']['balance'] == 0 and r['wallet']['inventory'] == 2 for r in results))
        self.call(client, '/api/shop', payload(1, 'different-purchase-request-123'), status=409, headers=auth)
        self.fund(70)
        def distinct(i):
            connection, _ = self.client()
            request = urllib.request.Request(self.base + '/api/shop', json.dumps(payload(1, f'unique-purchase-request-{i}')).encode(), headers={'Content-Type': 'application/json', **auth})
            try:
                with connection.open(request, timeout=5) as response: return response.status
            except urllib.error.HTTPError as error:
                error.close(); return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(distinct, range(2))), [200, 409])
        db = server.load_db()
        self.assertEqual((db['betting']['wallets']['a']['balance'], db['duos'][0]['blueShells']), (0, 3))

    def test_failed_save_and_lost_response_retry_without_another_charge(self):
        client, _ = self.client(); auth = self.login(client); self.fund(70)
        before = server.load_db()
        with patch.object(server, 'save_db', side_effect=StorageError('offline')):
            self.call(client, '/api/shop', payload(), status=503, headers=auth)
        self.assertEqual(server.load_db(), before)
        save = server.save_db
        def save_then_fail(db): save(db); raise StorageError('lost response')
        with patch.object(server, 'save_db', side_effect=save_then_fail):
            self.call(client, '/api/shop', payload(), status=503, headers=auth)
        result, _ = self.call(client, '/api/shop', payload(), headers=auth)
        self.assertEqual((result['wallet']['balance'], result['wallet']['inventory']), (0, 2))
        self.assertEqual(len(server.load_db()['shop']['purchases']), 1)

    def test_shop_and_bets_use_the_same_available_gold(self):
        client, _ = self.client(); auth = self.login(client); self.fund(140)
        self.call(client, '/api/bets', {'action': 'create', 'metric': 'result', 'targetId': 'b', 'amount': 70, 'requestId': 'reserved-betting-request-123'}, headers=auth)
        bought, _ = self.call(client, '/api/shop', payload(), headers=auth)
        self.assertEqual((bought['wallet']['balance'], bought['wallet']['reserved']), (0, 70))
        self.call(client, '/api/shop', payload(1, 'another-purchase-request-123'), status=409, headers=auth)
        bets, _ = self.call(client, '/api/bets', headers=auth)
        self.assertEqual((bets['wallet']['balance'], bets['wallet']['reserved']), (0, 70))

    def test_public_files_are_explicitly_allowed_without_exposing_service_or_traversal(self):
        client, _ = self.client()
        for path in ('tienda.html', 'tienda.css', 'tienda.js', 'assets/shop/pepe-shop.webp', 'assets/shop/pepazo.webp'):
            with client.open(self.base + '/' + path, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertGreater(len(response.read()), 100)
        for path in ('shop_service.py', 'assets/shop/../../db.json', 'assets/shop/unknown.webp'):
            self.call(client, '/' + path, status=404)


if __name__ == '__main__': unittest.main()
