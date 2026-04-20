# teams/models.py
from django.db import models
from players.models import Player, Rank, Role

class Team(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.name} ({self.get_member_count()}/5 players)"
    
    def get_member_count(self):
        return self.team_members.count()
    
    def is_full(self):
        return self.get_member_count() >= 5
    
    def get_team_roles(self):
        """Get all roles in the team"""
        roles = []
        for member in self.team_members.all():
            roles.append(member.player.primary_role)
            roles.extend(member.player.get_secondary_roles_list())
        return roles
    
    def get_average_rank_score(self):
        """Calculate average rank score for the team"""
        members = self.team_members.all()
        if not members:
            return 0
        rank_order = list(Rank)
        total = 0
        for member in members:
            rank_index = rank_order.index(member.player.current_rank)
            total += rank_index
        return total / len(members)
    
    def get_team_strength_score(self):
        """Calculate overall team strength based on ranks"""
        members = self.team_members.all()
        if not members:
            return 0
        rank_order = list(Rank)
        current_total = 0
        highest_total = 0
        for member in members:
            current_total += rank_order.index(member.player.current_rank)
            highest_total += rank_order.index(member.player.highest_rank)
        return (current_total * 0.6) + (highest_total * 0.4)

class TeamMember(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='team_members')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='player_teams')
    joined_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['team', 'player']
    
    def __str__(self):
        return f"{self.player.name} - {self.team.name}"

class WaitingList(models.Model):
    player = models.OneToOneField(Player, on_delete=models.CASCADE, unique=True)
    added_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=200, blank=True)
    
    def __str__(self):
        return f"Waiting: {self.player.name}"