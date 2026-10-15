"""Weekly Pick'em ballots and atomic shell prizes from stored participant games."""
import copy
import hashlib
import re
import time
import uuid
from datetime import datetime
from fractions import Fraction
from trophies import rank_key
from shell_rules import individual_shell_criteria
import weekly_summary as weeks

MAX_TEAM_BALLOTS = 2
REWARD_RULE = {'minCorrect': 3, 'shells': 1}
SETTLEMENT_GRACE = 300
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
               'description': 'Último ELO registrado antes de terminar la semana: rango, división y LP; desempate por winrate. En empate exacto, valen los equipos empatados.'},
              {'id': 'first_week_last', 'kind': 'team', 'icon': '🪦', 'eventLabel': 'ESTRENO DEL TORNEO',
               'placeholder': 'Selecciona un equipo',
               'title': '¿Qué equipo quedará último la primera semana?',
               'description': 'El equipo con menor ELO al cierre de la primera semana: rango, división y LP; desempate por winrate. En empate exacto, valen todos los equipos empatados.'},
              {'id': 'best_game_kda', 'kind': 'player', 'icon': '⚔', 'placeholder': 'Selecciona un jugador',
               'title': '¿Quién hará la partida con mejor KDA?',
               'description': 'La mejor partida individual de la semana: (asesinatos + asistencias) / máximo(muertes, 1). En empate exacto, valen todos los empatados.'},
              {'id': 'first_individual_shell', 'kind': 'player', 'icon': '🐢', 'eventLabel': 'ESTRENO DEL TORNEO',
               'placeholder': 'Selecciona un jugador',
               'title': '¿Quién conseguirá el primer caparazón individual del torneo?',
               'description': 'Primer jugador con pentakill, 20+ asesinatos, 30+ asistencias o 0 muertes y más de 20 asesinatos + asistencias. Cuenta aunque su equipo tenga el inventario lleno. Se usa el final de la partida; si coinciden varios jugadores, todos valen.'},
              {'id': 'joji_parradise_deaths', 'kind': 'duel', 'icon': '💀', 'eventLabel': 'EVENTO · PRIMERA SEMANA',
               'placeholder': 'Selecciona a Joji o Parradise',
               'title': '¿Quién morirá más: Joji o Parradise?',
               'description': 'Muertes acumuladas de Joji y Parradise en las Solo/Duo registradas durante la primera semana del torneo. Gana quien sume más muertes; en empate, ambas respuestas valen.',
               'contenders': ['Joji', 'Parradise']},
              {'id': 'first_five_negative', 'kind': 'count', 'icon': '📉', 'eventLabel': 'ESTRENO DEL TORNEO',
               'placeholder': 'Selecciona cuántos dúos',
               'title': '¿Cuántos dúos tendrán winrate negativo en sus primeras 5 ranked?',
               'description': 'Las cinco primeras Solo/Duo registradas desde el inicio del torneo. Un dúo cuenta con 0, 1 o 2 victorias; si le faltan partidas, esperamos a que las complete. Al terminar el torneo, los incompletos no cuentan.',
               'options': [{'id':str(n),'label':str(n)} for n in range(10)]}]


def account(player):
    return [str(player.get('name') or '').strip().casefold(), str(player.get('tag') or 'EUW').strip().casefold()]


def category_definitions(db, week=None):
    definitions = copy.deepcopy(CATEGORIES)
    if week and week != weeks.week_key(weeks.timestamp(db.get('config',{}).get('startDate'))):
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
                              for k in ('player1','player2') for f in ('name','tag')]] for d in db.get('duos',[])])


def period(db, week):
    start, end = weeks.bounds(week)
    tournament_start = weeks.timestamp(db.get('config',{}).get('startDate'))
    tournament_end = weeks.timestamp(db.get('config',{}).get('endDate'))
    if not tournament_start or tournament_end <= tournament_start:
        raise ValueError('El calendario del torneo no está configurado.')
    return {'startsAt': max(start,tournament_start), 'endsAt': min(end,tournament_end),
            'closesAt': min(end-60,tournament_end)}


