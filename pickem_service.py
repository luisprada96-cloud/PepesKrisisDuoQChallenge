"""Weekly Pick'em ballots and atomic shell prizes from stored participant games."""
import player_accounts
import copy
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path
from competition_ranking import average_rank, average_rank_key
from shell_rules import individual_shell_criteria
import weekly_summary as weeks

MAX_TEAM_BALLOTS = 2
REWARD_RULE = {'version': 2, 'minCorrect': 3, 'shells': 1,
               'tiers': [{'minCorrect': 3, 'shells': 1}, {'minCorrect': 5, 'shells': 2}]}
SETTLEMENT_GRACE = 300
MIN_CHAMPION_GAMES = 3
NEW_SCHEDULE = {
    'firstStartsAt': '2026-10-16T00:00:00+02:00',
    'firstEndsAt': '2026-10-26T00:00:00+01:00',
    'firstClosesAt': '2026-10-17T00:00:00+02:00',
}
CHAMPION_OPTIONS = json.loads((Path(__file__).parent / 'assets' / 'pickem' / 'champions.json').read_text(encoding='utf-8'))['champions']
RANK_CATEGORIES = {'weekly_leader', 'first_week_last'}
OPENING_CATEGORIES = {'first_five_negative', 'first_individual_shell', 'joji_parradise_deaths', 'first_week_last'}
OPTIONS = [{'id': '0-19', 'label': 'Menos de 20', 'min': 0, 'max': 19}] + [
    {'id': f'{n}-{n+9}', 'label': f'{n}–{n+9}', 'min': n, 'max': n+9} for n in range(20,120,10)
] + [{'id': '120+', 'label': '120 o más', 'min': 120, 'max': None}]
CATEGORIES = [{'id': 'unique_champions', 'kind': 'range', 'icon': '?', 'placeholder': 'Selecciona un rango',
               'title': '¿Cuántos campeones distintos se jugarán?',
               'description': 'Los campeones de los participantes en las partidas registradas de la semana, sin repetir.',
               'options': OPTIONS},
              {'id': 'weekly_leader', 'kind': 'team', 'icon': '🏆', 'placeholder': 'Selecciona un equipo',
               'title': '¿Qué equipo terminará primero esta semana?',
               'description': 'Mayor media de ELO de ambos integrantes al cierre, usando la cuenta seleccionada de cada uno; desempate por winrate conjunto de esas cuentas. En empate exacto, valen los equipos empatados.'},
              {'id': 'first_week_last', 'kind': 'team', 'icon': '🪦', 'eventLabel': 'ESTRENO DEL TORNEO',
               'placeholder': 'Selecciona un equipo',
               'title': '¿Qué equipo quedará último la primera semana?',
               'description': 'Menor media de ELO de ambos integrantes al cierre de la primera semana, usando la cuenta seleccionada de cada uno; desempate por winrate conjunto de esas cuentas. En empate exacto, valen todos los equipos empatados.'},
              {'id': 'best_game_kda', 'kind': 'player', 'icon': '⚔', 'placeholder': 'Selecciona un jugador',
               'title': '¿Quién hará la partida con mejor KDA?',
               'description': 'La mejor partida individual de la semana: (asesinatos + asistencias) / máximo(muertes, 1). En empate exacto, valen todos los empatados.'},
              {'id': 'weekly_player_kda', 'kind': 'player', 'icon': '📊', 'placeholder': 'Selecciona un integrante',
               'title': '¿Quién tendrá el mejor KDA de la semana?',
               'description': 'KDA individual acumulado de la semana: (asesinatos totales + asistencias totales) / máximo(muertes totales, 1). No es la media de los KDA de cada partida. Cuenta con al menos una Solo/Duo registrada; en empate exacto, valen todos los integrantes empatados.'},
              {'id': 'first_individual_shell', 'kind': 'player', 'icon': '🐢', 'eventLabel': 'ESTRENO DEL TORNEO',
               'placeholder': 'Selecciona un jugador',
               'title': '¿Quién conseguirá el primer pepazo individual del torneo?',
               'description': 'Primer jugador con pentakill, 20+ asesinatos, 30+ asistencias o 0 muertes y más de 20 asesinatos + asistencias. Cuenta aunque su equipo tenga el inventario lleno. Se usa el final de la partida; si coinciden varios jugadores, todos valen.'},
              {'id': 'joji_parradise_deaths', 'kind': 'duel', 'icon': '💀', 'eventLabel': 'EVENTO · PRIMERA SEMANA',
               'placeholder': 'Selecciona a Joji o Parradise',
               'title': '¿Quién morirá más: Joji o Parradise?',
               'description': 'Muertes acumuladas de Joji y Parradise en las Solo/Duo registradas durante la primera semana del torneo. Gana quien sume más muertes; en empate, ambas respuestas valen.',
               'contenders': ['Joji', 'Parradise']},
              {'id': 'chicha_fogell_kills', 'kind': 'duel', 'icon': '⚔️', 'eventLabel': 'DUELO SEMANAL',
               'placeholder': 'Selecciona a Chicha o Fogell',
               'title': '¿Quién hará más kills esta semana: Chicha o Fogell?',
               'description': 'Kills individuales acumuladas de Chicha y Fogell en las Solo/Duo registradas esta semana. Gana quien sume más kills; en empate, ambas respuestas valen.',
               'contenders': ['Chicha', 'Fogell']},
              {'id': 'first_five_negative', 'kind': 'count', 'icon': '📉', 'eventLabel': 'ESTRENO DEL TORNEO',
               'placeholder': 'Selecciona cuántos dúos',
               'title': '¿Cuántos dúos tendrán winrate negativo en sus primeras 5 ranked?',
               'description': 'Las cinco primeras Solo/Duo registradas desde el inicio del torneo. Un dúo cuenta con 0, 1 o 2 victorias; si le faltan partidas, esperamos a que las complete. Al terminar el torneo, los incompletos no cuentan.',
               'options': [{'id':str(n),'label':str(n)} for n in range(10)]},
              {'id': 'best_champion_winrate', 'kind': 'champion', 'icon': '👑',
               'placeholder': 'Busca y selecciona un campeón',
               'title': '¿Qué campeón tendrá mejor winrate?',
               'description': 'Winrate de los campeones jugados por los participantes esta semana. Mínimo 3 partidas individuales con el campeón para puntuar. En empate exacto, valen todos los campeones empatados.',
               'options': CHAMPION_OPTIONS}]


