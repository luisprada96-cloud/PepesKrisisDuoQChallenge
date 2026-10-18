"""Read-only cumulative combat series, one per participant across their accounts."""
import math

import player_accounts
import riot_match_policy
from weekly_summary import timestamp

METRICS = ('kills', 'deaths', 'assists')


def combat_values(stats):
    return all(isinstance(stats.get(key), int) and not isinstance(stats[key], bool) and stats[key] >= 0 for key in METRICS)


def build_progression(db, minimum_duration=600):
    end = timestamp((db.get('config') or {}).get('endDate')) or None
    people, pending, seen = [], set(), set()
    for duo in db.get('duos', []):
        pending.update((duo.get('riotMatchDiscovery') or {}).get('pendingMatchIds', []))
        excluded = duo.get('excludedRiotMatches') or {}
        candidates = {key: {} for key in ('player1', 'player2')}
        for match in duo.get('history', []):
            mid = match.get('matchId')
            if not mid or mid in excluded or match.get('isTest') or match.get('queueId') not in (None, 420):
                continue
            began = riot_match_policy.match_timestamp_ms(match)
            ended = riot_match_policy.match_timestamp_ms({'gameEndTimestamp': match.get('gameEndTimestamp')}) or began
            if began is None or ended is None:
                pending.add(mid)
                continue
            if began < riot_match_policy.MIN_START_TIMESTAMP * 1000 or (end and ended >= end * 1000):
                continue
            duration = match.get('durationSeconds')
            if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not math.isfinite(duration) or duration <= 0:
                raw_start = match.get('gameStartTimestamp')
                duration = (ended - raw_start)/1000 if isinstance(raw_start, (int, float)) and raw_start > 0 and ended > raw_start else None
            if duration is not None and 0 < duration < minimum_duration:
                continue
            for key in ('player1', 'player2'):
                player = duo.get(key) or {}
                if not player.get('name'):
                    continue
                stats = match.get(key+'Stats')
                if not isinstance(stats, dict):
                    if (match.get('participantsChecked') or {}).get(key) is not True:
                        pending.add(mid)
                    continue
                if not player_accounts.owns_stats(player, stats):
                    continue
                complete = combat_values(stats)
                previous = candidates[key].get(mid)
                if previous is None or (complete and not combat_values(previous[1])):
                    candidates[key][mid] = (ended, stats)
        for key in ('player1', 'player2'):
            player = duo.get(key) or {}
            if not player.get('name'):
                continue
            totals = {metric: 0 for metric in METRICS}
            points = []
            for mid, (at, stats) in sorted(candidates[key].items(), key=lambda item: (item[1][0], item[0])):
                if not combat_values(stats):
                    pending.add(mid)
                    continue
                markers = {(mid, 'slot', duo.get('id'), key)}
                if stats.get('puuid'):
                    markers.add((mid, 'account', str(stats['puuid'])))
                if stats.get('participantId'):
                    markers.add((mid, 'participant', str(stats['participantId'])))
                duplicate = bool(markers & seen)
                seen.update(markers)
                if duplicate:
                    continue
                for metric in METRICS:
                    totals[metric] += stats[metric]
                points.append({'game': len(points)+1, **totals})
            people.append({'id': f"{duo['id']}:{key}", 'name': player.get('displayName') or player['name'],
                           'teamName': duo.get('teamName') or 'Equipo', 'games': len(points),
                           'points': points, 'totals': totals})
    return {'players': people, 'pendingMatches': len(pending), 'startTimestamp': riot_match_policy.MIN_START_TIMESTAMP,
            'endTimestamp': end}
