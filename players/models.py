# players/models.py
from django.db import models

class Rank(models.TextChoices):
    WARRIOR = 'warrior', 'Warrior'
    ELITE = 'elite', 'Elite'
    MASTER = 'master', 'Master'
    GRANDMASTER = 'grandmaster', 'Grandmaster'
    EPIC = 'epic', 'Epic'
    LEGEND = 'legend', 'Legend'
    MYTHIC = 'mythic', 'Mythic'
    MYTHICAL_HONOR = 'mythical_honor', 'Mythical Honor'
    MYTHICAL_GLORY = 'mythical_glory', 'Mythical Glory'

class Role(models.TextChoices):
    GOLD_LANE = 'gold_lane', 'Gold Lane'
    EXP_LANE = 'exp_lane', 'Exp Lane'
    MAGE = 'mage', 'Mage'
    TANK_SUPPORT = 'tank_support', 'Tank/Support'
    JUNGLER = 'jungler', 'Jungler'

class Player(models.Model):
    name = models.CharField(max_length=100, verbose_name="Player Name")
    primary_role = models.CharField(
        max_length=50, 
        choices=Role.choices, 
        verbose_name="Primary Role"
    )
    secondary_roles = models.CharField(
        max_length=500, 
        blank=True, 
        default='',
        help_text="Select multiple secondary roles separated by commas", 
        verbose_name="Secondary Roles"
    )
    current_rank = models.CharField(
        max_length=50, 
        choices=Rank.choices,
        verbose_name="Current Rank"
    )
    highest_rank = models.CharField(
        max_length=50, 
        choices=Rank.choices, 
        verbose_name="Highest Rank Reached"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-current_rank', 'name']
    
    def __str__(self):
        return f"{self.name} - {self.get_current_rank_display()}"
    
    def get_secondary_roles_list(self):
        """Return secondary roles as a list"""
        if self.secondary_roles:
            return [role.strip() for role in self.secondary_roles.split(',') if role.strip()]
        return []
    
    def get_all_roles(self):
        """Get all roles (primary + secondary)"""
        roles = [self.get_primary_role_display()]
        roles.extend(self.get_secondary_roles_list())
        return roles