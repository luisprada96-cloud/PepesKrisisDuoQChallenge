"""Only ranked games started on/after 15 October 2026 in Madrid count."""
import math
from datetime import datetime
from zoneinfo import ZoneInfo

MIN_START_TIMESTAMP = int(datetime(2026, 10, 15, tzinfo=ZoneInfo('Europe/Madrid')).timestamp())
MIN_START_ISO = '2026-10-15T00:00:00+02:00'


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
                or match.get('queueId') not in (None, 420)):
            continue
        duration = match.get('durationSeconds')
        if isinstance(duration, (int, float)) and 0 < duration < minimum_duration:
            continue
        if match.get('result') in ('WIN', 'LOSS'):
            results.setdefault(mid, match['result'])
    wins = sum(result == 'WIN' for result in results.values())
    losses = sum(result == 'LOSS' for result in results.values())
    return {'wins': wins, 'losses': losses, 'games': wins + losses}
