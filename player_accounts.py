"""A participant owns accounts; rank selection never changes their identity."""
import copy
import hashlib
import time

ACCOUNT_FIELDS = ('puuid', 'puuidAliases', 'rank', 'eloHistory', 'flashBaseline', 'matchDiscovery', 'avatar')


def identity(account):
    return [str(account.get('name') or '').strip().casefold(), str(account.get('tag') or 'EUW').strip().casefold()]


def account_id(account):
    return account.get('id') or hashlib.sha256(repr(identity(account)).encode()).hexdigest()[:20]


def accounts(player):
    return player.get('accounts') or ([player] if player.get('name') else [])


def elo_account(player):
    choices = accounts(player)
    return next((a for a in choices if account_id(a) == player.get('eloAccountId')), choices[0] if choices else player)


def elo_account_at(player, timestamp):
    choices = accounts(player)
    history = [entry for entry in player.get('eloSelections', []) if entry['selectedAt'] < timestamp]
    if not history:
        return elo_account(player)
    selected_id = max(history, key=lambda entry: entry['selectedAt'])['accountId']
    return next((a for a in choices if account_id(a) == selected_id), elo_account(player))


def elo_identity(player):
    if player.get('accounts'):
        return identity(elo_account(player))
    return [str(player.get('name', '')).lower(), str(player.get('tag', '')).lower()]


def known_puuids(account):
    return {p for p in [account.get('puuid'), *account.get('puuidAliases', [])] if p}


def account_for_stats(player, stats):
    uid = stats.get('puuid')
    if uid:
        return next((a for a in accounts(player) if uid in known_puuids(a)), None)
    if stats.get('riotIdGameName'):
        candidate = {'name': stats['riotIdGameName'], 'tag': stats.get('riotIdTagline')}
        return next((a for a in accounts(player) if identity(a) == identity(candidate)), None)
    return None


def owns_stats(player, stats):
    if not player.get('name') or not stats.get('puuid') or (not player.get('accounts') and not player.get('puuid')):
        return True  # Legacy evidence without an account ID retains its old interpretation.
    return account_for_stats(player, stats) is not None


def configuration(player):
    return [(account_id(a), *identity(a)) for a in accounts(player)], player.get('eloAccountId')


def remember_puuid(account, puuid):
    if not puuid:
        raise ValueError('Riot no devolvió la identidad de la cuenta.')
    previous = account.get('puuid')
    if previous and previous != puuid:
        account['puuidAliases'] = sorted(known_puuids(account))
    account['puuid'] = puuid


def project_elo(player):
    selected = elo_account(player)
    if selected is player:
        return
    player['rank'] = copy.deepcopy(selected.get('rank'))
    player['eloHistory'] = copy.deepcopy(selected.get('eloHistory', []))
    player['eloHistoryAccount'] = identity(selected)


def update_accounts(player, submitted):
    """Accept identities/selection only; clients cannot submit Riot evidence."""
    previous = copy.deepcopy(accounts(player))
    for item in previous:
        item['id'] = account_id(item)
    # Legacy profile is the original account, not whichever account supplies ELO.
    if not player.get('accounts') and previous:
        previous[0] = {k: copy.deepcopy(v) for k,v in previous[0].items()
                       if k in ('id','name','tag', *ACCOUNT_FIELDS)}
        previous[0].setdefault('tag', 'EUW')
    old_by_id = {account_id(a): a for a in previous}
    raw = submitted.get('accounts', previous)
    if not isinstance(raw, list) or not 1 <= len(raw) <= 10:
        raise ValueError('Cada integrante debe tener entre 1 y 10 cuentas.')
    clean, aliases, seen = [], {}, set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError('Cuenta de LoL no válida.')
        name, tag = str(entry.get('name') or '').strip(), str(entry.get('tag') or 'EUW').strip()
        if not name or len(name) > 60 or not tag or len(tag) > 10 or any(ord(c)<32 for c in name+tag) or '#' in name+tag:
            raise ValueError('Indica el nombre y tag de cada cuenta por separado, sin #.')
        candidate = {'name': name, 'tag': tag}
        marker = tuple(identity(candidate))
        if marker in seen:
            raise ValueError('Una cuenta no puede aparecer dos veces.')
        seen.add(marker)
        old = old_by_id.get(entry.get('id'))
        if old and identity(old) != identity(candidate):
            raise ValueError('Las cuentas guardadas no se sustituyen: añade otra cuenta.')
        old = old or next((a for a in previous if identity(a) == identity(candidate)), None)
        candidate = copy.deepcopy(old) if old else {**candidate, 'registeredAt': time.time()}
        candidate['id'] = account_id(candidate)
        aliases[entry.get('id')] = candidate['id']
        clean.append(candidate)
    if set(old_by_id) - {a['id'] for a in clean}:
        raise ValueError('Conserva las cuentas guardadas para no perder su historial.')
    selection = submitted.get('eloAccountId', player.get('eloAccountId') or clean[0]['id'])
    selection = aliases.get(selection, selection)
    if selection not in {a['id'] for a in clean}:
        raise ValueError('Selecciona una de las cuentas del integrante para el ELO.')
    previous_selection = player.get('eloAccountId') or (previous[0]['id'] if previous else clean[0]['id'])
    selections = player.setdefault('eloSelections', [{'accountId': previous_selection, 'selectedAt': 0}])
    if selection != previous_selection:
        player['eloAccountSelectedAt'] = time.time()
        selections.append({'accountId': selection, 'selectedAt': player['eloAccountSelectedAt']})
    player['accounts'], player['eloAccountId'] = clean, selection
    project_elo(player)


def validate_ownership(duos):
    seen, puuids = set(), set()
    for duo in duos:
        for key in ('player1','player2'):
            for account in accounts(duo.get(key) or {}):
                marker = tuple(identity(account))
                ids = known_puuids(account)
                if marker in seen or ids & puuids:
                    raise ValueError('Esta cuenta ya pertenece a otro integrante del torneo.')
                seen.add(marker)
                puuids.update(ids)
