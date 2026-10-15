"""Weekly accumulated KDA category; isolated fixtures, no real Riot calls or votes."""
import copy
import json
import unittest

import pickem_service as pickem
import test_pickem as fixtures


class WeeklyPlayerKdaTests(unittest.TestCase):
    setUp = fixtures.PickemServiceTests.setUp
    settle = fixtures.PickemServiceTests.settle
    add_game = fixtures.PickemServiceTests.add_kda_game
    category_id = 'weekly_player_kda'

    def category(self):
        return next(c for c in self.board['categories'] if c['id'] == self.category_id)

    def player(self, key='player1'):
        return next(o for o in self.category()['options'] if o['teamId'] == 'a' and o['playerKey'] == key and not o.get('disabled'))

    def result(self):
        return pickem.category_result(self.db, self.board, self.category())

    def test_all_integrants_available_every_week_without_resetting_ballots(self):
        for i in range(7):
            self.db['duos'].append({'id':f'extra{i}', 'teamName':f'Extra {i}',
                'player1':{'name':f'P{i}'}, 'player2':{'name':f'Q{i}'}})
        old, _ = pickem.submit(self.db, 'a', 'one', 'unique_champions', '0-19', now=fixtures.NOW)
        self.board['categories'] = [c for c in self.board['categories'] if c['id'] != self.category_id]
        pickem.ensure_week(self.db, fixtures.NOW)
        self.assertEqual(len(self.category()['options']), 18)
        pickem.submit(self.db, 'a', 'one', self.category_id, self.player()['id'], now=fixtures.NOW)
        self.assertEqual(len(self.board['ballots']), 1)
        self.assertEqual(old['answers']['unique_champions'], '0-19')
        later, _ = pickem.ensure_week(self.db, fixtures.NOW + 7*86400)
        self.assertIn(self.category_id, [c['id'] for c in self.db['pickem']['weeks'][later]['categories']])
        # Adding a category must never rewrite an archived week's options/results.
        self.board['categories'] = [c for c in self.board['categories'] if c['id'] != self.category_id]
        pickem.ensure_week(self.db, pickem.period(self.db, fixtures.WEEK)['closesAt'])
        self.assertNotIn(self.category_id, [c['id'] for c in self.board['categories']])

    def test_accumulated_ratio_is_not_best_match_average_or_combined_team_score(self):
        self.add_game('one', (20,1,0), (4,2,4))
        self.add_game('two', (0,19,0), (4,2,4))
        # P1 best game: 20; mean KDA: 10; accumulated: 1. P2 accumulated: 4.
        result = self.result()
        self.assertEqual(result['optionIds'], [self.player('player2')['id']])
        self.assertEqual(result['value'], 4)
        self.assertEqual(result['evidence'][0]['kills'], 8)
        self.assertEqual(result['evidence'][0]['deaths'], 4)
        self.assertEqual(result['evidence'][0]['assists'], 8)
        self.assertEqual(result['evidence'][0]['games'], 2)
        self.assertEqual(result['evidence'][0]['matchIds'], ['one','two'])

    def test_exact_ties_zero_deaths_and_no_games(self):
        self.assertEqual(self.result()['status'], 'NO_GAMES')
        self.add_game('one', (0,0,5), (10,2,0))
        result = self.result()
        self.assertEqual(result['value'], 5)
        self.assertEqual(len(result['optionIds']), 2)
        self.add_game('two', (0,0,0), (1,3,0))
        self.assertEqual(self.result()['optionIds'], [self.player()['id']])

    def test_compares_exact_ratios_instead_of_rounded_values(self):
        self.add_game('one', (1,3,0), (334,1000,0))
        self.assertEqual(self.result()['optionIds'], [self.player('player2')['id']])

    def test_deduplicates_and_filters_test_queue_and_week_tournament_boundaries(self):
        valid = self.add_game('valid', (1,1,1), (0,2,0))
        duo = self.db['duos'][0]
        duo['history'] += [copy.deepcopy(valid),
            {**copy.deepcopy(valid), 'matchId':'test', 'isTest':True},
            {**copy.deepcopy(valid), 'matchId':'aram', 'queueId':450}]
        for mid, at in [('before',pickem.period(self.db,fixtures.WEEK)['startsAt']-1),
                        ('after',pickem.period(self.db,fixtures.WEEK)['endsAt'])]:
            self.add_game(mid, (999,0,999), (999,0,999), at=at)
        result = self.result()
        self.assertEqual(result['value'], 2)
        self.assertEqual(result['evidence'][0]['games'], 1)
        self.assertEqual(result['evidence'][0]['matchIds'], ['valid'])

    def test_missing_imports_checks_and_invalid_stats_delay_resolution(self):
        match = self.add_game('one', (1,1,1), (1,2,0))
        for field, value in [('kills',None), ('deaths',-1), ('assists',True)]:
            with self.subTest(field=field):
                before = match['player2Stats'][field]
                match['player2Stats'][field] = value
                self.assertTrue(self.result()['pending'])
                match['player2Stats'][field] = before
        match['participantsChecked']['player2'] = False
        self.assertTrue(self.result()['pending'])
        match['participantsChecked']['player2'] = True
        match['statsVersion'] = 1
        self.assertTrue(self.result()['pending'])
        match['statsVersion'] = 2
        self.db['duos'][1]['riotMatchDiscovery'] = {'pendingMatchIds':['missing']}
        self.assertTrue(self.result()['pending'])
        del self.db['duos'][1]['riotMatchDiscovery']
        match['player2Stats'] = None
        self.assertEqual(self.result()['status'], 'SETTLED', 'a confirmed absence is not missing stats')

    def test_account_replacement_preserves_original_performance_and_privacy(self):
        self.add_game('old', (10,1,0), (0,5,0))
        original = self.player()
        self.db['duos'][0]['player1'].update(name='Replacement', puuid='new')
        pickem.ensure_week(self.db, fixtures.NOW)
        self.assertEqual(self.result()['optionIds'], [original['id']])
        self.assertTrue(next(o for o in self.category()['options'] if o['id']==original['id'])['disabled'])
        public = pickem.public_board(self.db, now=fixtures.NOW)
        category = next(c for c in public['categories'] if c['id']==self.category_id)
        self.assertTrue(all(not {'account','puuid','playerKey'} & o.keys() for o in category['options']))

    def test_independent_choices_contribute_to_normal_three_correct_reward_once(self):
        self.add_game('one', (5,1,5), (0,5,0))
        for duo in self.db['duos']:
            duo.update(tier='Gold',division='IV',lp=50,wins=5,losses=5,rankObservedAt=fixtures.NOW)
        for category, answer in [('unique_champions','0-19'), ('weekly_leader','a'),
                                 (self.category_id,self.player()['id'])]:
            pickem.submit(self.db, 'a', 'one', category, answer, now=fixtures.NOW)
        pickem.submit(self.db, 'a', 'two', self.category_id, self.player('player2')['id'], now=fixtures.NOW)
        self.settle()
        result = self.board['results'][self.category_id]
        self.assertEqual(result['value'], 10)
        self.assertEqual(result['optionIds'], [self.player()['id']])
        self.assertEqual(self.db['duos'][0]['blueShells'], 6)
        self.assertEqual(len(self.db['events']), 1)
        restored = json.loads(json.dumps(self.db))
        self.settle(restored)
        self.assertEqual(restored['duos'][0]['blueShells'], 6)


if __name__ == '__main__': unittest.main()
