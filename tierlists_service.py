"""Permanent published tierlists; browser identity is never part of public data."""
import copy
import time
import uuid

TIERS = ('S', 'A', 'B', 'C', 'D')
MAX_TEAM_POSTS = 2
ITEMS = (
    {'id': 'atodoflash', 'name': 'ATodoFlash', 'image': '/assets/tierlist/atodoflash.png'},
    {'id': 'loselogidos', 'name': 'LosELOgidos', 'image': '/assets/tierlist/loselogidos.png'},
    {'id': 'marx-mises', 'name': 'Marx&Mises', 'image': '/assets/tierlist/marx-mises.png'},
    {'id': 'nocturnidad', 'name': 'NocturnidadYGunthervosia', 'image': '/assets/tierlist/nocturnidad.png'},
    {'id': 'patarrota', 'name': 'Pat@rrota', 'image': '/assets/tierlist/patarrota.png'},
    {'id': 'supersalidos', 'name': 'Supersalidos', 'image': '/assets/tierlist/supersalidos.png'},
    {'id': 'tiltanic', 'name': 'TILTanic', 'image': '/assets/tierlist/tiltanic.png'},
    {'id': 'triperosgap', 'name': 'TriperosGAP', 'image': '/assets/tierlist/triperosgap.png'},
    {'id': 'vapores', 'name': 'VaporesEnElC2', 'image': '/assets/tierlist/vapores.png'},
)


# Stable public tiles, matching the team catalog; profile edits do not move past rankings.
PLAYER_ITEMS = tuple(
    {'id': 'player-' + slug, 'name': name, 'teamName': team,
     'image': '/assets/tierlist/player-' + slug + '.png'}
    for slug, name, team in (
        ('markel', 'Markel', 'ATodoFlash'), ('guille', 'Guille', 'ATodoFlash'),
        ('unluckypingu', 'UnluckyPingu', 'LosELOgidos'), ('unluckypanda', 'UnluckyPanda', 'LosELOgidos'),
        ('joji', 'Joji', 'Marx&Mises'), ('luis', 'Luis', 'Marx&Mises'),
        ('sendi', 'Sendi', 'NocturnidadYGunthervosia'), ('chicha', 'Chicha', 'NocturnidadYGunthervosia'),
        ('ikerpantv', 'IkerpanTv', 'Pat@rrota'), ('pato', 'Pato', 'Pat@rrota'),
        ('mclovin', 'McLOVIN', 'Supersalidos'), ('fogell', 'Fogell', 'Supersalidos'),
        ('taberneta', 'Taberneta', 'TILTanic'), ('ameteum', 'Ameteum', 'TILTanic'),
        ('papaportu', 'Papaportu', 'TriperosGAP'), ('parradise', 'Parradise', 'TriperosGAP'),
        ('pablo-crespo', 'Pablo Crespo', 'VaporesEnElC2'), ('pablo-casco', 'Pablo Casco', 'VaporesEnElC2'),
    )
)
CATALOGS = {'teams': ITEMS, 'players': PLAYER_ITEMS}
ALL_ITEMS = ITEMS + PLAYER_ITEMS


def catalog(kind='teams'):
    if not isinstance(kind, str) or kind not in CATALOGS:
        raise ValueError('Selecciona Equipos o Integrantes.')
    return CATALOGS[kind]


def posts_for(db, kind='teams'):
    catalog(kind)
    posts = db.get('tierlists', [])
    if not isinstance(posts, list):
        raise ValueError('Formato de tierlists inválido.')
    return [p for p in posts if p.get('kind', 'teams') == kind]


def publication_status(db, team_id, visitor, kind='teams'):
    catalog(kind)
    team = next((d for d in db.get('duos', []) if d.get('id') == team_id), None)
    if not team:
        return {'canPublish': False, 'reason': 'login', 'message': 'Inicia sesión con tu equipo para publicar.'}
    own_posts = posts_for(db, kind)
    if visitor and any(p.get('visitor') == visitor for p in own_posts):
        reason, message = 'browser', 'Ya has publicado una tierlist desde este navegador.'
    elif sum(p.get('teamId') == team_id for p in own_posts) >= MAX_TEAM_POSTS:
        reason, message = 'team', 'Tu equipo ya ha publicado sus dos tierlists.'
    else:
        reason, message = 'ready', f"Publicando como {team['teamName']}."
    return {'teamId': team_id, 'teamName': team['teamName'], 'canPublish': reason == 'ready',
            'reason': reason, 'message': message}


def validate_tiers(tiers, kind='teams'):
    items = catalog(kind)
    if not isinstance(tiers, dict) or set(tiers) != set(TIERS):
        raise ValueError('Utiliza las filas S, A, B, C y D.')
    ids = []
    for tier in TIERS:
        if not isinstance(tiers[tier], list) or any(not isinstance(i, str) for i in tiers[tier]):
            raise ValueError('La distribución no es válida.')
        ids.extend(tiers[tier])
    if len(ids) != len(items) or set(ids) != {i['id'] for i in items}:
        label = 'equipos' if kind == 'teams' else 'integrantes'
        raise ValueError(f'Coloca los {len(items)} {label} exactamente una vez.')
    return {tier: list(tiers[tier]) for tier in TIERS}


def publish(db, team_id, visitor, author, tiers, now=None, kind='teams'):
    if not isinstance(visitor, str) or not visitor:
        raise ValueError('Activa las cookies y vuelve a cargar la página.')
    status = publication_status(db, team_id, visitor, kind)
    if not status.get('teamId'):
        raise PermissionError(status['message'])
    if not status['canPublish']:
        raise FileExistsError(status['message'])
    if author is None:
        author = ''
    if not isinstance(author, str) or len(author.strip()) > 60 or any(ord(c) < 32 for c in author):
        raise ValueError('El nombre del autor debe tener como máximo 60 caracteres y una sola línea.')
    arrangement = validate_tiers(tiers, kind)
    post = {'id': uuid.uuid4().hex, 'kind': kind, 'teamId': team_id, 'teamName': status['teamName'],
            'author': author.strip(), 'visitor': visitor, 'tiers': arrangement,
            'createdAt': time.time() if now is None else now}
    db.setdefault('tierlists', []).append(post)
    return post


def public_board(db, team_id=None, visitor=None, offset=0, limit=6, kind='teams'):
    items = catalog(kind)
    posts = sorted(posts_for(db, kind), key=lambda p: (p['createdAt'], p['id']), reverse=True)
    public = [{key: copy.deepcopy(post[key]) for key in ('id', 'teamId', 'teamName', 'author', 'tiers', 'createdAt')}
              for post in posts[offset:offset + limit]]
    return {'kind': kind, 'items': copy.deepcopy(items), 'tiers': list(TIERS), 'posts': public,
            'total': len(posts), 'offset': offset, 'limit': limit,
            'publishing': publication_status(db, team_id, visitor, kind)}
