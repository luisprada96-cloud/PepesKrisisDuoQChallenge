"""The main position belongs to the person, across all registered Riot accounts."""
import math
from collections import Counter

import player_accounts
import riot_match_policy

POSITIONS = ('TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY')


def role_games(duo, key, before_ms=None):
    """One confirmed, non-remake Solo/Duo appearance per person and match."""
    player = duo.get(key) or {}
    if not player.get('name'):
        return []
    found = {}
    for match in duo.get('history', []):
        mid = match.get('matchId')
        if not mid or mid in (duo.get('excludedRiotMatches') or {}) or match.get('isTest') or match.get('queueId') not in (None, 420):
            continue
        stamp = riot_match_policy.match_timestamp_ms(match)
        if stamp is None or riot_match_policy.before_cutoff(match):
            continue
        end = match.get('gameEndTimestamp')
        end = end if isinstance(end, (int, float)) and not isinstance(end, bool) and math.isfinite(end) and end > 0 else stamp
        if before_ms is not None and end >= before_ms:
            continue
        duration = match.get('durationSeconds')
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not math.isfinite(duration) or duration <= 0:
            began = match.get('gameStartTimestamp')
            duration = (end-began)/1000 if isinstance(began, (int, float)) and 0 < began < end else None
        if duration is not None and 0 < duration < 600:
            continue
        stats = match.get(key+'Stats')
        if not isinstance(stats, dict) or str(stats.get('position') or '').upper() not in POSITIONS:
            continue
        if not player_accounts.owns_stats(player, stats):
            continue
        sources = player_accounts.accounts(player)
        source_match = player_accounts.account_for_stats(player, stats)
        if stats.get('riotIdGameName') and not source_match:
            identity = player_accounts.identity({'name':stats['riotIdGameName'],'tag':stats.get('riotIdTagline')})
            if not any(player_accounts.identity(a) == identity for a in sources):
                continue
        if stats.get('puuid') and not any(player_accounts.known_puuids(a) for a in sources) and not stats.get('riotIdGameName'):
            continue  # An edited identity must not inherit the previous account's games.
        if player.get('accounts') and (stats.get('puuid') or stats.get('riotIdGameName')) and not source_match:
            continue
        position = str(stats['position']).upper()
        quality = (bool(stats.get('puuid')), bool(stats.get('participantId')), -POSITIONS.index(position))
        if mid not in found or quality > found[mid][0]:
            found[mid] = (quality, end, match, stats)
    return [(match, stats, end) for _,end,match,stats in sorted(found.values(), key=lambda row:(row[1],str(row[2]['matchId'])))]


def role_summary(duo, key, before_ms=None):
    counts, latest = Counter(), {}
    for _,stats,end in role_games(duo, key, before_ms):
        position = str(stats['position']).upper()
        counts[position] += 1
        latest[position] = max(latest.get(position, 0), end)
    position = min(counts, key=lambda p:(-counts[p],-latest[p],POSITIONS.index(p))) if counts else None
    return {'position':position,'games':counts.get(position,0),'totalGames':sum(counts.values()),'counts':dict(counts)}


def update_roles(duo):
    changed = False
    for key in ('player1','player2'):
        player = duo.get(key)
        if not isinstance(player, dict) or not player.get('name'):
            continue
        summary = role_summary(duo, key)
        fields = {'mainRole':summary['position'],'mainRoleSource':'most_played',
                  'mainRoleGames':summary['games'],'mainRoleCounts':summary['counts']}
        if any(player.get(field) != value for field,value in fields.items()):
            player.update(fields)
            changed = True
    return changed
