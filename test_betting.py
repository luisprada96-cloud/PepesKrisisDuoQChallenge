"""Gold conservation, receipt timers, identity, daily grants and atomic API operations."""
import copy
import json
import unittest
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import betting_service as bets
import riot_match_policy
import server
import test_clips as fixtures
from storage import StorageError


def at(value): return datetime.fromisoformat(value).timestamp()
NOW=at('2026-10-20T12:00:00+02:00')
START=riot_match_policy.MIN_START_TIMESTAMP*1000


def database():
    return {'config':{},'duos':[{'id':key,'teamName':key.upper(),'blueShells':4,
        'player1':{'name':key+'One','tag':'EUW','displayName':'Luis','puuid':key+'main'},
        'player2':{'name':key+'Two','tag':'EUW','displayName':'Pepe','puuid':key+'two'},'history':[]}
        for key in ('a','b','c')]}


def game(mid='M1',result='WIN',**extra):
    return {'matchId':mid,'result':result,'gameStartTimestamp':START+1000000,
            'gameEndTimestamp':START+2200000,'durationSeconds':1200,'queueId':420,**extra}


def create(db,owner='a',amount=5,now=NOW,**extra):
    body={'action':'create','requestId':f'create-{len(db["betting"]["bets"]):016d}','metric':'result',
          'targetId':'c','amount':amount,**extra}
    return bets.participate(db,owner,body,now)


def join(db,owner='b',amount=5,side='LOSS',now=NOW):
    return bets.participate(db,owner,{'action':'join','requestId':f'join-{len(db["betting"]["bets"]):016d}',
        'marketId':db['betting']['markets'][-1]['id'],'side':side,'amount':amount},now)


