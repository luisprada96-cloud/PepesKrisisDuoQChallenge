"""Permanent final-standing predictions, separate from tierlists and weekly Pick'em."""
import copy
import re
import time
import unicodedata
import uuid

from tierlists_service import ITEMS, MAX_TEAM_POSTS
from weekly_summary import timestamp


def name_key(value):
    value = unicodedata.normalize('NFKD', str(value)).casefold()
    return re.sub(r'[^a-z0-9]', '', value)


def roster(db):
    images = {name_key(item['name']): item['image'] for item in ITEMS}
    return [{'id': d['id'], 'name': d['teamName'], 'image': images.get(name_key(d['teamName']), '')}
            for d in sorted(db.get('duos', []), key=lambda d: (d['teamName'].casefold(), d['id']))]


def ensure_board(db):
    if 'finalPredictions' not in db:
        db['finalPredictions'] = {'items': roster(db), 'posts': [], 'result': None}
        return True
    board = db['finalPredictions']
    # Once someone has published, their roster and names remain readable permanently.
    if not board['posts'] and not board.get('result') and board['items'] != roster(db):
        board['items'] = roster(db)
        return True
    return False


def maintain(db, now=None):
    board = db.get('finalPredictions')
    if not board or board.get('result'): return False
    now = time.time() if now is None else now
    trophies = db.get('awardedTrophies') or {}
    end = timestamp(trophies.get('endDate'))
    if trophies.get('status') != 'awarded' or not end or now < end: return False
    champion = next((c for c in trophies.get('cards', []) if c['id'] == 'champion'), None)
    if not champion or not champion.get('entries'): return False
    rows = [{'id': e['id'], 'name': e.get('name') or e.get('teamName', ''),
             'position': i + 1, 'elo': e.get('value', '')}
            for i, e in enumerate(champion['entries'])]
    board['result'] = {'order': [r['id'] for r in rows], 'rows': rows,
                       'settledAt': now, 'endDate': trophies['endDate'], 'source': 'awardedTrophies'}
    return True


def publishing_status(db, team_id, visitor):
    team = next((d for d in db.get('duos', []) if d['id'] == team_id), None)
    if not team:
        return {'canPublish': False, 'reason': 'login', 'message': 'Inicia sesión con tu equipo para publicar.'}
    board = db['finalPredictions']
    posts = board['posts']
    if len(board['items']) < 2:
        reason, message = 'roster', 'Faltan equipos para preparar la porra.'
    elif visitor and any(p['visitor'] == visitor for p in posts):
        reason, message = 'browser', 'Ya has publicado tu pronóstico desde este navegador.'
    elif sum(p['teamId'] == team_id for p in posts) >= MAX_TEAM_POSTS:
        reason, message = 'team', 'Tu equipo ya ha publicado sus dos pronósticos.'
    else:
        reason, message = 'ready', f"Publicando como {team['teamName']}."
    return {'teamId': team_id, 'teamName': team['teamName'], 'canPublish': reason == 'ready',
            'reason': reason, 'message': message}


def validate_order(board, order):
    expected = {item['id'] for item in board['items']}
    if not expected or not isinstance(order, list) or any(not isinstance(i, str) for i in order):
        raise ValueError('Ordena todos los equipos una sola vez.')
    if len(order) != len(expected) or set(order) != expected:
        raise ValueError('Ordena todos los equipos una sola vez, sin repetir ni omitir ninguno.')
    return list(order)


def publish(db, team_id, visitor, author, order, now=None):
    ensure_board(db)
    board = db['finalPredictions']
    if not isinstance(visitor, str) or not visitor:
        raise ValueError('Activa las cookies y vuelve a cargar la página.')
    if not any(d['id'] == team_id for d in db.get('duos', [])):
        raise PermissionError('Inicia sesión con tu equipo para publicar.')
    author = '' if author is None else author
    if not isinstance(author, str) or len(author.strip()) > 60 or any(ord(c) < 32 for c in author):
        raise ValueError('El nombre opcional debe tener como máximo 60 caracteres y una sola línea.')
    order = validate_order(board, order)
    existing = next((p for p in board['posts'] if p['visitor'] == visitor), None)
    if existing and existing['teamId'] == team_id and existing['order'] == order and existing['author'] == author.strip():
        return existing, False  # Safe retry after a lost response; never spend another slot.
    status = publishing_status(db, team_id, visitor)
    if not status['canPublish']: raise FileExistsError(status['message'])
    post = {'id': uuid.uuid4().hex, 'teamId': team_id, 'teamName': status['teamName'],
            'author': author.strip(), 'visitor': visitor, 'order': order,
            'createdAt': time.time() if now is None else now}
    board['posts'].append(post)
    return post, True


def comparison(post, result):
    if not result: return None
    actual = result['order']
    if len(actual) != len(post['order']) or set(actual) != set(post['order']):
        return {'status': 'UNAVAILABLE', 'exact': None, 'total': len(post['order']), 'positions': []}
    positions = [{'teamId': team, 'predicted': i + 1, 'actual': actual.index(team) + 1,
                  'correct': actual.index(team) == i} for i, team in enumerate(post['order'])]
    return {'status': 'SETTLED', 'exact': sum(p['correct'] for p in positions),
            'total': len(positions), 'positions': positions}


def public_board(db, team_id=None, visitor=None, offset=0, limit=6):
    board = db['finalPredictions']
    posts = sorted(board['posts'], key=lambda p: (p['createdAt'], p['id']), reverse=True)
    public = [{**{k: copy.deepcopy(p[k]) for k in ('id', 'teamId', 'teamName', 'author', 'createdAt', 'order')},
               'comparison': comparison(p, board.get('result'))} for p in posts[offset:offset + limit]]
    return {'items': copy.deepcopy(board['items']), 'posts': public, 'total': len(posts),
            'offset': offset, 'limit': limit, 'result': copy.deepcopy(board.get('result')),
            'publishing': publishing_status(db, team_id, visitor)}