def account(player):
    return [str(player.get('name') or '').strip().casefold(), str(player.get('tag') or 'EUW').strip().casefold()]


def category_definitions(db, week=None):
    definitions = copy.deepcopy(CATEGORIES)
    if week and week != calendar_key(db, weeks.timestamp(db.get('config',{}).get('startDate'))):
        definitions = [c for c in definitions if c['id'] not in OPENING_CATEGORIES]
    teams, players = [], []
    for duo in db.get('duos', []):
        teams.append({'id': duo['id'], 'label': duo['teamName']})
        for key in ('player1', 'player2'):
            player = duo.get(key) or {}
            if not player.get('name'): continue
            identity = account(player)
            suffix = hashlib.sha256(repr(identity).encode()).hexdigest()[:16]
            name = player.get('displayName') or player['name']
            players.append({'id': f"{duo['id']}:{key}:{suffix}", 'label': f"{name} · {duo['teamName']}",
                            'teamId': duo['id'], 'playerKey': key, 'account': identity, 'puuid': player.get('puuid'),
                            'displayName': name})
    for category in definitions:
        if category['kind'] in ('team','player'):
            category['options'] = sorted(teams if category['kind']=='team' else players, key=lambda o: o['label'].casefold())
        elif category['kind']=='duel':
            category['options'] = []
            for name in category['contenders']:
                matches = [p for p in players if p['displayName'].strip().casefold()==name.casefold()]
                binding = matches[0] if len(matches)==1 else {'disabled':True}
                category['options'].append({**binding, 'id':name.casefold(), 'label':name})
        elif category['id']=='first_five_negative':
            category['teamIds'] = sorted(d['id'] for d in db.get('duos',[]))
    return definitions


def roster_key(db):
    return sorted([[d['id'], *[str((d.get(k) or {}).get(f) or '').strip().casefold()
                              for k in ('player1','player2') for f in ('name','tag')],
                    *[repr(player_accounts.configuration(d.get(k) or {})) for k in ('player1','player2')]] for d in db.get('duos',[])])


def calendar_key(db, now):
    schedule = db.get('config', {}).get('pickemSchedule')
    if schedule and now < weeks.timestamp(schedule['firstEndsAt']):
        return datetime.fromtimestamp(weeks.timestamp(schedule['firstStartsAt']), weeks.MADRID).date().isoformat()
    return weeks.week_key(now)


def period(db, week):
    tournament_start = weeks.timestamp(db.get('config',{}).get('startDate'))
    tournament_end = weeks.timestamp(db.get('config',{}).get('endDate'))
    if not tournament_start or tournament_end <= tournament_start:
        raise ValueError('El calendario del torneo no está configurado.')
    schedule = db.get('config', {}).get('pickemSchedule')
    if schedule:
        first_start, first_end, first_close = (weeks.timestamp(schedule[key]) for key in
                                              ('firstStartsAt', 'firstEndsAt', 'firstClosesAt'))
        if not tournament_start <= first_start < first_close < first_end <= tournament_end:
            raise ValueError('El calendario de Pick’em no es válido.')
        first_key = calendar_key(db, first_start)
        if week == first_key:
            return {'startsAt': first_start, 'endsAt': first_end, 'closesAt': first_close}
        start, end = weeks.bounds(week)
        if start < first_end:
            raise ValueError('Esta semana es anterior al calendario de Pick’em.')
        # Local midnight after Monday includes its entire 23:59 minute, also across DST.
        monday = datetime.fromtimestamp(start, weeks.MADRID)
        close = (monday + timedelta(days=1)).timestamp()
        return {'startsAt': start, 'endsAt': min(end, tournament_end), 'closesAt': min(close, tournament_end)}
    start, end = weeks.bounds(week)
    return {'startsAt': max(start,tournament_start), 'endsAt': min(end,tournament_end),
            'closesAt': min(end-60,tournament_end)}


def reset_calendar(db):
    """Explicit one-off reset; callers back up and atomically save the tournament."""
    db['config']['pickemSchedule'] = dict(NEW_SCHEDULE)
    db['pickem'] = {'weeks': {}}
    db['events'] = [event for event in db.get('events', []) if event.get('type') != 'PICKEM_REWARD']
    for duo in db.get('duos', []):
        duo.pop('pickemShellsEarnedTotal', None)


def ensure_week(db, now=None):
    now = time.time() if now is None else now
    config = db.get('config',{})
    start, end = weeks.timestamp(config.get('startDate')), weeks.timestamp(config.get('endDate'))
    if not start or end <= start: raise ValueError('El calendario del torneo no está configurado.')
    key = calendar_key(db, min(max(now,start),end-0.001))
    state = db.setdefault('pickem', {'weeks': {}})
    changed = key not in state['weeks']
    if changed:
        state['weeks'][key] = {'week':key, 'categories':category_definitions(db,key), 'ballots':[], 'results':{}}
    board = state['weeks'][key]
    changed = ensure_reward_rule(board) or changed
    # Add new categories only to an open week. Existing ballots keep their answers.
    if now < period(db,key)['closesAt']:
        for definition in category_definitions(db,key):
            previous = next((c for c in board['categories'] if c['id']==definition['id']), None)
            if previous is None:
                board['categories'].append(definition)
                changed = True
            elif definition['kind'] != 'range':
                if definition['kind']=='duel':
                    # Bind the named person once; later profile edits must not move their predictions to another account.
                    for option in definition['options']:
                        saved = next((o for o in previous['options'] if o['id']==option['id'] and o.get('account')), None)
                        if not saved: continue
                        option.clear()
                        option.update(copy.deepcopy(saved))
                        duo = next((d for d in db['duos'] if d['id']==saved['teamId']), {})
                        player = duo.get(saved['playerKey']) or {}
                        if account(player)==saved['account'] and player.get('puuid'):
                            option['puuid'] = player['puuid']
                current_ids = {o['id'] for o in definition['options']}
                # Keep retired identities as disabled options so saved guesses remain readable.
                definition['options'] += [{**o, 'disabled': True} for o in previous['options'] if o['id'] not in current_ids]
                if previous != definition:
                    previous.update(definition)
                    changed = True
    return key, capture_rankings(db) or changed


