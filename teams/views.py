# teams/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from .models import Team, TeamMember, WaitingList
from .forms import TeamForm, AddTeamMemberForm
from .team_generator import create_balanced_teams, get_team_balance_report
from players.models import Player

def team_list(request):
    """List all teams"""
    teams = Team.objects.all()
    waiting_players = WaitingList.objects.all()
    return render(request, 'teams/team_list.html', {
        'teams': teams,
        'waiting_players': waiting_players
    })

def create_team_manual(request):
    """Manually create a team"""
    if request.method == 'POST':
        form = TeamForm(request.POST)
        if form.is_valid():
            team = form.save()
            messages.success(request, f'Team "{team.name}" created successfully!')
            return redirect('teams:add_member', team_id=team.id)
    else:
        form = TeamForm()
    
    return render(request, 'teams/create_team.html', {'form': form})

def add_team_member(request, team_id):
    """Add a player to a team"""
    team = get_object_or_404(Team, id=team_id)
    
    if team.is_full():
        messages.error(request, f'Team "{team.name}" is already full (5/5 players)!')
        return redirect('teams:team_detail', team_id=team.id)
    
    # Get players not already in this team
    existing_players = team.team_members.values_list('player_id', flat=True)
    available_players = Player.objects.exclude(id__in=existing_players)
    
    if request.method == 'POST':
        form = AddTeamMemberForm(request.POST)
        form.fields['player'].queryset = available_players
        
        if form.is_valid():
            player = form.cleaned_data['player']
            
            # Check if player is already in any team
            if TeamMember.objects.filter(player=player).exists():
                messages.error(request, f'{player.name} is already in another team!')
                return redirect('teams:add_member', team_id=team.id)
            
            TeamMember.objects.create(team=team, player=player)
            messages.success(request, f'{player.name} added to {team.name}!')
            
            if team.is_full():
                messages.info(request, f'Team {team.name} is now complete with 5 players!')
                return redirect('teams:team_list')
            else:
                return redirect('teams:add_member', team_id=team.id)
    else:
        form = AddTeamMemberForm()
        form.fields['player'].queryset = available_players
    
    return render(request, 'teams/add_member.html', {
        'form': form,
        'team': team,
        'current_members': team.team_members.all(),
        'slots_left': 5 - team.get_member_count()
    })

def generate_balanced_teams_view(request):
    """Generate balanced teams automatically"""
    if request.method == 'POST':
        teams, waiting_players = create_balanced_teams()
        
        if teams:
            messages.success(request, f'{len(teams)} balanced teams created successfully!')
            if waiting_players:
                messages.info(request, f'{len(waiting_players)} players added to waiting list.')
        else:
            messages.warning(request, 'Not enough players to create a team (need at least 5 players).')
        
        return redirect('teams:team_list')
    
    player_count = Player.objects.count()
    return render(request, 'teams/generate_teams.html', {
        'player_count': player_count,
        'teams_needed': player_count // 5,
        'remaining_players': player_count % 5
    })

def team_detail(request, team_id):
    """View team details"""
    team = get_object_or_404(Team, id=team_id)
    members = team.team_members.all()
    balance_report = get_team_balance_report()
    
    return render(request, 'teams/team_detail.html', {
        'team': team,
        'members': members,
        'balance_report': balance_report
    })

def delete_team(request, team_id):
    """Delete a team"""
    team = get_object_or_404(Team, id=team_id)
    if request.method == 'POST':
        team_name = team.name
        team.delete()
        messages.success(request, f'Team "{team_name}" deleted successfully!')
        return redirect('teams:team_list')
    
    return render(request, 'teams/delete_team.html', {'team': team})

def remove_member(request, team_id, member_id):
    """Remove a member from a team"""
    team = get_object_or_404(Team, id=team_id)
    member = get_object_or_404(TeamMember, id=member_id, team=team)
    
    if request.method == 'POST':
        player_name = member.player.name
        member.delete()
        messages.success(request, f'{player_name} removed from {team.name}!')
        return redirect('teams:team_detail', team_id=team.id)
    
    return render(request, 'teams/remove_member.html', {'team': team, 'member': member})

def waiting_list_view(request):
    """View waiting list players"""
    waiting_players = WaitingList.objects.all().order_by('added_at')
    
    if request.method == 'POST':
        # Clear waiting list
        waiting_players.delete()
        messages.success(request, 'Waiting list cleared!')
        return redirect('teams:waiting_list')
    
    return render(request, 'teams/waiting_list.html', {'waiting_players': waiting_players})