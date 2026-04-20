from django.test import TestCase
from django.urls import reverse

from teams.models import Team

from .models import BracketType, Match, MatchFormat, MatchStage, Tournament, TournamentFormat
from .tournament_generator import advance_match, generate_tournament_matches, sync_tournament_matches


class TournamentBracketTests(TestCase):
    def create_teams(self, count):
        return [Team.objects.create(name=f"Team {index:02d}") for index in range(1, count + 1)]

    def create_tournament(self, name, team_count, format_type=TournamentFormat.DOUBLE_ELIMINATION):
        tournament = Tournament.objects.create(name=name, format=format_type)
        tournament.teams.set(self.create_teams(team_count))
        return tournament

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

    def test_double_elimination_assigns_byes_for_five_teams(self):
        tournament = self.create_tournament("Five Team DE", 5)

        generate_tournament_matches(tournament.id)

        winners_round_one = list(
            tournament.matches.filter(bracket_type=BracketType.WINNERS, round_number=1).order_by('game_number')
        )
        self.assertEqual(len(winners_round_one), 4)
        self.assertEqual(sum(1 for match in winners_round_one if match.status == Match.MatchStatus.BYE), 3)
        self.assertEqual(sum(1 for match in winners_round_one if match.status == Match.MatchStatus.READY), 1)

        losers_round_one = list(
            tournament.matches.filter(bracket_type=BracketType.LOSERS, round_number=1).order_by('game_number')
        )
        self.assertTrue(any(match.status == Match.MatchStatus.BYE for match in losers_round_one))

        grand_final = tournament.matches.get(bracket_type=BracketType.GRAND)
        grand_reset = tournament.matches.get(bracket_type=BracketType.GRAND_RESET)
        self.assertEqual(grand_final.status, Match.MatchStatus.WAITING)
        self.assertEqual(grand_reset.status, Match.MatchStatus.WAITING)

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
        tournament = self.create_tournament("Render Check", 5)
        generate_tournament_matches(tournament.id)

        detail_response = self.client.get(reverse('tournament:detail', args=[tournament.id]))
        bracket_response = self.client.get(reverse('tournament:bracket', args=[tournament.id]))

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(bracket_response.status_code, 200)
        self.assertContains(bracket_response, "Winners Bracket")
        self.assertContains(bracket_response, "Losers Bracket")
