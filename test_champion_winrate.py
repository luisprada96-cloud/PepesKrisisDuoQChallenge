"""Champion winrate predictions: thresholds, exact ties and weekly settlement."""
import copy
import unittest

import pickem_service as pickem
from test_pickem import database, game, NOW, WEEK, CATEGORY


class ChampionWinrateTests(unittest.TestCase):
    def setUp(self):
        self.db = database()
        pickem.ensure_week(self.db, NOW)
        self.board = self.db['pickem']['weeks'][WEEK]
        self.category = next(c for c in self.board['categories'] if c['id']=='best_champion_winrate')

    def add_games(self, champion, outcomes, team=0):
        history = self.db['duos'][team]['history']
        for win in outcomes:
            match = game(f'EUW1_{team}_{len(history)}', first=champion)
            match['player1Stats']['puuid'] = f'player-{team}'
            match['player1Stats']['win'] = win
            match['player2Stats'] = None
            history.append(match)

    def result(self):
        return pickem.category_result(self.db, self.board, self.category)

    def test_catalog_has_all_champions_display_names_and_validates_selections(self):
        options = {o['id']:o['label'] for o in self.category['options']}
        self.assertGreaterEqual(len(options), 173)
        self.assertEqual(options['MonkeyKing'], 'Wukong')
        self.assertEqual(options['Kaisa'], "Kai'Sa")
        self.assertEqual(options['MasterYi'], 'Maestro Yi')
        ballot, _ = pickem.submit(self.db, 'a', 'one', self.category['id'], 'MonkeyKing', now=NOW)
        self.assertEqual(ballot['answers'][self.category['id']], 'MonkeyKing')
        with self.assertRaises(ValueError):
            pickem.submit(self.db, 'a', 'two', self.category['id'], 'not-a-champion', now=NOW)
        pickem.ensure_week(self.db, pickem.weeks.timestamp('2026-10-19T12:00'))
        self.assertIn(self.category['id'], [c['id'] for c in self.db['pickem']['weeks']['2026-10-19']['categories']])

    def test_three_games_required_and_winrate_beats_number_of_wins(self):
        self.add_games('Teemo', [True, True])
        self.add_games('Ahri', [True, True, False])
        self.add_games('Lux', [True, True, True, False, False])
        self.add_games('Jinx', [False, False, False])
        result = self.result()
        self.assertEqual(result['optionIds'], ['Ahri'])
        self.assertAlmostEqual(result['value'], 200/3)
        self.assertEqual(result['evidence'][0], {'optionId':'Ahri', 'label':'Ahri', 'games':3, 'wins':2, 'losses':1})

    def test_exact_ties_accept_all_champions_even_with_different_game_counts(self):
        self.add_games('Ahri', [True, True, False])
        self.add_games('Lux', [True, True, True, True, False, False], team=1)
        self.assertEqual(self.result()['optionIds'], ['Ahri', 'Lux'])

    def test_aliases_aggregate_across_teams_and_match_copies_do_not_inflate_games(self):
        self.add_games('Wukong', [True, False])
        self.db['duos'][1]['history'] = copy.deepcopy(self.db['duos'][0]['history'])
        self.assertEqual(self.result()['status'], 'NO_DATA', 'duplicate participant matches cannot reach the minimum')
        self.add_games('MonkeyKing', [True], team=1)
        result = self.result()
        self.assertEqual(result['optionIds'], ['MonkeyKing'])
        self.assertEqual(result['evidence'][0]['games'], 3)
        self.assertEqual(result['evidence'][0]['wins'], 2)

    def test_only_participants_solo_duo_and_weekly_tournament_games_count(self):
        self.add_games('Ahri', [True, True, False])
        valid = self.db['duos'][0]['history'][0]
        ignored = [
            {**copy.deepcopy(valid), 'isTest':True},
            {**copy.deepcopy(valid), 'queueId':450},
            {**copy.deepcopy(valid), 'gameEndTimestamp':(pickem.period(self.db,WEEK)['startsAt']-1)*1000},
            {**copy.deepcopy(valid), 'gameEndTimestamp':pickem.period(self.db,WEEK)['endsAt']*1000}
        ]
        for index, match in enumerate(ignored):
            match['matchId'] = f'ignored-{index}'
            match['player1Stats']['championName'] = 'Lux'
        self.db['duos'][0]['history'] += ignored
        for match in self.db['duos'][0]['history']:
            match['participants'] = [{'puuid':'outsider', 'championName':'Teemo', 'win':True}]
        self.assertEqual(self.result()['optionIds'], ['Ahri'])
        self.assertEqual(self.result()['evidence'][0]['games'], 3)

    def test_each_present_participant_uses_their_own_champion_and_result(self):
        self.add_games('Ahri', [True, True, False])
        for match in self.db['duos'][0]['history']:
            match['result'] = 'LOSS'
            match['player2Stats'] = {'puuid':'other', 'championName':'Lux', 'win':True}
        self.assertEqual(self.result()['optionIds'], ['Lux'])

    def test_no_eligible_champion_voids_category_but_zero_winrate_is_valid(self):
        self.assertEqual(self.result()['status'], 'NO_DATA')
        self.add_games('Ahri', [False, False])
        self.assertEqual(self.result()['optionIds'], [])
        self.add_games('Ahri', [False])
        self.assertEqual(self.result()['status'], 'SETTLED')
        self.assertEqual(self.result()['value'], 0)

    def test_incomplete_stats_or_imports_leave_result_pending(self):
        self.add_games('Ahri', [True, True, True])
        original = copy.deepcopy(self.db['duos'][0]['history'][0])
        for changes in [
            {'statsVersion':1}, {'participantsChecked':{'player1':True}},
            {'player1Stats':{'championName':'Ahri', 'win':'true'}},
            {'player1Stats':{'championName':'Unknown', 'win':True}}
        ]:
            with self.subTest(changes=changes):
                self.db['duos'][0]['history'][0] = {**original, **changes}
                self.assertTrue(self.result()['pending'])
        self.db['duos'][0]['history'][0] = original
        self.db['duos'][1]['riotMatchDiscovery'] = {'pendingMatchIds':['missing']}
        self.assertTrue(self.result()['pending'])

    def test_new_category_preserves_ballots_and_only_enriches_open_weeks(self):
        pickem.submit(self.db, 'a', 'one', CATEGORY, '0-19', now=NOW)
        self.board['categories'].remove(self.category)
        pickem.ensure_week(self.db, NOW)
        self.assertEqual(self.board['ballots'][0]['answers'], {CATEGORY:'0-19'})
        self.assertIn(self.category['id'], [c['id'] for c in self.board['categories']])
        self.board['categories'] = [c for c in self.board['categories'] if c['id']!=self.category['id']]
        pickem.ensure_week(self.db, pickem.period(self.db,WEEK)['closesAt'])
        self.assertNotIn(self.category['id'], [c['id'] for c in self.board['categories']])

    def test_settlement_records_winners_and_category_contributes_to_ballot_reward(self):
        pickem.submit(self.db, 'a', 'one', self.category['id'], 'Ahri', now=NOW)
        ballot = self.board['ballots'][0]
        for category_id in (CATEGORY, 'weekly_leader'):
            ballot['answers'][category_id] = 'correct'
            self.board['results'][category_id] = {'status':'SETTLED', 'optionIds':['correct']}
        self.add_games('Ahri', [True, True, True])
        at = pickem.period(self.db,WEEK)['endsAt'] + pickem.SETTLEMENT_GRACE
        pickem.record_complete_sync(self.db, copy.deepcopy(self.db), at, now=at+60)
        result = self.board['results'][self.category['id']]
        self.assertEqual(result['optionIds'], ['Ahri'])
        self.assertEqual(result['optionLabel'], 'Ahri')
        self.assertEqual(pickem.ballot_score(self.board,ballot)['correct'], 3)
        self.assertEqual(self.db['duos'][0]['blueShells'], 6)
        pickem.maintain(self.db, at+120)
        self.assertEqual(self.db['duos'][0]['blueShells'], 6, 'the category must not cause duplicate prizes')


if __name__ == '__main__': unittest.main()