def ballot_status(db, board, team_id, visitor, now=None):
    now = time.time() if now is None else now
    team = next((d for d in db.get('duos',[]) if d['id']==team_id),None)
    own = next((b for b in board['ballots'] if visitor and b['visitor']==visitor),None)
    bounds = period(db,board['week'])
    if not team: reason, message = 'login','Inicia sesión con tu equipo para rellenar la quiniela.'
    elif now < bounds['startsAt']: reason,message = 'upcoming','Las predicciones de este periodo todavía no están abiertas.'
    elif now >= bounds['closesAt']: reason,message = 'closed','Las predicciones de esta semana están cerradas.'
    elif bounds['startsAt'] >= bounds['endsAt']: reason,message = 'closed','Esta semana queda fuera del torneo.'
    elif own and own['teamId']!=team_id: reason,message = 'browser','Este navegador ya tiene una quiniela esta semana.'
    elif not own and sum(b['teamId']==team_id for b in board['ballots'])>=MAX_TEAM_BALLOTS:
        reason,message = 'team','Tu equipo ya ha utilizado sus dos quinielas esta semana.'
    else: reason,message = 'ready',f"Participando como {team['teamName']}."
    return {'teamId':team_id if team else None, 'teamName':team['teamName'] if team else None,
            'canAnswer':reason=='ready', 'reason':reason, 'message':message,
            'ballot':own if own and team and own['teamId']==team_id else None}


def team_duel_choice(board, team_id, category_id):
    """One immutable side per team and duel, derived from confirmed ballots."""
    answers = {b['answers'][category_id] for b in board['ballots']
               if b['teamId'] == team_id and category_id in b['answers']}
    return {'answer': next(iter(answers)) if len(answers) == 1 else None,
            'conflict': len(answers) > 1}


def submit(db, team_id, visitor, category_id, option_id, author='', now=None):
    now = time.time() if now is None else now
    key, _ = ensure_week(db,now)
    board = db['pickem']['weeks'][key]
    status = ballot_status(db,board,team_id,visitor,now)
    if not status['teamId']: raise PermissionError(status['message'])
    if not visitor: raise ValueError('Activa las cookies y vuelve a cargar la página.')
    if not status['canAnswer']: raise FileExistsError(status['message'])
    category = next((c for c in board['categories'] if c['id']==category_id),None)
    if not category or not any(o['id']==option_id for o in category['options']):
        raise ValueError('Selecciona una opción válida.')
    if not isinstance(author,str) or len(author.strip())>60 or any(ord(c)<32 for c in author):
        raise ValueError('El nombre opcional debe tener como máximo 60 caracteres y una sola línea.')
    if category.get('kind') == 'duel':
        choice = team_duel_choice(board, team_id, category_id)
        if choice['conflict']:
            raise FileExistsError('Tu equipo tiene respuestas anteriores distintas para este duelo. Consulta a la administración.')
        if choice['answer'] is not None and choice['answer'] != option_id:
            label = next(o['label'] for o in category['options'] if o['id'] == choice['answer'])
            raise FileExistsError(f'Tu equipo ya ha elegido {label} en este duelo. Ambos debéis seleccionar la misma opción.')
    ballot = status['ballot']
    if ballot and category_id in ballot['answers']:
        if ballot['answers'][category_id]!=option_id: raise FileExistsError('Ya has enviado tu predicción para esta categoría.')
        return ballot,False
    if next(o for o in category['options'] if o['id']==option_id).get('disabled'):
        raise ValueError('Ese participante ya no está disponible para nuevas predicciones.')
    if not ballot:
        ballot = {'id':uuid.uuid4().hex,'teamId':team_id,'teamName':status['teamName'],
                  'visitor':visitor,'author':author.strip(),'createdAt':now,'answers':{}}
        board['ballots'].append(ballot)
    ballot['answers'][category_id] = option_id
    return ballot,True


def champion_key(value):
    name = re.sub(r'[^a-z0-9]', '', str(value or '').casefold())
    return {'wukong':'monkeyking', 'nunuandwillump':'nunu', 'nunuywillump':'nunu'}.get(name, name)


def champion_count(db, board):
    bounds = period(db,board['week'])
    champions, games, pending = set(),set(),False
    seen = set()
    for duo in db.get('duos',[]):
        if (duo.get('riotMatchDiscovery') or {}).get('pendingMatchIds'): pending=True
        for game in duo.get('history',[]):
            mid=game.get('matchId')
            if not mid or game.get('isTest') or game.get('queueId') not in (None,420): continue
            at=weeks.game_time(game)
            if not bounds['startsAt']<=at<bounds['endsAt']: continue
            games.add(mid)
            checked=game.get('participantsChecked') or {}
            if game.get('statsVersion',0)<2 or not all(checked.get(k) for k in ('player1','player2')):
                pending=True
            for key in ('player1','player2'):
                stats=game.get(key+'Stats')
                if not isinstance(stats,dict): continue
                marker=(mid,stats.get('puuid') or (duo['id'],key))
                if marker in seen: continue
                seen.add(marker)
                name=champion_key(stats.get('championName'))
                if not name or name=='unknown': pending=True;continue
                champions.add(name)
    return {'value':len(champions),'games':len(games),'pending':pending}


