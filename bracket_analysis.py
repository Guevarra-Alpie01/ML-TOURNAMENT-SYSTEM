#!/usr/bin/env python
"""
Script to analyze and visualize the double elimination bracket structure
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'MLSYSTEM.settings')
django.setup()

from tournament.models import Tournament, Match, BracketType, TournamentFormat
from teams.models import Team
from tournament.tournament_generator import generate_tournament_matches
import math

def visualize_bracket(tournament):
    """Visualize the bracket structure for debugging"""
    print(f"\n{'='*80}")
    print(f"Tournament: {tournament.name}")
    print(f"Format: {tournament.format}")
    print(f"Total Teams: {tournament.get_team_count()}")
    print(f"{'='*80}\n")
    
    # Group matches by bracket type and round
    matches = tournament.matches.select_related('team_a', 'team_b', 'winner').order_by('bracket_type', 'round_number', 'game_number')
    
    bracket_data = {}
    for match in matches:
        bracket_type = match.bracket_type
        round_num = match.round_number
        
        if bracket_type not in bracket_data:
            bracket_data[bracket_type] = {}
        if round_num not in bracket_data[bracket_type]:
            bracket_data[bracket_type][round_num] = []
        
        bracket_data[bracket_type][round_num].append(match)
    
    # Print Winners Bracket
    print("WINNERS BRACKET:")
    print("-" * 80)
    if BracketType.WINNERS in bracket_data:
        for round_num in sorted(bracket_data[BracketType.WINNERS].keys()):
            round_matches = bracket_data[BracketType.WINNERS][round_num]
            print(f"\n  Round {round_num}:")
            for match in round_matches:
                team_a_name = match.team_a.name if match.team_a else "TBD"
                team_b_name = match.team_b.name if match.team_b else "TBD"
                winner_name = match.winner.name if match.winner else "-"
                bye_status = " (BYE)" if match.is_bye else ""
                print(f"    Match {match.game_number}: {team_a_name} vs {team_b_name} -> {winner_name}{bye_status}")
                if match.loser_next_match:
                    print(f"      -> Loser goes to: LB Round {match.loser_next_match.round_number}")
    
    # Print Losers Bracket
    print("\n\nLOSERS BRACKET:")
    print("-" * 80)
    if BracketType.LOSERS in bracket_data:
        for round_num in sorted(bracket_data[BracketType.LOSERS].keys()):
            round_matches = bracket_data[BracketType.LOSERS][round_num]
            print(f"\n  Round {round_num}:")
            for match in round_matches:
                team_a_name = match.team_a.name if match.team_a else "TBD"
                team_b_name = match.team_b.name if match.team_b else "TBD"
                winner_name = match.winner.name if match.winner else "-"
                bye_status = " (BYE)" if match.is_bye else ""
                print(f"    Match {match.game_number}: {team_a_name} vs {team_b_name} -> {winner_name}{bye_status}")
                if match.parent_match_a:
                    print(f"      -> team_a from: {match.parent_match_a.bracket_type} R{match.parent_match_a.round_number}M{match.parent_match_a.game_number} ({match.get_team_a_source_type_display()})")
                if match.parent_match_b:
                    print(f"      -> team_b from: {match.parent_match_b.bracket_type} R{match.parent_match_b.round_number}M{match.parent_match_b.game_number} ({match.get_team_b_source_type_display()})")
    
    # Print Grand Finals
    if BracketType.GRAND in bracket_data:
        print("\n\nGRAND FINAL:")
        print("-" * 80)
        for match in bracket_data[BracketType.GRAND][1]:
            team_a_name = match.team_a.name if match.team_a else "TBD"
            team_b_name = match.team_b.name if match.team_b else "TBD"
            print(f"  {team_a_name} vs {team_b_name}")
    
    if BracketType.GRAND_RESET in bracket_data:
        print("\n\nGRAND FINAL RESET:")
        print("-" * 80)
        for match in bracket_data[BracketType.GRAND_RESET][1]:
            team_a_name = match.team_a.name if match.team_a else "TBD"
            team_b_name = match.team_b.name if match.team_b else "TBD"
            print(f"  {team_a_name} vs {team_b_name}")

def test_bracket_generation(num_teams=8):
    """Test bracket generation with specified number of teams"""
    print(f"\n\nTESTING BRACKET GENERATION FOR {num_teams} TEAMS")
    print("="*80)
    
    # Create test tournament
    tournament = Tournament.objects.create(
        name=f"Test Double Elimination - {num_teams} Teams",
        format=TournamentFormat.DOUBLE_ELIMINATION,
    )
    
    # Create teams
    teams = []
    for i in range(num_teams):
        team, created = Team.objects.get_or_create(name=f"Team {i+1}_DE_{num_teams}")
        teams.append(team)
    
    tournament.teams.set(teams)
    
    # Generate matches
    generate_tournament_matches(tournament.id)
    
    # Visualize
    visualize_bracket(tournament)
    
    return tournament

if __name__ == "__main__":
    # Test with different team counts
    for num_teams in [4, 6, 8]:
        test_bracket_generation(num_teams)
        print("\n" * 3)
