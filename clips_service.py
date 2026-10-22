"""Weekly clips, authenticated team votes and guest discussions in the database."""
import copy
import hashlib
import hmac
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
COMMENT_NAME_LIMIT = 15
COMMENT_TEXT_LIMIT = 200
COMMENT_PAGE_SIZE = 10
COMMENT_MAX_PER_CLIP = 50
COMMENT_COOLDOWN = 15
COMMENT_HOURLY_LIMIT = 20


class CommentRateLimit(ValueError):
    def __init__(self, message, retry_after=COMMENT_COOLDOWN):
        super().__init__(message)
        self.retry_after = retry_after


PREVIEW_POSTS = [
    {'id': 'demo-1', 'title': 'Cinco contra uno. ¿Qué podía salir mal?', 'team': 'ELDUOYASS', 'initials': 'EY', 'duration': '0:32', 'scene': 1},
    {'id': 'demo-2', 'title': 'El robo de Nashor que nos devolvió la fe', 'team': 'Krisis', 'initials': 'KR', 'duration': '0:24', 'scene': 2},
    {'id': 'demo-3', 'title': 'Cuando el pepazo te obliga a jugar support', 'team': 'Pingu', 'initials': 'PI', 'duration': '0:41', 'scene': 3},
]


def week_key(now=None):
    day = (datetime.fromtimestamp(time.time() if now is None else now, MADRID)).date()
    return (day - timedelta(days=day.weekday())).isoformat()


def week_closes_at(week):
    monday = datetime.strptime(week, '%Y-%m-%d').replace(tzinfo=MADRID)
    if monday.weekday() != 0:
        raise ValueError('Invalid clips week')
    return (monday + timedelta(days=6, hours=23, minutes=59)).timestamp()


def opening_period(db):
    start = weekly_summary.timestamp((db.get('config') or {}).get('startDate'))
    if not start:
        return None
    local = datetime.fromtimestamp(start, MADRID)
    monday = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=local.weekday())
    end = (monday + timedelta(days=14)).timestamp()
    return {'week': local.date().isoformat(), 'startsAt': start, 'endsAt': end, 'closesAt': end - 60}


def period_for(db, week):
    first = opening_period(db)
    if first and week == first['week']:
        return dict(first)
    start, end = weekly_summary.bounds(week)
    return {'week': week, 'startsAt': start, 'endsAt': end, 'closesAt': end - 60}


def current_week(db, now):
    first = opening_period(db)
    if first and first['startsAt'] <= now < first['endsAt']:
        return first['week']
    return week_key(now)


def board_closes_at(board):
    return board['closesAt'] if 'closesAt' in board else week_closes_at(board['week'])


def migrate_opening_board(db, now):
    """Join the former short boards without changing votes or granting prizes."""
    first = opening_period(db)
    if not first or db.get('clipsCalendarVersion') == 2:
        return False
    legacy = {week_key(first['startsAt']), week_key(first['endsAt'] - 1)}
    board = db.get('clips')
    if board is not None and (not isinstance(board, dict) or not isinstance(board.get('posts'), list)):
        raise ValueError('Invalid clips data')
    archives = db.get('clipArchives') or {}
    sources = [b for b in [board, *archives.values()] if b and b.get('week') in legacy | {first['week']}]
    if sources:
        posts = {}
        for source in sources:
            for post in source['posts']:
                # The active board is authoritative if a saved source repeats an ID.
                posts.setdefault(post['id'], copy.deepcopy(post))
        merged = {**first, 'posts': list(posts.values())}
        if board and board.get('week') in legacy | {first['week']}:
            db['clips'] = merged
        else:
            merged['archived'] = True
            db.setdefault('clipArchives', {})[first['week']] = merged
        for key in legacy - {first['week']}:
            db.get('clipArchives', {}).pop(key, None)
    db['clipsCalendarVersion'] = 2
    return True


def settle_board(db, board, timestamp):
    closes_at = board_closes_at(board)
    if timestamp < closes_at:
        return False
    ledger = db.setdefault('clipWeeklyRewards', {})
    if board['week'] in ledger:
        if board.get('weeklyAward') != ledger[board['week']]:
            board['weeklyAward'] = copy.deepcopy(ledger[board['week']])
            return True
        return False
    teams = {duo['id']: duo for duo in db.get('duos', [])}
    starts_at = board.get('startsAt')
    if starts_at is None:
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
            'message': f"🏆 {team['teamName']} gana {WEEKLY_REWARD_SHELLS} pepazos por el clip más votado de la semana: {winner['title']} ({award['votes']} likes)."})
    ledger[board['week']] = award
    board['weeklyAward'] = copy.deepcopy(award)
    return True


def settle_weekly_reward(db, now=None):
    """Settle stored boards once, preserving the complete archive."""
    timestamp = time.time() if now is None else now
    changed = migrate_opening_board(db, timestamp)
    board = db.get('clips')
    if board is not None and (not isinstance(board, dict) or not isinstance(board.get('posts'), list)):
        raise ValueError('Invalid clips data')
    for item in [*db.get('clipArchives', {}).values(), *([board] if board else [])]:
        changed = settle_board(db, item, timestamp) or changed
    return changed