def best_champion_winrate(db, board, category):
    bounds = period(db, board['week'])
    options = {champion_key(value): option for option in category['options'] for value in (option['id'], option['label'])}
    totals, seen = {}, set()
    for duo in db.get('duos', []):
        if (duo.get('riotMatchDiscovery') or {}).get('pendingMatchIds'): return {'pending':True}
        for game in duo.get('history', []):
            mid = game.get('matchId')
            if not mid or game.get('isTest') or game.get('queueId') not in (None, 420): continue
            if not bounds['startsAt'] <= weeks.game_time(game) < bounds['endsAt']: continue
            checked = game.get('participantsChecked') or {}
            if game.get('statsVersion', 0) < 2 or not all(checked.get(key) for key in ('player1', 'player2')):
                return {'pending':True}
            for key in ('player1', 'player2'):
                stats = game.get(key + 'Stats')
                if not isinstance(stats, dict): continue  # Confirmed absent from this match.
                marker = (mid, stats.get('puuid') or (duo['id'], key))
                if marker in seen: continue
                seen.add(marker)
                option = options.get(champion_key(stats.get('championName')))
                if not option or not isinstance(stats.get('win'), bool): return {'pending':True}
                total = totals.setdefault(option['id'], {'optionId':option['id'], 'label':option['label'],
                                                       'games':0, 'wins':0, 'losses':0})
                total['games'] += 1
                total['wins'] += int(stats['win'])
                total['losses'] += int(not stats['win'])
    eligible = [total for total in totals.values() if total['games'] >= MIN_CHAMPION_GAMES]
    if not eligible:
        return {'status':'NO_DATA', 'optionIds':[], 'minGames':MIN_CHAMPION_GAMES,
                'summary':'Ningún campeón alcanzó las 3 partidas esta semana. Esta categoría no suma un acierto.'}
    best = max(Fraction(total['wins'], total['games']) for total in eligible)
    leaders = sorted((total for total in eligible if Fraction(total['wins'], total['games']) == best),
                     key=lambda total:total['optionId'])
    return {'status':'SETTLED', 'optionIds':[total['optionId'] for total in leaders],
            'value':float(best * 100), 'minGames':MIN_CHAMPION_GAMES, 'evidence':leaders,
            'summary':f'Mejor winrate semanal · {float(best * 100):.2f} % · mínimo 3 partidas'}


def participant_rank_observation(duo, key, bounds, previous=None):
    """Only evidence for the account selected before this week's deadline."""
    player = duo.get(key) or {}
    selected = player_accounts.elo_account_at(player, bounds['endsAt'])
    identity = account(selected)
    candidates = []
    if previous and previous.get('account') == identity:
        candidates.append(previous)
    current = player_accounts.elo_account(player)
    if current is selected or account(current) == identity:
        if selected.get('rank'):
            candidates.append(selected['rank'])
        # Older records put only P1's rank on the team, never P2's.
        if key == 'player1' and not player.get('accounts') and 'rank' not in player and duo.get('rankObservedAt'):
            candidates.append({**{k: duo.get(k) for k in ('tier','division','lp','wins','losses')}, 'observedAt':duo['rankObservedAt']})
    candidates += selected.get('eloHistory', [])
    for owner in (player, duo) if key == 'player1' else (player,):
        marker = owner.get('eloHistoryAccount')
        if marker and account({'name':marker[0], 'tag':marker[1]}) == identity:
            candidates += owner.get('eloHistory', [])
    candidates = [p for p in candidates if p.get('source','riot') == 'riot' and p.get('tier')
                  and bounds['startsAt'] <= weeks.timestamp(p.get('observedAt')) < bounds['endsAt']]
    if not candidates:
        return None
    latest = max(candidates, key=lambda p: weeks.timestamp(p['observedAt']))
    return {**{k:latest.get(k) for k in ('tier','division','lp','wins','losses','observedAt')}, 'account':identity}


def capture_rankings(db):
    """Preserve pre-close observations before the daily ELO point can be overwritten."""
    changed = False
    for board in (db.get('pickem') or {}).get('weeks', {}).values():
        if not any(c['id'] in RANK_CATEGORIES and c['id'] not in board['results'] for c in board['categories']): continue
        for category in board['categories']:
            if category['id'] in RANK_CATEGORIES and category['id'] not in board['results']:
                description = next(c['description'] for c in CATEGORIES if c['id'] == category['id'])
                if category.get('description') != description:
                    category['description'] = description
                    changed = True
        try: bounds = period(db, board['week'])
        except ValueError: continue
        observations = board.get('rankObservations', {})
        for duo in db.get('duos', []):
            existing = observations.get(duo['id'])
            previous = (existing or {}).get('players', {})
            if existing and existing.get('version') != 2:
                previous = {'player1':existing}  # Upgrade old P1-only evidence, not its result.
            players = {key:participant_rank_observation(duo, key, bounds, previous.get(key)) for key in ('player1','player2')}
            if not any(players.values()): continue
            snapshot = average_rank(players['player1'], players['player2'])
            snapshot.update(players=players, observedAt=min(weeks.timestamp(p['observedAt']) for p in players.values() if p))
            if snapshot != existing:
                observations[duo['id']] = snapshot
                changed = True
        if observations: board['rankObservations'] = observations
    return changed


def weekly_leader(db, board, category):
    return weekly_rank_result(db, board, category)