def ensure_week(db, now=None):
    now = time.time() if now is None else now
    config = db.get('config',{})
    start, end = weeks.timestamp(config.get('startDate')), weeks.timestamp(config.get('endDate'))
    if not start or end <= start: raise ValueError('El calendario del torneo no está configurado.')
    key = weeks.week_key(min(max(now,start),end-0.001))
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
    elif now >= bounds['closesAt']: reason,message = 'closed','Las predicciones de esta semana están cerradas.'
    elif bounds['startsAt'] >= bounds['endsAt']: reason,message = 'closed','Esta semana queda fuera del torneo.'
    elif own and own['teamId']!=team_id: reason,message = 'browser','Este navegador ya tiene una quiniela esta semana.'
    elif not own and sum(b['teamId']==team_id for b in board['ballots'])>=MAX_TEAM_BALLOTS:
        reason,message = 'team','Tu equipo ya ha utilizado sus dos quinielas esta semana.'
    else: reason,message = 'ready',f"Participando como {team['teamName']}."
    return {'teamId':team_id if team else None, 'teamName':team['teamName'] if team else None,
            'canAnswer':reason=='ready', 'reason':reason, 'message':message,
            'ballot':own if own and team and own['teamId']==team_id else None}


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
                name=re.sub(r'[^a-z0-9]','',str(stats.get('championName') or '').casefold())
                if not name or name=='unknown': pending=True;continue
                champions.add({'wukong':'monkeyking','nunuandwillump':'nunu'}.get(name,name))
    return {'value':len(champions),'games':len(games),'pending':pending}


def capture_rankings(db):
    """Preserve pre-close observations before the daily ELO point can be overwritten."""
    changed = False
    for board in (db.get('pickem') or {}).get('weeks', {}).values():
        if not any(c['id'] in RANK_CATEGORIES and c['id'] not in board['results'] for c in board['categories']): continue
        try: bounds = period(db, board['week'])
        except ValueError: continue
        observations = board.get('rankObservations', {})
        for duo in db.get('duos', []):
            player = duo.get('player1') or {}
            identity = account(player)
            candidates = []
            # The team leaderboard uses the first account's rank, just like the main table.
            if duo.get('rankObservedAt') and not ('rank' in player and player['rank'] is None):
                candidates.append({**{k: duo.get(k) for k in ('tier','division','lp','wins','losses')},
                                   'observedAt': duo['rankObservedAt']})
            for owner in (duo, player):
                if owner.get('eloHistoryAccount') == [str(player.get('name','')).lower(), str(player.get('tag','')).lower()]:
                    candidates += owner.get('eloHistory', [])
            candidates = [p for p in candidates if p.get('source','riot') == 'riot' and p.get('tier')
                          and bounds['startsAt'] <= weeks.timestamp(p.get('observedAt')) < bounds['endsAt']]
            if not candidates: continue
            latest = max(candidates, key=lambda p: weeks.timestamp(p['observedAt']))
            snapshot = {k: latest.get(k) for k in ('tier','division','lp','wins','losses','observedAt')}
            snapshot['account'] = identity
            existing = observations.get(duo['id'])
            if not existing or existing['account'] != identity or weeks.timestamp(snapshot['observedAt']) > weeks.timestamp(existing['observedAt']):
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
        if not rank or rank['account'] != account(duo.get('player1') or {}):
            return {'status':'NO_DATA', 'optionIds':[], 'summary':'Sin observaciones de ELO suficientes antes del cierre. Esta categoría no suma un acierto.'}
        candidates.append((duo['id'], rank))
    if lowest and available - {oid for oid,_ in candidates}:
        return {'status':'NO_DATA', 'optionIds':[], 'summary':'Falta un equipo del listado de la primera semana. Esta categoría no suma un acierto.'}
    if not candidates or not any(rank_key(rank)[0] for _,rank in candidates):
        return {'status':'NO_DATA', 'optionIds':[], 'summary':'Sin clasificación semanal disponible. Esta categoría no suma un acierto.'}
    best = (min if lowest else max)(rank_key(rank) for _,rank in candidates)
    leaders = [(oid,rank) for oid,rank in candidates if rank_key(rank)==best]
    rank = leaders[0][1]
    elo = f"{rank['tier']} {rank.get('division') or ''} · {rank.get('lp') or 0} LP".replace('  ', ' ')
    label = 'Último puesto de la primera semana' if lowest else 'Primer puesto'
    return {'status':'SETTLED', 'optionIds':[oid for oid,_ in leaders], 'summary':f'{label} · {elo}',
            'observedAt':min(weeks.timestamp(rank['observedAt']) for _,rank in leaders)}