def board_for(db, preview=False, now=None):
    timestamp = time.time() if now is None else now
    week = current_week(db, timestamp)
    settled = settle_weekly_reward(db, timestamp)
    board = db.get('clips')
    archived = weekly_summary.maintain(db, timestamp)
    if board is not None and board.get('week') == week:
        period = period_for(db, week)
        if any(board.get(key) != value for key, value in period.items()):
            board.update(period)
            settled = True
        return board, settled or archived
    if board:
        saved = copy.deepcopy(board)
        saved['archived'] = True
        db.setdefault('clipArchives', {})[board['week']] = saved
    board = {**period_for(db, week), 'posts': []}
    ledger = db.get('clipWeeklyRewards', {})
    previous = [award for key, award in sorted(ledger.items()) if key < week and award.get('status') != 'REVOKED']
    if previous:
        board['previousWeeklyAward'] = copy.deepcopy(previous[-1])
    if preview:
        for index, example in enumerate(PREVIEW_POSTS):
            post = copy.deepcopy(example)
            post.update(createdAt=timestamp - (5 - index * 2) * 3600, teamVotes={}, example=True)
            board['posts'].append(post)
    db['clips'] = board
    settle_board(db, board, timestamp)
    return board, True


def public_payload(db, team_id=None, preview=False, visitor=None, week=None, now=None, admin=False):
    timestamp = time.time() if now is None else now
    current, changed = board_for(db, preview, timestamp)
    boards = {**db.get('clipArchives', {}), current['week']: current}
    selected = week or current['week']
    if selected not in boards:
        raise LookupError('Semana de clips no encontrada.')
    result = public_board(boards[selected], team_id, preview, db.get('duos', []), visitor, timestamp, admin)
    result['currentWeek'] = current['week']
    result['weeks'] = [{'week': key, 'startsAt': item.get('startsAt', weekly_summary.timestamp(key)),
                       'endsAt': item['endsAt'] if 'endsAt' in item else board_closes_at(item) + 60,
                       'archived': key != current['week']}
                      for key, item in sorted(boards.items(), reverse=True)]
    return result, changed


def visitor_hash(token):
    return hashlib.sha256(token.encode('ascii')).hexdigest()


def public_board(board, team_id=None, preview=False, duos=(), visitor=None, now=None, admin=False):
    voter = next((duo for duo in duos if duo['id'] == team_id), None)
    posts = []
    for post in board['posts']:
        item = {key: post[key] for key in ('id', 'title', 'teamId', 'team', 'initials', 'duration', 'scene', 'createdAt', 'slug', 'url', 'example') if key in post}
        item.update(votes=vote_count(post), liked=bool(voter) and browser_liked(post, visitor),
                    commentCount=len(post.get('comments', [])), canDelete=can_delete(post, visitor, team_id, admin))
        posts.append(item)
    return {'week': board['week'], 'preview': preview, 'clips': posts,
            'voting': {'teamId': voter['id'], 'teamName': voter['teamName']} if voter else None,
            'teams': [{'id': duo['id'], 'name': duo['teamName']} for duo in duos],
            'startsAt': board.get('startsAt', weekly_summary.timestamp(board['week'])),
            'endsAt': board['endsAt'] if 'endsAt' in board else board_closes_at(board) + 60,
            'archived': bool(board.get('archived')),
            'weeklyReward': {'shells': WEEKLY_REWARD_SHELLS, 'closesAt': board_closes_at(board),
                             'closed': bool(board.get('archived') or board.get('weeklyAward')) or (time.time() if now is None else now) >= board_closes_at(board), 'award': board.get('weeklyAward'),
                             'previousAward': board.get('previousWeeklyAward')}}


