"""Weekly public recaps from stored evidence, never from additional Riot calls."""
import copy
import time
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from clip_votes import vote_count

MADRID = ZoneInfo('Europe/Madrid')
VERSION = 1


def week_key(now=None):
    day = datetime.fromtimestamp(time.time() if now is None else now, MADRID).date()
    return (day - timedelta(days=day.weekday())).isoformat()


def bounds(week):
    start = datetime.strptime(week, '%Y-%m-%d').replace(tzinfo=MADRID)
    if start.weekday() != 0:
        raise ValueError('Invalid summary week')
    return start.timestamp(), (start + timedelta(days=7)).timestamp()


def timestamp(value):
    try:
        if isinstance(value, (float, int)):
            return float(value)
        date = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return date.replace(tzinfo=MADRID).timestamp() if date.tzinfo is None else date.timestamp()
    except (ValueError, TypeError, OverflowError):
        return 0


def game_time(match):
    # No guessing dates from localized display labels or win/loss totals.
    return timestamp(match.get('gameEndTimestamp', 0)) / 1000


def kda(totals, games):
    if not games:
        return None
    return round((totals['kills'] + totals['assists']) / max(1, totals['deaths']), 2)


def account(player):
    return [str(player.get('name', '')).strip().lower(), str(player.get('tag') or 'EUW').strip().lower()]


def elo_summary(player, start, end):
    points = sorted((p for p in player.get('eloHistory', []) if timestamp(p.get('observedAt')) < end
                     and timestamp(p.get('observedAt')) > 0 and p.get('source') != 'test'),
                    key=lambda p: timestamp(p['observedAt']))
    before = [p for p in points if timestamp(p['observedAt']) <= start]
    inside = [p for p in points if start <= timestamp(p['observedAt']) < end]
    first = before[-1] if before else inside[0] if inside else None
    last = points[-1] if inside else None
    def public(point):
        return {key: point.get(key) for key in ('tier', 'division', 'lp', 'observedAt')}
    comparable = first and last and timestamp(first['observedAt']) < timestamp(last['observedAt']) and all(
        p.get('tier', '').upper() != 'UNRANKED' and isinstance(p.get('totalLp'), (int, float)) for p in (first, last))
    return {'start': public(first) if first else None, 'end': public(last) if last else None,
            'delta': last['totalLp'] - first['totalLp'] if comparable else None,
            'partial': not bool(before), 'observations': len(inside)}


def clip_stats(db, board):
    start, end = bounds(board['week'])
    posts = [p for p in board.get('posts', []) if not p.get('example') and p.get('slug')
             and start <= timestamp(p.get('createdAt')) < end]
    teams = Counter(p.get('teamId') for p in posts if p.get('teamId'))
    votes = sum(vote_count(p) for p in posts)
    award = db.get('clipWeeklyRewards', {}).get(board['week']) or board.get('weeklyAward')
    winner = {k: award[k] for k in ('status', 'clipId', 'title', 'url', 'teamId', 'teamName', 'votes', 'shells') if k in award} if award else None
    return {'posts': len(posts), 'votes': votes, 'byTeam': dict(teams), 'winner': winner, 'available': True}


