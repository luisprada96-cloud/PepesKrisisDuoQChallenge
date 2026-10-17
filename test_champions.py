"""The album counts registered participants only, without changing tournament state."""
import copy
import json
import unittest
import urllib.request

import champions_service as album
import server
import test_shell_penalties as fixtures

START='2026-10-15T18:00:00+02:00'
END='2026-11-15T23:59:00+01:00'
AT=album.timestamp(START)+3600


def game(mid='EUW1_ONE', first='Ahri', second='Lux', **extra):
    return {'matchId':mid,'gameEndTimestamp':int(AT*1000),'durationSeconds':1200,'queueId':420,
            'participantsChecked':{'player1':True,'player2':True},
            'player1Stats':{'championName':first,'puuid':'one','participantId':1},
            'player2Stats':{'championName':second,'puuid':'two','participantId':2},**extra}


def database(*games):
    return {'config':{'startDate':START,'endDate':END},'duos':[{'id':'a',
        'player1':{'name':'One','puuid':'one'},'player2':{'name':'Two','puuid':'two'},'history':list(games)}]}


def counts(result):
    return {row['id']:row['games'] for row in result['champions']}


class AlbumTests(unittest.TestCase):
    def test_catalog_sort_zeroes_and_no_mutation(self):
        db=database(game(),game('EUW1_TWO','Ahri','Zed'))
        before=copy.deepcopy(db)
        result=album.build_album(db)
        self.assertEqual(db,before)
        self.assertEqual(result['totalChampions'],len(album.OPTIONS))
        self.assertEqual(result['playedChampions'],3)
        self.assertEqual(result['totalPicks'],4)
        self.assertEqual(result['totalMatches'],2)
        self.assertEqual(result['champions'][0]['id'],'Ahri')
        self.assertEqual(counts(result)['Ahri'],2)
        self.assertTrue(any(row['games']==0 and not row['played'] for row in result['champions']))
        empty=album.build_album(database())
        self.assertEqual(empty['playedChampions'],0)
        self.assertEqual(empty['totalPicks'],0)

    def test_duplicate_history_teams_and_participants_count_once(self):
        db=database(game(),game())
        duplicate=copy.deepcopy(db['duos'][0]);duplicate['id']='b'
        db['duos'].append(duplicate)
        db['duos'].append({'id':'c','player1':{'name':'Third'},'history':[game(player1Stats={
            'championName':'Ahri','puuid':'third','participantId':3},player2Stats=None,
            participantsChecked={'player1':True,'player2':True},participants=[{'championName':'Zed'}])]})
        result=album.build_album(db)
        self.assertEqual(result['totalMatches'],1)
        self.assertEqual(result['totalPicks'],3)
        self.assertEqual(counts(result)['Ahri'],2)
        self.assertEqual(counts(result)['Lux'],1)
        self.assertEqual(counts(result)['Zed'],0)
        self.assertEqual(result['pendingMatches'],0)

    def test_dates_queue_tests_exclusions_and_duration_boundary(self):
        db=database(game('valid',durationSeconds=600),game('short',durationSeconds=599),
                    game('test',isTest=True),game('queue',queueId=440),
                    game('early',gameEndTimestamp=int((album.timestamp(START)-1)*1000)),
                    game('late',gameEndTimestamp=int(album.timestamp(END)*1000)),
                    game('excluded'),game('fallback',durationSeconds=None,gameStartTimestamp=int((AT-76)*1000)))
        db['duos'][0]['excludedRiotMatches']={'excluded':{'reason':'manual'}}
        result=album.build_album(db)
        self.assertEqual(result['totalMatches'],1)
        self.assertEqual(result['totalPicks'],2)

    def test_aliases_and_missing_data_are_explicit(self):
        db=database(game('one','Wukong','MonkeyKing'),game('missing',second='Unknown'))
        db['duos'][0]['riotMatchDiscovery']={'pendingMatchIds':['pending']}
        result=album.build_album(db)
        self.assertEqual(counts(result)['MonkeyKing'],2)
        self.assertEqual(result['pendingMatches'],2)
        # Confirmed absent P2 is not an incomplete participant.
        result=album.build_album(database(game(player2Stats=None)))
        self.assertEqual(result['pendingMatches'],0)
        self.assertEqual(result['totalPicks'],1)

    def test_legacy_champion_fallback_and_incomplete_participant(self):
        row=game(player1Stats=None,player2Stats=None,championP1='Ahri',participantsChecked={})
        result=album.build_album(database(row))
        self.assertEqual(counts(result)['Ahri'],1)
        self.assertEqual(result['pendingMatches'],1)
        with self.assertRaises(ValueError):album.build_album({'config':{},'duos':[]})


class AlbumEndpointTests(unittest.TestCase):
    setUp=fixtures.ShellEndpointTests.setUp
    tearDown=fixtures.ShellEndpointTests.tearDown

    def test_public_api_and_files_with_no_sensitive_data_or_writes(self):
        db=server.load_db();db['config'].update(startDate=START,endDate=END)
        db['duos'][0]['history']=[game()]
        server.save_db(db)
        before=copy.deepcopy(server.load_db())
        with urllib.request.urlopen(self.base+'/api/champions') as response:
            payload=json.load(response)
        self.assertEqual(payload['totalPicks'],2)
        self.assertNotIn('password',json.dumps(payload))
        self.assertNotIn('puuid',json.dumps(payload))
        self.assertEqual(server.load_db(),before)
        for filename in ('campeones.html','campeones.css','campeones.js'):
            with urllib.request.urlopen(self.base+'/'+filename) as response:
                self.assertEqual(response.status,200)


if __name__=='__main__':unittest.main()
