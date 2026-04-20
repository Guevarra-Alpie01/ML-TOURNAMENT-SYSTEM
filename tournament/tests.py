from django.test import TestCase
from django.urls import reverse

from teams.models import Team

from .models import BracketType, Match, MatchFormat, MatchStage, Tournament, TournamentFormat
from .tournament_generator import advance_match, generate_tournament_matches, sync_tournament_matches


class TournamentBracketTests(TestCase):
    def create_teams(self, count):
        base = Team.objects.count()
        return [Team.objects.create(name=f"Team {base + index:03d}") for index in range(1, count + 1)]

    def create_tournament(self, name, team_count, format_type=TournamentFormat.DOUBLE_ELIMINATION):
        tournament = Tournament.objects.create(name=name, format=format_type)
        tournament.teams.set(self.create_teams(team_count))
        return tournament

    def assert_no_duplicate_active_assignments(self, tournament):
        active_matches = tournament.matches.filter(
            status__in=[Match.MatchStatus.READY, Match.MatchStatus.IN_PROGRESS]
        ).select_related('team_a', 'team_b')
        active_team_ids = []
        for match in active_matches:
            if match.team_a_id:
                active_team_ids.append(match.team_a_id)
            if match.team_b_id:
                active_team_ids.append(match.team_b_id)
        self.assertEqual(len(active_team_ids), len(set(active_team_ids)))

    def winning_score(self, match):
        return match.get_required_wins()

    def test_status_rules_follow_required_transitions(self):
        tournament = Tournament.objects.create(name="Status Rules", format=TournamentFormat.SINGLE_ELIMINATION)
        team_a, team_b = self.create_teams(2)
        tournament.teams.set([team_a, team_b])

        match = Match.objects.create(
            tournament=tournament,
            round_number=1,
            game_number=1,
            stage=MatchStage.FINAL,
            match_format=MatchFormat.BO3,
            bracket_type=BracketType.WINNERS,
            team_a=team_a,
            team_b=team_b,
        )

        sync_tournament_matches(tournament)
        match.refresh_from_db()
        self.assertEqual(match.status, Match.MatchStatus.READY)

        match.team_a_score = 1
        match.save(update_fields=['team_a_score'])
        sync_tournament_matches(tournament)
        match.refresh_from_db()
        self.assertEqual(match.status, Match.MatchStatus.IN_PROGRESS)

        match.team_b_score = 0
        match.save(update_fields=['team_b_score'])
        sync_tournament_matches(tournament)
        match.refresh_from_db()
        self.assertEqual(match.status, Match.MatchStatus.IN_PROGRESS)

        match.winner = team_a
        match.save(update_fields=['winner'])
        sync_tournament_matches(tournament)
        match.refresh_from_db()
        self.assertEqual(match.status, Match.MatchStatus.COMPLETED)

    def test_double_elimination_seeded_byes_and_winners_round_sizes(self):
        expected_layouts = {
            4: {'bye_matches': 0, 'winner_rounds': {1: 2, 2: 1}},
            5: {'bye_matches': 3, 'winner_rounds': {1: 1, 2: 2, 3: 1}},
            6: {'bye_matches': 2, 'winner_rounds': {1: 2, 2: 2, 3: 1}},
            7: {'bye_matches': 1, 'winner_rounds': {1: 3, 2: 2, 3: 1}},
            8: {'bye_matches': 0, 'winner_rounds': {1: 4, 2: 2, 3: 1}},
            10: {'bye_matches': 6, 'winner_rounds': {1: 2, 2: 4, 3: 2, 4: 1}},
            16: {'bye_matches': 0, 'winner_rounds': {1: 8, 2: 4, 3: 2, 4: 1}},
        }

        for team_count, expected in expected_layouts.items():
            with self.subTest(team_count=team_count):
                tournament = self.create_tournament(f"Bracket {team_count}", team_count)
                generate_tournament_matches(tournament.id)

                bye_matches = tournament.matches.filter(
                    bracket_type=BracketType.WINNERS,
                    round_number=0,
                    status=Match.MatchStatus.BYE,
                )
                self.assertEqual(bye_matches.count(), expected['bye_matches'])

                for round_number, match_count in expected['winner_rounds'].items():
                    self.assertEqual(
                        tournament.matches.filter(
                            bracket_type=BracketType.WINNERS,
                            round_number=round_number,
                        ).count(),
                        match_count,
                    )

                self.assert_no_duplicate_active_assignments(tournament)

    def test_ten_team_play_in_losers_feed_into_single_lower_round_one_match(self):
        tournament = self.create_tournament("Ten Team Example", 10)
        generate_tournament_matches(tournament.id)

        winners_round_one = list(
            tournament.matches.filter(bracket_type=BracketType.WINNERS, round_number=1).order_by('game_number')
        )
        self.assertEqual(len(winners_round_one), 2)
        self.assertTrue(all(match.status == Match.MatchStatus.READY for match in winners_round_one))

        for match in winners_round_one:
            result = advance_match(match.id, match.team_a_id, self.winning_score(match), 0)
            self.assertNotIn('error', result)

        lower_round_one = list(
            tournament.matches.filter(bracket_type=BracketType.LOSERS, round_number=1).order_by('game_number')
        )
        self.assertEqual(len(lower_round_one), 1)

        lower_match = lower_round_one[0]
        lower_match.refresh_from_db()
        losers = {winners_round_one[0].team_b_id, winners_round_one[1].team_b_id}
        self.assertEqual(lower_match.status, Match.MatchStatus.READY)
        self.assertEqual({lower_match.team_a_id, lower_match.team_b_id}, losers)

        winners_round_two = tournament.matches.filter(
            bracket_type=BracketType.WINNERS,
            round_number=2,
            status=Match.MatchStatus.READY,
        )
        self.assertEqual(winners_round_two.count(), 4)
        self.assert_no_duplicate_active_assignments(tournament)

    def test_single_play_in_loser_gets_bye_without_generating_fake_loser(self):
        tournament = self.create_tournament("Five Team Example", 5)
        generate_tournament_matches(tournament.id)

        lower_round_one = tournament.matches.get(bracket_type=BracketType.LOSERS, round_number=1)
        winners_round_one = tournament.matches.get(bracket_type=BracketType.WINNERS, round_number=1)

        self.assertEqual(lower_round_one.status, Match.MatchStatus.WAITING)
        result = advance_match(
            winners_round_one.id,
            winners_round_one.team_a_id,
            self.winning_score(winners_round_one),
            0,
        )
        self.assertNotIn('error', result)

        lower_round_one.refresh_from_db()
        self.assertEqual(lower_round_one.status, Match.MatchStatus.BYE)
        self.assertEqual(lower_round_one.bye_team_id, winners_round_one.team_b_id)
        self.assertIsNone(lower_round_one.team_b_id)

    def test_match_result_validation_rejects_incomplete_or_invalid_results(self):
        tournament = self.create_tournament("Validation", 4)
        generate_tournament_matches(tournament.id)
        match = tournament.matches.filter(bracket_type=BracketType.WINNERS, round_number=1).first()

        missing_score = advance_match(match.id, match.team_a_id, self.winning_score(match), None)
        self.assertEqual(missing_score['error'], 'Both teams must have recorded scores')

        wrong_winner = advance_match(match.id, match.team_a_id, 0, self.winning_score(match))
        self.assertEqual(wrong_winner['error'], 'Selected winner does not match the submitted scoreline')

        tied_score = advance_match(
            match.id,
            match.team_a_id,
            self.winning_score(match),
            self.winning_score(match),
        )
        self.assertEqual(tied_score['error'], 'Tied scores are not valid for elimination matches')

    def test_two_team_double_elimination_activates_grand_final_reset(self):
        tournament = self.create_tournament("Two Team DE", 2)
        generate_tournament_matches(tournament.id)

        winners_final = tournament.matches.get(bracket_type=BracketType.WINNERS)
        losers_final = tournament.matches.get(bracket_type=BracketType.LOSERS)
        grand_final = tournament.matches.get(bracket_type=BracketType.GRAND)
        grand_reset = tournament.matches.get(bracket_type=BracketType.GRAND_RESET)

        self.assertEqual(winners_final.status, Match.MatchStatus.READY)
        self.assertEqual(losers_final.status, Match.MatchStatus.WAITING)
        self.assertEqual(grand_final.status, Match.MatchStatus.WAITING)
        self.assertEqual(grand_reset.status, Match.MatchStatus.WAITING)

        result = advance_match(winners_final.id, winners_final.team_a.id, 3, 0)
        self.assertNotIn('error', result)

        losers_final.refresh_from_db()
        grand_final.refresh_from_db()
        grand_reset.refresh_from_db()
        tournament.refresh_from_db()

        self.assertEqual(losers_final.status, Match.MatchStatus.BYE)
        self.assertEqual(losers_final.bye_team, winners_final.team_b)
        self.assertEqual(grand_final.status, Match.MatchStatus.READY)
        self.assertEqual(grand_reset.status, Match.MatchStatus.WAITING)

        result = advance_match(grand_final.id, grand_final.team_b.id, 2, 3)
        self.assertNotIn('error', result)

        grand_final.refresh_from_db()
        grand_reset.refresh_from_db()
        tournament.refresh_from_db()

        self.assertEqual(grand_final.status, Match.MatchStatus.COMPLETED)
        self.assertEqual(grand_final.winner, grand_final.team_b)
        self.assertEqual(grand_reset.status, Match.MatchStatus.READY)
        self.assertFalse(tournament.is_complete())

        result = advance_match(grand_reset.id, grand_reset.team_a.id, 3, 1)
        self.assertNotIn('error', result)

        grand_reset.refresh_from_db()
        tournament.refresh_from_db()
        self.assertEqual(grand_reset.status, Match.MatchStatus.COMPLETED)
        self.assertTrue(tournament.is_complete())
        self.assertEqual(tournament.get_champion(), grand_reset.winner)

    def test_detail_and_bracket_views_render_for_double_elimination(self):
        tournament = self.create_tournament("Render Check", 10)
        generate_tournament_matches(tournament.id)

        detail_response = self.client.get(reverse('tournament:detail', args=[tournament.id]))
        bracket_response = self.client.get(reverse('tournament:bracket', args=[tournament.id]))

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(bracket_response.status_code, 200)
        self.assertContains(bracket_response, "Winners Bracket")
        self.assertContains(bracket_response, "Losers Bracket")
        self.assertContains(bracket_response, "Grand Finals")
