"""Only ranked games started on/after 15 October 2026 in Madrid count."""
import math
import copy
from datetime import datetime
from zoneinfo import ZoneInfo
import player_accounts as accounts

MIN_START_TIMESTAMP = int(datetime(2026, 10, 15, tzinfo=ZoneInfo('Europe/Madrid')).timestamp())
MIN_START_ISO = '2026-10-15T00:00:00+02:00'
PAIR_EXCLUSIONS = {'not_duo', 'not_same_team'}


def account_sources(duo):
    # ELO selection is deliberately not part of match eligibility.
    return [[[accounts.account_id(a), *accounts.identity(a)] for a in accounts.accounts(duo.get(key) or {})]
            for key in ('player1', 'player2')]


def required_players(duo):
    return [key for key in ('player1', 'player2') if accounts.accounts(duo.get(key) or {})]


def find_pair(duo, participants):
    if (not isinstance(participants, list) or not participants or
            any(not isinstance(p, dict) or not p.get('puuid') for p in participants)):
        raise ValueError('La partida no confirma sus participantes; se reintentará.')
    rows = {key: [p for p in participants if accounts.account_for_stats(duo.get(key) or {}, p)]
            for key in ('player1', 'player2')}
    for first in rows['player1']:
        for second in rows['player2']:
            if (first['puuid'] != second['puuid'] and first.get('teamId') in (100, 200)
                    and first.get('teamId') == second.get('teamId')):
                return {'player1': first, 'player2': second}
    return {key: rows[key][0] if rows[key] else None for key in rows}


def validate_pair(duo, found, resolved):
    """None means valid; absent evidence is retried, not permanently rejected."""
    keys = required_players(duo)
    missing = [key for key in keys if not found.get(key)]
    if missing:
        if any(not resolved.get(key) for key in missing):
            raise ValueError('Identidad de un integrante pendiente; se reintentará la partida.')
        return 'not_duo'
    if len(keys) < 2:
        return None  # Preserve explicitly supported individual profiles.
    first, second = found['player1'], found['player2']
    if first.get('puuid') == second.get('puuid'):
        return 'not_duo'
    if any(p.get('teamId') not in (100, 200) for p in (first, second)):
        raise ValueError('La partida no confirma los equipos de ambos integrantes; se reintentará.')
    return None if first['teamId'] == second['teamId'] else 'not_same_team'


def stored_pair_status(duo, match):
    """Tri-state proof from saved Match-V5 details: valid / invalid / unknown."""
    if len(required_players(duo)) < 2:
        return True
    found = {}
    for key in ('player1', 'player2'):
        player = duo.get(key) or {}
        stats = match.get(key + 'Stats')
        if stats:
            if accounts.account_for_stats(player, stats) is None:
                return None
            found[key] = stats
        elif ((match.get('participantsChecked') or {}).get(key) and
              all(a.get('puuid') for a in accounts.accounts(player)) and
              (match.get('accountSources') == account_sources(duo) or
               ('accountSources' not in match and all(len(accounts.accounts(duo.get(k) or {})) <= 1
                                                     for k in ('player1', 'player2'))))):
            return False
        else:
            return None
    try:
        return validate_pair(duo, found, {'player1': True, 'player2': True}) is None
    except ValueError:
        return None


def needs_pair_validation(duo, match):
    return bool(not match.get('isTest') and match.get('matchId') and stored_pair_status(duo, match) is None)


def pair_rechecks(duo):
    signature = account_sources(duo)
    return [mid for mid, record in duo.get('excludedRiotMatches', {}).items()
            if record.get('reason') in PAIR_EXCLUSIONS and record.get('accountSources') != signature]


def exclude_pair(duo, mid, reason, previous=None):
    excluded = duo.setdefault('excludedRiotMatches', {})
    old = excluded.get(mid) or {}
    record = {'reason': reason, 'accountSources': account_sources(duo)}
    # Keep old achievement ledgers for a possible later recheck, never re-award
    # them just because an additional account makes the match eligible.
    archive = previous or old.get('match')
    if archive:
        record['match'] = copy.deepcopy(archive)
    excluded[mid] = record