def build_summary(db, week, clips=None, previous=None):
    start, end = bounds(week)
    in_week = lambda value: start <= timestamp(value) < end
    all_games = set()
    teams = []
    for duo in db.get('duos', []):
        seen = set()
        games = []
        matches = {}
        for match in duo.get('history', []):
            mid = match.get('matchId')
            if mid and not match.get('isTest'):
                matches[mid] = match
                if mid not in seen and start <= game_time(match) < end:
                    seen.add(mid)
                    games.append(match)
                    all_games.add(mid)
        games.sort(key=lambda m: (game_time(m), m['matchId']))
        wins = sum(m.get('result') == 'WIN' for m in games)
        losses = sum(m.get('result') == 'LOSS' for m in games)
        run = best_run = 0
        for match in games:
            run = run + 1 if match.get('result') == 'WIN' else 0
            best_run = max(best_run, run)
        players = []
        combined = {'kills': 0, 'deaths': 0, 'assists': 0}
        detail_games = 0
        best_match = None
        for key in ('player1', 'player2'):
            player = duo.get(key) or {}
            totals = {'kills': 0, 'deaths': 0, 'assists': 0}
            champions = Counter()
            played = player_wins = 0
            for match in games:
                stats = match.get(key + 'Stats')
                if not isinstance(stats, dict) or (player.get('puuid') and stats.get('puuid') and player['puuid'] != stats['puuid']):
                    continue
                if not all(isinstance(stats.get(k), (int, float)) for k in totals):
                    continue
                played += 1
                player_wins += stats.get('win') is True
                for field in totals:
                    totals[field] += stats[field]
                champion = stats.get('championName')
                if champion and champion != 'Unknown':
                    champions[champion] += 1
            for field in combined:
                combined[field] += totals[field]
            favorite = sorted(champions, key=lambda c: (-champions[c], c))
            players.append({'key': key, 'name': player.get('displayName') or player.get('name') or ('Integrante 1' if key == 'player1' else 'Integrante 2'),
                            'riotId': f"{player.get('name', '')}#{player.get('tag') or 'EUW'}" if player.get('name') else '',
                            'account': account(player), 'games': played, 'wins': player_wins, 'totals': totals,
                            'kda': kda(totals, played), 'mainRole': player.get('mainRole'),
                            'favorite': {'name': favorite[0], 'games': champions[favorite[0]]} if favorite else None,
                            'elo': elo_summary(player, start, end), 'penaltiesCompleted': 0})
        for match in games:
            stats = [match.get(k + 'Stats') for k in ('player1', 'player2')]
            if not all(isinstance(p, dict) and all(isinstance(p.get(f), (int, float)) for f in combined) for p in stats):
                continue
            # Only a complete pair can be called the duo's best match.
            if any((duo.get(key) or {}).get('puuid') and p.get('puuid') and duo[key]['puuid'] != p['puuid']
                   for key, p in zip(('player1', 'player2'), stats)):
                continue
            detail_games += 1
            totals = {f: sum(p[f] for p in stats) for f in combined}
            score = kda(totals, 1)
            candidate = {'matchId': match['matchId'], 'at': game_time(match), 'totals': totals, 'kda': score,
                         'champions': [p.get('championName', '') for p in stats]}
            if best_match is None or (score, totals['kills'] + totals['assists'], -totals['deaths']) > (
                    best_match['kda'], best_match['totals']['kills'] + best_match['totals']['assists'], -best_match['totals']['deaths']):
                best_match = candidate
        shells = {'launched': 0, 'received': 0, 'returned': 0, 'achievements': 0, 'credited': 0, 'blocked': 0, 'creditUnknown': 0, 'clipPrize': 0}
        for attack in db.get('shellAttacks', []):
            if not in_week(attack.get('launchedAt')):
                continue
            if attack.get('attackerTeamId') == duo.get('id'):
                shells['returned' if attack.get('returnedFromAttackId') else 'launched'] += 1
            if attack.get('targetTeamId') == duo.get('id'):
                shells['received'] += 1
        for match in games:
            for rule in match.get('shellRewardIds', []):
                shells['achievements'] += 1
                credited = match.get('shellRewardCredits', {}).get(rule)
                shells['credited' if credited is True else 'blocked' if credited is False else 'creditUnknown'] += 1
        award = (clips or {}).get('winner') or {}
        if award.get('teamId') == duo.get('id'):
            shells['clipPrize'] = award.get('shells', 0)
        penalties = {'received': 0, 'completed': 0, 'manual': 0, 'pending': 0}
        for debuff in duo.get('activeDebuffs', []):
            assigned = timestamp(debuff.get('assignedAt')) or timestamp(debuff.get('assignedAtEpochMs')) / 1000
            if not assigned or assigned >= end:
                continue
            penalties['received'] += start <= assigned < end
            manual = bool(debuff.get('manualResolution'))
            evidence = matches.get(debuff.get('resolvedByMatchId'))
            resolved = timestamp(debuff.get('resolvedAt')) if manual or evidence is None else game_time(evidence)
            retired = timestamp(debuff.get('retiredAt'))
            completed = debuff.get('status') == 'COMPLETED' or debuff.get('resolved')
            if completed and in_week(resolved):
                penalties['manual' if manual else 'completed'] += 1
                key = debuff.get('requirements', {}).get('assignedPlayer')
                assigned_account = debuff.get('requirements', {}).get('assignedAccount') or {}
                same_account = not assigned_account.get('name') or account(assigned_account) == account(duo.get(key) or {})
                if not manual and same_account and (debuff.get('scope') or debuff.get('penalty', {}).get('scope')) == 'ONE' and key in ('player1', 'player2'):
                    players[0 if key == 'player1' else 1]['penaltiesCompleted'] += 1
            if (not completed or not resolved or resolved >= end) and (debuff.get('status') != 'CANCELLED' or retired >= end):
                penalties['pending'] += 1
        teams.append({'id': duo['id'], 'name': duo.get('teamName', 'Equipo'), 'matchIds': sorted(seen), 'games': len(games), 'wins': wins, 'losses': losses,
                      'winrate': round(100 * wins / (wins + losses)) if wins + losses else None, 'bestStreak': best_run,
                      'totals': combined, 'kda': kda(combined, sum(p['games'] for p in players)),
                      'detailGames': detail_games, 'bestMatch': best_match, 'players': players, 'shells': shells, 'penalties': penalties})
    if previous:
        current = {t['id']: t for t in teams}
        for old in previous.get('teams', []):
            team = current.get(old['id'])
            if not team or team['games'] < old['games'] or [p['account'] for p in old['players']] != [p['account'] for p in team['players']]:
                current[old['id']] = copy.deepcopy(old)
            else:
                # Preserve labels and observations captured before renames or history cleanup.
                team['name'] = old['name']
                for player, saved in zip(team['players'], old['players']):
                    player['name'] = saved['name']
                    if player['elo']['end'] is None:
                        player['elo'] = copy.deepcopy(saved['elo'])
        teams = list(current.values())
    all_games = {mid for team in teams for mid in team['matchIds']}
    comparable = [{**p, 'teamId': t['id'], 'teamName': t['name']} for t in teams for p in t['players']
                  if p['elo']['delta'] is not None and not p['elo']['partial']]
    rising = sorted((p for p in comparable if p['elo']['delta'] > 0), key=lambda p: (-p['elo']['delta'], p['teamId'], p['key']))
    falling = sorted((p for p in comparable if p['elo']['delta'] < 0), key=lambda p: (p['elo']['delta'], p['teamId'], p['key']))
    attacks = sorted((t for t in teams if t['shells']['launched']), key=lambda t: (-t['shells']['launched'], t['id']))
    completed = sorted((dict(p, teamName=t['name']) for t in teams for p in t['players'] if p['penaltiesCompleted']),
                       key=lambda p: (-p['penaltiesCompleted'], p['teamName'], p['key']))
    return {'version': VERSION, 'week': week, 'startsAt': start, 'endsAt': end, 'teams': sorted(teams, key=lambda t: (t['name'].lower(), t['id'])),
            'totals': {'games': len(all_games), 'shellsLaunched': sum(t['shells']['launched'] for t in teams),
                       'penaltiesCompleted': sum(t['penalties']['completed'] for t in teams),
                       'penaltiesManual': sum(t['penalties']['manual'] for t in teams)},
            'highlights': {'rising': rising[0] if rising else None, 'falling': falling[0] if falling else None,
                           'attacker': attacks[0] if attacks else None, 'completed': completed[0] if completed else None},
            'clips': clips or {'available': False, 'posts': None, 'votes': None, 'byTeam': {}, 'winner': None}}


