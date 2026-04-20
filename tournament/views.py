from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.template.defaulttags import register
from django.db import models
import json

from .models import Tournament, Match, TournamentFormat, MatchStage, MatchFormat, BracketType
from .tournament_generator import (
    advance_match,
    generate_tournament_matches,
    get_bracket_structure,
    sync_tournament_matches,
)
from teams.models import Team


FINAL_MATCH_STATUSES = {Match.MatchStatus.COMPLETED, Match.MatchStatus.BYE}

# Custom template filter for dictionary access
@register.filter
def get_item(dictionary, key):
    """Get item from dictionary by key"""
    return dictionary.get(key, 0)

@register.filter
def get_bracket_type_display(bracket_type):
    """Get display name for bracket type"""
    return dict(BracketType.choices).get(bracket_type, '')

def tournament_list(request):
    """List all tournaments"""
    tournaments = Tournament.objects.all()
    return render(request, 'tournament/tournament_list.html', {'tournaments': tournaments})

def create_tournament(request):
    """Create a new tournament"""
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        format_type = request.POST.get('format')
        team_ids = request.POST.getlist('teams')
        
        if not name or len(team_ids) < 2:
            messages.error(request, 'Please provide tournament name and select at least 2 teams')
            return redirect('tournament:create')
        
        tournament = Tournament.objects.create(
            name=name,
            description=description,
            format=format_type
        )
        
        # Add teams
        teams = Team.objects.filter(id__in=team_ids)
        tournament.teams.set(teams)
        
        # Auto-suggest format if not specified
        if not format_type:
            tournament.format = tournament.get_suggested_format()
            tournament.save()
        
        messages.success(request, f'Tournament "{name}" created successfully!')
        
        # Generate matches automatically
        try:
            generate_tournament_matches(tournament.id)
            messages.info(request, 'Tournament matches have been generated!')
        except Exception as e:
            messages.warning(request, f'Tournament created but match generation failed: {str(e)}')
        
        return redirect('tournament:detail', tournament_id=tournament.id)
    
    teams = Team.objects.all()
    return render(request, 'tournament/create_tournament.html', {
        'teams': teams,
        'formats': TournamentFormat.choices
    })

def tournament_detail(request, tournament_id):
    """View tournament details and bracket"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    sync_tournament_matches(tournament)
    bracket_structure = get_bracket_structure(tournament)
    
    # Get matches by round for display
    matches_by_round = {}
    match_completion_counts = {}
    
    for match in tournament.matches.all().order_by('round_number', 'bracket_type', 'game_number'):
        if match.round_number not in matches_by_round:
            matches_by_round[match.round_number] = []
            match_completion_counts[match.round_number] = 0
        matches_by_round[match.round_number].append(match)
        
        # Count completed matches
        if match.status in FINAL_MATCH_STATUSES:
            match_completion_counts[match.round_number] = match_completion_counts.get(match.round_number, 0) + 1
    
    context = {
        'tournament': tournament,
        'bracket': bracket_structure,
        'matches_by_round': matches_by_round,
        'match_completion_counts': match_completion_counts,
        'team_count': tournament.get_team_count(),
        'suggested_format': tournament.get_suggested_format(),
        'BracketType': BracketType,
        'bracket_sections': bracket_structure,
    }
    return render(request, 'tournament/tournament_detail.html', context)

def generate_matches(request, tournament_id):
    """Generate or regenerate matches for a tournament"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    if request.method == 'POST':
        try:
            # Use transaction to ensure atomic operation
            from django.db import transaction
            
            with transaction.atomic():
                # Clear existing matches
                Match.objects.filter(tournament=tournament).delete()
                # Generate new matches
                generate_tournament_matches(tournament.id)
                
            messages.success(request, 'Matches generated successfully!')
        except Exception as e:
            messages.error(request, f'Error generating matches: {str(e)}')
            # Log the error for debugging
            import traceback
            print(traceback.format_exc())
        
        return redirect('tournament:detail', tournament_id=tournament.id)
    
    return render(request, 'tournament/generate_matches.html', {'tournament': tournament})

