"""Team gold and next-received-match prediction pools. All writes are atomic with the DB."""
import copy
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import player_accounts
import riot_match_policy

MADRID = ZoneInfo('Europe/Madrid')
DAILY_GOLD = 10
INITIAL_GOLD = 10
WAIT_SECONDS = 20 * 60
METRICS = {'result', 'kills', 'deaths', 'assists'}


def ensure(db, now):
    changed = False
    if 'betting' not in db:
        db['betting'] = {'version':1, 'activatedAt':now, 'wallets':{}, 'receipts':{},
                         'markets':[], 'bets':[], 'rounds':[], 'operations':{}, 'ledger':[]}
        changed = True
    state = db['betting']
    today = datetime.fromtimestamp(now,MADRID).date()
    for duo in db.get('duos',[]):
        if not duo.get('id'): continue
        if duo['id'] not in state['wallets']:
            cutoff = datetime.combine(today, datetime.min.time(), MADRID).replace(hour=23,minute=59).timestamp()
            first_day = today + timedelta(days=now > cutoff)
            state['wallets'][duo['id']] = {'balance':INITIAL_GOLD, 'createdAt':now,
                'nextDailyDate':first_day.isoformat()}
            if INITIAL_GOLD:
                state['ledger'].append({'id':'initial:'+duo['id'], 'teamId':duo['id'], 'amount':INITIAL_GOLD,
                                        'kind':'INITIAL', 'at':now})
            changed = True
    return state, changed


def grant_daily(db, state, now):
    local = datetime.fromtimestamp(now,MADRID)
    due = local.date() if (local.hour,local.minute) >= (23,59) else local.date()-timedelta(days=1)
    changed = False
    active = {d['id'] for d in db.get('duos',[]) if d.get('id')}
    for team_id,wallet in state['wallets'].items():
        first = datetime.fromisoformat(wallet['nextDailyDate']).date()
        if first > due: continue
        days = (due-first).days+1
        if team_id in active:
            amount = days*DAILY_GOLD
            wallet['balance'] += amount
            state['ledger'].append({'id':f'daily:{team_id}:{first}:{due}', 'kind':'DAILY',
                'teamId':team_id, 'amount':amount, 'firstDate':str(first), 'lastDate':str(due), 'at':now})
        wallet['nextDailyDate'] = str(due+timedelta(days=1))
        changed = True
    return changed


def valid_match(duo, match):
    duration = match.get('durationSeconds')
    return bool(match.get('matchId') and not match.get('isTest')
        and match['matchId'] not in (duo.get('excludedRiotMatches') or {})
        and match.get('queueId') in (None,420)
        and riot_match_policy.match_timestamp_ms(match) is not None
        and not riot_match_policy.before_cutoff(match)
        and not (isinstance(duration,(int,float)) and 0 < duration < 600))


def observe(db, state, now):
    changed = False
    for duo in db.get('duos',[]):
        if not duo.get('id'): continue
        receipts = state['receipts'].setdefault(duo['id'], {})
        matches = sorted((m for m in duo.get('history',[]) if valid_match(duo,m)),
                         key=lambda m:(riot_match_policy.match_timestamp_ms({'gameEndTimestamp':m.get('gameEndTimestamp')}) or riot_match_policy.match_timestamp_ms(m),m['matchId']))
        for match in matches:
            if match['matchId'] not in receipts:
                receipts[match['matchId']] = {'at':now,'sequence':len(receipts)+1}
                changed = True
    return changed


def threshold(value):
    if not isinstance(value,str) or not re.fullmatch(r'(?:0|[1-9][0-9]?)['+re.escape(',.')+r']5',value):
        raise ValueError('Introduce una línea terminada en ,5, entre 0,5 y 49,5.')
    whole = int(re.split(r'[,\.]',value)[0])
    if whole > 49: raise ValueError('La línea debe ser menor de 50 y terminar en ,5.')
    return whole*2+1


def outcome(duo, market, match):
    # None means pending evidence; SKIP means a confirmed absence or invalid match.
    if not match or not valid_match(duo,match): return 'SKIP',None
    if market['metric']=='result':
        result = match.get('result')
        return (result if result in ('WIN','LOSS') else None),result
    player = duo.get(market['playerKey']) or {}
    if player_accounts.identity(player) != market['playerIdentity']: return 'VOID',None
    stats = match.get(market['playerKey']+'Stats')
    if not isinstance(stats,dict):
        absent = (match.get('participantsChecked') or {}).get(market['playerKey']) is True
        return ('SKIP' if absent else None),None
    if not player_accounts.owns_stats(player,stats): return 'SKIP',None
    number = stats.get(market['metric'])
    if type(number) is not int or number < 0: return None,None
    return ('OVER' if number*2 > market['lineHalf'] else 'UNDER'),number