def comment_post(db, week, clip_id):
    if not isinstance(week, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', week):
        raise ValueError('Indica la semana del clip.')
    if not isinstance(clip_id, str) or not clip_id or len(clip_id) > 80:
        raise ValueError('Indica un clip válido.')
    boards = [db.get('clips') or {}, *db.get('clipArchives', {}).values()]
    board = next((b for b in boards if b.get('week') == week), None)
    post = next((p for p in (board or {}).get('posts', []) if p['id'] == clip_id and not p.get('example')), None)
    if post is None:
        raise LookupError('Clip no encontrado en esta semana.')
    return post


def public_comment(comment):
    # Browser hashes and retry identifiers are private, even for guests.
    return {key:comment[key] for key in ('id', 'name', 'text', 'createdAt')}


def comment_page(db, week, clip_id, offset=0, limit=COMMENT_PAGE_SIZE):
    post = comment_post(db, week, clip_id)
    comments = list(reversed(post.get('comments', [])))
    offset, limit = max(0, int(offset)), min(50, max(1, int(limit)))
    return {'week':week, 'clipId':clip_id, 'comments':[public_comment(c) for c in comments[offset:offset+limit]],
            'total':len(comments), 'offset':offset, 'limit':limit,
            'hasMore':offset+limit < len(comments)}


def add_comment(db, week, clip_id, visitor, name, text, request_id, now=None):
    post = comment_post(db, week, clip_id)
    if not isinstance(name, str) or len(name.strip()) > COMMENT_NAME_LIMIT:
        raise ValueError('El nombre es opcional y admite hasta 15 caracteres.')
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= COMMENT_TEXT_LIMIT:
        raise ValueError('Escribe un comentario de entre 1 y 200 caracteres.')
    name, text = name.strip(), text.strip()
    if any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in name) or any(
            (ord(c) < 32 and c not in '\n\t') or 0xD800 <= ord(c) <= 0xDFFF for c in text):
        raise ValueError('El comentario contiene caracteres no válidos.')
    if not visitor or not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',request_id):
        raise ValueError('Identificador de envío no válido. Recarga la página.')
    existing = next((c for c in post.get('comments', []) if c.get('visitor') == visitor and c.get('requestId') == request_id), None)
    if existing:
        if existing['name'] != name or existing['text'] != text:
            raise ValueError('Este envío ya corresponde a otro comentario. Vuelve a intentarlo.')
        return existing, False
    if len(post.get('comments', [])) >= COMMENT_MAX_PER_CLIP:
        raise OverflowError('No se pueden añadir más comentarios a este clip.')
    timestamp = time.time() if now is None else now
    limits = {key:[t for t in stamps if t > timestamp-3600] for key,stamps in db.get('clipCommentLimits', {}).items()}
    limits = {key:stamps for key,stamps in limits.items() if stamps}
    recent = limits.get(visitor, [])
    if recent and timestamp-recent[-1] < COMMENT_COOLDOWN:
        raise CommentRateLimit('Espera 15 segundos entre comentarios.')
    if len(recent) >= COMMENT_HOURLY_LIMIT:
        raise CommentRateLimit('Has alcanzado el límite de 20 comentarios por hora. Inténtalo más tarde.', max(1,int(recent[0]+3600-timestamp)+1))
    comment = {'id':str(uuid.uuid4()), 'name':name, 'text':text, 'createdAt':timestamp,
               'visitor':visitor, 'requestId':request_id}
    post.setdefault('comments', []).append(comment)
    limits[visitor] = [*recent, timestamp]
    db['clipCommentLimits'] = limits
    return comment, True


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


def publish(board, title, url, now=None, team=None, visitor=None, uploader_team_id=None):
    timestamp = time.time() if now is None else now
    if board.get('archived') or board.get('weeklyAward') or timestamp >= board_closes_at(board):
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
    if visitor:
        post['uploaderVisitor'] = visitor
    if uploader_team_id:
        post['uploaderTeamId'] = uploader_team_id
    board['posts'].append(post)
    return post


def can_delete(post, visitor=None, team_id=None, admin=False):
    if post.get('example'):
        return False
    return bool(admin or (isinstance(visitor, str) and visitor and
                          isinstance(post.get('uploaderVisitor'), str) and
                          hmac.compare_digest(visitor, post['uploaderVisitor'])) or
                (team_id and post.get('uploaderTeamId') == team_id))


def remove_clip(db, week, clip_id, visitor=None, team_id=None, admin=False, now=None):
    """Withdraw a post and its discussion; retain private recovery/audit evidence.

    Already-settled prizes are immutable, even if an archived winner is removed.
    """
    if not isinstance(week, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', week):
        raise ValueError('Indica la semana del clip.')
    if not isinstance(clip_id, str) or not clip_id or len(clip_id) > 80:
        raise ValueError('Indica un clip válido.')
    boards = [db.get('clips') or {}, *db.get('clipArchives', {}).values()]
    board = next((b for b in boards if b.get('week') == week), None)
    post = next((p for p in (board or {}).get('posts', []) if p['id'] == clip_id), None)
    deleted = db.get('deletedClips', {}).get(clip_id)
    if post is None:
        if deleted and deleted.get('week') == week:
            if not can_delete(deleted['post'], visitor, team_id, admin):
                raise PermissionError('Solo quien publicó el clip o el administrador puede borrarlo.')
            return False  # A retry after a lost response cannot delete twice.
        raise LookupError('Clip no encontrado en esta semana.')
    if not can_delete(post, visitor, team_id, admin):
        raise PermissionError('Solo quien publicó el clip o el administrador puede borrarlo.')
    db.setdefault('deletedClips', {})[clip_id] = {
        'week': week, 'post': copy.deepcopy(post), 'deletedAt': time.time() if now is None else now,
        'deletedBy': 'admin' if admin else 'uploader', 'teamId': team_id if not admin else None}
    board['posts'] = [p for p in board['posts'] if p['id'] != clip_id]
    return True


def set_like(board, clip_id, team_id, visitor, liked, now=None):
    if board.get('archived') or board.get('weeklyAward') or (time.time() if now is None else now) >= board_closes_at(board):
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