class BettingTests(unittest.TestCase):
    def setUp(self):
        self.db=database();bets.maintain(self.db,NOW)
    def receive(self,match,now):
        self.db['duos'][2]['history'].append(match);return bets.maintain(self.db,now)
    def balances(self): return [w['balance'] for w in self.db['betting']['wallets'].values()]

    def test_initial_gold_is_once_per_team_and_separate_from_pepazos(self):
        self.assertEqual(self.balances(),[10,10,10])
        self.assertFalse(bets.maintain(self.db,NOW+1))
        restored=json.loads(json.dumps(self.db));bets.maintain(restored,NOW+1)
        self.assertEqual(restored,self.db)
        self.db['duos'].append({'id':'new','teamName':'New','history':[]})
        bets.maintain(self.db,NOW+1)
        self.assertEqual(self.db['betting']['wallets']['new']['balance'],10)
        self.assertEqual(self.db['duos'][0]['blueShells'],4)

    def test_daily_at_2359_is_idempotent_and_catches_missed_days(self):
        before=at('2026-10-20T23:58:59+02:00');close=at('2026-10-20T23:59:00+02:00')
        self.assertFalse(bets.maintain(self.db,before))
        self.assertTrue(bets.maintain(self.db,close));self.assertEqual(self.balances(),[20]*3)
        self.assertFalse(bets.maintain(self.db,close+1))
        bets.maintain(self.db,at('2026-10-23T00:00:00+02:00'))
        self.assertEqual(self.balances(),[40]*3)
        self.assertFalse(bets.maintain(self.db,at('2026-10-23T00:00:01+02:00')))

    def test_daily_across_dst_uses_local_dates_and_no_days_before_activation(self):
        db=database();bets.maintain(db,at('2026-10-24T23:58:00+02:00'))
        bets.maintain(db,at('2026-10-24T23:59:00+02:00'))
        bets.maintain(db,at('2026-10-25T23:58:59+01:00'))
        self.assertEqual(db['betting']['wallets']['a']['balance'],20)
        bets.maintain(db,at('2026-10-25T23:59:00+01:00'))
        self.assertEqual(db['betting']['wallets']['a']['balance'],30)

    def test_twenty_minutes_and_total_gold_conservation(self):
        create(self.db);join(self.db)
        self.assertEqual(self.balances(),[5,5,10])
        self.receive(game('EARLY'),NOW+1199)
        self.assertFalse(self.db['betting']['rounds'])
        self.receive(game('COUNTS'),NOW+1200)
        self.assertEqual(self.balances(),[15,5,10])
        self.assertEqual(sum(self.balances()),30)
        self.assertEqual(self.db['betting']['rounds'][0]['matchId'],'COUNTS')
        self.assertFalse(bets.maintain(self.db,NOW+1300))

    def test_later_participation_does_not_share_a_different_match_pool(self):
        create(self.db);join(self.db,now=NOW+900)
        self.receive(game('FIRST'),NOW+1500)
        self.assertEqual(self.db['betting']['bets'][0]['payout'],5)
        self.assertEqual(self.db['betting']['bets'][1]['status'],'PENDING')
        self.receive(game('SECOND','LOSS'),NOW+2200)
        self.assertEqual([r['matchId'] for r in self.db['betting']['rounds']],['FIRST','SECOND'])
        self.assertEqual(self.balances(),[10,10,10])
        public=bets.public_board(self.db,'a',view='history')
        self.assertEqual([r['matchId'] for r in public['markets'][0]['rounds']],['FIRST','SECOND'])
        self.assertTrue(all('bets' not in r for r in public['markets'][0]['rounds']))
        self.assertEqual(public['markets'][0]['mine'][0]['matchId'],'FIRST')

    def test_same_batch_selects_oldest_match_then_id_and_cannot_replay(self):
        create(self.db);join(self.db)
        self.db['duos'][2]['history']=[game('B','LOSS'),game('A','WIN')]
        bets.maintain(self.db,NOW+1300)
        self.assertEqual(self.db['betting']['rounds'][0]['matchId'],'A')
        receipt=copy.deepcopy(self.db['betting']['receipts'])
        create(self.db,now=NOW+1400);join(self.db,now=NOW+1400)
        bets.maintain(self.db,NOW+3000)
        self.assertEqual(self.db['betting']['receipts'],receipt)
        self.assertEqual(len(self.db['betting']['rounds']),1)

    def test_missing_evidence_waits_and_cannot_let_new_stakes_join_an_old_receipt(self):
        create(self.db,metric='deaths',playerKey='player1',line='5,5',side='OVER')
        join(self.db,side='UNDER')
        match=game(player1Stats=None);self.receive(match,NOW+1300)
        self.assertTrue(all(b['waitingMatchId']=='M1' for b in self.db['betting']['bets']))
        self.receive(game('LATER',player1Stats={'puuid':'cmain','deaths':3}),NOW+1400)
        self.assertFalse(self.db['betting']['rounds'])
        match['player1Stats']={'puuid':'cmain','deaths':6}
        bets.maintain(self.db,NOW+1500)
        self.assertEqual(self.db['betting']['rounds'][0]['matchId'],'M1')
        self.assertEqual(self.balances(),[15,5,10])

    def test_confirmed_absence_and_foreign_stats_skip_to_next_valid_game(self):
        create(self.db,metric='kills',playerKey='player1',line='8.5',side='OVER');join(self.db,side='UNDER')
        self.receive(game('ABSENT',participantsChecked={'player1':True}),NOW+1300)
        self.receive(game('FOREIGN',player1Stats={'puuid':'foreign','kills':30}),NOW+1400)
        self.receive(game('VALID',player1Stats={'puuid':'cmain','kills':8}),NOW+1500)
        self.assertEqual(self.db['betting']['rounds'][0]['winner'],'UNDER')
        self.assertEqual(self.balances(),[5,15,10])

    def test_multiple_accounts_belong_to_the_selected_person(self):
        player=self.db['duos'][2]['player1'];player['accounts']=[dict(player),{'name':'Alt','tag':'EUW','puuid':'alt'}]
        create(self.db,metric='assists',playerKey='player1',line='10,5',side='OVER');join(self.db,side='UNDER')
        self.receive(game(player1Stats={'puuid':'alt','assists':11}),NOW+1300)
        self.assertEqual(self.balances(),[15,5,10])

    def test_invalid_matches_and_existing_history_never_resolve(self):
        self.receive(game('BEFORE'),NOW-10)
        create(self.db);join(self.db)
        self.receive(game('SHORT',durationSeconds=599),NOW+1300)
        self.receive(game('TEST',isTest=True),NOW+1300)
        self.receive(game('OLD',gameStartTimestamp=START-1),NOW+1300)
        self.receive(game('FLEX',queueId=440),NOW+1300)
        self.assertFalse(self.db['betting']['rounds'])
        self.assertEqual(self.db['betting']['receipts']['c']['BEFORE']['at'],NOW-10)

    def test_replaced_or_removed_targets_refund_pending_gold(self):
        create(self.db,metric='deaths',playerKey='player1',line='8,5',side='OVER');join(self.db,side='UNDER')
        self.db['duos'][2]['player1']['name']='Replacement'
        bets.maintain(self.db,NOW+1)
        self.assertEqual(self.balances(),[10,10,10])
        self.assertEqual(self.db['betting']['rounds'][0]['reason'],'target_changed')

    def test_fifo_matching_returns_the_unmatched_remainder_in_whole_coins(self):
        create(self.db,amount=2);join(self.db,side='WIN',amount=1);join(self.db,owner='c',side='LOSS',amount=2)
        self.receive(game(),NOW+1300)
        settled=self.db['betting']['bets']
        self.assertEqual([b['payout'] for b in settled],[4,1,0])
        self.assertEqual([b['matchedAmount'] for b in settled],[2,0,2])
        self.assertEqual([b['refundAmount'] for b in settled],[0,1,0])
        self.assertEqual(sum(self.balances()),30)

    def test_ten_against_one_never_risks_more_than_one_on_either_side(self):
        for result in ('WIN','LOSS'):
            with self.subTest(result=result):
                self.db=database();bets.maintain(self.db,NOW)
                create(self.db,amount=10);join(self.db,amount=1)
                self.receive(game(result=result),NOW+1300)
                state=self.db['betting'];one,two=state['bets']
                self.assertEqual([one['matchedAmount'],two['matchedAmount']],[1,1])
                self.assertEqual([one['refundAmount'],two['refundAmount']],[9,0])
                self.assertEqual([one['payout'],two['payout']],[11,0] if result=='WIN' else [9,2])
                self.assertEqual([one['profit'],two['profit']],[1,-1] if result=='WIN' else [-1,1])
                self.assertEqual(self.balances(),[11,9,10] if result=='WIN' else [9,11,10])
                self.assertEqual((state['rounds'][0]['pool'],state['rounds'][0]['reservedPool']),(2,11))
                self.assertEqual(state['rounds'][0]['unmatchedReturned'],9)
                self.assertFalse(bets.maintain(self.db,NOW+1301))

    def test_fifo_pairs_multiple_counterparties_and_respects_actual_arrival_time(self):
        entries=[{'id':'late','side':'WIN','amount':10,'createdAt':20},
                 {'id':'first','side':'WIN','amount':3,'createdAt':10},
                 {'id':'opposite1','side':'LOSS','amount':2,'createdAt':12},
                 {'id':'opposite2','side':'LOSS','amount':4,'createdAt':15}]
        matched,pairs=bets.match_contributions(entries)
        self.assertEqual(matched,{'late':3,'first':3,'opposite1':2,'opposite2':4})
        self.assertEqual(pairs,[{'leftBetId':'first','rightBetId':'opposite1','amount':2},
                                {'leftBetId':'first','rightBetId':'opposite2','amount':1},
                                {'leftBetId':'late','rightBetId':'opposite2','amount':3}])

    def test_arbitrary_pools_conserve_gold_and_each_risk_is_fully_backed(self):
        import random
        rng=random.Random(5101)
        for case in range(200):
            entries=[{'id':str(i),'teamId':str(i%3),'side':rng.choice(('OVER','UNDER')),
                      'amount':rng.randint(1,100),'createdAt':rng.randint(0,20)} for i in range(rng.randint(1,25))]
            winner=rng.choice(('OVER','UNDER'))
            state={'wallets':{str(i):{'balance':0} for i in range(3)},'ledger':[],'rounds':[]}
            bets.settle_pool(state,{'id':'market'},entries,'match',NOW,winner,8,NOW+1)
            total=sum(b['amount'] for b in entries)
            self.assertEqual(sum(w['balance'] for w in state['wallets'].values()),total)
            expected=min(sum(b['amount'] for b in entries if b['side']=='OVER'),sum(b['amount'] for b in entries if b['side']=='UNDER'))
            for side in ('OVER','UNDER'):
                self.assertEqual(sum(b['matchedAmount'] for b in entries if b['side']==side),expected)
            for bet in entries:
                self.assertEqual(bet['amount'],bet['matchedAmount']+bet['refundAmount'])
                self.assertEqual(bet['profit'],bet['matchedAmount']*(1 if bet['side']==winner else -1))
                self.assertGreaterEqual(bet['payout'],bet['refundAmount'])
            self.assertEqual(state['rounds'][0]['pool'],2*expected)

    def test_legacy_settled_rounds_and_wallets_are_not_recalculated(self):
        create(self.db,amount=10);join(self.db,amount=1)
        state=self.db['betting'];one,two=state['bets']
        for bet,payout in ((one,0),(two,11)):
            bet.update(status='SETTLED',payout=payout,roundId='legacy')
        state['wallets']['b']['balance']+=11
        state['rounds']=[{'id':'legacy','marketId':one['marketId'],'matchId':'old',
            'receivedAt':NOW,'settledAt':NOW,'winner':'LOSS','value':'LOSS','pool':11,
            'status':'SETTLED','reason':None,'bets':[one['id'],two['id']]}]
        before=copy.deepcopy(self.db)
        self.assertFalse(bets.maintain(self.db,NOW+1300))
        self.assertEqual(self.db,before)
        public=bets.public_board(self.db,'a',view='history')
        self.assertNotIn('payoutRule',public['markets'][0]['lastRound'])
        self.assertEqual(public['markets'][0]['lastRound']['pool'],11)

    def test_validation_has_no_wallet_or_market_side_effects(self):
        cases=[{'amount':True},{'amount':-1},{'amount':0},{'amount':1.5},{'amount':'5'},{'amount':11},
            {'metric':'other'},{'targetId':'unknown'},{'metric':'deaths','playerKey':'bad','line':'5,5','side':'OVER'},
            *[{'metric':'deaths','playerKey':'player1','line':line,'side':'OVER'} for line in ('50,5','50','5','5,4','-1,5','1e1,5','1,5abc')]]
        for extra in cases:
            before=copy.deepcopy(self.db)
            with self.assertRaises((ValueError,FileExistsError)):create(self.db,**extra)
            self.assertEqual(self.db,before)
        for line,half in [('0,5',1),('5.5',11),('49,5',99)]:self.assertEqual(bets.threshold(line),half)

    def test_idempotency_and_mismatch_and_public_privacy(self):
        body={'action':'create','metric':'result','targetId':'c','amount':5,'requestId':'same-operation-123456'}
        one=bets.participate(self.db,'a',body,NOW)
        self.assertEqual(bets.participate(self.db,'a',body,NOW+1),one)
        with self.assertRaises(FileExistsError):bets.participate(self.db,'a',{**body,'amount':3},NOW+1)
        public=bets.public_board(self.db)
        self.assertIsNone(public['wallet']);self.assertEqual(public['markets'][0]['mine'],[])
        self.assertFalse(any(term in json.dumps(public) for term in ('puuid','playerIdentity','password','fingerprint','requestId')))
        mine=bets.public_board(self.db,'a')
        self.assertEqual(mine['wallet']['reserved'],5)
        self.assertEqual(mine['wallet']['balance'],5)


