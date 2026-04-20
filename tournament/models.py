from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from teams.models import Team

class TournamentFormat(models.TextChoices):
    SINGLE_ELIMINATION = 'single_elimination', 'Single Elimination'
    DOUBLE_ELIMINATION = 'double_elimination', 'Double Elimination'
    ROUND_ROBIN = 'round_robin', 'Round Robin'

class MatchStage(models.TextChoices):
    PLAY_IN = 'play_in', 'Play-In Round'
    QUALIFIER = 'qualifier', 'Qualifier'
    QUARTER_FINAL = 'quarter_final', 'Quarter Final'
    SEMI_FINAL = 'semi_final', 'Semi Final'
    FINAL = 'final', 'Final'
    THIRD_PLACE = 'third_place', 'Third Place Playoff'
    GROUP_STAGE = 'group_stage', 'Group Stage'
    WINNERS_FINAL = 'winners_final', 'Winners Final'
    LOSERS_FINAL = 'losers_final', 'Losers Final'
    GRAND_FINAL = 'grand_final', 'Grand Final'
    GRAND_FINAL_RESET = 'grand_final_reset', 'Grand Final Reset'

class MatchFormat(models.TextChoices):
    BO1 = 'bo1', 'Best of 1'
    BO3 = 'bo3', 'Best of 3'
    BO5 = 'bo5', 'Best of 5'

class BracketType(models.TextChoices):
    WINNERS = 'winners', 'Winners Bracket'
    LOSERS = 'losers', 'Losers Bracket'
    GRAND = 'grand', 'Grand Finals'
    GRAND_RESET = 'grand_reset', 'Grand Finals Reset'


class MatchSourcePosition(models.TextChoices):
    WINNER = 'winner', 'Winner'
    LOSER = 'loser', 'Loser'

