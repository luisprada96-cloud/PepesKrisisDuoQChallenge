"""Weekly clips and authenticated team votes, stored in the database document."""
import copy
import hashlib
import re
import time
import uuid
import weekly_summary
from clip_votes import MAX_TEAM_VOTES, browser_liked, vote_count
from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

MADRID = ZoneInfo('Europe/Madrid')
WEEKLY_REWARD_SHELLS = 3
PREVIEW_POSTS = [
    {'id': 'demo-1', 'title': 'Cinco contra uno. ¿Qué podía salir mal?', 'team': 'ELDUOYASS', 'initials': 'EY', 'duration': '0:32', 'scene': 1},
    {'id': 'demo-2', 'title': 'El robo de Nashor que nos devolvió la fe', 'team': 'Krisis', 'initials': 'KR', 'duration': '0:24', 'scene': 2},
    {'id': 'demo-3', 'title': 'Cuando el caparazón te obliga a jugar support', 'team': 'Pingu', 'initials': 'PI', 'duration': '0:41', 'scene': 3},
]


def week_key(now=None):
    day = (datetime.fromtimestamp(time.time() if now is None else now, MADRID)).date()
    return (day - timedelta(days=day.weekday())).isoformat()


def week_closes_at(week):
    monday = datetime.strptime(week, '%Y-%m-%d').replace(tzinfo=MADRID)
    if monday.weekday() != 0:
        raise ValueError('Invalid clips week')
    return (monday + timedelta(days=6, hours=23, minutes=59)).timestamp()


def settle_weekly_reward(db, now=None):
    """Award before pruning, once per week, in the same database transaction."""
    board = db.get('clips')
    if board is None:
        return False
    if not isinstance(board, dict) or not isinstance(board.get('posts'), list):
        raise ValueError('Invalid clips data')
    timestamp = time.time() if now is None else now
    closes_at = week_closes_at(board['week'])
    if timestamp < closes_at:
        return False
    ledger = db.setdefault('clipWeeklyRewards', {})
    if board['week'] in ledger:
        if board.get('weeklyAward') != ledger[board['week']]:
            board['weeklyAward'] = copy.deepcopy(ledger[board['week']])
            return True
        return False
    teams = {duo['id']: duo for duo in db.get('duos', [])}
    starts_at = datetime.strptime(board['week'], '%Y-%m-%d').replace(tzinfo=MADRID).timestamp()
    eligible = [post for post in board['posts'] if not post.get('example') and post.get('slug')
                and post.get('teamId') in teams and starts_at <= post.get('createdAt', 0) < closes_at]
    eligible.sort(key=lambda post: (-vote_count(post), post['createdAt'], post['id']))
    winner = eligible[0] if eligible and vote_count(eligible[0]) else None
    award = {'week': board['week'], 'closesAt': closes_at, 'settledAt': timestamp,
             'status': 'AWARDED' if winner else 'NO_WINNER', 'shells': WEEKLY_REWARD_SHELLS if winner else 0}
    if winner:
        team = teams[winner['teamId']]
        team['blueShells'] = int(team.get('blueShells', 0) or 0) + WEEKLY_REWARD_SHELLS
        team['clipShellsEarnedTotal'] = int(team.get('clipShellsEarnedTotal', 0) or 0) + WEEKLY_REWARD_SHELLS
        award.update(clipId=winner['id'], title=winner['title'], url=winner['url'],
                     teamId=team['id'], teamName=team['teamName'], votes=vote_count(winner))
        db.setdefault('events', []).insert(0, {
            'id': f"clip-week-{board['week']}", 'type': 'CLIP_WEEKLY_REWARD',
            'timestamp': datetime.fromtimestamp(timestamp, MADRID).strftime('%Y-%m-%d %H:%M:%S'),
            'week': board['week'], 'target': team['teamName'], 'teamId': team['id'],
            'clipId': winner['id'], 'shells': WEEKLY_REWARD_SHELLS,
            'message': f"🏆 {team['teamName']} gana {WEEKLY_REWARD_SHELLS} caparazones por el clip más votado de la semana: {winner['title']} ({award['votes']} likes)."})
    ledger[board['week']] = award
    board['weeklyAward'] = copy.deepcopy(award)
    return True


def board_for(db, preview=False, now=None):
    timestamp = time.time() if now is None else now
    week = week_key(timestamp)
    board = db.get('clips')
    if board is not None and (not isinstance(board, dict) or not isinstance(board.get('posts'), list)):
        raise ValueError('Invalid clips data')
    settled = settle_weekly_reward(db, timestamp)
    archived = weekly_summary.maintain(db, timestamp)
    if board is not None and board.get('week') == week:
        return board, settled or archived
    board = {'week': week, 'posts': []}
    ledger = db.get('clipWeeklyRewards', {})
    if ledger:
        board['previousWeeklyAward'] = copy.deepcopy(ledger[max(ledger)])
    if preview:
        for index, example in enumerate(PREVIEW_POSTS):
            post = copy.deepcopy(example)
            post.update(createdAt=timestamp - (5 - index * 2) * 3600, teamVotes={}, example=True)
            board['posts'].append(post)
    db['clips'] = board
    settle_weekly_reward(db, timestamp)
    return board, True