def weekly_rank_result(db, board, category, lowest=False):
    observations = board.get('rankObservations', {})
    candidates = []
    available = {o['id'] for o in category['options']}
    for duo in db.get('duos', []):
        if duo['id'] not in available: continue
        rank = observations.get(duo['id'])
        end = period(db, board['week'])['endsAt']
        if not rank or not rank.get('ready') or rank.get('version') != 2 or any(
                (rank.get('players', {}).get(key) or {}).get('account') != account(player_accounts.elo_account_at(duo.get(key) or {}, end))
                for key in ('player1','player2')):
            return {'status':'NO_DATA', 'optionIds':[], 'summary':'Sin observaciones de ELO suficientes antes del cierre. Esta categoría no suma un acierto.'}
        candidates.append((duo['id'], rank))
    if lowest and available - {oid for oid,_ in candidates}:
        return {'status':'NO_DATA', 'optionIds':[], 'summary':'Falta un equipo del listado de la primera semana. Esta categoría no suma un acierto.'}
    if not candidates:
        return {'status':'NO_DATA', 'optionIds':[], 'summary':'Sin clasificación semanal disponible. Esta categoría no suma un acierto.'}
    best = (min if lowest else max)(average_rank_key(rank) for _,rank in candidates)
    leaders = [(oid,rank) for oid,rank in candidates if average_rank_key(rank)==best]
    rank = leaders[0][1]
    elo = f"ELO medio: {rank['totalLp']:g} puntos · {rank['label']}"
    label = 'Último puesto de la primera semana' if lowest else 'Primer puesto'
    return {'status':'SETTLED', 'optionIds':[oid for oid,_ in leaders], 'summary':f'{label} · {elo}',
            'observedAt':min(weeks.timestamp(rank['observedAt']) for _,rank in leaders)}


def player_option(options, duo, key, stats):
    """Match saved Riot identities, including retired accounts, rather than a reused slot."""
    player = duo.get(key) or {}
    candidates = [o for (team,slot,_),o in options.items() if team==duo['id'] and slot==key]
    if len(player_accounts.accounts(player)) > 1 and player_accounts.account_for_stats(player, stats):
        owner = next((o for o in candidates if o.get('account') == account(player)), None)
        if owner is not None:
            return owner
    option = next((o for o in candidates if o.get('puuid') and o['puuid']==stats.get('puuid')),None)
    if option is None and stats.get('riotIdGameName'):
        option = next((o for o in candidates if o['account']==account({'name':stats['riotIdGameName'],'tag':stats.get('riotIdTagline')})),None)
    if option is None and (not stats.get('puuid') or player.get('puuid')==stats['puuid']):
        option = options.get((duo['id'],key,tuple(account(player))))
    return option


def best_game_kda(db, board, category):
    bounds = period(db,board['week'])
    options = {(o['teamId'],o['playerKey'],tuple(o['account'])):o for o in category['options']}
    best, leaders, evidence, seen = None, set(), [], set()
    for duo in db.get('duos', []):
        for game in duo.get('history', []):
            mid = game.get('matchId')
            if not mid or game.get('isTest') or game.get('queueId') not in (None,420): continue
            if not bounds['startsAt'] <= weeks.game_time(game) < bounds['endsAt']: continue
            for key in ('player1','player2'):
                stats = game.get(key+'Stats')
                if not isinstance(stats,dict): continue
                option = player_option(options, duo, key, stats)
                if not option or (mid,option['id']) in seen: continue
                seen.add((mid,option['id']))
                totals = [stats.get(k) for k in ('kills','deaths','assists')]
                if any(not isinstance(v,int) or isinstance(v,bool) or v<0 for v in totals):
                    return {'pending':True}
                kills,deaths,assists = totals
                ratio = Fraction(kills+assists,max(deaths,1))
                if best is None or ratio>best: best,leaders,evidence = ratio,set(),[]
                if ratio==best:
                    leaders.add(option['id'])
                    evidence.append({'optionId':option['id'],'matchId':mid,'kills':kills,'deaths':deaths,'assists':assists})
    if best is None:
        return {'status':'NO_GAMES', 'optionIds':[], 'summary':'Sin partidas individuales válidas. Esta categoría no suma un acierto.'}
    return {'status':'SETTLED','optionIds':sorted(leaders),'value':float(best),
            'summary':f'Mejor partida individual · {float(best):.2f} KDA', 'evidence':evidence}


def weekly_player_kda(db, board, category):
    """Compare each account's accumulated weekly K/D/A, not its best game or average."""
    bounds = period(db, board['week'])
    options = {(o['teamId'], o['playerKey'], tuple(o['account'])): o for o in category['options']}
    totals, seen = {}, set()
    for duo in db.get('duos', []):
        if (duo.get('riotMatchDiscovery') or {}).get('pendingMatchIds'): return {'pending': True}
        for game in duo.get('history', []):
            mid = game.get('matchId')
            if not mid or game.get('isTest') or game.get('queueId') not in (None, 420): continue
            if not bounds['startsAt'] <= weeks.game_time(game) < bounds['endsAt']: continue
            checked = game.get('participantsChecked') or {}
            if game.get('statsVersion', 0) < 2 or not all(checked.get(key) for key in ('player1', 'player2')):
                return {'pending': True}
            for key in ('player1', 'player2'):
                stats = game.get(key + 'Stats')
                if not isinstance(stats, dict): continue  # Confirmed absent from this match.
                option = player_option(options, duo, key, stats)
                if not option or (mid, option['id']) in seen: continue
                seen.add((mid, option['id']))
                values = [stats.get(field) for field in ('kills', 'deaths', 'assists')]
                if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
                    return {'pending': True}
                total = totals.setdefault(option['id'], {'optionId': option['id'], 'label': option['label'],
                    'kills': 0, 'deaths': 0, 'assists': 0, 'games': 0, 'matchIds': []})
                for field, value in zip(('kills', 'deaths', 'assists'), values): total[field] += value
                total['games'] += 1
                total['matchIds'].append(mid)
    if not totals:
        return {'status': 'NO_GAMES', 'optionIds': [],
                'summary': 'Sin partidas individuales válidas esta semana. Esta categoría no suma un acierto.'}
    ratio = lambda total: Fraction(total['kills'] + total['assists'], max(total['deaths'], 1))
    best = max(ratio(total) for total in totals.values())
    leaders = sorted((total for total in totals.values() if ratio(total) == best), key=lambda total: total['optionId'])
    return {'status': 'SETTLED', 'optionIds': [total['optionId'] for total in leaders], 'value': float(best),
            'summary': f'Mejor KDA acumulado semanal · {float(best):.2f} KDA', 'evidence': leaders}