def credit(state, bet, amount, round_id, now):
    state['wallets'][bet['teamId']]['balance'] += amount
    state['ledger'].append({'id':f'payout:{bet["id"]}', 'kind':'PAYOUT', 'teamId':bet['teamId'],
                            'amount':amount, 'roundId':round_id, 'at':now})
    bet.update(status='SETTLED', payout=amount, roundId=round_id, settledAt=now)


def settle_pool(state, market, bets, match_id, received_at, winning, value, now, reason=None):
    round_id = str(uuid.uuid4())
    sides = {b['side'] for b in bets}
    refund = reason is not None or len(sides)<2
    pool = sum(b['amount'] for b in bets)
    payouts = {b['id']:b['amount'] if refund else 0 for b in bets}
    winners = [b for b in bets if b['side']==winning]
    if not refund:
        total = sum(b['amount'] for b in winners)
        for b in winners: payouts[b['id']] = pool*b['amount']//total
        remainder = pool-sum(payouts.values())
        order = sorted(winners,key=lambda b:(-(pool*b['amount']%total),b['createdAt'],b['id']))
        for b in order[:remainder]: payouts[b['id']] += 1
    for bet in bets: credit(state,bet,payouts[bet['id']],round_id,now)
    state['rounds'].append({'id':round_id,'marketId':market['id'],'matchId':match_id,
        'receivedAt':received_at, 'settledAt':now,'winner':winning,'value':value,'pool':pool,
        'status':'REFUNDED' if refund else 'SETTLED', 'reason':reason or ('no_opposition' if refund else None),
        'bets':[b['id'] for b in bets]})


def settle(db, state, now):
    teams = {d['id']:d for d in db.get('duos',[]) if d.get('id')}
    changed = False
    for market in state['markets']:
        pending = [b for b in state['bets'] if b['marketId']==market['id'] and b['status']=='PENDING']
        if not pending: continue
        duo = teams.get(market['targetId'])
        replaced = market['metric']!='result' and duo and player_accounts.identity(duo.get(market['playerKey']) or {}) != market['playerIdentity']
        if not duo or replaced:
            settle_pool(state,market,pending,None,None,None,None,now,'target_changed')
            changed = True
            continue
        matches = {m.get('matchId'):m for m in duo.get('history',[])}
        receipts = state['receipts'].get(duo['id'],{})
        for mid,receipt in sorted(receipts.items(),key=lambda item:item[1]['sequence']):
            eligible = [b for b in pending if b['status']=='PENDING' and b['eligibleAt']<=receipt['at']
                        and b['afterSequence']<receipt['sequence']]
            if not eligible: continue
            winning,value = outcome(duo,market,matches.get(mid))
            if winning is None:
                for b in eligible:
                    if b.get('waitingMatchId') != mid:
                        b['waitingMatchId'] = mid; changed = True
                # All pools for this market wait for earlier incomplete evidence.
                break
            if winning=='SKIP':
                for b in eligible:
                    b['afterSequence']=receipt['sequence'];b.pop('waitingMatchId',None)
                changed = True
                continue
            settle_pool(state,market,eligible,mid,receipt['at'],winning,value,now,
                        'target_changed' if winning=='VOID' else None)
            changed = True
    return changed


def maintain(db, now=None):
    now = time.time() if now is None else now
    state,changed = ensure(db,now)
    changed = grant_daily(db,state,now) or changed
    changed = observe(db,state,now) or changed
    return settle(db,state,now) or changed


