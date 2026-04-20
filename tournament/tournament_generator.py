import math

from django.db import transaction

from teams.models import Team

from .models import (
    BracketType,
    Match,
    MatchFormat,
    MatchSourcePosition,
    MatchStage,
    Tournament,
    TournamentFormat,
)


FINAL_MATCH_STATUSES = {Match.MatchStatus.COMPLETED, Match.MatchStatus.BYE}
BRACKET_SYNC_ORDER = {
    BracketType.WINNERS: 0,
    BracketType.LOSERS: 1,
    BracketType.GRAND: 2,
    BracketType.GRAND_RESET: 3,
}


def generate_tournament_matches(tournament_id):
    """Generate matches for a tournament based on its format."""
    tournament = Tournament.objects.get(id=tournament_id)

    teams = list(tournament.teams.all())
    if len(teams) < 2:
        raise ValueError("At least 2 teams are required to generate matches")
    if len(teams) > 64:
        raise ValueError("This bracket generator supports up to 64 teams")

    with transaction.atomic():
        Match.objects.filter(tournament=tournament).delete()
        tournament.current_round = 1
        tournament.current_round_wb = 1
        tournament.current_round_lb = 1
        tournament.save(update_fields=['current_round', 'current_round_wb', 'current_round_lb'])

        if tournament.format == TournamentFormat.SINGLE_ELIMINATION:
            generate_single_elimination_matches(tournament, teams)
        elif tournament.format == TournamentFormat.DOUBLE_ELIMINATION:
            generate_double_elimination_matches(tournament, teams)
        elif tournament.format == TournamentFormat.ROUND_ROBIN:
            generate_round_robin_matches(tournament, teams)

        sync_tournament_matches(tournament)

    return True


def calculate_bracket_size(num_teams):
    """Calculate the next power-of-two bracket size, bye count, and total rounds."""
    if num_teams < 2:
        raise ValueError("Bracket size requires at least 2 teams")
    if num_teams > 64:
        raise ValueError("Bracket size supports at most 64 teams")

    perfect_size = 1 << math.ceil(math.log2(num_teams))
    num_byes = perfect_size - num_teams
    rounds = int(math.log2(perfect_size))
    return perfect_size, num_byes, rounds


def get_seeded_teams(teams):
    """Return teams sorted so higher seeds receive byes first."""
    if teams and hasattr(teams[0], 'seed'):
        seeded = [team for team in teams if getattr(team, 'seed', None) is not None]
        if len(seeded) == len(teams):
            return sorted(teams, key=lambda team: (team.seed, team.name.lower(), team.id))

    return sorted(
        teams,
        key=lambda team: (
            -team.get_team_strength_score(),
            team.name.lower(),
            team.id,
        ),
    )


def build_seed_positions(size):
    """Return standard bracket seed ordering for any power-of-two bracket size."""
    positions = [1, 2]
    while len(positions) < size:
        next_size = len(positions) * 2 + 1
        positions = [seed for value in positions for seed in (value, next_size - value)]
    return positions


def get_seeded_slots(teams, bracket_size):
    slots = [None] * bracket_size
    seed_order = build_seed_positions(bracket_size)
    for seed_number, team in enumerate(get_seeded_teams(teams), start=1):
        slot_index = seed_order.index(seed_number)
        slots[slot_index] = team
    return slots


def create_match(
    tournament,
    round_number,
    game_number,
    bracket_type,
    stage,
    match_format,
    team_a=None,
    team_b=None,
):
    return Match.objects.create(
        tournament=tournament,
        round_number=round_number,
        game_number=game_number,
        bracket_type=bracket_type,
        stage=stage,
        match_format=match_format,
        team_a=team_a,
        team_b=team_b,
        status=Match.MatchStatus.WAITING,
    )


def connect_slot(match, slot_name, source_match, source_type):
    if slot_name == 'team_a':
        match.parent_match_a = source_match
        match.team_a_source_type = source_type
    else:
        match.parent_match_b = source_match
        match.team_b_source_type = source_type


def assign_next_match(source_match, target_match, source_type):
    if source_type == MatchSourcePosition.WINNER:
        source_match.next_match = target_match
    else:
        source_match.loser_next_match = target_match
    source_match.save(
        update_fields=['next_match'] if source_type == MatchSourcePosition.WINNER else ['loser_next_match']
    )