def prune_duo_history(duo):
    removed = []
    kept = []
    for match in duo.get('history', []):
        if not match.get('isTest') and match.get('matchId') and stored_pair_status(duo, match) is False:
            exclude_pair(duo, match['matchId'], 'not_duo', match)
            removed.append(match)
        else:
            kept.append(match)
    duo['history'] = kept
    return removed


def merge_exclusions(current, incoming, original):
    """Preserve concurrent manual exclusions, but permit roster-based rechecks."""
    excluded = copy.deepcopy(current.get('excludedRiotMatches', {}))
    old = original.get('excludedRiotMatches', {})
    for mid, record in incoming.get('excludedRiotMatches', {}).items():
        present = excluded.get(mid)
        if present is None or (present == old.get(mid) and present.get('reason') in PAIR_EXCLUSIONS):
            excluded[mid] = copy.deepcopy(record)
    for match in incoming.get('history', []):
        mid = match.get('matchId')
        present = excluded.get(mid)
        if (present and present == old.get(mid) and present.get('reason') in PAIR_EXCLUSIONS
                and stored_pair_status(current, match) is True):
            del excluded[mid]
    return excluded


def match_timestamp_ms(match):
    # A game crossing midnight belongs to the day when it started.
    # An older end timestamp is also sufficient evidence for legacy rows.
    for key in ('gameStartTimestamp', 'gameCreation', 'gameEndTimestamp'):
        value = match.get(key)
        if isinstance(value, bool):
            continue
        try:
            stamp = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(stamp) and stamp > 0:
            return stamp
    return None


def before_cutoff(match):
    stamp = match_timestamp_ms(match)
    return stamp is not None and stamp < MIN_START_TIMESTAMP * 1000


def exclusion(match):
    return {'reason': 'before_tournament_start', 'gameStartTimestamp': match_timestamp_ms(match),
            'minimumStartTimestamp': MIN_START_TIMESTAMP * 1000}


def prune_history(duo):
    """Retain valid rows and their ledgers; tombstones prevent stale reimports."""
    removed = [m for m in duo.get('history', []) if not m.get('isTest') and before_cutoff(m)]
    if not removed:
        return []
    removed_objects = {id(m) for m in removed}
    duo['history'] = [m for m in duo.get('history', []) if id(m) not in removed_objects]
    mids = {m['matchId'] for m in removed if m.get('matchId')}
    excluded = duo.setdefault('excludedRiotMatches', {})
    for match in removed:
        if match.get('matchId'):
            excluded[match['matchId']] = exclusion(match)
    owners = [duo]
    for key in ('player1', 'player2'):
        player = duo.get(key) or {}
        owners.extend([player, *player.get('accounts', [])])
    for owner in owners:
        for field in ('riotMatchDiscovery', 'matchDiscovery'):
            state = owner.get(field)
            if isinstance(state, dict):
                state['pendingMatchIds'] = [m for m in state.get('pendingMatchIds', []) if m not in mids]
        baseline = owner.get('flashBaseline') or {}
        if baseline.get('matchId') in mids or before_cutoff(baseline):
            owner.pop('flashBaseline', None)
    return removed


def history_record(duo, minimum_duration=600):
    """The challenge record is independent from a source account's season totals."""
    results = {}
    excluded = duo.get('excludedRiotMatches') or {}
    for match in duo.get('history', []):
        mid = match.get('matchId')
        if (not mid or mid in excluded or match.get('isTest') or match_timestamp_ms(match) is None or before_cutoff(match)
                or match.get('queueId') not in (None, 420) or stored_pair_status(duo, match) is False):
            continue
        duration = match.get('durationSeconds')
        if isinstance(duration, (int, float)) and 0 < duration < minimum_duration:
            continue
        if match.get('result') in ('WIN', 'LOSS'):
            results.setdefault(mid, match['result'])
    wins = sum(result == 'WIN' for result in results.values())
    losses = sum(result == 'LOSS' for result in results.values())
    return {'wins': wins, 'losses': losses, 'games': wins + losses}
