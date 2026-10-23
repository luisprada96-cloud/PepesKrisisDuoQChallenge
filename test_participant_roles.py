"""Main positions are derived from registered tournament appearances, never edits."""
import copy
import unittest

import participant_roles as roles
import riot_match_policy
import server
import test_shell_penalties as fixtures
from trophies import build_trophies

BASE = riot_match_policy.MIN_START_TIMESTAMP * 1000 + 7200000


def game(index, first='TOP', second='JUNGLE', uid='p1', **extra):
    return {'matchId':f'role-{index}', 'gameStartTimestamp':BASE+index*1000-1200000,
            'gameEndTimestamp':BASE+index*1000,'durationSeconds':1200,'queueId':420,
            'player1Stats':{'puuid':uid,'position':first,'kills':4,'deaths':2,'assists':6},
            'player2Stats':{'puuid':'p2','position':second,'kills':2,'deaths':1,'assists':8},**extra}


def team():
    return {'id':'a','teamName':'A','player1':{'name':'One','puuid':'p1','mainRole':'UTILITY'},
            'player2':{'name':'Two','puuid':'p2','mainRole':'BOTTOM'},'history':[]}


class ParticipantRoleTests(unittest.TestCase):
    def test_most_played_position_across_accounts_is_independent_of_elo_selection(self):
        duo=team()
        duo['player1'].update(accounts=[{'id':'main','name':'One','puuid':'p1'},{'id':'alt','name':'Alt','puuid':'alt'}],eloAccountId='main')
        duo['history']=[game(0),game(1),game(2,'JUNGLE',uid='alt'),game(3,'JUNGLE',uid='alt'),game(4,'JUNGLE',uid='alt')]
        self.assertTrue(roles.update_roles(duo))
        self.assertEqual(duo['player1']['mainRole'],'JUNGLE')
        self.assertEqual(duo['player1']['mainRoleCounts'],{'TOP':2,'JUNGLE':3})
        duo['player1']['eloAccountId']='alt'
        self.assertFalse(roles.update_roles(duo))
        self.assertEqual(duo['player1']['mainRoleGames'],3)

    def test_ties_follow_most_recent_tied_position_and_are_order_independent(self):
        duo=team();duo['history']=[game(1),game(2,'MIDDLE'),game(3),game(4,'MIDDLE')]
        self.assertEqual(roles.role_summary(duo,'player1')['position'],'MIDDLE')
        duo['history'].reverse()
        self.assertEqual(roles.role_summary(duo,'player1')['position'],'MIDDLE')
        self.assertEqual(roles.role_summary(duo,'player1',BASE+3000)['position'],'MIDDLE')

    def test_only_valid_unique_registered_solo_positions_contribute(self):
        duo=team();valid=game(1)
        duo['history']=[valid,copy.deepcopy(valid),game(2,'UNKNOWN'),game(3,'MIDDLE',isTest=True),
            game(4,'MIDDLE',durationSeconds=599),game(5,'MIDDLE',queueId=440),game(6,'MIDDLE',uid='outsider'),
            game(7,'MIDDLE',gameStartTimestamp=riot_match_policy.MIN_START_TIMESTAMP*1000-1),game(8,'MIDDLE')]
        duo['excludedRiotMatches']={'role-8':{'reason':'excluded'}}
        missing=game(9,'MIDDLE');missing.pop('gameStartTimestamp');missing.pop('gameEndTimestamp');duo['history'].append(missing)
        self.assertEqual(roles.role_summary(duo,'player1'),{'position':'TOP','games':1,'totalGames':1,'counts':{'TOP':1}})
        duo['history'].append(game(10,'TOP',durationSeconds=600))
        self.assertEqual(roles.role_summary(duo,'player1')['games'],2)

    def test_no_position_never_uses_a_legacy_manual_role(self):
        duo=team();roles.update_roles(duo)
        self.assertIsNone(duo['player1']['mainRole'])
        self.assertEqual(duo['player1']['mainRoleSource'],'most_played')
        duo['history']=[game(1,'UNKNOWN','UNKNOWN')]
        self.assertIsNone(roles.role_summary(duo,'player2')['position'])

    def test_confirmed_puuid_keeps_the_persons_games_after_a_riot_name_change(self):
        duo=team();duo['history']=[game(1)]
        duo['history'][0]['player1Stats'].update(riotIdGameName='AnOldRiotName',riotIdTagline='OLD')
        self.assertEqual(roles.role_summary(duo,'player1')['position'],'TOP')

    def test_insights_and_trophy_follow_the_same_main_role(self):
        duo=team();duo['history']=[game(1,'MIDDLE'),game(2,'MIDDLE'),game(3)]
        insight=server.calculate_player_insights(duo)
        self.assertEqual(insight['player1']['mostPlayedPosition'],{'position':'MIDDLE','games':2})
        cards=build_trophies([duo],None)['cards']
        self.assertEqual(next(c for c in cards if c['id']=='MIDDLE')['entries'][0]['games'],2)
        self.assertEqual(next(c for c in cards if c['id']=='TOP')['entries'],[])

    def test_polivalente_freezes_derived_reference_even_after_the_main_role_changes(self):
        duo=team();duo['history']=[game(1),game(2)]
        penalty=next(p for p in server.PENALTY_CATALOG if p['id']=='autofill_both')
        req=server.penalty_requirements(duo,penalty,[duo])
        self.assertEqual(req['mainRoles'],{'player1':'TOP','player2':'JUNGLE'})
        duo['activeDebuffs']=[fixtures.penalty('autofill','BOTH',req)]
        duo['history'] += [game(i,'MIDDLE','BOTTOM') for i in range(3,7)]
        roles.update_roles(duo);server.fill_pending_penalty_roles(duo)
        self.assertEqual(duo['player1']['mainRole'],'MIDDLE')
        self.assertEqual(req['mainRoles']['player1'],'TOP')
        self.assertEqual(server.evaluate_active_penalties(duo,game(7,req['randomPositions']['player1'],req['randomPositions']['player2'])),1)

    def test_pending_automatic_roles_fill_once_without_rewriting_legacy_penalties(self):
        duo=team()
        req=server.penalty_requirements(duo,{'baseId':'autofill','scope':'BOTH'},[duo])
        self.assertIsNone(req['mainRoles']['player1'])
        legacy={'mainRoles':{'player1':'UTILITY','player2':'BOTTOM'}}
        duo['activeDebuffs']=[fixtures.penalty('autofill','BOTH',req),fixtures.penalty('autofill','BOTH',legacy)]
        duo['history']=[game(1)]
        self.assertEqual(len(server.fill_pending_penalty_roles(duo)),1)
        self.assertEqual(req['mainRoles'],{'player1':'TOP','player2':'JUNGLE'})
        self.assertEqual(legacy['mainRoles']['player1'],'UTILITY')
        self.assertEqual(server.fill_pending_penalty_roles(duo),[])


