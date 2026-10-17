"""Read-only tournament champion album from stored participant evidence."""
import json
import math
import unicodedata
from collections import Counter
from pathlib import Path

from pickem_service import champion_key
from weekly_summary import game_time, timestamp

CATALOG = json.loads((Path(__file__).parent / 'assets' / 'pickem' / 'champions.json').read_text(encoding='utf-8'))
OPTIONS = CATALOG['champions']
LOOKUP = {champion_key(value): row['id'] for row in OPTIONS for value in (row['id'], row['label'])}


def build_album(db, minimum_duration=600):
    config = db.get('config') or {}
    start, end = timestamp(config.get('startDate')), timestamp(config.get('endDate'))
    if not start or end <= start:
        raise ValueError('El calendario del torneo no está configurado.')
    counts, games, pending, candidates = Counter(), set(), set(), []
    for duo in db.get('duos', []):
        pending.update((duo.get('riotMatchDiscovery') or {}).get('pendingMatchIds', []))
        excluded = duo.get('excludedRiotMatches') or {}
        for match in duo.get('history', []):
            mid = match.get('matchId')
            if not mid or mid in excluded or match.get('isTest') or match.get('queueId') not in (None, 420):
                continue
            if not start <= game_time(match) < end:
                continue
            duration = match.get('durationSeconds')
            if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not math.isfinite(duration) or duration <= 0:
                began = match.get('gameStartTimestamp')
                duration = (match['gameEndTimestamp'] - began) / 1000 if isinstance(began, (int, float)) and began > 0 else None
            if duration is not None and 0 < duration < minimum_duration:
                continue
            games.add(mid)
            for key, legacy in (('player1', 'championP1'), ('player2', 'championP2')):
                player = duo.get(key) or {}
                stats = match.get(key + 'Stats')
                if not player.get('name') and not isinstance(stats, dict):
                    continue
                checked = (match.get('participantsChecked') or {}).get(key)
                if not isinstance(stats, dict):
                    # A resolved account absent from the match is not a missing import.
                    if checked is True:
                        continue
                    pending.add(mid)
                    stats = {}
                name = stats.get('championName') or match.get(legacy)
                champion = LOOKUP.get(champion_key(name))
                if not champion:
                    pending.add(mid)
                    continue
                uid = stats.get('puuid') or player.get('puuid')
                participant = stats.get('participantId')
                markers = {(mid, 'slot', duo.get('id'), key)}
                if uid:
                    markers.add((mid, 'account', str(uid)))
                if participant:
                    markers.add((mid, 'participant', str(participant)))
                candidates.append((bool(stats.get('championName')), champion, mid, markers))
    # Prefer full participant evidence over a duplicated legacy row.
    seen = set()
    for _, champion, mid, markers in sorted(candidates, key=lambda row: row[0], reverse=True):
        duplicate = bool(markers & seen)
        seen.update(markers)
        if not duplicate:
            counts[champion] += 1
    champions = [{'id': row['id'], 'name': row['label'], 'games': counts[row['id']],
                  'played': counts[row['id']] > 0} for row in OPTIONS]
    def order(row):
        name = ''.join(c for c in unicodedata.normalize('NFKD', row['name']) if not unicodedata.combining(c))
        return -row['games'], name.casefold(), row['id']
    champions.sort(key=order)
    return {'champions': champions, 'catalogVersion': CATALOG['version'],
            'totalChampions': len(champions), 'playedChampions': sum(row['played'] for row in champions),
            'totalPicks': sum(counts.values()), 'totalMatches': len(games),
            'pendingMatches': len(pending), 'lastRiotApiSuccessAt': db.get('lastRiotApiSuccessAt')}