def opening_deaths_duel(db, board, category):
    """Accumulate only the two bound participants' deaths in the opening week's stored games."""
    return participant_stat_duel(db, board, category, 'deaths', 'muertes')


def participant_stat_duel(db, board, category, metric, metric_label):
    """Sum a weekly stat for two bound accounts, preserving identities and confirmed data."""
    contenders = category['options']
    if len(contenders)!=2 or any(not o.get('account') for o in contenders):
        names = ' o '.join(category.get('contenders') or [o['label'] for o in contenders])
        return {'status':'NO_DATA', 'optionIds':[], 'summary':f'Falta identificar a {names}. Esta categoría no suma un acierto.'}
    bounds = period(db,board['week'])
    options = {(o['teamId'],o['playerKey'],tuple(o['account'])):o for o in contenders}
    totals, evidence = [], []
    for contender in contenders:
        duo = next((d for d in db.get('duos',[]) if d['id']==contender['teamId']),None)
        if not duo:
            return {'status':'NO_DATA', 'optionIds':[], 'summary':'Falta un participante del evento. Esta categoría no suma un acierto.'}
        if (duo.get('riotMatchDiscovery') or {}).get('pendingMatchIds'): return {'pending':True}
        key, total, games, seen = contender['playerKey'],0,0,set()
        for game in duo.get('history',[]):
            mid = game.get('matchId')
            if not mid or mid in seen or game.get('isTest') or game.get('queueId') not in (None,420): continue
            at = weeks.game_time(game)
            if not bounds['startsAt']<=at<bounds['endsAt']: continue
            seen.add(mid)
            if game.get('statsVersion',0)<2 or not (game.get('participantsChecked') or {}).get(key): return {'pending':True}
            stats = game.get(key+'Stats')
            if not isinstance(stats,dict): continue  # Confirmed absent from this match.
            matched = player_option(options,duo,key,stats)
            if not matched or matched['id']!=contender['id']: continue
            value = stats.get(metric)
            if not isinstance(value,int) or isinstance(value,bool) or value<0: return {'pending':True}
            total += value
            games += 1
            evidence.append({'optionId':contender['id'],'matchId':mid,metric:value,'gameEndTimestamp':at*1000})
        totals.append({'optionId':contender['id'],'label':contender['label'],metric:total,'games':games})
    if not any(t['games'] for t in totals):
        return {'status':'NO_GAMES', 'optionIds':[], 'totals':totals,
                'summary':f"Sin partidas válidas de {' y '.join(o['label'] for o in contenders)} esta semana. Esta categoría no suma un acierto."}
    most = max(t[metric] for t in totals)
    return {'status':'SETTLED', 'optionIds':[t['optionId'] for t in totals if t[metric]==most],
            'totals':totals, 'evidence':evidence,
            'summary':' · '.join(f"{t['label']}: {t[metric]} {metric_label}" for t in totals)}


def first_individual_shell(db, category, now=None):
    """First qualifying individual performance of the tournament, independent of import order or inventory."""
    now = time.time() if now is None else now
    start = weeks.timestamp(db['config']['startDate'])
    end = weeks.timestamp(db['config']['endDate'])
    options = {(o['teamId'],o['playerKey'],tuple(o['account'])):o for o in category['options']}
    first, leaders, evidence, seen, incomplete = None, set(), [], set(), []
    for duo in db.get('duos', []):
        if (duo.get('riotMatchDiscovery') or {}).get('pendingMatchIds'): return {'pending':True}
        for game in duo.get('history', []):
            mid, at = game.get('matchId'), weeks.game_time(game)
            if not mid or game.get('isTest') or game.get('queueId') not in (None,420): continue
            if not start <= at < min(now,end): continue
            checked = game.get('participantsChecked') or {}
            if game.get('statsVersion',0)<2 or not all(checked.get(k) for k in ('player1','player2')):
                incomplete.append(at)
            for key in ('player1','player2'):
                stats = game.get(key+'Stats')
                if not isinstance(stats,dict): continue
                option = player_option(options, duo, key, stats)
                if not option or (mid,option['id']) in seen: continue
                seen.add((mid,option['id']))
                totals = [stats.get(k) for k in ('kills','deaths','assists')]
                if any(not isinstance(v,int) or isinstance(v,bool) or v<0 for v in totals):
                    incomplete.append(at)
                    continue
                kills,deaths,assists = totals
                penta = stats.get('pentaKills')
                multi = stats.get('largestMultiKill')
                valid_penta = isinstance(penta,int) and not isinstance(penta,bool) and penta>=0
                valid_multi = isinstance(multi,int) and not isinstance(multi,bool) and multi>=0
                if not valid_penta and not valid_multi and game.get('pentaKill') is not False:
                    # A team pentakill flag cannot identify its author.
                    incomplete.append(at)
                    continue
                criteria = individual_shell_criteria({**stats, 'pentaKills':penta if valid_penta else 0,
                                                      'largestMultiKill':multi if valid_multi else 0})
                if not criteria: continue
                if first is None or at<first: first,leaders,evidence = at,set(),[]
                if at==first:
                    leaders.add(option['id'])
                    evidence.append({'optionId':option['id'],'teamId':duo['id'],'matchId':mid,
                        'gameEndTimestamp':at*1000,'criteria':criteria,'kills':kills,'deaths':deaths,
                        'assists':assists,'pentaKills':penta,'largestMultiKill':multi})
    if any(first is None or at<=first for at in incomplete): return {'pending':True}
    if first is not None:
        return {'status':'SETTLED','optionIds':sorted(leaders),'firstAt':first,'evidence':evidence,
                'summary':'Primer logro individual del torneo · '+datetime.fromtimestamp(first,weeks.MADRID).strftime('%d/%m %H:%M')}
    final_scan = (db.get('pickem',{}).get('lastCompleteSync') or {}).get('startedAt',0) >= end+SETTLEMENT_GRACE
    if not final_scan: return {'pending':True}
    return {'status':'NO_GAMES','optionIds':[], 'summary':'Nadie consiguió un logro individual durante el torneo. Esta categoría no suma un acierto.'}