def player_option(options, duo, key, stats):
    """Match saved Riot identities, including retired accounts, rather than a reused slot."""
    player = duo.get(key) or {}
    candidates = [o for (team,slot,_),o in options.items() if team==duo['id'] and slot==key]
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


def opening_deaths_duel(db, board, category):
    """Accumulate only the two bound participants' deaths in the opening week's stored games."""
    contenders = category['options']
    if len(contenders)!=2 or any(not o.get('account') for o in contenders):
        return {'status':'NO_DATA', 'optionIds':[], 'summary':'Falta identificar a Joji o Parradise. Esta categoría no suma un acierto.'}
    bounds = period(db,board['week'])
    options = {(o['teamId'],o['playerKey'],tuple(o['account'])):o for o in contenders}
    totals, evidence = [], []
    for contender in contenders:
        duo = next((d for d in db.get('duos',[]) if d['id']==contender['teamId']),None)
        if not duo:
            return {'status':'NO_DATA', 'optionIds':[], 'summary':'Falta un participante del evento. Esta categoría no suma un acierto.'}
        if (duo.get('riotMatchDiscovery') or {}).get('pendingMatchIds'): return {'pending':True}
        key, deaths, games, seen = contender['playerKey'],0,0,set()
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
            value = stats.get('deaths')
            if not isinstance(value,int) or isinstance(value,bool) or value<0: return {'pending':True}
            deaths += value
            games += 1
            evidence.append({'optionId':contender['id'],'matchId':mid,'deaths':value,'gameEndTimestamp':at*1000})
        totals.append({'optionId':contender['id'],'label':contender['label'],'deaths':deaths,'games':games})
    if not any(t['games'] for t in totals):
        return {'status':'NO_GAMES', 'optionIds':[], 'totals':totals,
                'summary':'Sin partidas válidas de Joji y Parradise esta semana. Esta categoría no suma un acierto.'}
    most = max(t['deaths'] for t in totals)
    return {'status':'SETTLED', 'optionIds':[t['optionId'] for t in totals if t['deaths']==most],
            'totals':totals, 'evidence':evidence,
            'summary':' · '.join(f"{t['label']}: {t['deaths']} muertes" for t in totals)}


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
    if 'rewardRule' in board: return False
    board['rewardRule'] = dict(REWARD_RULE)
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
    for ballot in board['ballots']:
        if ballot['id'] in board['ballotRewards']: continue
        score = ballot_score(board, ballot)
        qualifies = score['correct'] >= rule['minCorrect']
        if not qualifies and score['pending']: continue
        team = next((d for d in db.get('duos', []) if d['id'] == ballot['teamId']), None)
        amount = rule['shells'] if qualifies and team else 0
        board['ballotRewards'][ballot['id']] = {
            **score, 'status': 'AWARDED' if amount else 'NO_REWARD', 'shells': amount, 'settledAt': now}
        if amount:
            team['blueShells'] = int(team.get('blueShells', 0) or 0) + amount
            team['pickemShellsEarnedTotal'] = int(team.get('pickemShellsEarnedTotal', 0) or 0) + amount
            db.setdefault('events', []).insert(0, {
                'id': f"pickem-{board['week']}-ballot-{ballot['id']}", 'type': 'PICKEM_REWARD',
                'timestamp': datetime.fromtimestamp(now, weeks.MADRID).strftime('%Y-%m-%d %H:%M:%S'),
                'week': board['week'], 'ballotId': ballot['id'], 'teamId': team['id'],
                'target': team['teamName'], 'shells': amount, 'correct': score['correct'],
                'message': f"🔮 {team['teamName']} gana {amount} caparazón por una quiniela con {score['correct']} aciertos"})
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
        categories.append(c)
    predictions=[]
    if now>=bounds['closesAt']:
        predictions=[{**{k:copy.deepcopy(b[k]) for k in ('id','teamId','teamName','author','answers','createdAt')}, **outcome(b)} for b in board['ballots']]
    return {'week':selected_week,'weeks':available,**bounds,'closed':now>=bounds['closesAt'],
            'categories':categories,'participation':status,'myBallot':personal,'predictions':predictions,
            'entries':len(board['ballots']), 'rewardRule':dict(rule)}
