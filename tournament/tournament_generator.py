from django.db import transaction
from teams.models import Team
from .models import Tournament, Match, TournamentFormat, MatchStage, MatchFormat, BracketType
import math
import random

def generate_tournament_matches(tournament_id):
    """Generate matches for a tournament based on its format"""
    tournament = Tournament.objects.get(id=tournament_id)
    
    # Clear existing matches - use delete() instead of filter().delete() to avoid constraint issues
    Match.objects.filter(tournament=tournament).delete()
    
    # Reset round counters
    tournament.current_round = 1
    tournament.current_round_wb = 1
    tournament.current_round_lb = 1
    tournament.save()
    
    # Get teams list
    teams = list(tournament.teams.all())
    
    if len(teams) < 2:
        raise ValueError("At least 2 teams are required to generate matches")
    
    if tournament.format == TournamentFormat.SINGLE_ELIMINATION:
        generate_single_elimination_matches(tournament, teams)
    elif tournament.format == TournamentFormat.DOUBLE_ELIMINATION:
        generate_double_elimination_matches(tournament, teams)
    elif tournament.format == TournamentFormat.ROUND_ROBIN:
        generate_round_robin_matches(tournament, teams)
    
    return True

def calculate_bracket_size(num_teams):
    """Calculate perfect bracket size and number of byes"""
    perfect_size = 1
    rounds = 0
    while perfect_size < num_teams:
        perfect_size *= 2
        rounds += 1
    
    num_byes = perfect_size - num_teams
    return perfect_size, num_byes, rounds

def get_seeded_teams(teams):
    """Return teams sorted by seed (assuming seed is available, otherwise random)"""
    # If teams have a seed attribute, use it
    if teams and hasattr(teams[0], 'seed') and teams[0].seed:
        return sorted(teams, key=lambda x: x.seed)
    # Otherwise randomize for fair distribution
    shuffled = teams.copy()
    random.shuffle(shuffled)
    return shuffled

def generate_single_elimination_matches(tournament, teams):
    """Generate single elimination bracket matches with proper bye handling"""
    num_teams = len(teams)
    perfect_size, num_byes, total_rounds = calculate_bracket_size(num_teams)
    
    # Seed teams (top seeds get byes)
    seeded_teams = get_seeded_teams(teams)
    
    # Create slots for the bracket
    slots = [None] * perfect_size
    
    # Fill slots using standard bracket seeding
    for i in range(min(num_teams, perfect_size)):
        slot_position = get_seed_position(i, perfect_size)
        slots[slot_position] = seeded_teams[i]
    
    # Create matches for each round
    current_round_matches = []
    match_counter = 1
    
    # Create first round matches
    num_matches = perfect_size // 2
    for i in range(num_matches):
        team_a = slots[i * 2]
        team_b = slots[i * 2 + 1]
        
        stage = get_match_stage(total_rounds, 1, perfect_size)
        match_format = get_match_format_for_round(1, total_rounds)
        
        # Check if match already exists
        match, created = Match.objects.get_or_create(
            tournament=tournament,
            round_number=1,
            game_number=i + 1,
            bracket_type=BracketType.WINNERS,
            defaults={
                'stage': stage,
                'match_format': match_format,
                'team_a': team_a,
                'team_b': team_b,
                'status': Match.MatchStatus.PENDING
            }
        )
        
        if not created:
            # Update existing match
            match.stage = stage
            match.match_format = match_format
            match.team_a = team_a
            match.team_b = team_b
            match.status = Match.MatchStatus.PENDING
        
        # Handle byes (matches with only one team)
        if team_a and not team_b:
            match.status = Match.MatchStatus.COMPLETED
            match.winner = team_a
            match.team_a_score = 0
            match.team_b_score = 0
        elif not team_a and team_b:
            match.status = Match.MatchStatus.COMPLETED
            match.winner = team_b
            match.team_a_score = 0
            match.team_b_score = 0
        elif not team_a and not team_b:
            # Both empty - shouldn't happen with correct bracket size
            match.status = Match.MatchStatus.COMPLETED
        
        match.save()
        current_round_matches.append(match)
        match_counter += 1
    
    # Generate subsequent rounds
    for round_num in range(2, total_rounds + 1):
        prev_matches = current_round_matches
        next_matches = []
        num_matches = len(prev_matches) // 2
        
        for i in range(num_matches):
            match_a = prev_matches[i * 2]
            match_b = prev_matches[i * 2 + 1]
            
            stage = get_match_stage(total_rounds, round_num, perfect_size)
            match_format = get_match_format_for_round(round_num, total_rounds)
            
            # Create or get match
            match, created = Match.objects.get_or_create(
                tournament=tournament,
                round_number=round_num,
                game_number=i + 1,
                bracket_type=BracketType.WINNERS,
                defaults={
                    'stage': stage,
                    'match_format': match_format,
                    'status': Match.MatchStatus.PENDING
                }
            )
            
            if not created:
                match.stage = stage
                match.match_format = match_format
                match.status = Match.MatchStatus.PENDING
            
            match.save()
            next_matches.append(match)
            
            # Link previous matches to this match
            match_a.next_match = match
            match_a.save()
            match_b.next_match = match
            match_b.save()
            
            # If both previous matches had winners (byes), set them up
            if match_a.winner and match_b.winner:
                match.team_a = match_a.winner
                match.team_b = match_b.winner
                match.save()
            elif match_a.winner:
                match.team_a = match_a.winner
                match.save()
            elif match_b.winner:
                match.team_b = match_b.winner
                match.save()
        
        current_round_matches = next_matches