def maintain(db, now=None, refresh=False):
    """Archive before the old clips board is replaced; caller persists atomically."""
    now = time.time() if now is None else now
    current = week_key(now)
    changed = False
    if 'weeklySummaryFirstWeek' not in db:
        board_week = (db.get('clips') or {}).get('week', current)
        db['weeklySummaryFirstWeek'] = min(board_week, current)
        changed = True
    ledger = db.setdefault('weeklySummaries', {})
    board = db.get('clips')
    week = db['weeklySummaryFirstWeek']
    while week < current:
        old = ledger.get(week)
        # Clip totals must be captured before pruning even when no one visits the recap.
        clips = clip_stats(db, board) if board and board.get('week') == week else copy.deepcopy((old or {}).get('clips'))
        if old is None or refresh or (clips and clips != old.get('clips')):
            summary = build_summary(db, week, clips, old)
            payload = {k: v for k, v in (old or {}).items() if k not in ('archivedAt', 'updatedAt')}
            if summary != payload:
                summary.update(archivedAt=(old or {}).get('archivedAt', now), updatedAt=now)
                ledger[week] = summary
                changed = True
        week = datetime.fromtimestamp(bounds(week)[1], MADRID).date().isoformat()
    return changed


def public_payload(db, week=None, now=None):
    now = time.time() if now is None else now
    current = week_key(now)
    available = [current] + sorted(db.get('weeklySummaries', {}), reverse=True)
    selected = week or available[0]
    if selected not in available:
        raise LookupError('Resumen semanal no encontrado.')
    if selected == current:
        board = db.get('clips') or {}
        stats = clip_stats(db, board) if board.get('week') == current else None
        summary = build_summary(db, current, stats)
        summary['status'] = 'CURRENT'
    else:
        summary = copy.deepcopy(db['weeklySummaries'][selected])
        summary['status'] = 'ARCHIVED'
    return {'weeks': available, 'summary': summary, 'timezone': 'Europe/Madrid'}
