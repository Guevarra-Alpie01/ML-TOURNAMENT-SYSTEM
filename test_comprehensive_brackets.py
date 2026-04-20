import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'MLSYSTEM.settings')
django.setup()

from tournament.models import Tournament, TournamentFormat
from teams.models import Team
from tournament.tournament_generator import generate_tournament_matches

def test_bracket(num_teams):
    """Test bracket generation for specified number of teams"""
    print(f"\n{'='*60}")
    print(f"Testing Double Elimination with {num_teams} Teams")
    print(f"{'='*60}")
    
    # Clear test data
    Tournament.objects.filter(name__startswith=f"Test_{num_teams}").delete()
    Team.objects.filter(name__startswith=f"TT{num_teams}_").delete()
    
    # Create teams
    teams = []
    for i in range(num_teams):
        team, _ = Team.objects.get_or_create(name=f"TT{num_teams}_{i+1}")
        teams.append(team)
    
    # Create tournament
    t = Tournament.objects.create(
        name=f"Test_{num_teams}_team_tournament",
        format=TournamentFormat.DOUBLE_ELIMINATION
    )
    t.teams.set(teams)
    
    # Generate matches
    try:
        generate_tournament_matches(t.id)
        
        print(f"✓ Bracket generated successfully")
        print(f"  Total matches: {t.matches.count()}")
        print(f"  - WB matches: {t.matches.filter(bracket_type='winners').count()}")
        print(f"  - LB matches: {t.matches.filter(bracket_type='losers').count()}")
        print(f"  - Grand matches: {t.matches.filter(bracket_type='grand').count()}")
        print(f"  - Grand Reset matches: {t.matches.filter(bracket_type='grand_reset').count()}")
        
        # Verify no Round 0
        round_0 = t.matches.filter(round_number=0).count()
        if round_0 == 0:
            print(f"✓ Clean structure (no Round 0)")
        else:
            print(f"✗ WARNING: Found {round_0} Round 0 matches")
        
        # Check WB R1
        wb_r1 = t.matches.filter(bracket_type='winners', round_number=1).count()
        expected_r1 = (2 ** ((num_teams - 1).bit_length())) // 2
        print(f"  - WB R1: {wb_r1} matches (expected: ~{expected_r1})")
        
        # Check bye count
        byes = t.matches.filter(is_bye=True).count()
        if byes > 0:
            print(f"  - Bye matches: {byes} (shown in R1)")
        
        return True
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

# Test different team counts
results = {}
for num_teams in [4, 5, 6, 7, 8, 12, 16]:
    results[num_teams] = test_bracket(num_teams)

print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
for num_teams, success in results.items():
    status = "✓ PASS" if success else "✗ FAIL"
    print(f"{num_teams} teams: {status}")