def get_seed_position(index, total_slots):
    """Calculate seeding position for fair bracket distribution"""
    # This implements a standard tournament seeding algorithm
    if total_slots == 2:
        return index
    if total_slots == 4:
        positions = [0, 3, 1, 2]
        return positions[index] if index < len(positions) else index
    if total_slots == 8:
        positions = [0, 7, 3, 4, 1, 6, 2, 5]
        return positions[index] if index < len(positions) else index
    if total_slots == 16:
        positions = [0, 15, 7, 8, 3, 12, 4, 11, 1, 14, 6, 9, 2, 13, 5, 10]
        return positions[index] if index < len(positions) else index
    
    # Default: simple alternating for larger brackets
    if index % 2 == 0:
        return index // 2
    else:
        return total_slots - (index // 2) - 1

def generate_double_elimination_matches(tournament, teams):
    """Generate double elimination bracket matches"""
    num_teams = len(teams)
    perfect_size, num_byes, total_wb_rounds = calculate_bracket_size(num_teams)
    
    # Seed teams
    seeded_teams = get_seeded_teams(teams)
    
    # Create slots for winners bracket
    wb_slots = [None] * perfect_size
    
    # Fill winners bracket slots with seeding
    for i in range(min(num_teams, perfect_size)):
        slot_position = get_seed_position(i, perfect_size)
        wb_slots[slot_position] = seeded_teams[i]
    
    # Generate Winners Bracket matches
    current_wb_matches = []
    match_counter = 1
    
    # Create first round winners bracket matches
    num_wb_matches = perfect_size // 2
    for i in range(num_wb_matches):
        team_a = wb_slots[i * 2]
        team_b = wb_slots[i * 2 + 1]
        
        stage = get_double_elim_stage(total_wb_rounds, 1, True)
        match_format = get_match_format_for_round(1, total_wb_rounds)
        
        match, created = Match.objects.get_or_create(
            tournament=tournament,
            round_number=1,
            game_number=i + 1,
            bracket_type=BracketType.WINNERS,
            defaults={
                'stage': stage,
                'match_format': match_format,
                'team_a': team_a,
                'team_b': team_b,
                'status': Match.MatchStatus.PENDING
            }
        )
        
        # Handle byes in winners bracket
        if team_a and not team_b:
            match.status = Match.MatchStatus.COMPLETED
            match.winner = team_a
        elif not team_a and team_b:
            match.status = Match.MatchStatus.COMPLETED
            match.winner = team_b
        
        match.save()
        current_wb_matches.append(match)
        match_counter += 1
    
    # Generate subsequent winners bracket rounds
    for round_num in range(2, total_wb_rounds + 1):
        prev_matches = current_wb_matches
        next_matches = []
        num_matches = len(prev_matches) // 2
        
        for i in range(num_matches):
            match_a = prev_matches[i * 2]
            match_b = prev_matches[i * 2 + 1]
            
            stage = get_double_elim_stage(total_wb_rounds, round_num, True)
            match_format = get_match_format_for_round(round_num, total_wb_rounds)
            
            match, created = Match.objects.get_or_create(
                tournament=tournament,
                round_number=round_num,
                game_number=i + 1,
                bracket_type=BracketType.WINNERS,
                defaults={
                    'stage': stage,
                    'match_format': match_format,
                    'status': Match.MatchStatus.PENDING
                }
            )
            
            match.save()
            next_matches.append(match)
            
            # Link previous matches
            match_a.next_match = match
            match_a.save()
            match_b.next_match = match
            match_b.save()
            
            # Set teams if winners already determined
            if match_a.winner and match_b.winner:
                match.team_a = match_a.winner
                match.team_b = match_b.winner
                match.save()
            elif match_a.winner:
                match.team_a = match_a.winner
                match.save()
            elif match_b.winner:
                match.team_b = match_b.winner
                match.save()
        
        current_wb_matches = next_matches
    
    # Create Grand Finals
    if current_wb_matches:
        final_match = current_wb_matches[0] if current_wb_matches else None
        
        grand_final, created = Match.objects.get_or_create(
            tournament=tournament,
            round_number=total_wb_rounds + 1,
            game_number=1,
            bracket_type=BracketType.GRAND,
            defaults={
                'stage': MatchStage.GRAND_FINAL,
                'match_format': MatchFormat.BO5,
                'status': Match.MatchStatus.PENDING
            }
        )
        
        if final_match:
            final_match.next_match = grand_final
            final_match.save()

def generate_round_robin_matches(tournament, teams):
    """Generate round robin matches where every team plays every other team"""
    num_teams = len(teams)
    matches = []
    
    # Clear existing matches first
    Match.objects.filter(tournament=tournament).delete()
    
    # Generate all possible pairings
    match_id = 1
    for i in range(num_teams):
        for j in range(i + 1, num_teams):
            match = Match.objects.create(
                tournament=tournament,
                round_number=1,
                game_number=match_id,
                stage=MatchStage.GROUP_STAGE,
                match_format=MatchFormat.BO3,
                bracket_type=BracketType.WINNERS,
                team_a=teams[i],
                team_b=teams[j],
                status=Match.MatchStatus.PENDING
            )
            match.save()
            matches.append(match)
            match_id += 1
    
    return matches

def get_match_stage(total_rounds, current_round, perfect_size):
    """Determine match stage for single elimination"""
    if total_rounds == 1:
        return MatchStage.FINAL
    elif current_round == total_rounds:
        return MatchStage.FINAL
    elif current_round == total_rounds - 1:
        return MatchStage.SEMI_FINAL
    elif current_round == total_rounds - 2:
        return MatchStage.QUARTER_FINAL
    elif current_round == total_rounds - 3 and perfect_size >= 16:
        return MatchStage.PLAY_IN
    else:
        return MatchStage.QUALIFIER

def get_double_elim_stage(total_rounds, current_round, is_winners):
    """Determine match stage for double elimination"""
    if is_winners:
        if current_round == total_rounds:
            return MatchStage.WINNERS_FINAL
        elif current_round == total_rounds - 1:
            return MatchStage.SEMI_FINAL
        elif current_round == total_rounds - 2:
            return MatchStage.QUARTER_FINAL
        else:
            return MatchStage.QUALIFIER
    else:
        if current_round == total_rounds - 1:
            return MatchStage.LOSERS_FINAL
        else:
            return MatchStage.QUALIFIER

def get_match_format_for_round(current_round, total_rounds):
    """Determine match format based on round importance"""
    if current_round == total_rounds:  # Finals
        return MatchFormat.BO5
    elif current_round >= total_rounds - 2:  # Semi-finals and Quarter-finals
        return MatchFormat.BO3
    else:
        return MatchFormat.BO1

def get_bracket_structure(tournament):
    """Get bracket structure for visualization"""
    matches_by_round = {}
    
    for match in tournament.matches.all().order_by('round_number', 'bracket_type', 'game_number'):
        if match.round_number not in matches_by_round:
            matches_by_round[match.round_number] = []
        matches_by_round[match.round_number].append(match)
    
    return matches_by_round

def advance_match(match_id, winner_team_id, team_a_score, team_b_score):
    """Advance a match result and update bracket"""
    match = Match.objects.get(id=match_id)
    
    if match.status == 'completed':
        return {'error': 'Match already completed'}
    
    winner = Team.objects.get(id=winner_team_id)
    
    # Update match
    match.team_a_score = team_a_score
    match.team_b_score = team_b_score
    match.winner = winner
    match.status = 'completed'
    match.save()
    
    result = {
        'winner': winner.name,
        'tournament_complete': False
    }
    
    # Advance to next match if exists
    if match.next_match:
        next_match = match.next_match
        
        # Assign winner to appropriate slot
        if not next_match.team_a:
            next_match.team_a = winner
        elif not next_match.team_b:
            next_match.team_b = winner
        
        next_match.save()
        
        # Check if next match is ready
        if next_match.team_a and next_match.team_b:
            next_match.status = Match.MatchStatus.PENDING
            next_match.save()
    
    # Check if tournament is complete
    if match.stage in [MatchStage.FINAL, MatchStage.GRAND_FINAL] and match.status == 'completed':
        result['tournament_complete'] = True
    
    return result