def generate_single_elimination_matches(tournament, teams):
    bracket_size, _, total_rounds = calculate_bracket_size(len(teams))
    slots = get_seeded_slots(teams, bracket_size)

    winners_rounds = []
    first_round = []
    for index in range(bracket_size // 2):
        match = create_match(
            tournament=tournament,
            round_number=1,
            game_number=index + 1,
            bracket_type=BracketType.WINNERS,
            stage=get_match_stage(total_rounds, 1, bracket_size),
            match_format=get_match_format_for_round(1, total_rounds),
            team_a=slots[index * 2],
            team_b=slots[index * 2 + 1],
        )
        first_round.append(match)
    winners_rounds.append(first_round)

    for round_number in range(2, total_rounds + 1):
        round_matches = []
        previous_round = winners_rounds[-1]
        for index in range(len(previous_round) // 2):
            match = create_match(
                tournament=tournament,
                round_number=round_number,
                game_number=index + 1,
                bracket_type=BracketType.WINNERS,
                stage=get_match_stage(total_rounds, round_number, bracket_size),
                match_format=get_match_format_for_round(round_number, total_rounds),
            )
            source_a = previous_round[index * 2]
            source_b = previous_round[index * 2 + 1]
            connect_slot(match, 'team_a', source_a, MatchSourcePosition.WINNER)
            connect_slot(match, 'team_b', source_b, MatchSourcePosition.WINNER)
            match.save(update_fields=['parent_match_a', 'team_a_source_type', 'parent_match_b', 'team_b_source_type'])
            assign_next_match(source_a, match, MatchSourcePosition.WINNER)
            assign_next_match(source_b, match, MatchSourcePosition.WINNER)
            round_matches.append(match)
        winners_rounds.append(round_matches)


def generate_double_elimination_matches(tournament, teams):
    bracket_size, _, total_wb_rounds = calculate_bracket_size(len(teams))
    slots = get_seeded_slots(teams, bracket_size)
    winners_rounds = build_double_elimination_winners_rounds(
        tournament,
        slots,
        total_wb_rounds,
    )
    losers_rounds = build_dynamic_losers_rounds(
        tournament,
        winners_rounds,
        total_wb_rounds,
    )

    winners_final = winners_rounds[total_wb_rounds][0]
    losers_final = losers_rounds[-1][0]

    grand_final = create_match(
        tournament=tournament,
        round_number=1,
        game_number=1,
        bracket_type=BracketType.GRAND,
        stage=MatchStage.GRAND_FINAL,
        match_format=MatchFormat.BO5,
    )
    connect_slot(grand_final, 'team_a', winners_final, MatchSourcePosition.WINNER)
    connect_slot(grand_final, 'team_b', losers_final, MatchSourcePosition.WINNER)
    grand_final.save(update_fields=['parent_match_a', 'team_a_source_type', 'parent_match_b', 'team_b_source_type'])
    assign_next_match(winners_final, grand_final, MatchSourcePosition.WINNER)
    assign_next_match(losers_final, grand_final, MatchSourcePosition.WINNER)

    grand_reset = create_match(
        tournament=tournament,
        round_number=1,
        game_number=1,
        bracket_type=BracketType.GRAND_RESET,
        stage=MatchStage.GRAND_FINAL_RESET,
        match_format=MatchFormat.BO5,
    )
    connect_slot(grand_reset, 'team_a', grand_final, MatchSourcePosition.LOSER)
    connect_slot(grand_reset, 'team_b', grand_final, MatchSourcePosition.WINNER)
    grand_reset.save(update_fields=['parent_match_a', 'team_a_source_type', 'parent_match_b', 'team_b_source_type'])


def build_double_elimination_winners_rounds(tournament, slots, total_wb_rounds):
    """
    Build winners bracket rounds for double elimination.
    
    Properly handles bye teams by creating them as regular Round 1 matches
    so the bracket structure is clean and all teams appear active from Round 1.
    """
    winners_rounds = {round_number: [] for round_number in range(1, total_wb_rounds + 1)}
    previous_sources = []
    round_one_game_number = 1

    for index in range(len(slots) // 2):
        team_a = slots[index * 2]
        team_b = slots[index * 2 + 1]

        # Create Round 1 match - will be bye if one or both teams missing
        match = create_match(
            tournament=tournament,
            round_number=1,
            game_number=round_one_game_number,
            bracket_type=BracketType.WINNERS,
            stage=get_double_elim_stage(total_wb_rounds, 1, True),
            match_format=MatchFormat.BO1,  # Use BO1 for bye matches
            team_a=team_a,
            team_b=team_b,
        )
        winners_rounds[1].append(match)
        previous_sources.append(match)
        round_one_game_number += 1

    for round_number in range(2, total_wb_rounds + 1):
        current_sources = []
        game_number = 1
        for index in range(0, len(previous_sources), 2):
            source_a = previous_sources[index]
            source_b = previous_sources[index + 1] if index + 1 < len(previous_sources) else None

            if not source_a and not source_b:
                current_sources.append(None)
                continue

            match = create_match(
                tournament=tournament,
                round_number=round_number,
                game_number=game_number,
                bracket_type=BracketType.WINNERS,
                stage=get_double_elim_stage(total_wb_rounds, round_number, True),
                match_format=get_match_format_for_round(round_number, total_wb_rounds),
            )
            attach_match_slot(match, 'team_a', build_match_slot(source_a, MatchSourcePosition.WINNER))
            attach_match_slot(match, 'team_b', build_match_slot(source_b, MatchSourcePosition.WINNER))
            match.save()

            register_target_match(build_match_slot(source_a, MatchSourcePosition.WINNER), match)
            register_target_match(build_match_slot(source_b, MatchSourcePosition.WINNER), match)

            winners_rounds[round_number].append(match)
            current_sources.append(match)
            game_number += 1

        previous_sources = current_sources

    return winners_rounds


def build_dynamic_losers_rounds(tournament, winners_rounds, total_wb_rounds):
    losers_rounds = []
    carry_slots = []
    lb_round_number = 1

    for wb_round_number in range(1, total_wb_rounds + 1):
        wb_matches = winners_rounds[wb_round_number]
        loser_slots = [
            build_match_slot(match, MatchSourcePosition.LOSER)
            for match in wb_matches
        ]

        if wb_round_number == 1:
            current_slots = loser_slots
            target_survivors = max(1, math.ceil(len(current_slots) / 2)) if current_slots else 0
        else:
            current_slots = interleave_slots(carry_slots, loser_slots)
            target_survivors = len(winners_rounds.get(wb_round_number + 1, [])) or 1

        phase_created_matches = []
        while len(current_slots) > target_survivors:
            round_matches, current_slots = build_losers_round(
                tournament,
                current_slots,
                lb_round_number,
            )
            losers_rounds.append(round_matches)
            phase_created_matches.extend(round_matches)
            lb_round_number += 1

        if not phase_created_matches and len(current_slots) == 1:
            round_matches, current_slots = build_losers_round(
                tournament,
                current_slots,
                lb_round_number,
            )
            losers_rounds.append(round_matches)
            lb_round_number += 1

        carry_slots = current_slots

    apply_losers_round_metadata(losers_rounds)
    return losers_rounds


def build_match_slot(source_match, source_type):
    if not source_match:
        return None
    return {
        'match': source_match,
        'source_type': source_type,
    }


def interleave_slots(existing_slots, new_slots):
    ordered = []
    max_length = max(len(existing_slots), len(new_slots))
    for index in range(max_length):
        if index < len(existing_slots):
            ordered.append(existing_slots[index])
        if index < len(new_slots):
            ordered.append(new_slots[index])
    return ordered


def build_losers_round(tournament, slots, round_number):
    round_matches = []
    next_round_slots = []
    game_number = 1

    for index in range(0, len(slots), 2):
        slot_a = slots[index]
        slot_b = slots[index + 1] if index + 1 < len(slots) else None

        match = create_match(
            tournament=tournament,
            round_number=round_number,
            game_number=game_number,
            bracket_type=BracketType.LOSERS,
            stage=MatchStage.QUALIFIER,
            match_format=MatchFormat.BO1,
        )
        attach_match_slot(match, 'team_a', slot_a)
        attach_match_slot(match, 'team_b', slot_b)
        match.save()

        register_target_match(slot_a, match)
        register_target_match(slot_b, match)

        round_matches.append(match)
        next_round_slots.append(build_match_slot(match, MatchSourcePosition.WINNER))
        game_number += 1

    return round_matches, next_round_slots


def attach_match_slot(match, slot_name, slot):
    if not slot:
        return
    if slot.get('team'):
        setattr(match, slot_name, slot['team'])
        return
    connect_slot(match, slot_name, slot['match'], slot['source_type'])


def register_target_match(slot, target_match):
    if not slot or not slot.get('match'):
        return
    assign_next_match(slot['match'], target_match, slot['source_type'])


def apply_losers_round_metadata(losers_rounds):
    total_rounds = len(losers_rounds)
    for round_index, round_matches in enumerate(losers_rounds, start=1):
        stage = MatchStage.LOSERS_FINAL if round_index == total_rounds else MatchStage.QUALIFIER
        if round_index == total_rounds:
            match_format = MatchFormat.BO5
        elif round_index >= max(1, total_rounds - 2):
            match_format = MatchFormat.BO3
        else:
            match_format = MatchFormat.BO1

        for match in round_matches:
            match.stage = stage
            match.match_format = match_format
            match.save(update_fields=['stage', 'match_format'])


def generate_round_robin_matches(tournament, teams):
    """Generate round robin matches where every team plays every other team."""
    match_id = 1
    for first_index in range(len(teams)):
        for second_index in range(first_index + 1, len(teams)):
            create_match(
                tournament=tournament,
                round_number=1,
                game_number=match_id,
                bracket_type=BracketType.WINNERS,
                stage=MatchStage.GROUP_STAGE,
                match_format=MatchFormat.BO3,
                team_a=teams[first_index],
                team_b=teams[second_index],
            )
            match_id += 1


def get_match_stage(total_rounds, current_round, perfect_size):
    """Determine match stage for single elimination."""
    if total_rounds == 1 or current_round == total_rounds:
        return MatchStage.FINAL
    if current_round == total_rounds - 1:
        return MatchStage.SEMI_FINAL
    if current_round == total_rounds - 2:
        return MatchStage.QUARTER_FINAL
    if current_round == total_rounds - 3 and perfect_size >= 16:
        return MatchStage.PLAY_IN
    return MatchStage.QUALIFIER


def get_double_elim_stage(total_rounds, current_round, is_winners):
    """Determine stage names for double elimination."""
    if is_winners:
        if current_round == total_rounds:
            return MatchStage.WINNERS_FINAL
        if current_round == total_rounds - 1:
            return MatchStage.SEMI_FINAL
        if current_round == total_rounds - 2:
            return MatchStage.QUARTER_FINAL
        return MatchStage.QUALIFIER

    final_losers_round = max(1, (total_rounds - 1) * 2)
    if current_round == final_losers_round:
        return MatchStage.LOSERS_FINAL
    return MatchStage.QUALIFIER


def get_match_format_for_round(current_round, total_rounds):
    """Determine match format based on round importance."""
    if current_round == total_rounds:
        return MatchFormat.BO5
    if current_round >= total_rounds - 2:
        return MatchFormat.BO3
    return MatchFormat.BO1


def get_match_format_for_losers_round(current_round, total_wb_rounds):
    final_losers_round = max(1, (total_wb_rounds - 1) * 2)
    if current_round == final_losers_round:
        return MatchFormat.BO5
    if current_round >= final_losers_round - 2:
        return MatchFormat.BO3
    return MatchFormat.BO1


def get_bracket_structure(tournament):
    """Group bracket data for template rendering."""
    grouped = {
        BracketType.WINNERS: {},
        BracketType.LOSERS: {},
        BracketType.GRAND: {},
        BracketType.GRAND_RESET: {},
    }
    winners_seed_byes = []

    matches = tournament.matches.select_related(
        'team_a',
        'team_b',
        'winner',
        'bye_team',
        'next_match',
        'loser_next_match',
    ).order_by('bracket_type', 'round_number', 'game_number')

    for match in matches:
        if match.bracket_type == BracketType.WINNERS and match.round_number == 0:
            winners_seed_byes.append(match)
            continue
        grouped.setdefault(match.bracket_type, {})
        grouped[match.bracket_type].setdefault(match.round_number, [])
        grouped[match.bracket_type][match.round_number].append(match)

    sections = []
    for bracket_type in [BracketType.WINNERS, BracketType.LOSERS, BracketType.GRAND, BracketType.GRAND_RESET]:
        rounds = grouped.get(bracket_type, {})
        if not rounds:
            continue
        section = {
            'bracket_type': bracket_type,
            'title': dict(BracketType.choices).get(bracket_type, bracket_type),
            'rounds': [
                {
                    'round_number': round_number,
                    'title': get_round_title(bracket_type, round_number, round_matches),
                    'matches': round_matches,
                }
                for round_number, round_matches in sorted(rounds.items())
            ],
        }
        if bracket_type == BracketType.WINNERS:
            section['seed_byes'] = winners_seed_byes
        sections.append(
            section
        )

    return sections


def get_round_title(bracket_type, round_number, matches):
    if matches:
        stage_display = matches[0].get_stage_display()
        if bracket_type in [BracketType.GRAND, BracketType.GRAND_RESET]:
            return stage_display
        return f"Round {round_number} - {stage_display}"
    return f"Round {round_number}"


def sync_tournament_matches(tournament):
    matches = list(
        tournament.matches.select_related(
            'team_a',
            'team_b',
            'winner',
            'bye_team',
            'parent_match_a',
            'parent_match_b',
        ).order_by('round_number', 'game_number')
    )
    matches.sort(key=lambda match: (BRACKET_SYNC_ORDER.get(match.bracket_type, 99), match.round_number, match.game_number))

    for match in matches:
        sync_match_from_sources(match)


def sync_match_from_sources(match):
    grand_final = None
    if match.bracket_type == BracketType.GRAND_RESET and match.parent_match_a_id:
        grand_final = Match.objects.select_related('team_a', 'team_b', 'winner').get(id=match.parent_match_a_id)
    if match.bracket_type == BracketType.GRAND_RESET and not should_activate_grand_reset(grand_final):
        clear_dynamic_match(match)
        return

    team_a_state, team_a = resolve_slot(match.parent_match_a, match.team_a_source_type, match.team_a)
    team_b_state, team_b = resolve_slot(match.parent_match_b, match.team_b_source_type, match.team_b)

    match.team_a = team_a
    match.team_b = team_b

    final_state_changed = False

    if team_a and team_b:
        match.is_bye = False
        match.bye_team = None
        if is_valid_completed_match(match):
            match.status = Match.MatchStatus.COMPLETED
        elif has_any_scores(match):
            match.status = Match.MatchStatus.IN_PROGRESS
            match.winner = None
        else:
            match.status = Match.MatchStatus.READY
            match.winner = None
            match.team_a_score = None
            match.team_b_score = None
        final_state_changed = True
    elif team_a or team_b:
        if 'pending' in [team_a_state, team_b_state]:
            match.is_bye = False
            match.bye_team = None
            match.winner = None
            match.team_a_score = None
            match.team_b_score = None
            match.status = Match.MatchStatus.WAITING
        else:
            bye_team = team_a or team_b
            match.is_bye = True
            match.bye_team = bye_team
            match.winner = bye_team
            match.team_a_score = None
            match.team_b_score = None
            match.status = Match.MatchStatus.BYE
        final_state_changed = True
    else:
        if team_a_state == 'pending' or team_b_state == 'pending':
            match.is_bye = False
            match.bye_team = None
            match.winner = None
            match.team_a_score = None
            match.team_b_score = None
            match.status = Match.MatchStatus.WAITING
        else:
            match.is_bye = True
            match.bye_team = None
            match.winner = None
            match.team_a_score = None
            match.team_b_score = None
            match.status = Match.MatchStatus.BYE
        final_state_changed = True

    if not final_state_changed:
        match.status = Match.MatchStatus.WAITING

    if match.status != Match.MatchStatus.COMPLETED:
        if match.status != Match.MatchStatus.IN_PROGRESS:
            match.team_a_score = None
            match.team_b_score = None
        if match.status != Match.MatchStatus.BYE:
            match.is_bye = False
            match.bye_team = None

    match.save()


def should_activate_grand_reset(grand_final):
    return (
        grand_final is not None
        and grand_final.status in FINAL_MATCH_STATUSES
        and grand_final.winner_id is not None
        and grand_final.team_b_id is not None
        and grand_final.winner_id == grand_final.team_b_id
    )


def clear_dynamic_match(match):
    match.team_a = None
    match.team_b = None
    match.team_a_score = None
    match.team_b_score = None
    match.winner = None
    match.status = Match.MatchStatus.WAITING
    match.is_bye = False
    match.bye_team = None
    match.save()


def resolve_slot(source_match, source_type, fixed_team):
    if not source_match or not source_type:
        return ('team', fixed_team) if fixed_team else ('empty', None)

    source_match = Match.objects.select_related('team_a', 'team_b', 'winner').get(id=source_match.id)

    if source_match.status not in FINAL_MATCH_STATUSES:
        return 'pending', None

    if source_type == MatchSourcePosition.WINNER:
        if source_match.winner:
            return 'team', source_match.winner
        return 'empty', None

    loser = get_match_loser(source_match)
    if loser:
        return 'team', loser
    return 'empty', None


def get_match_loser(match):
    if match.status not in FINAL_MATCH_STATUSES:
        return None
    if match.is_bye:
        return None
    if not match.team_a_id or not match.team_b_id or not match.winner_id:
        return None
    if match.winner_id == match.team_a_id:
        return match.team_b
    if match.winner_id == match.team_b_id:
        return match.team_a
    return None


def is_valid_completed_match(match):
    if not match.team_a_id or not match.team_b_id:
        return False
    if not match.winner_id:
        return False
    if match.winner_id not in [match.team_a_id, match.team_b_id]:
        return False
    return match.team_a_score is not None and match.team_b_score is not None


def has_any_scores(match):
    return match.team_a_score is not None or match.team_b_score is not None


def validate_match_result(match, winner_team_id, team_a_score, team_b_score):
    if match.status in FINAL_MATCH_STATUSES and not match.is_bye:
        return 'Match already completed', None
    if match.is_bye:
        return 'Bye matches advance automatically', None
    if not match.team_a or not match.team_b:
        return 'Both teams must be assigned before recording a result', None
    if winner_team_id is None:
        return 'A winner must be selected', None
    if team_a_score is None or team_b_score is None:
        return 'Both teams must have recorded scores', None

    try:
        team_a_score = int(team_a_score)
        team_b_score = int(team_b_score)
    except (TypeError, ValueError):
        return 'Scores must be whole numbers', None

    if team_a_score < 0 or team_b_score < 0:
        return 'Scores cannot be negative', None

    winner = Team.objects.filter(id=winner_team_id).first()
    if winner is None or winner.id not in [match.team_a_id, match.team_b_id]:
        return 'Winner must be one of the assigned teams', None

    required_wins = match.get_required_wins()
    if max(team_a_score, team_b_score) != required_wins:
        return f'The winner must have exactly {required_wins} wins', None
    if team_a_score == team_b_score:
        return 'Tied scores are not valid for elimination matches', None
    if min(team_a_score, team_b_score) >= required_wins:
        return 'The losing team score is too high for this match format', None

    expected_winner_id = match.team_a_id if team_a_score > team_b_score else match.team_b_id
    if winner.id != expected_winner_id:
        return 'Selected winner does not match the submitted scoreline', None

    return None, winner


def advance_match(match_id, winner_team_id, team_a_score, team_b_score):
    """Advance a match result and update the bracket."""
    match = Match.objects.select_related('tournament', 'team_a', 'team_b').get(id=match_id)

    error, winner = validate_match_result(match, winner_team_id, team_a_score, team_b_score)
    if error:
        return {'error': error}

    match.team_a_score = int(team_a_score)
    match.team_b_score = int(team_b_score)
    match.winner = winner
    match.save(update_fields=['team_a_score', 'team_b_score', 'winner'])

    sync_tournament_matches(match.tournament)

    return {
        'winner': winner.name,
        'tournament_complete': match.tournament.is_complete(),
        'next_match': match.next_match.id if match.next_match else None,
    }
