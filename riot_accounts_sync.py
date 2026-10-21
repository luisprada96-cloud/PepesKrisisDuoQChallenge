"""Incremental import for teams whose participants own multiple Riot accounts."""
import copy
import json
import time
import urllib.parse

import player_accounts as pa
import riot_match_policy
from elo_history import record_player_elo


def sync_team(duo, fetch, failure, api):
    resolved = {}
    for key in ('player1','player2'):
        player = duo.get(key) or {}
        resolved[key] = []
        for account in pa.accounts(player):
            try:
                name, tag = urllib.parse.quote(account['name'], safe=''), urllib.parse.quote(account.get('tag') or 'EUW', safe='')
                result = fetch(f'https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}')
                pa.remember_puuid(account, result.get('puuid'))
                resolved[key].append(account)
            except Exception as error:
                failure(error)
            if account.get('puuid'):
                try:
                    rank = api.solo_rank_snapshot(fetch(f"https://euw1.api.riotgames.com/lol/league/v4/entries/by-puuid/{account['puuid']}"))
                    account['rank'] = rank
                    account.setdefault('initialTotalLp', (account.get('eloHistory') or [{}])[0].get('totalLp', api.calc_total_lp(rank['tier'], rank['division'], rank['lp'])))
                    record_player_elo(account, api.calc_total_lp(rank['tier'], rank['division'], rank['lp']), rank['observedAt'])
                except Exception as error:
                    failure(error)
        pa.project_elo(player)
    # Distinct registered accounts must not resolve to the same Riot participant.
    pa.validate_ownership([duo])
    riot_match_policy.prune_duo_history(duo)
    selected = pa.elo_account(duo.get('player1') or {})
    rank = selected.get('rank') or {}
    if rank:
        duo.update({f: rank.get(f, 0 if f in ('lp','wins','losses') else '') for f in ('tier','division','lp','wins','losses')})
        duo['rankObservedAt'] = rank.get('observedAt', 0)
        duo['initialTotalLp'] = selected.get('initialTotalLp', duo.get('initialTotalLp', 0))
        duo['netLp'] = api.calc_total_lp(rank.get('tier'), rank.get('division'), rank.get('lp')) - duo.get('initialTotalLp',0)
    existing = {m['matchId']: m for m in duo.get('history',[]) if m.get('matchId')}
    excluded = duo.setdefault('excludedRiotMatches', {})
    sources = [a for rows in resolved.values() for a in rows]
    all_pending = []
    for account in sources:
        try:
            temporary = {'player1': account, 'history': list(existing.values()), 'excludedRiotMatches': excluded,
                         'riotMatchDiscovery': account.get('matchDiscovery', {})}
            account['matchDiscovery'] = api.discover_riot_matches(temporary, account['puuid'], fetch, riot_match_policy.MIN_START_TIMESTAMP)
        except Exception as error:
            failure(error)
    all_accounts = [a for key in ('player1','player2') for a in pa.accounts(duo.get(key) or {})]
    for account in all_accounts:
        all_pending.extend((account.get('matchDiscovery') or {}).get('pendingMatchIds', []))
    signature = [pa.configuration(duo.get(key) or {})[0] for key in ('player1','player2')]
    # JSON persistence turns tuples into lists; compare the serialized signature.
    signature = json.loads(json.dumps(signature))
    legacy = [mid for mid,m in existing.items() if not m.get('isTest') and
              (m.get('accountSources') != signature or api.needs_match_details(m) or int(m.get('statsVersion',0)) < 2
               or riot_match_policy.needs_pair_validation(duo, m))]
    # Existing rows may be missing evidence for a newly registered account.
    # Keep them visibly pending until each detail has been checked against every source.
    for mid in legacy:
        if existing[mid].get('accountSources') != signature or riot_match_policy.needs_pair_validation(duo, existing[mid]):
            existing[mid]['matchDetailsVersion'] = 0
    fetch_ids = list(dict.fromkeys(all_pending + legacy + riot_match_policy.pair_rechecks(duo)))[:api.RIOT_MATCH_DETAIL_BATCH_PER_DUO]
    for mid in fetch_ids:
        try:
            time.sleep(0.2)
            info = fetch(f'https://europe.api.riotgames.com/lol/match/v5/matches/{mid}').get('info',{})
            if riot_match_policy.match_timestamp_ms(info) is None:
                raise ValueError('La partida no tiene fecha confirmada; se reintentará.')
            if riot_match_policy.before_cutoff(info):
                excluded[mid] = riot_match_policy.exclusion(info)
                existing.pop(mid, None)
                continue
            duration = int(info.get('gameDuration',0) or 0)
            if info.get('queueId') is None:
                raise ValueError('La partida no confirma el tipo de cola; se reintentará.')
            if info['queueId'] != 420 or 0 < duration < api.MIN_RIOT_MATCH_DURATION_SECONDS:
                excluded[mid] = {'reason':'duration_below_minimum' if duration < api.MIN_RIOT_MATCH_DURATION_SECONDS else 'wrong_queue', 'durationSeconds':duration}
                existing.pop(mid,None)
                continue
            participants = info.get('participants', [])
            found = riot_match_policy.find_pair(duo, participants)
            resolved_all = {key: len(resolved[key]) == len(pa.accounts(duo.get(key) or {})) for key in ('player1', 'player2')}
            reason = riot_match_policy.validate_pair(duo, found, resolved_all)
            if reason:
                riot_match_policy.exclude_pair(duo, mid, reason, existing.pop(mid, None))
                continue
            match = copy.deepcopy(existing.get(mid) or (excluded.get(mid) or {}).get('match') or {'matchId':mid,'lpChange':''})
            end = int(info.get('gameEndTimestamp') or info.get('gameStartTimestamp') or 0)
            match.update(gameStartTimestamp=int(info.get('gameStartTimestamp') or 0), gameEndTimestamp=end,
                         date=time.strftime('%d/%m/%Y %H:%M',time.localtime(end/1000)) if end else '', accountSources=signature)
            api.enrich_match_record(match, info, (found['player1'] or {}).get('puuid'), (found['player2'] or {}).get('puuid'))
            for key in ('player1','player2'):
                stats = match.get(key+'Stats')
                if stats:
                    account = pa.account_for_stats(duo[key],stats)
                    stats['sourceAccountId'] = pa.account_id(account)
                    if found[key].get('profileIcon'):
                        account['avatar'] = f"https://ddragon.leagueoflegends.com/cdn/15.3.1/img/profileicon/{found[key]['profileIcon']}.png"
                    if not found['player1']:
                        match['result'] = 'WIN' if stats['win'] else 'LOSS'
                match.setdefault('participantsChecked',{})[key] = len(resolved[key]) == len(pa.accounts(duo.get(key) or {}))
            match['matchDetailsVersion'] = 1 if all(match['participantsChecked'].values()) else 0
            api.record_flash_baselines(duo,match)
            excluded.pop(mid, None)
            existing[mid] = match
        except Exception as error:
            failure(error)
    known = set(existing) | set(excluded)
    for account in all_accounts:
        if account.get('matchDiscovery'):
            account['matchDiscovery']['pendingMatchIds'] = [m for m in account['matchDiscovery']['pendingMatchIds'] if m not in known]
    pending = list(dict.fromkeys([m for a in all_accounts for m in (a.get('matchDiscovery') or {}).get('pendingMatchIds',[])]
                                + riot_match_policy.pair_rechecks(duo)))
    duo['riotMatchDiscovery'] = {'version':2,'pendingMatchIds':pending}
    duo['history'] = api.sort_history_chronologically(list(existing.values()) + [m for m in duo.get('history',[]) if not m.get('matchId')])
    for key in ('player1','player2'):
        player = duo.get(key) or {}
        # Keep the legacy identity's PUUID usable by existing predictions.
        original = next((a for a in pa.accounts(player) if pa.identity(a)==pa.identity(player)),None)
        if original and original is not player and original.get('puuid'):
            player['puuid'] = original['puuid']
        selected = pa.elo_account(player)
        if selected.get('avatar'):
            player['avatar'] = selected['avatar']
    api.update_stats_backfill_status(duo,include_timestamp=True)
    api.update_match_details_backfill(duo)
    return len(pending)
