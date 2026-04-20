# teams/team_generator.py
from players.models import Player, Rank, Role
from .models import Team, TeamMember, WaitingList

def calculate_player_score(player):
    """Calculate individual player score based on ranks"""
    rank_order = list(Rank)
    current_score = rank_order.index(player.current_rank)
    highest_score = rank_order.index(player.highest_rank)
    
    # Weight: current rank 60%, highest rank 40%
    return (current_score * 0.6) + (highest_score * 0.4)

def get_role_priority(role):
    """Get role priority for team balance"""
    role_priority = {
        Role.GOLD_LANE: 1,
        Role.EXP_LANE: 2,
        Role.MAGE: 3,
        Role.TANK_SUPPORT: 4,
        Role.JUNGLER: 5
    }
    return role_priority.get(role, 99)

def can_player_play_role(player, required_role):
    """Check if player can play a specific role"""
    if player.primary_role == required_role:
        return True
    if required_role in player.get_secondary_roles_list():
        return True
    return False

def create_balanced_teams():
    """Main function to generate balanced teams"""
    # Clear existing teams and waiting list
    Team.objects.all().delete()
    WaitingList.objects.all().delete()
    
    # Get all players
    all_players = list(Player.objects.all())
    
    if not all_players:
        return [], []
    
    # Sort players by skill score (highest to lowest)
    players_with_scores = [(p, calculate_player_score(p)) for p in all_players]
    players_with_scores.sort(key=lambda x: x[1], reverse=True)
    sorted_players = [p for p, score in players_with_scores]
    
    # Calculate number of teams needed (5 players per team)
    num_teams = len(sorted_players) // 5
    remaining_players = len(sorted_players) % 5
    
    if num_teams == 0:
        # Not enough players for a full team
        for player in sorted_players:
            WaitingList.objects.create(player=player, reason="Not enough players for a full team")
        return [], list(sorted_players)
    
    # Initialize teams
    teams = []
    for i in range(num_teams):
        team = Team.objects.create(name=f"Team {chr(65 + i)}")  # Team A, B, C, etc.
        teams.append(team)
    
    # Snake draft for balanced teams
    team_players = [[] for _ in range(num_teams)]
    
    for idx, player in enumerate(sorted_players[:num_teams * 5]):
        team_idx = idx % num_teams
        if (idx // num_teams) % 2 == 1:
            team_idx = num_teams - 1 - team_idx
        team_players[team_idx].append(player)
    
    # Role balancing - swap players if needed
    for team_idx, team in enumerate(teams):
        current_players = team_players[team_idx]
        
        # Check if team has all required roles
        required_roles = [Role.GOLD_LANE, Role.EXP_LANE, Role.MAGE, 
                         Role.TANK_SUPPORT, Role.JUNGLER]
        
        missing_roles = []
        for required_role in required_roles:
            has_role = False
            for player in current_players:
                if can_player_play_role(player, required_role):
                    has_role = True
                    break
            if not has_role:
                missing_roles.append(required_role)
        
        # If missing roles, try to swap with other teams
        if missing_roles:
            for other_team_idx, other_team in enumerate(teams):
                if other_team_idx != team_idx:
                    for player_idx, player in enumerate(team_players[other_team_idx]):
                        player_roles = [player.primary_role] + player.get_secondary_roles_list()
                        for missing_role in missing_roles:
                            if missing_role in player_roles:
                                # Try to swap with a player from current team
                                for current_player in current_players:
                                    if can_player_play_role(current_player, missing_role):
                                        # Swap players
                                        team_players[team_idx][team_players[team_idx].index(current_player)] = player
                                        team_players[other_team_idx][player_idx] = current_player
                                        break
                                break
                        break
                    break
    
    # Add players to teams
    for team_idx, team in enumerate(teams):
        for player in team_players[team_idx]:
            TeamMember.objects.create(team=team, player=player)
    
    # Add remaining players to waiting list
    waiting_players = sorted_players[num_teams * 5:]
    for player in waiting_players:
        WaitingList.objects.create(player=player, reason=f"Extra player - {len(waiting_players)} players waiting")
    
    return teams, waiting_players

def get_team_balance_report():
    """Get balance report for all teams"""
    teams = Team.objects.all()
    report = []
    
    for team in teams:
        members = team.team_members.all()
        scores = [calculate_player_score(m.player) for m in members]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        roles = []
        for member in members:
            roles.append(member.player.get_primary_role_display())
        
        report.append({
            'team': team,
            'players': list(members),
            'avg_score': avg_score,
            'roles': roles,
            'is_full': team.is_full()
        })
    
    return report