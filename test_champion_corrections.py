import copy
import unittest

import champion_corrections
import champions_service
import server
import test_shell_penalties as fixtures
from test_champions import database, game


def confirmed_game(mid='EUW1_8014333109'):
    match=game(mid,first='Vex',second='Ahri')
    match.update(championP1='Vex',matchDetailsVersion=1,shellRewardIds=['streak'],processedForShell=True)
    match['player1Stats'].update(riotIdGameName='JaGenau',riotIdTagline='JOYAS',kills=7,deaths=11,assists=4)
    return match


class ConfirmedChampionCorrectionsTests(unittest.TestCase):
    def test_only_confirmed_games_and_identity_change_once(self):
        first=confirmed_game()
        second=confirmed_game('EUW1_8017228945')
        future=confirmed_game('EUW1_FUTURE')
        other=confirmed_game()
        other['player1Stats']['riotIdGameName']='OtherPerson'
        verified=confirmed_game()
        verified['player1Stats']['championId']=711
        duo={'history':[first,second,future,other,verified]}
        untouched=copy.deepcopy(duo['history'][2:])
        self.assertTrue(champion_corrections.repair_confirmed_locke(duo))
        for match in (first,second):
            self.assertEqual(match['championP1'],'Locke')
            self.assertEqual(match['player1Stats']['championName'],'Locke')
            self.assertEqual(match['player1Stats']['championCorrection']['from'],'Vex')
            self.assertEqual(match['shellRewardIds'],['streak'])
            self.assertEqual(match['player1Stats']['kills'],7)
        self.assertEqual(duo['history'][2:],untouched)
        self.assertFalse(champion_corrections.repair_confirmed_locke(duo))

    def test_album_marks_locke_and_retains_other_players_vex(self):
        db=database(confirmed_game(),confirmed_game('EUW1_8017228945'),game('pingu',first='Vex'))
        before=champions_service.build_album(db)
        champion_corrections.repair_confirmed_locke(db['duos'][0])
        after=champions_service.build_album(db)
        counts={row['id']:row['games'] for row in after['champions']}
        self.assertEqual(counts['Locke'],2)
        self.assertEqual(counts['Vex'],1)
        self.assertEqual(before['totalPicks'],after['totalPicks'])
        self.assertEqual(before['totalMatches'],after['totalMatches'])


class ChampionCorrectionPersistenceTests(unittest.TestCase):
    setUp=fixtures.ShellEndpointTests.setUp
    tearDown=fixtures.ShellEndpointTests.tearDown

    def test_loading_persists_correction_and_refreshes_summaries_without_rewards(self):
        db=server.load_db()
        db['duos'][0]['history']=[confirmed_game()]
        db['duos'][0]['blueShells']=3
        server.save_db(db)
        loaded=server.load_db()
        duo=loaded['duos'][0]
        self.assertEqual(duo['history'][0]['player1Stats']['championName'],'Locke')
        self.assertEqual(duo['playerInsights']['player1']['topChampion']['name'],'Locke')
        self.assertEqual(duo['blueShells'],3)
        self.assertEqual(duo['history'][0]['shellRewardIds'],['streak'])
        reloaded=server.load_db()
        self.assertEqual(duo['history'],reloaded['duos'][0]['history'])
        self.assertEqual(reloaded['events'],loaded['events'])


if __name__=='__main__':
    unittest.main()