def update_match(request, match_id):
    """Update match results and automatically advance to next round"""
    match = get_object_or_404(Match, id=match_id)
    
    if not match.team_a or not match.team_b:
        messages.error(request, 'Cannot update match: Both teams are not assigned yet. Waiting for previous matches to complete.')
        return redirect('tournament:detail', tournament_id=match.tournament.id)
    if match.status == Match.MatchStatus.BYE:
        messages.error(request, 'Bye matches are advanced automatically and cannot be edited.')
        return redirect('tournament:detail', tournament_id=match.tournament.id)
    if match.status == Match.MatchStatus.COMPLETED:
        messages.error(request, 'This match is already complete.')
        return redirect('tournament:detail', tournament_id=match.tournament.id)
    if match.status == Match.MatchStatus.WAITING:
        messages.error(request, 'This match is still waiting for teams to be assigned.')
        return redirect('tournament:detail', tournament_id=match.tournament.id)
    
    if request.method == 'POST':
        try:
            winner_id = request.POST.get('winner')
            result = advance_match(
                match.id,
                winner_id,
                request.POST.get('team_a_score'),
                request.POST.get('team_b_score'),
            )
            if result.get('error'):
                messages.error(request, result['error'])
                return redirect('tournament:update_match', match_id=match_id)

            messages.success(request, f'Match result updated successfully! Winner: {result["winner"]}')
            return redirect('tournament:detail', tournament_id=match.tournament.id)
            
        except Exception as e:
            messages.error(request, f'Error updating match: {str(e)}')
            return redirect('tournament:update_match', match_id=match_id)
    
    return render(request, 'tournament/update_match.html', {'match': match})

def handle_single_elimination_advancement(match, winner, request):
    """Handle advancement for single elimination bracket"""
    sync_tournament_matches(match.tournament)
    if match.next_match and match.next_match.status in [Match.MatchStatus.READY, Match.MatchStatus.IN_PROGRESS]:
        messages.info(request, f'{winner.name} advanced to the next round!')

def handle_double_elimination_advancement(match, winner, request):
    """Handle advancement for double elimination bracket"""
    sync_tournament_matches(match.tournament)
    if match.next_match and match.next_match.status in [Match.MatchStatus.READY, Match.MatchStatus.IN_PROGRESS]:
        messages.info(request, f'{winner.name} advanced in the bracket!')