class Tournament(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    format = models.CharField(max_length=20, choices=TournamentFormat.choices, default=TournamentFormat.SINGLE_ELIMINATION)
    teams = models.ManyToManyField(Team, related_name='tournaments')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    current_round = models.IntegerField(default=1)
    current_round_wb = models.IntegerField(default=1)  # Winners bracket round
    current_round_lb = models.IntegerField(default=1)  # Losers bracket round
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    def get_team_count(self):
        return self.teams.count()
    
    def get_total_matches(self):
        return self.matches.count()
    
    def get_completed_matches(self):
        return self.matches.filter(
            status__in=[Match.MatchStatus.COMPLETED, Match.MatchStatus.BYE]
        ).count()
    
    def get_suggested_format(self):
        """Suggest tournament format based on number of teams"""
        team_count = self.get_team_count()
        if team_count <= 8:
            return TournamentFormat.SINGLE_ELIMINATION
        elif team_count <= 16:
            return TournamentFormat.DOUBLE_ELIMINATION
        else:
            return TournamentFormat.ROUND_ROBIN
    
    def is_complete(self):
        """Check if tournament is complete"""
        if self.format == TournamentFormat.SINGLE_ELIMINATION:
            finals = self.matches.filter(
                stage='final',
                status__in=[Match.MatchStatus.COMPLETED, Match.MatchStatus.BYE],
            ).first()
            return finals is not None and finals.winner is not None
        elif self.format == TournamentFormat.DOUBLE_ELIMINATION:
            grand_final = self.matches.filter(
                bracket_type=BracketType.GRAND
            ).first()
            grand_reset = self.matches.filter(
                bracket_type=BracketType.GRAND_RESET
            ).first()

            if not grand_final or grand_final.status not in [
                Match.MatchStatus.COMPLETED,
                Match.MatchStatus.BYE,
            ]:
                return False

            if grand_final.winner == grand_final.team_a:
                return grand_final.winner is not None

            return (
                grand_reset is not None
                and grand_reset.status in [Match.MatchStatus.COMPLETED, Match.MatchStatus.BYE]
                and grand_reset.winner is not None
            )
        elif self.format == TournamentFormat.ROUND_ROBIN:
            total_matches = self.get_total_matches()
            completed_matches = self.get_completed_matches()
            return total_matches > 0 and total_matches == completed_matches
        return False
    
    def get_champion(self):
        """Get tournament champion"""
        if self.format == TournamentFormat.SINGLE_ELIMINATION:
            finals = self.matches.filter(
                stage='final',
                status__in=[Match.MatchStatus.COMPLETED, Match.MatchStatus.BYE],
            ).first()
            if finals and finals.winner:
                return finals.winner
        elif self.format == TournamentFormat.DOUBLE_ELIMINATION:
            grand_final = self.matches.filter(bracket_type=BracketType.GRAND).first()
            grand_reset = self.matches.filter(bracket_type=BracketType.GRAND_RESET).first()

            if (
                grand_final
                and grand_final.status in [Match.MatchStatus.COMPLETED, Match.MatchStatus.BYE]
                and grand_final.winner == grand_final.team_a
            ):
                return grand_final.winner

            if (
                grand_reset
                and grand_reset.status in [Match.MatchStatus.COMPLETED, Match.MatchStatus.BYE]
                and grand_reset.winner
            ):
                return grand_reset.winner
        elif self.format == TournamentFormat.ROUND_ROBIN:
            # Calculate standings to find champion
            from django.db import models
            standings = {}
            for team in self.teams.all():
                matches = self.matches.filter(
                    models.Q(team_a=team) | models.Q(team_b=team),
                    status='completed'
                )
                points = 0
                for match in matches:
                    if match.winner == team:
                        points += 3
                standings[team.id] = points
            
            if standings:
                champion_id = max(standings, key=standings.get)
                return Team.objects.get(id=champion_id)
        return None

class Match(models.Model):
    class MatchStatus(models.TextChoices):
        WAITING = 'waiting', 'Waiting'
        READY = 'ready', 'Ready'
        IN_PROGRESS = 'in_progress', 'In Progress'
        COMPLETED = 'completed', 'Completed'
        BYE = 'bye', 'Bye'
    
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name='matches')
    round_number = models.IntegerField()
    game_number = models.IntegerField(default=1)
    stage = models.CharField(max_length=20, choices=MatchStage.choices, default=MatchStage.QUALIFIER)
    match_format = models.CharField(max_length=5, choices=MatchFormat.choices, default=MatchFormat.BO3)
    bracket_type = models.CharField(max_length=20, choices=BracketType.choices, default=BracketType.WINNERS, null=True, blank=True)
    
    team_a = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='matches_as_team_a')
    team_b = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='matches_as_team_b')
    team_a_score = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(3)])
    team_b_score = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(3)])
    
    winner = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='matches_won')
    status = models.CharField(max_length=20, choices=MatchStatus.choices, default=MatchStatus.WAITING)
    
    # For bracket tournament linking
    next_match = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='previous_matches')
    parent_match_a = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='child_match_a')
    parent_match_b = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='child_match_b')
    team_a_source_type = models.CharField(max_length=10, choices=MatchSourcePosition.choices, null=True, blank=True)
    team_b_source_type = models.CharField(max_length=10, choices=MatchSourcePosition.choices, null=True, blank=True)
    
    # For double elimination - where loser goes
    loser_next_match = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='loser_feeds_into')
    is_bye = models.BooleanField(default=False)
    bye_team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bye_matches',
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['round_number', 'game_number', 'bracket_type']
        indexes = [models.Index(fields=['tournament', 'round_number', 'bracket_type']),]
    
    def __str__(self):
        team_a_name = self.team_a.name if self.team_a else 'TBD'
        team_b_name = self.team_b.name if self.team_b else 'TBD'
        bracket = f" [{self.get_bracket_type_display()}]" if self.bracket_type else ""
        return f"Round {self.round_number}{bracket} - {team_a_name} vs {team_b_name}"
    
    def get_required_wins(self):
        """Get number of wins required to win the match"""
        if self.match_format == 'bo1':
            return 1
        elif self.match_format == 'bo3':
            return 2
        elif self.match_format == 'bo5':
            return 3
        return 1
    
    def is_ready_to_play(self):
        """Check if match is ready to be played"""
        return (
            self.team_a is not None
            and self.team_b is not None
            and self.status in [self.MatchStatus.READY, self.MatchStatus.IN_PROGRESS]
        )
    
    def get_winner_name(self):
        """Get winner name or 'TBD'"""
        return self.winner.name if self.winner else 'TBD'

    @property
    def team1_source(self):
        return self._get_source_payload(self.parent_match_a, self.team_a_source_type)

    @property
    def team2_source(self):
        return self._get_source_payload(self.parent_match_b, self.team_b_source_type)

    def _get_source_payload(self, source_match, source_type):
        if not source_match or not source_type:
            return None
        return {'match_id': str(source_match.id), 'position': source_type}

    def scores_recorded(self):
        return self.team_a_score is not None and self.team_b_score is not None

    def has_assigned_teams(self):
        return self.team_a_id is not None and self.team_b_id is not None

    def has_partial_scores(self):
        return (self.team_a_score is not None or self.team_b_score is not None) and not self.scores_recorded()

    @property
    def status_label(self):
        labels = {
            self.MatchStatus.WAITING: 'Waiting',
            self.MatchStatus.READY: 'Ready to Play',
            self.MatchStatus.IN_PROGRESS: 'In Progress',
            self.MatchStatus.COMPLETED: 'Complete',
            self.MatchStatus.BYE: 'Bye',
        }
        if self.status == self.MatchStatus.BYE and self.bye_team_id:
            return 'Bye Complete'
        return labels.get(self.status, self.get_status_display())

    @property
    def team_a_display_name(self):
        if self.team_a_id:
            return self.team_a.name
        if self.parent_match_a_id:
            return 'Waiting for opponent'
        return 'TBD'

    @property
    def team_b_display_name(self):
        if self.team_b_id:
            return self.team_b.name
        if self.parent_match_b_id:
            return 'Waiting for opponent'
        return 'TBD'

    @property
    def can_update_result(self):
        return (
            self.has_assigned_teams()
            and self.status in [self.MatchStatus.READY, self.MatchStatus.IN_PROGRESS]
            and not self.is_bye
        )

    @property
    def action_label(self):
        if self.can_update_result:
            return 'Update Result'
        if self.status in [self.MatchStatus.COMPLETED, self.MatchStatus.BYE]:
            return 'View Results'
        return 'Disabled'

    @property
    def bracket_code(self):
        if self.bracket_type == BracketType.WINNERS:
            return f"W{self.game_number}"
        if self.bracket_type == BracketType.LOSERS:
            return f"L{self.game_number}"
        if self.bracket_type == BracketType.GRAND:
            return "GF1"
        if self.bracket_type == BracketType.GRAND_RESET:
            return "GF2"
        return f"M{self.game_number}"

    def _describe_route(self, target_match, route_type):
        if not target_match:
            return None

        bracket_labels = {
            BracketType.WINNERS: 'W',
            BracketType.LOSERS: 'L',
            BracketType.GRAND: 'GF',
            BracketType.GRAND_RESET: 'GF Reset',
        }
        route_prefix = 'Winner' if route_type == 'winner' else 'Loser'
        bracket = bracket_labels.get(target_match.bracket_type, 'M')
        if target_match.bracket_type in [BracketType.GRAND, BracketType.GRAND_RESET]:
            return f"{route_prefix} to {bracket}"
        return f"{route_prefix} to {bracket} Round {target_match.round_number}, Match {target_match.game_number}"

    @property
    def winner_route_label(self):
        return self._describe_route(self.next_match, 'winner')

    @property
    def loser_route_label(self):
        return self._describe_route(self.loser_next_match, 'loser')