def visitor_hash(token):
    return hashlib.sha256(token.encode('ascii')).hexdigest()


def public_board(board, team_id=None, preview=False, duos=(), visitor=None):
    voter = next((duo for duo in duos if duo['id'] == team_id), None)
    posts = []
    for post in board['posts']:
        item = {key: post[key] for key in ('id', 'title', 'teamId', 'team', 'initials', 'duration', 'scene', 'createdAt', 'slug', 'url', 'example') if key in post}
        item.update(votes=vote_count(post), liked=bool(voter) and browser_liked(post, visitor))
        posts.append(item)
    return {'week': board['week'], 'preview': preview, 'clips': posts,
            'voting': {'teamId': voter['id'], 'teamName': voter['teamName']} if voter else None,
            'teams': [{'id': duo['id'], 'name': duo['teamName']} for duo in duos],
            'weeklyReward': {'shells': WEEKLY_REWARD_SHELLS, 'closesAt': week_closes_at(board['week']),
                             'closed': bool(board.get('weeklyAward')), 'award': board.get('weeklyAward'),
                             'previousAward': board.get('previousWeeklyAward')}}


def parse_url(value):
    if not isinstance(value, str):
        raise ValueError('Expected clip URL')
    url = urlparse(value.strip())
    if url.scheme != 'https' or url.username or url.password or url.port or url.params:
        raise ValueError('Invalid clip URL')
    parts = [part for part in url.path.split('/') if part]
    slug = None
    if url.hostname == 'clips.twitch.tv' and len(parts) == 1:
        slug = parts[0]
    elif url.hostname in ('twitch.tv', 'www.twitch.tv') and len(parts) == 3 and parts[1] == 'clip':
        slug = parts[2]
    if slug == 'embed' or not slug or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', slug):
        raise ValueError('Invalid clip URL')
    return slug


def publish(board, title, url, now=None, team=None):
    timestamp = time.time() if now is None else now
    if board.get('weeklyAward') or timestamp >= week_closes_at(board['week']):
        raise FileExistsError('La votación semanal ha cerrado. Podrás publicar de nuevo el lunes a las 00:00.')
    if not isinstance(team, dict) or not team.get('id') or not team.get('teamName'):
        raise ValueError('Selecciona un equipo válido al que representa el clip.')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
        raise ValueError('Invalid title')
    slug = parse_url(url)
    if any(post.get('slug') == slug for post in board['posts']):
        raise FileExistsError('Este clip ya está publicado esta semana.')
    if len(board['posts']) >= 200:
        raise OverflowError('Se ha alcanzado el máximo de clips de esta semana.')
    post = {'id': str(uuid.uuid4()), 'title': title.strip(), 'slug': slug,
            'url': f'https://clips.twitch.tv/{slug}', 'teamId': team['id'], 'team': team['teamName'],
            'initials': ''.join(word[0] for word in team['teamName'].split()[:2]).upper()[:2] or 'CL',
            'createdAt': timestamp, 'scene': 1, 'teamVotes': {}}
    board['posts'].append(post)
    return post


def set_like(board, clip_id, team_id, visitor, liked, now=None):
    if board.get('weeklyAward') or (time.time() if now is None else now) >= week_closes_at(board['week']):
        raise FileExistsError('La votación semanal ha cerrado. Los likes ya no se pueden cambiar.')
    if not isinstance(team_id, str) or not team_id:
        raise ValueError('Se necesita un equipo para votar.')
    if type(liked) is not bool or not isinstance(clip_id, str) or not isinstance(visitor, str) or not visitor:
        raise ValueError('Se necesita un clip válido y un estado de like verdadero o falso.')
    post = next((post for post in board['posts'] if post['id'] == clip_id), None)
    if post is None:
        raise LookupError('El clip ya no está disponible esta semana.')
    already_liked = browser_liked(post, visitor)
    if already_liked == liked:
        return False
    if not liked:
        if visitor in post.get('likedBy', []):
            post['likedBy'] = [value for value in post['likedBy'] if value != visitor]
        for owner, values in list(post.get('teamVotes', {}).items()):
            if isinstance(values, list) and visitor in values:
                remaining = sorted(set(values) - {visitor})
                if remaining:
                    post['teamVotes'][owner] = remaining
                else:
                    del post['teamVotes'][owner]
        return True
    stored = post.get('teamVotes', {}).get(team_id, [])
    # Older shared counters had no browser identity. Claim their reserved slots
    # without discarding a vote or adding a new one during the transition.
    voters = set(stored) if isinstance(stored, list) else {f'legacy:{i}' for i in range(stored)}
    reserved = next((value for value in sorted(voters) if value.startswith('legacy:')), None)
    if reserved:
        voters.remove(reserved)
    elif len(voters) >= MAX_TEAM_VOTES:
        raise OverflowError('Tu equipo ya ha dado el máximo de likes a este clip.')
    voters.add(visitor)
    post.setdefault('teamVotes', {})[team_id] = sorted(voters)
    return True