def advance_to_next_round(request, tournament_id):
    """Advance tournament to the next round after all current round matches are complete"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    if request.method == 'POST':
        if tournament.format == TournamentFormat.SINGLE_ELIMINATION:
            return advance_single_elimination_round(tournament, request)
        elif tournament.format == TournamentFormat.DOUBLE_ELIMINATION:
            return advance_double_elimination_round(tournament, request)
    
    return redirect('tournament:detail', tournament_id=tournament.id)

def advance_single_elimination_round(tournament, request):
    """Advance to next round in single elimination"""
    current_round = tournament.current_round
    
    # Check if all matches in current round are completed
    current_round_matches = tournament.matches.filter(round_number=current_round, bracket_type=BracketType.WINNERS)
    incomplete_matches = current_round_matches.exclude(status__in=FINAL_MATCH_STATUSES)
    
    if incomplete_matches.exists():
        messages.error(request, f'Cannot advance: {incomplete_matches.count()} matches in Round {current_round} are still pending.')
        return redirect('tournament:detail', tournament_id=tournament.id)
    
    # Check if there's a next round
    next_round_matches = tournament.matches.filter(round_number=current_round + 1)
    
    if not next_round_matches.exists():
        if tournament.is_complete():
            messages.success(request, '🎉 Tournament Complete! 🎉')
        else:
            messages.info(request, 'Tournament complete! No more rounds to play.')
        return redirect('tournament:detail', tournament_id=tournament.id)
    
    # Update tournament current round
    tournament.current_round = current_round + 1
    tournament.save()
    
    messages.success(request, f'Advanced to Round {tournament.current_round}!')
    return redirect('tournament:detail', tournament_id=tournament.id)

def advance_double_elimination_round(tournament, request):
    """Advance to next round in double elimination"""
    # For double elimination, we need to track both brackets
    current_wb_round = tournament.current_round_wb
    current_lb_round = tournament.current_round_lb
    
    # Check winners bracket progress
    wb_matches = tournament.matches.filter(round_number=current_wb_round, bracket_type=BracketType.WINNERS)
    wb_incomplete = wb_matches.exclude(status__in=FINAL_MATCH_STATUSES)
    
    # Check losers bracket progress
    lb_matches = tournament.matches.filter(round_number=current_lb_round, bracket_type=BracketType.LOSERS)
    lb_incomplete = lb_matches.exclude(status__in=FINAL_MATCH_STATUSES)
    
    if wb_incomplete.exists() or lb_incomplete.exists():
        messages.error(request, 'Cannot advance: Some matches in current round are still pending.')
        return redirect('tournament:detail', tournament_id=tournament.id)
    
    # Check if we should advance winners bracket
    next_wb_matches = tournament.matches.filter(round_number=current_wb_round + 1, bracket_type=BracketType.WINNERS)
    if next_wb_matches.exists():
        tournament.current_round_wb = current_wb_round + 1
        tournament.save()
        messages.success(request, f'Advanced to Winners Bracket Round {tournament.current_round_wb}!')
    
    # Check if we should advance losers bracket
    next_lb_matches = tournament.matches.filter(round_number=current_lb_round + 1, bracket_type=BracketType.LOSERS)
    if next_lb_matches.exists():
        tournament.current_round_lb = current_lb_round + 1
        tournament.save()
        messages.success(request, f'Advanced to Losers Bracket Round {tournament.current_round_lb}!')
    
    return redirect('tournament:detail', tournament_id=tournament.id)

def get_round_status(request, tournament_id):
    """API endpoint to get round completion status"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    if tournament.format == TournamentFormat.SINGLE_ELIMINATION:
        return get_single_elimination_status(tournament)
    elif tournament.format == TournamentFormat.DOUBLE_ELIMINATION:
        return get_double_elimination_status(tournament)
    else:
        return JsonResponse({'error': 'Invalid format'}, status=400)

def get_single_elimination_status(tournament):
    """Get status for single elimination tournament"""
    current_round = tournament.current_round
    current_round_matches = tournament.matches.filter(round_number=current_round, bracket_type=BracketType.WINNERS)
    total_matches = current_round_matches.count()
    completed_matches = current_round_matches.filter(status__in=FINAL_MATCH_STATUSES).count()
    
    next_round_exists = tournament.matches.filter(round_number=current_round + 1).exists()
    all_complete = completed_matches == total_matches and total_matches > 0
    is_complete = tournament.is_complete()
    champion = tournament.get_champion().name if tournament.get_champion() else None
    
    return JsonResponse({
        'current_round': current_round,
        'total_matches': total_matches,
        'completed_matches': completed_matches,
        'all_complete': all_complete,
        'next_round_exists': next_round_exists,
        'is_complete': is_complete,
        'champion': champion,
        'format': 'single_elimination'
    })