def first_five_negative(db, category, now=None):
    """One tournament-opening prediction; never replace unfinished games with losses."""
    now = time.time() if now is None else now
    start = weeks.timestamp(db['config']['startDate'])
    end = weeks.timestamp(db['config']['endDate'])
    final_scan = (db.get('pickem',{}).get('lastCompleteSync') or {}).get('startedAt',0) >= end+SETTLEMENT_GRACE
    teams = {d['id']:d for d in db.get('duos',[])}
    evidence, negative = [], 0
    for team_id in category['teamIds']:
        duo = teams.get(team_id)
        if not duo:
            return {'status':'NO_DATA','optionIds':[], 'summary':'Falta un equipo del listado original. Esta categoría no suma un acierto.'}
        if (duo.get('riotMatchDiscovery') or {}).get('pendingMatchIds'): return {'pending':True}
        matches = {}
        for match in duo.get('history',[]):
            mid = match.get('matchId')
            if not mid or match.get('isTest') or match.get('queueId') not in (None,420): continue
            if start <= weeks.game_time(match) < min(end,now): matches.setdefault(mid,match)
        first = sorted(matches.values(),key=lambda m:(weeks.game_time(m),m['matchId']))[:5]
        if len(first)<5:
            if not final_scan: return {'pending':True}
            evidence.append({'teamId':team_id,'teamName':duo['teamName'],'games':len(first),'completed':False})
            continue
        if any(m.get('result') not in ('WIN','LOSS') for m in first): return {'pending':True}
        wins = sum(m['result']=='WIN' for m in first)
        negative += wins<3
        evidence.append({'teamId':team_id,'teamName':duo['teamName'],'games':5,'completed':True,
                         'wins':wins,'losses':5-wins,'winrate':wins*20,'negative':wins<3,
                         'matchIds':[m['matchId'] for m in first]})
    if not evidence or not any(e['completed'] for e in evidence):
        return {'status':'NO_GAMES','optionIds':[], 'summary':'Ningún dúo completó sus primeras cinco ranked. Esta categoría no suma un acierto.','evidence':evidence}
    return {'status':'SETTLED','optionIds':[str(negative)],'value':negative,'evidence':evidence,
            'summary':f'{negative} '+('dúo con' if negative==1 else 'dúos con')+' winrate negativo en sus primeras 5 ranked'}


def category_result(db, board, category, now=None):
    if category['id']=='chicha_fogell_kills': return participant_stat_duel(db,board,category,'kills','kills')
    if category['id']=='weekly_player_kda': return weekly_player_kda(db,board,category)
    if category['id']=='best_champion_winrate': return best_champion_winrate(db,board,category)
    if category['id']=='weekly_leader': return weekly_leader(db,board,category)
    if category['id']=='first_week_last': return weekly_rank_result(db,board,category,lowest=True)
    if category['id']=='joji_parradise_deaths': return opening_deaths_duel(db,board,category)
    if category['id']=='first_five_negative': return first_five_negative(db,category,now)
    if category['id']=='first_individual_shell': return first_individual_shell(db,category,now)
    metric = champion_count(db,board)
    if metric['pending']: return {'pending':True}
    if category['id']=='best_game_kda': return best_game_kda(db,board,category)
    if category['id']!='unique_champions': return {'pending':True}
    option = next(o for o in category['options'] if o['min']<=metric['value'] and (o['max'] is None or metric['value']<=o['max']))
    return {**metric, 'status':'SETTLED' if metric['games'] else 'NO_GAMES',
            'optionIds':[option['id']] if metric['games'] else [],
            'summary':f"{metric['value']} campeones distintos" if metric['games'] else 'Sin partidas válidas. Esta categoría no suma un acierto.'}


def ensure_reward_rule(board):
    """Keep already paid legacy prizes, without paying them again under the new rule."""
    if 'rewardRule' in board:
        if board['rewardRule'].get('version', 1) < 2 and not board.get('ballotRewards'):
            board['rewardRule'] = copy.deepcopy(REWARD_RULE)
            board.setdefault('ballotRewards', {})
            return True
        return False
    board['rewardRule'] = copy.deepcopy(REWARD_RULE)
    board['ballotRewards'] = {}
    for result in board.get('results', {}).values():
        for winner in result.get('winners', []):
            if not winner.get('shells'): continue
            reward = board['ballotRewards'].setdefault(winner['ballotId'], {
                'status': 'AWARDED', 'shells': 0, 'legacy': True, 'settledAt': result.get('settledAt')})
            reward['shells'] += winner['shells']
    return True


def ballot_score(board, ballot):
    correct, pending = [], []
    for category in board['categories']:
        answer = ballot['answers'].get(category['id'])
        if answer is None: continue
        result = board['results'].get(category['id'])
        if result is None:
            pending.append(category['id'])
        elif result['status'] == 'SETTLED' and answer in result.get('optionIds', []):
            correct.append(category['id'])
    return {'correct': len(correct), 'correctCategoryIds': correct, 'pending': len(pending)}


