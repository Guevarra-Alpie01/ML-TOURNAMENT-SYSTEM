from django.core.management import call_command
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'MLSYSTEM.settings')
django.setup()

from tournament.models import Tournament, TournamentFormat
from teams.models import Team
from tournament.tournament_generator import generate_tournament_matches

# Clear test data
Tournament.objects.filter(name__startswith="Final Test").delete()
Team.objects.filter(name__startswith="FT_").delete()

# Create teams
teams = []
for i in range(8):
    team, _ = Team.objects.get_or_create(name=f"FT_Team_{i+1}")
    teams.append(team)

# Create tournament
t = Tournament.objects.create(
    name="Final Test - Double Elimination 8 Teams",
    format=TournamentFormat.DOUBLE_ELIMINATION
)
t.teams.set(teams)

# Generate matches
try:
    generate_tournament_matches(t.id)
    print("✓ Bracket generation successful!")
    print(f"  Total matches: {t.matches.count()}")
    print(f"  WB matches: {t.matches.filter(bracket_type='winners').count()}")
    print(f"  LB matches: {t.matches.filter(bracket_type='losers').count()}")
    print(f"  Grand matches: {t.matches.filter(bracket_type='grand').count()}")
    
    # Check for Round 0 matches (should be none now)
    round_0_matches = t.matches.filter(round_number=0).count()
    if round_0_matches == 0:
        print("✓ No Round 0 matches (clean structure!)")
    else:
        print(f"⚠ Found {round_0_matches} Round 0 matches (should be 0)")
    
    # Verify WB structure
    wb_r1 = t.matches.filter(bracket_type='winners', round_number=1).count()
    print(f"✓ Winners Bracket Round 1: {wb_r1} matches (should be 4 for 8 teams)")
        
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