class BettingEndpointTests(unittest.TestCase):
    setUp=fixtures.SharedLikesTests.setUp
    tearDown=fixtures.SharedLikesTests.tearDown
    client=fixtures.SharedLikesTests.client
    call=fixtures.SharedLikesTests.call
    login=fixtures.SharedLikesTests.login
    def payload(self):return {'action':'create','metric':'result','targetId':'b','amount':5,'requestId':'atomic-operation-123456'}

    def test_auth_origin_and_forged_owner(self):
        client,_=self.client()
        self.call(client,'/api/bets',self.payload(),status=401)
        auth=self.login(client)
        self.call(client,'/api/bets',self.payload(),status=403,headers={**auth,'Origin':'https://evil.test'})
        result,_=self.call(client,'/api/bets',{**self.payload(),'teamId':'b'},headers=auth)
        self.assertEqual(result['wallet']['teamId'],'a');self.assertEqual(result['wallet']['balance'],5)
        other,_=self.client();public,_=self.call(other,'/api/bets')
        self.assertIsNone(public['wallet']);self.assertEqual(public['markets'][0]['mine'],[])

    def test_concurrent_retry_debits_once_and_insufficient_gold_cannot_overdraw(self):
        owner,_=self.client();auth=self.login(owner)
        def send(i):
            client,_=self.client()
            return self.call(client,'/api/bets',self.payload(),headers=auth)[0]
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(send,range(4)))
        self.assertTrue(all(r['betId']==results[0]['betId'] for r in results))
        db=server.load_db();self.assertEqual(len(db['betting']['bets']),1)
        self.assertEqual(db['betting']['wallets']['a']['balance'],5)
        self.call(owner,'/api/bets',{**self.payload(),'amount':6,'requestId':'another-operation-12345'},status=409,headers=auth)
        self.assertEqual(server.load_db()['betting']['wallets']['a']['balance'],5)

    def test_failed_write_and_lost_response_do_not_double_charge(self):
        client,_=self.client();auth=self.login(client)
        before=server.load_db()
        with patch.object(server,'save_db',side_effect=StorageError('offline')):
            self.call(client,'/api/bets',self.payload(),status=503,headers=auth)
        self.assertEqual(server.load_db(),before)
        save=server.save_db
        def save_then_fail(db):save(db);raise StorageError('lost response')
        with patch.object(server,'save_db',side_effect=save_then_fail):
            self.call(client,'/api/bets',self.payload(),status=503,headers=auth)
        result,_=self.call(client,'/api/bets',self.payload(),headers=auth)
        self.assertEqual(result['wallet']['balance'],5)
        self.assertEqual(len(server.load_db()['betting']['bets']),1)

    def test_unbalanced_pool_api_reports_refund_risk_and_private_pairings(self):
        with patch.object(bets.time,'time',return_value=NOW):
            one,_=self.client();two,_=self.client();a=self.login(one);b=self.login(two,'b')
            first,_=self.call(one,'/api/bets',{**self.payload(),'amount':10},headers=a)
            self.call(two,'/api/bets',{'action':'join','marketId':first['markets'][0]['id'],'side':'LOSS','amount':1,'requestId':'one-coin-counterparty-123'},headers=b)
        with patch.object(bets.time,'time',return_value=NOW+1300):
            db=server.load_db();db['duos'][1]['history']=[game(result='LOSS')];server.save_db(db)
            result,_=self.call(one,'/api/bets?view=history',headers=a)
            self.assertEqual(result['wallet']['balance'],9)
            own=result['markets'][0]['mine'][0]
            self.assertEqual((own['matchedAmount'],own['refundAmount'],own['payout'],own['profit']),(1,9,9,-1))
            self.assertEqual(result['markets'][0]['lastRound']['pool'],2)
            self.assertNotIn('pairings',json.dumps(result))
            self.assertNotIn('leftBetId',json.dumps(result))
            opposite,_=self.call(two,'/api/bets?view=history',headers=b)
            self.assertEqual(opposite['wallet']['balance'],11)
            self.assertEqual(opposite['markets'][0]['mine'][0]['payout'],2)

    def test_receipts_settlement_are_saved_in_the_same_state_as_history(self):
        with patch.object(bets.time,'time',return_value=NOW):
            one,_=self.client();two,_=self.client();a=self.login(one);b=self.login(two,'b')
            first,_=self.call(one,'/api/bets',self.payload(),headers=a)
            self.call(two,'/api/bets',{'action':'join','marketId':first['markets'][0]['id'],'side':'LOSS','amount':5,'requestId':'join-operation-123456'},headers=b)
        with patch.object(bets.time,'time',return_value=NOW+1300):
            db=server.load_db();db['duos'][1]['history']=[game()];server.save_db(db)
            saved=server.load_db();self.assertEqual(saved['betting']['wallets']['a']['balance'],15)
            self.assertEqual(saved['betting']['receipts']['b']['M1']['at'],NOW+1300)
            result,_=self.call(one,'/api/bets?view=history',headers=a)
            self.assertEqual(result['markets'][0]['lastRound']['matchId'],'M1')
            self.assertEqual(result['markets'][0]['mine'][0]['payout'],10)


if __name__=='__main__':unittest.main()