def reward_ballots(db, board, now):
    changed = False
    rule = board['rewardRule']
    tiers = rule.get('tiers') or [rule]
    for ballot in board['ballots']:
        previous = board['ballotRewards'].get(ballot['id'])
        if previous and (previous.get('legacy') or previous.get('final', True)): continue
        score = ballot_score(board, ballot)
        earned = max((tier['shells'] for tier in tiers if score['correct'] >= tier['minCorrect']), default=0)
        if not earned and score['pending']: continue
        team = next((d for d in db.get('duos', []) if d['id'] == ballot['teamId']), None)
        paid = int((previous or {}).get('shells', 0))
        amount = max(paid, earned if team else 0)
        additional = amount - paid
        next_threshold = min((tier['minCorrect'] for tier in tiers if tier['shells'] > amount), default=None)
        final = not team or next_threshold is None or not score['pending'] or score['correct'] + score['pending'] < next_threshold
        reward = {**score, 'status': 'AWARDED' if amount else 'NO_REWARD', 'shells': amount, 'final': final}
        if previous and all(previous.get(key) == value for key, value in reward.items()): continue
        reward['settledAt'] = now if additional or not previous else previous['settledAt']
        board['ballotRewards'][ballot['id']] = reward
        if additional:
            team['blueShells'] = int(team.get('blueShells', 0) or 0) + additional
            team['pickemShellsEarnedTotal'] = int(team.get('pickemShellsEarnedTotal', 0) or 0) + additional
            noun = 'pepazo' if additional == 1 else 'pepazos'
            bonus = f' ({amount} pepazos en total)' if paid else ''
            db.setdefault('events', []).insert(0, {
                'id': f"pickem-{board['week']}-ballot-{ballot['id']}" + (f'-upgrade-{amount}' if paid else ''), 'type': 'PICKEM_REWARD',
                'timestamp': datetime.fromtimestamp(now, weeks.MADRID).strftime('%Y-%m-%d %H:%M:%S'),
                'week': board['week'], 'ballotId': ballot['id'], 'teamId': team['id'],
                'target': team['teamName'], 'shells': additional, 'totalShells': amount, 'correct': score['correct'],
                'message': f"🔮 {team['teamName']} gana {additional} {noun} por una quiniela con {score['correct']} aciertos{bonus}"})
        changed = True
    return changed


def maintain(db, now=None):
    state=db.get('pickem')
    if not state: return False
    now=time.time() if now is None else now
    changed=False
    checkpoint=state.get('lastCompleteSync') or {}
    for board in state['weeks'].values():
        changed = ensure_reward_rule(board) or changed
        try: bounds=period(db,board['week'])
        except ValueError: continue
        if now<bounds['endsAt']+SETTLEMENT_GRACE or checkpoint.get('startedAt',0)<bounds['endsAt']+SETTLEMENT_GRACE:
            continue
        if checkpoint.get('roster')!=roster_key(db): continue
        for category in board['categories']:
            if category['id'] in board['results']: continue
            metric=category_result(db,board,category,now)
            if metric.get('pending'): continue
            correct_ids=metric.pop('optionIds')
            correct_options=[o for o in category['options'] if o['id'] in correct_ids]
            board['results'][category['id']]={**metric, 'optionIds':correct_ids,
                'optionId':correct_ids[0] if correct_ids else None,
                'optionLabel':' / '.join(o['label'] for o in correct_options) or None,'settledAt':now}
            changed=True
        changed = reward_ballots(db, board, now) or changed
    return changed


def record_complete_sync(db, original, started_at, now=None):
    if not db.get('pickem') or roster_key(db)!=roster_key(original): return False
    db['pickem']['lastCompleteSync']={'startedAt':started_at,'finishedAt':time.time() if now is None else now,'roster':roster_key(db)}
    maintain(db,now)
    return True


def visible_ballot(board, ballot):
    return {**{key: copy.deepcopy(ballot.get(key)) for key in
               ('id', 'teamId', 'teamName', 'author', 'answers', 'createdAt')},
            **ballot_score(board, ballot),
            'reward': copy.deepcopy(board.get('ballotRewards', {}).get(ballot['id']))}


def period_list(db):
    return {key: period(db, key) for key in sorted(db['pickem']['weeks'], reverse=True)}


def admin_board(db, selected_week=None, now=None):
    """Only for authenticated admin routes. No visitor hashes or account credentials."""
    public = public_board(db, selected_week=selected_week, now=now)
    board = db['pickem']['weeks'][public['week']]
    public['predictions'] = [visible_ballot(board, ballot) for ballot in board['ballots']]
    return public


def public_board(db, team_id=None, visitor=None, selected_week=None, now=None):
    now=time.time() if now is None else now
    state=db['pickem']
    available=sorted(state['weeks'],reverse=True)
    selected_week=selected_week or available[0]
    if selected_week not in state['weeks']: raise LookupError('No existe esa semana de Pick’em.')
    board=state['weeks'][selected_week]
    rule = board.get('rewardRule', REWARD_RULE)
    bounds=period(db,selected_week)
    status=ballot_status(db,board,team_id,visitor,now)
    ballot=status.pop('ballot')
    def outcome(b):
        return {**ballot_score(board, b), 'reward': copy.deepcopy(board.get('ballotRewards', {}).get(b['id']))}
    personal={'author':ballot['author'],'answers':copy.deepcopy(ballot['answers']), **outcome(ballot)} if ballot else None
    categories=[]
    for category in board['categories']:
        c=copy.deepcopy(category)
        c.pop('reward', None)
        c['options']=[{k:o[k] for k in ('id','label','disabled') if k in o} for o in c['options']]
        c['result']=copy.deepcopy(board['results'].get(c['id']))
        c['myAnswer']=(ballot or {}).get('answers',{}).get(c['id'])
        if c.get('kind') == 'duel':
            choice = team_duel_choice(board, status['teamId'], c['id']) if status['teamId'] else {'answer':None, 'conflict':False}
            c['sharedWithTeam'] = True
            c['teamAnswer'] = choice['answer']
            c['teamAnswerConflict'] = choice['conflict']
        categories.append(c)
    predictions=[]
    visible_at = bounds['endsAt'] if db.get('config', {}).get('pickemSchedule') else bounds['closesAt']
    if now>=visible_at:
        predictions=[visible_ballot(board, b) for b in board['ballots']]
    return {'week':selected_week,'weeks':available,**bounds,'closed':now>=bounds['closesAt'],
            'categories':categories,'participation':status,'myBallot':personal,'predictions':predictions,
            'teamBallots':[visible_ballot(board, b) for b in board['ballots'] if status['teamId'] and b['teamId']==status['teamId']],
            'resultsVisible':now>=visible_at, 'periods':period_list(db),
            'entries':len(board['ballots']), 'rewardRule':copy.deepcopy(rule)}
