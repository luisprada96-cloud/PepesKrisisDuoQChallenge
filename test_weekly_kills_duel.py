"""Chicha versus Fogell: individual weekly kills and shared team predictions."""
import copy
import unittest

import pickem_service as pickem
from test_pickem import database, game, NOW, WEEK


class WeeklyKillsDuelTests(unittest.TestCase):
    category_id = 'chicha_fogell_kills'

    def setUp(self):
        self.db = database()
        self.db['duos'][0]['player2'].update(displayName='Chicha', puuid='chicha-account')
        self.db['duos'][1]['player1'].update(displayName='Fogell', puuid='fogell-account')
        pickem.ensure_week(self.db, NOW)
        self.board = self.db['pickem']['weeks'][WEEK]

    def category(self):
        return next(c for c in self.board['categories'] if c['id']==self.category_id)

    def add_game(self, name='chicha', kills=5, mid='one', at=NOW, **extra):
        team, key = (0, 'player2') if name=='chicha' else (1, 'player1')
        duo = self.db['duos'][team]
        match = game(mid, at=at)
        match[key+'Stats'].update(puuid=duo[key]['puuid'], kills=kills, deaths=100-kills,
                                 riotIdGameName=duo[key]['name'], riotIdTagline='EUW')
        match.update(extra)
        duo['history'].append(match)
        return match

    def result(self):
        return pickem.category_result(self.db, self.board, self.category())

    def test_two_bound_names_every_week_and_private_account_details(self):
        category = self.category()
        self.assertEqual([(o['id'], o['label'], o['playerKey']) for o in category['options']],
                         [('chicha','Chicha','player2'), ('fogell','Fogell','player1')])
        public = next(c for c in pickem.public_board(self.db,now=NOW)['categories'] if c['id']==self.category_id)
        self.assertEqual(public['options'], [{'id':'chicha','label':'Chicha'}, {'id':'fogell','label':'Fogell'}])
        self.assertEqual(public['kind'], 'duel')
        next_week, _ = pickem.ensure_week(self.db, NOW+7*86400)
        self.assertIn(self.category_id, [c['id'] for c in self.db['pickem']['weeks'][next_week]['categories']])

    def test_sum_individual_kills_not_team_totals_deaths_or_best_game(self):
        first = self.add_game(kills=6)
        first['player1Stats']['kills'] = 100
        self.add_game(kills=7, mid='two')
        self.add_game('fogell', kills=10)
        result = self.result()
        self.assertEqual(result['optionIds'], ['chicha'])
        self.assertEqual([(t['kills'],t['games']) for t in result['totals']], [(13,2),(10,1)])
        self.assertEqual(result['summary'], 'Chicha: 13 kills · Fogell: 10 kills')
        self.assertEqual(len(result['evidence']), 3)
        self.add_game('fogell', kills=5, mid='three')
        self.assertEqual(self.result()['optionIds'], ['fogell'])

    def test_ties_accept_both_and_no_games_does_not_invent_a_tie(self):
        self.assertEqual(self.result()['status'], 'NO_GAMES')
        self.assertEqual(self.result()['optionIds'], [])
        for kills in (0, 8):
            with self.subTest(kills=kills):
                self.setUp()
                self.add_game(kills=kills)
                self.add_game('fogell', kills=kills)
                self.assertEqual(self.result()['optionIds'], ['chicha','fogell'])

    def test_weekly_boundaries_test_games_other_queues_and_duplicates_are_excluded(self):
        end = pickem.period(self.db,WEEK)['endsAt']
        self.add_game(kills=50, mid='before', at=NOW-86400)
        self.add_game(kills=50, mid='after', at=end)
        self.add_game(kills=50, mid='test', isTest=True)
        self.add_game(kills=50, mid='aram', queueId=450)
        valid = self.add_game(kills=2, mid='valid', at=end-.001)
        self.db['duos'][0]['history'].append(copy.deepcopy(valid))
        self.add_game('fogell', kills=3)
        self.assertEqual(self.result()['optionIds'], ['fogell'])
        self.assertEqual(self.result()['totals'][0]['kills'], 2)

    def test_missing_or_invalid_stats_and_pending_discovery_wait(self):
        match = self.add_game()
        for value in (None, -1, True, '5'):
            with self.subTest(value=value):
                match['player2Stats']['kills'] = value
                self.assertTrue(self.result()['pending'])
        match['player2Stats']['kills'] = 5
        match['participantsChecked']['player2'] = False
        self.assertTrue(self.result()['pending'])
        match['participantsChecked']['player2'] = True
        match['statsVersion'] = 1
        self.assertTrue(self.result()['pending'])
        match['statsVersion'] = 2
        self.db['duos'][1]['riotMatchDiscovery'] = {'pendingMatchIds':['missing']}
        self.assertTrue(self.result()['pending'])

    def test_confirmed_absence_does_not_count_as_a_played_game(self):
        self.add_game()['player2Stats'] = None
        self.add_game('fogell', kills=3)
        self.assertEqual(self.result()['totals'][0]['games'], 0)
        self.assertEqual(self.result()['optionIds'], ['fogell'])

    def test_account_replacements_do_not_transfer_saved_predictions(self):
        self.add_game(kills=7)
        old = copy.deepcopy(self.category()['options'][0])
        self.db['duos'][0]['player2'].update(name='Replacement', puuid='other-account', displayName='Otro')
        self.db['duos'][0]['player1']['displayName'] = 'Chicha'
        pickem.ensure_week(self.db, NOW)
        self.assertEqual(self.category()['options'][0], old)
        self.add_game(kills=50, mid='replacement')
        self.add_game('fogell', kills=3)
        self.assertEqual(self.result()['totals'][0]['kills'], 7)

    def test_missing_or_ambiguous_contenders_are_disabled_without_guessing(self):
        self.db['duos'][0]['player2']['displayName'] = 'Otro'
        self.board['categories'] = pickem.category_definitions(self.db,WEEK)
        self.assertTrue(self.category()['options'][0]['disabled'])
        self.assertEqual(self.result()['status'], 'NO_DATA')
        with self.assertRaises(ValueError):
            pickem.submit(self.db,'a','one',self.category_id,'chicha',now=NOW)
        self.db['duos'][0]['player1']['displayName'] = 'Chicha'
        self.db['duos'][0]['player2']['displayName'] = 'Chicha'
        self.board['categories'] = pickem.category_definitions(self.db,WEEK)
        self.assertTrue(self.category()['options'][0]['disabled'])

    def test_team_choice_shared_between_ballots_and_independent_of_other_duels(self):
        pickem.submit(self.db,'a','one',self.category_id,'chicha',now=NOW)
        with self.assertRaises(FileExistsError):
            pickem.submit(self.db,'a','two',self.category_id,'fogell',now=NOW)
        pickem.submit(self.db,'a','two',self.category_id,'chicha',now=NOW)
        pickem.submit(self.db,'a','one','joji_parradise_deaths','parradise',now=NOW)
        own = next(c for c in pickem.public_board(self.db,'a','two',now=NOW)['categories'] if c['id']==self.category_id)
        self.assertEqual(own['teamAnswer'], 'chicha')
        self.assertEqual(len(self.board['ballots']), 2)
        guest = next(c for c in pickem.public_board(self.db,now=NOW)['categories'] if c['id']==self.category_id)
        self.assertIsNone(guest['teamAnswer'])

    def test_settlement_is_frozen_and_contributes_to_one_ballot_reward(self):
        pickem.submit(self.db,'a','one',self.category_id,'chicha',now=NOW)
        ballot = self.board['ballots'][0]
        for category_id in ('unique_champions','weekly_leader'):
            ballot['answers'][category_id] = 'correct'
            self.board['results'][category_id] = {'status':'SETTLED','optionIds':['correct']}
        self.add_game(kills=10)
        self.add_game('fogell', kills=5)
        at = pickem.period(self.db,WEEK)['endsAt'] + pickem.SETTLEMENT_GRACE
        pickem.record_complete_sync(self.db,copy.deepcopy(self.db),at,now=at+60)
        saved = copy.deepcopy(self.board['results'][self.category_id])
        self.assertEqual(saved['optionIds'], ['chicha'])
        self.assertEqual(pickem.ballot_score(self.board,ballot)['correct'], 3)
        self.assertEqual(self.db['duos'][0]['blueShells'], 6)
        self.add_game('fogell',kills=50,mid='later',at=at+60)
        pickem.record_complete_sync(self.db,copy.deepcopy(self.db),at+120,now=at+180)
        self.assertEqual(self.board['results'][self.category_id], saved)
        self.assertEqual(self.db['duos'][0]['blueShells'], 6)


if __name__ == '__main__': unittest.main()