class ParticipantRoleEndpointTests(unittest.TestCase):
    setUp=fixtures.ShellEndpointTests.setUp
    tearDown=fixtures.ShellEndpointTests.tearDown
    post=fixtures.ShellEndpointTests.post

    def test_admin_cannot_override_a_computed_role(self):
        db=server.load_db();db['duos'][0]['history']=[game(1,'MIDDLE'),game(2,'MIDDLE')]
        db['duos'][0]['player1']['puuid']='p1';db['duos'][0]['player2']['puuid']='p2'
        server.save_db(db)
        response=self.post('/api/duos',{'authPin':'9999','duo':{'id':'a','player1':{'mainRole':'UTILITY','mainRoleGames':999}}})
        self.assertEqual(response['duo']['player1']['mainRole'],'MIDDLE')
        self.assertEqual(response['duo']['player1']['mainRoleGames'],2)
        self.assertEqual(server.public_duo_summaries()[0]['playerInsights']['player1']['mostPlayedPosition']['position'],'MIDDLE')

    def test_creation_needs_no_manual_roles_and_waits_for_evidence(self):
        response=self.post('/api/duos',{'authPin':'9999','duo':{'id':'fresh','teamName':'Nuevo',
            'player1':{'name':'NewOne','tag':'EUW'},'player2':{'name':'NewTwo','tag':'EUW'}}})
        self.assertTrue(response['success'])
        self.assertIsNone(response['duo']['player1']['mainRole'])
        self.assertEqual(response['duo']['player1']['mainRoleSource'],'most_played')

    def test_replacing_a_legacy_identity_cannot_reuse_the_previous_persons_role(self):
        db=server.load_db();db['duos'][0]['history']=[game(1,'MIDDLE')]
        db['duos'][0]['player1']['puuid']='p1';server.save_db(db)
        self.assertEqual(server.load_db()['duos'][0]['player1']['mainRole'],'MIDDLE')
        response=self.post('/api/duos',{'authPin':'9999','duo':{'id':'a','player1':{'name':'DifferentPerson'}}})
        self.assertIsNone(response['duo']['player1']['mainRole'])


if __name__ == '__main__':unittest.main()
