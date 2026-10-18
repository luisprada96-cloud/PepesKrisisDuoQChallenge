"""Madrid cutoff, safe repair and enforcement for all account sources."""
import copy
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import riot_match_policy as policy
import repair_riot_history
import server
import test_riot_incremental as single
import test_player_accounts as multi

CUTOFF = policy.MIN_START_TIMESTAMP * 1000


class DatePolicyTests(unittest.TestCase):
    def test_midnight_madrid_and_crossing_midnight(self):
        self.assertEqual(policy.MIN_START_TIMESTAMP,1792015200)
        self.assertTrue(policy.before_cutoff({'gameStartTimestamp':CUTOFF-1,'gameEndTimestamp':CUTOFF+1200000}))
        self.assertFalse(policy.before_cutoff({'gameStartTimestamp':CUTOFF}))
        self.assertFalse(policy.before_cutoff({'gameStartTimestamp':CUTOFF+1}))
        self.assertTrue(policy.before_cutoff({'gameEndTimestamp':CUTOFF-1}))
        for invalid in (None, False, 'bad', float('nan'), -1):
            self.assertIsNone(policy.match_timestamp_ms({'gameStartTimestamp':invalid}))

    def test_challenge_record_uses_unique_valid_history_not_the_season(self):
        valid = lambda mid, result, **extra: {'matchId':mid, 'result':result,
            'gameStartTimestamp':CUTOFF, 'durationSeconds':1200, **extra}
        duo = {'wins':100, 'losses':200, 'excludedRiotMatches':{'EXCLUDED':{}}, 'history':[
            valid('ONE','WIN'), valid('ONE','WIN'), valid('TWO','LOSS'),
            valid('THREE','LOSS'), valid('FOUR','WIN',durationSeconds=600),
            valid('OLD','LOSS',gameStartTimestamp=CUTOFF-1), valid('TEST','WIN',isTest=True),
            valid('SHORT','WIN',durationSeconds=599), valid('FLEX','WIN',queueId=440),
            valid('EXCLUDED','WIN'), valid('PENDING','UNKNOWN'), valid('UNDATED','WIN',gameStartTimestamp=None)]}
        before = copy.deepcopy(duo)
        self.assertEqual(policy.history_record(duo), {'wins':2,'losses':2,'games':4})
        summary = server.duo_summary(duo)
        self.assertEqual(summary['tournamentRecord'], {'wins':2,'losses':2,'games':4})
        self.assertEqual((summary['wins'],summary['losses']), (100,200))
        self.assertNotIn('history',summary)
        self.assertEqual(duo,before)
        self.assertEqual(policy.history_record({'wins':100,'losses':200,'history':[]}),
                         {'wins':0,'losses':0,'games':0})

    def test_discovery_clamps_the_requested_date_for_any_caller(self):
        observed=[]
        def fetch(url):
            observed.append(parse_qs(urlparse(url).query)['startTime'][0])
            return []
        server.discover_riot_matches({'player1':{'name':'One'},'history':[]},'p',fetch,1767225600)
        self.assertEqual(observed,[str(policy.MIN_START_TIMESTAMP)])

    def fixture(self):
        old={'matchId':'OLD','gameStartTimestamp':CUTOFF-1,'gameEndTimestamp':CUTOFF+1,
             'result':'LOSS','player1Stats':{'kills':99,'deaths':1,'assists':1}}
        valid={'matchId':'VALID','gameStartTimestamp':CUTOFF,'gameEndTimestamp':CUTOFF+1200000,
               'result':'WIN','statsVersion':2,'matchDetailsVersion':1,'shellRewardIds':['kills'],
               'shellRewardCredits':{'kills':True},'processedForShell':True,
               'player1Stats':{'championName':'Ahri','kills':20,'deaths':2,'assists':10,'win':True}}
        duo={'id':'target','teamName':'ATodoFlash','history':[valid,old],'blueShells':3,'shellsEarnedTotal':7,
             'player1':{'name':'Markel','rank':{'tier':'Gold'},'accounts':[{'id':'alt','name':'Unlucky Lemür',
                 'flashBaseline':{'matchId':'OLD','gameStartTimestamp':CUTOFF-1},
                 'matchDiscovery':{'pendingMatchIds':['OLD','GAP']}}]},
             'riotMatchDiscovery':{'pendingMatchIds':['OLD','GAP']},'activeDebuffs':[{'status':'ACTIVE','requirements':{'keep':True}}]}
        return {'config':{},'duos':[duo,{'id':'other','history':[copy.deepcopy(old)]}], 'pickem':{'keep':True},'events':[{'keep':True}]}

    def test_repair_preserves_valid_ledgers_other_teams_inventory_and_castigos(self):
        before=self.fixture();snapshot=copy.deepcopy(before)
        after, report=repair_riot_history.prepare_repair(before,'target')
        self.assertEqual(before,snapshot)
        self.assertEqual((report['removedCount'],report['keptCount']),(1,1))
        duo=after['duos'][0]
        self.assertEqual(duo['history'],[before['duos'][0]['history'][0]])
        for field in ('blueShells','shellsEarnedTotal','activeDebuffs'):
            self.assertEqual(duo[field],before['duos'][0][field])
        self.assertEqual(duo['player1']['rank'],before['duos'][0]['player1']['rank'])
        self.assertEqual(duo['playerInsights']['player1']['totals']['kills'],20)
        self.assertEqual(duo['riotMatchDiscovery']['pendingMatchIds'],['GAP'])
        self.assertNotIn('flashBaseline',duo['player1']['accounts'][0])
        self.assertEqual(duo['player1']['accounts'][0]['matchDiscovery']['pendingMatchIds'],['GAP'])
        self.assertEqual(duo['excludedRiotMatches']['OLD']['reason'],'before_tournament_start')
        for field in ('pickem','events'):
            self.assertEqual(after[field],before[field])
        self.assertEqual(after['duos'][1],before['duos'][1])
        repeated, report=repair_riot_history.prepare_repair(after,'target')
        self.assertEqual(report['removedCount'],0)
        self.assertEqual(repeated,after)

    def test_old_awards_or_completed_penalties_require_review(self):
        for kind in ('reward','penalty'):
            before=self.fixture()
            if kind=='reward': before['duos'][0]['history'][1]['shellRewardIds']=['penta']
            else: before['duos'][0]['activeDebuffs']=[{'status':'COMPLETED','resolvedByMatchId':'OLD'}]
            snapshot=copy.deepcopy(before)
            with self.assertRaises(ValueError): repair_riot_history.prepare_repair(before,'target')
            self.assertEqual(before,snapshot)

    def test_test_and_undated_rows_are_not_deleted_by_guessing(self):
        duo={'history':[{'matchId':'TEST','isTest':True,'gameStartTimestamp':CUTOFF-1},{'matchId':'UNKNOWN'}]}
        self.assertEqual(policy.prune_history(duo),[])
        self.assertEqual(len(duo['history']),2)