def get_double_elimination_status(tournament):
    """Get status for double elimination tournament"""
    current_wb_round = tournament.current_round_wb
    current_lb_round = tournament.current_round_lb
    
    wb_matches = tournament.matches.filter(round_number=current_wb_round, bracket_type=BracketType.WINNERS)
    lb_matches = tournament.matches.filter(round_number=current_lb_round, bracket_type=BracketType.LOSERS)
    
    wb_total = wb_matches.count()
    wb_completed = wb_matches.filter(status__in=FINAL_MATCH_STATUSES).count()
    lb_total = lb_matches.count()
    lb_completed = lb_matches.filter(status__in=FINAL_MATCH_STATUSES).count()
    
    is_complete = tournament.is_complete()
    champion = tournament.get_champion().name if tournament.get_champion() else None
    
    return JsonResponse({
        'wb_round': current_wb_round,
        'lb_round': current_lb_round,
        'wb_total': wb_total,
        'wb_completed': wb_completed,
        'lb_total': lb_total,
        'lb_completed': lb_completed,
        'all_complete': (wb_completed == wb_total and lb_completed == lb_total),
        'is_complete': is_complete,
        'champion': champion,
        'format': 'double_elimination'
    })

@csrf_exempt
@require_http_methods(["POST"])
def update_match_result(request, match_id):
    """API endpoint to update match results"""
    try:
        data = json.loads(request.body)
        winner_team_id = data.get('winner_team_id')
        team_a_score = data.get('team_a_score', 0)
        team_b_score = data.get('team_b_score', 0)
        
        match = Match.objects.get(id=match_id)
        
        if match.status in FINAL_MATCH_STATUSES:
            return JsonResponse({'error': 'Match already completed'}, status=400)
        
        result = advance_match(match_id, winner_team_id, team_a_score, team_b_score)
        if result.get('error'):
            return JsonResponse({'error': result['error']}, status=400)
        
        return JsonResponse({
            'success': True,
            'tournament_complete': result.get('tournament_complete', False),
            'winner': result.get('winner'),
            'next_match': match.next_match.id if match.next_match else None
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

def tournament_bracket_view(request, tournament_id):
    """View bracket in a visual format"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    sync_tournament_matches(tournament)
    bracket = get_bracket_structure(tournament)
    
    return render(request, 'tournament/bracket_view.html', {
        'tournament': tournament,
        'bracket': bracket,
        'champion': tournament.get_champion(),
    })

def round_robin_standings(request, tournament_id):
    """Calculate and display round robin standings"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    if tournament.format != TournamentFormat.ROUND_ROBIN:
        messages.warning(request, 'This tournament is not a Round Robin format')
        return redirect('tournament:detail', tournament_id=tournament.id)
    
    # Calculate standings
    standings = []
    for team in tournament.teams.all():
        matches = tournament.matches.filter(
            models.Q(team_a=team) | models.Q(team_b=team),
            status='completed'
        )
        
        wins = 0
        losses = 0
        points = 0
        total_score_for = 0
        total_score_against = 0
        
        for match in matches:
            if match.winner == team:
                wins += 1
                points += 3
            else:
                losses += 1
            
            # Calculate scores
            if match.team_a == team:
                total_score_for += match.team_a_score
                total_score_against += match.team_b_score
            else:
                total_score_for += match.team_b_score
                total_score_against += match.team_a_score
        
        standings.append({
            'team': team,
            'wins': wins,
            'losses': losses,
            'points': points,
            'matches_played': wins + losses,
            'score_for': total_score_for,
            'score_against': total_score_against,
            'score_difference': total_score_for - total_score_against
        })
    
    # Sort by points (descending), then by score difference
    standings.sort(key=lambda x: (x['points'], x['score_difference']), reverse=True)
    
    # Add position
    for idx, standing in enumerate(standings, 1):
        standing['position'] = idx
    
    return render(request, 'tournament/round_robin_standings.html', {
        'tournament': tournament,
        'standings': standings
    })

def delete_tournament(request, tournament_id):
    """Delete a tournament"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    if request.method == 'POST':
        tournament_name = tournament.name
        tournament.delete()
        messages.success(request, f'Tournament "{tournament_name}" deleted successfully!')
        return redirect('tournament:list')
    
    return render(request, 'tournament/delete_tournament.html', {'tournament': tournament})
