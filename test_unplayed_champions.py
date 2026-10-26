"""Random-champion penalties share the tournament album's played evidence."""
import copy
import unittest
from unittest.mock import patch

import server
import champions_service
import test_shell_penalties as fixtures
from test_champions import database, game


class UnplayedChampionTests(unittest.TestCase):
    def requirements(self, db, scope='ONE', pool=('Ahri','Lux','Locke')):
        penalty = next(p for p in server.PENALTY_CATALOG if p['baseId']=='random_champion' and p['scope']==scope)
        def draw(options):
            return 'player1' if options == ('player1','player2') else options[0]
        with patch.object(server, 'champion_pool', return_value=list(pool)), patch.object(server.secrets,'choice',side_effect=draw) as choice:
            result = server.penalty_requirements(db['duos'][0], penalty, db['duos'], config=db['config'])
        pools = [list(call.args[0]) for call in choice.call_args_list if call.args[0] != ('player1','player2')]
        return result, pools

    def test_played_anywhere_in_tournament_is_excluded(self):
        db = database(game(first='Ahri',second='Lux'))
        db['duos'].append({'id':'b','player1':{'name':'New'},'player2':{'name':'Other'},'history':[]})
        db['duos'].reverse()  # The punished team has never played either champion.
        before = copy.deepcopy(db)
        req, pools = self.requirements(db)
        self.assertEqual(req['randomChampions'],{'player1':'Locke'})
        self.assertEqual(req['randomChampionPool'],'unplayed')
        self.assertEqual(pools,[['Locke']])
        self.assertEqual(db,before)

    def test_every_champion_returns_only_when_all_have_been_played(self):
        db=database(game(first='Ahri',second='Lux'),game('two',first='Locke',second='Vex'))
        req,pools=self.requirements(db)
        self.assertEqual(req['randomChampionPool'],'all')
        self.assertEqual(pools,[['Ahri','Lux','Locke']])

    def test_both_players_draw_from_the_remaining_pool(self):
        db=database(game(first='Ahri',second='Ahri'))
        req,pools=self.requirements(db,'BOTH')
        self.assertEqual(set(req['randomChampions']),{'player1','player2'})
        self.assertEqual(pools,[['Lux','Locke'],['Locke']])
        self.assertNotEqual(req['randomChampions']['player1'],req['randomChampions']['player2'])

    def test_last_remaining_goes_to_one_player_and_the_other_gets_a_different_champion(self):
        db=database(game(first='Ahri',second='Lux'))
        req,pools=self.requirements(db,'BOTH')
        self.assertEqual(req['randomChampionPool'],'last_unplayed')
        self.assertEqual(req['randomChampions'],{'player1':'Locke','player2':'Ahri'})
        self.assertEqual(req['randomChampionPoolByPlayer'],{'player1':'unplayed','player2':'all'})
        self.assertEqual(pools,[['Locke'],['Ahri','Lux']])

    def test_tests_short_games_other_queues_dates_and_exclusions_do_not_unlock_repeats(self):
        db=database(game('test',first='Locke',isTest=True),
                    game('short',first='Locke',durationSeconds=599),
                    game('flex',first='Locke',queueId=440),
                    game('old',first='Locke',gameEndTimestamp=1000),
                    game('excluded',first='Locke'))
        db['duos'][0]['excludedRiotMatches']={'excluded':{}}
        req,pools=self.requirements(db,pool=('Locke',))
        self.assertEqual(req['randomChampionPool'],'unplayed')
        self.assertEqual(pools,[['Locke']])

    def test_locke_and_vex_are_independent_album_entries(self):
        db=database(game(first='Locke',second='Ahri'))
        req,pools=self.requirements(db,pool=('Locke','Vex'))
        self.assertEqual(pools,[['Vex']])
        album=champions_service.build_album(db)
        rows={row['id']:row for row in album['champions']}
        self.assertEqual(rows['Locke']['games'],1)
        self.assertEqual(rows['Vex']['games'],0)
        self.assertEqual(server.normalize_champion_name('Locke'),'Locke')

    def test_catalog_is_complete_offline_and_matches_the_album(self):
        with patch.object(server.urllib.request,'urlopen',side_effect=AssertionError('no network')):
            pool=server.champion_pool([])
        self.assertEqual(set(pool),{row['id'] for row in champions_service.OPTIONS})
        self.assertIn('Locke',pool)
        self.assertIn('Vex',pool)


class UnplayedChampionEndpointTests(unittest.TestCase):
    setUp=fixtures.ShellEndpointTests.setUp
    tearDown=fixtures.ShellEndpointTests.tearDown
    post=fixtures.ShellEndpointTests.post

    def test_spin_uses_current_album_and_persists_assignment_without_redrawing(self):
        db=server.load_db()
        db['config'].update(database()['config'])
        db['config']['penaltyWeights']={p['id']:100 if p['id']=='random_champion_one' else 0 for p in server.PENALTY_CATALOG}
        server.save_db(db)
        sender=self.post('/api/player/login',{'teamId':'a','password':'a-pass'})['sessionToken']
        receiver=self.post('/api/player/login',{'teamId':'b','password':'b-pass'})['sessionToken']
        attack=self.post('/api/player/launch-shell',{'targetId':'b','sessionToken':sender})['attack']
        db=server.load_db()
        db['duos'][0]['history']=[game(first='Ahri',second='Lux')]
        server.save_db(db)  # Games played after launch must influence the spin.
        with patch.object(server,'champion_pool',return_value=['Ahri','Lux','Locke']):
            result=self.post('/api/player/spin-shell',{'attackId':attack['id'],'sessionToken':receiver})
        req=result['penaltyInstance']['requirements']
        self.assertEqual(req['randomChampions'],{req['assignedPlayer']:'Locke'})
        self.assertEqual(req['randomChampionPool'],'unplayed')
        self.assertEqual(result['attack']['requirements'],req)
        stored=server.load_db()
        event=next(e for e in stored['events'] if e['type']=='SHELL_SPUN')
        self.assertEqual(event['requirements'],req)
        with patch.object(server.secrets,'choice',side_effect=AssertionError('must not redraw')):
            reloaded=self.post('/api/player/state',{'sessionToken':receiver})
            self.post('/api/player/spin-shell',{'attackId':attack['id'],'sessionToken':receiver},expected=409)
        self.assertEqual(reloaded['duo']['activeDebuffs'][0]['requirements'],req)


if __name__=='__main__':
    unittest.main()