class SingleAccountCutoffTests(unittest.TestCase):
    setUp=single.IncrementalSyncTests.setUp
    tearDown=single.IncrementalSyncTests.tearDown
    prepare=single.IncrementalSyncTests.prepare

    def test_old_pending_details_are_excluded_and_exact_boundary_is_kept(self):
        self.prepare()
        worker=single.IncrementalSyncTests()
        calls=[]
        base=worker.responses(['OLD','VALID'],calls)
        fetched_details=[]
        def reply(request,**kwargs):
            import io,json
            if request.full_url.endswith('/OLD') or request.full_url.endswith('/VALID'):
                fetched_details.append(request.full_url.rsplit('/',1)[-1])
                payload=single.detail()
                payload['info']['gameStartTimestamp']=CUTOFF-1 if request.full_url.endswith('/OLD') else CUTOFF
                payload['info']['gameEndTimestamp']=CUTOFF+1200000
                return io.BytesIO(json.dumps(payload).encode())
            return base(request,**kwargs)
        for _ in range(2):
            with patch.object(server,'get_riot_api_key',return_value='fake'),patch.object(server,'riot_open',side_effect=reply),patch.object(server.time,'sleep'):
                self.assertTrue(server.sync_riot_data()['success'])
        duo=server.load_db()['duos'][0]
        self.assertEqual([m['matchId'] for m in duo['history']],['VALID'])
        self.assertEqual(duo['excludedRiotMatches']['OLD']['reason'],'before_tournament_start')
        self.assertEqual(duo['riotMatchDiscovery']['pendingMatchIds'],[])
        self.assertEqual(fetched_details.count('OLD'),1)


class MultipleAccountCutoffTests(unittest.TestCase):
    setUp=multi.MultiAccountEndpointTests.setUp
    tearDown=multi.MultiAccountEndpointTests.tearDown
    post=multi.MultiAccountEndpointTests.post
    configure=multi.MultiAccountEndpointTests.configure
    sync=multi.MultiAccountEndpointTests.sync

    def test_multiple_sources_reject_an_old_detail_even_if_api_returns_it(self):
        self.configure()
        original=server.riot_accounts_sync.sync_team
        import riot_accounts_sync
        def sync_team(duo,fetch,failure,api):
            def detail_filter(url):
                data=fetch(url)
                if url.endswith('/EUW1_ALT'):
                    data['info']['gameStartTimestamp']=CUTOFF-1
                    data['info']['gameEndTimestamp']=CUTOFF+1200000
                return data
            return original(duo,detail_filter,failure,api)
        with patch.object(riot_accounts_sync,'sync_team',side_effect=sync_team):
            result,calls=self.sync()
        self.assertTrue(result['success'])
        duo=server.load_db()['duos'][0]
        self.assertEqual([m['matchId'] for m in duo['history']],['EUW1_SHARED'])
        self.assertEqual(duo['excludedRiotMatches']['EUW1_ALT']['reason'],'before_tournament_start')
        self.assertEqual(duo['riotMatchDiscovery']['pendingMatchIds'],[])
        self.assertTrue(all(parse_qs(urlparse(u).query)['startTime']==[str(policy.MIN_START_TIMESTAMP)] for u in calls if 'startTime=' in u))


if __name__=='__main__': unittest.main()