def participate(db, team_id, body, now=None):
    now = time.time() if now is None else now
    state = db['betting']
    if team_id not in {d['id'] for d in db.get('duos',[]) if d.get('id')}: raise PermissionError('Inicia sesión con tu equipo.')
    request_id = body.get('requestId')
    if not isinstance(request_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}',request_id):
        raise ValueError('Falta el identificador de la apuesta. Recarga la página.')
    op_key = team_id+':'+request_id
    fingerprint = hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    previous = state['operations'].get(op_key)
    if previous:
        if previous['fingerprint'] != fingerprint: raise FileExistsError('Ese envío ya se utilizó con otros datos.')
        return previous['betId']
    amount = body.get('amount')
    if type(amount) is not int or not 1<=amount<=1000000: raise ValueError('Apuesta un número entero de monedas, como mínimo 1.')
    if state['wallets'][team_id]['balance'] < amount: raise FileExistsError('No tienes suficiente oro disponible.')
    if sum(b['teamId']==team_id and b['status']=='PENDING' for b in state['bets'])>=100:
        raise FileExistsError('Ya tienes 100 apuestas pendientes. Espera a que se resuelvan.')
    action = body.get('action')
    if action=='create':
        metric = body.get('metric')
        if metric not in METRICS: raise ValueError('Elige win/lose, kills, muertes o asistencias.')
        duo = next((d for d in db.get('duos',[]) if d.get('id')==body.get('targetId')),None)
        if not duo: raise ValueError('Elige un equipo válido.')
        player_key,identity,name,line = None,None,None,None
        if metric!='result':
            player_key = body.get('playerKey')
            if player_key not in ('player1','player2') or not (duo.get(player_key) or {}).get('name'):
                raise ValueError('Elige un integrante del equipo.')
            identity = player_accounts.identity(duo[player_key])
            name = duo[player_key].get('displayName') or duo[player_key]['name']
            line = threshold(body.get('line'))
        side = 'WIN' if metric=='result' else body.get('side')
        allowed = ('WIN',) if metric=='result' else ('OVER','UNDER')
        if side not in allowed:
            raise ValueError('Elige más o menos que la línea.')
        signature = [duo['id'],metric,player_key,identity,line]
        market = next((m for m in state['markets'] if m['signature']==signature and any(
            b['marketId']==m['id'] and b['status']=='PENDING' for b in state['bets'])),None)
        if not market:
            market = {'id':str(uuid.uuid4()),'signature':signature,'targetId':duo['id'],'teamName':duo['teamName'],
                      'metric':metric,'playerKey':player_key,'playerIdentity':identity,'playerName':name,
                      'lineHalf':line,'createdAt':now,'creatorTeamId':team_id}
            state['markets'].append(market)
    elif action=='join':
        market = next((m for m in state['markets'] if m['id']==body.get('marketId')),None)
        if not market or not any(b['marketId']==market['id'] and b['status']=='PENDING' for b in state['bets']):
            raise FileExistsError('Esta apuesta ya se ha resuelto. Puedes crear una nueva.')
        side = body.get('side')
        if side not in (('WIN','LOSS') if market['metric']=='result' else ('OVER','UNDER')):
            raise ValueError('Elige un lado válido de la apuesta.')
    else: raise ValueError('Acción inválida.')
    receipts = state['receipts'].get(market['targetId'],{})
    bet = {'id':str(uuid.uuid4()),'marketId':market['id'],'teamId':team_id,'side':side,'amount':amount,
           'createdAt':now,'eligibleAt':now+WAIT_SECONDS,'afterSequence':len(receipts),'status':'PENDING'}
    state['wallets'][team_id]['balance'] -= amount
    state['bets'].append(bet)
    state['operations'][op_key] = {'fingerprint':fingerprint,'betId':bet['id']}
    state['ledger'].append({'id':'stake:'+bet['id'],'kind':'STAKE','teamId':team_id,'amount':-amount,'at':now})
    return bet['id']


def public_board(db, team_id=None, offset=0, limit=12, view='open'):
    state = db['betting']
    teams = {d['id']:d for d in db.get('duos',[]) if d.get('id')}
    pending = [b for b in state['bets'] if b['status']=='PENDING']
    cards = []
    for market in reversed(state['markets']):
        bets = [b for b in state['bets'] if b['marketId']==market['id']]
        active = [b for b in bets if b['status']=='PENDING']
        if (view=='open') != bool(active): continue
        card = {k:market[k] for k in ('id','targetId','teamName','metric','playerKey','playerName','lineHalf','createdAt')}
        rounds = [r for r in state['rounds'] if r['marketId']==market['id']]
        card.update(status='OPEN' if active else 'CLOSED', sides={side:sum(b['amount'] for b in active if b['side']==side)
            for side in (('WIN','LOSS') if market['metric']=='result' else ('OVER','UNDER'))},
            participants=len({b['teamId'] for b in active}), lastRound=copy.deepcopy(rounds[-1]) if rounds else None,
            mine=[{k:b[k] for k in ('id','side','amount','createdAt','eligibleAt','status','payout','roundId','waitingMatchId') if k in b}
                  for b in bets if b['teamId']==team_id])
        card['rounds'] = [{key:value for key,value in r.items() if key!='bets'} for r in rounds]
        by_round = {r['id']:r for r in rounds}
        for own in card['mine']:
            if own.get('roundId') in by_round:
                own['matchId'] = by_round[own['roundId']]['matchId']
        if card['lastRound']: card['lastRound'].pop('bets',None)
        cards.append(card)
    wallet = state['wallets'].get(team_id)
    return {'markets':cards[offset:offset+limit], 'total':len(cards),'offset':offset,'limit':limit,
        'wallet':{'teamId':team_id,'teamName':teams[team_id]['teamName'],'balance':wallet['balance'],
                  'reserved':sum(b['amount'] for b in pending if b['teamId']==team_id)} if wallet and team_id in teams else None,
        'teams':[{'id':d['id'],'name':d['teamName'],'players':[{'key':key,'name':(d.get(key) or {}).get('displayName') or d[key]['name']}
                   for key in ('player1','player2') if (d.get(key) or {}).get('name')]} for d in db.get('duos',[]) if d.get('id')],
        'rules':{'dailyGold':DAILY_GOLD,'initialGold':INITIAL_GOLD,'waitSeconds':WAIT_SECONDS,'timezone':'Europe/Madrid'}}
