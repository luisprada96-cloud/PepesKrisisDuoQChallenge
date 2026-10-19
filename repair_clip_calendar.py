"""Revoke the premature 18 October clip prize and recover its saved board."""
import argparse
import copy
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from clip_votes import vote_count
from postgres_storage import PostgresStorage

OLD_WEEK = '2026-10-12'
REPAIR_ID = 'opening-clips-through-2026-10-25'


def prepare_repair(before, recovered, now=None):
    after = copy.deepcopy(before)
    repairs = after.setdefault('clipCalendarRepairs', {})
    if REPAIR_ID in repairs:
        return after, {'changed':False, **repairs[REPAIR_ID]}
    timestamp = time.time() if now is None else now
    award = after.get('clipWeeklyRewards', {}).get(OLD_WEEK)
    if not award or award.get('status') != 'AWARDED' or award.get('shells') != 3:
        raise ValueError('No se ha encontrado el premio adelantado de tres pepazos.')
    if recovered.get('week') != OLD_WEEK or not isinstance(recovered.get('posts'), list):
        raise ValueError('La copia no contiene la semana que debe recuperarse.')
    posts = recovered['posts']
    summary = (after.get('weeklySummaries', {}).get(OLD_WEEK) or {}).get('clips') or {}
    counts = {'posts':len(posts), 'votes':sum(vote_count(p) for p in posts)}
    if not counts['posts'] or any(counts[key] != summary.get(key) for key in counts):
        raise ValueError('La copia no coincide con los totales archivados; no se ha cambiado nada.')
    winning = next((p for p in posts if p.get('id') == award.get('clipId')), None)
    if not winning or vote_count(winning) != award.get('votes'):
        raise ValueError('La copia no coincide con el clip premiado y sus votos.')
    team = next((d for d in after['duos'] if d['id'] == award.get('teamId')), None)
    if not team or min(team.get('blueShells',0), team.get('clipShellsEarnedTotal',0)) < 3:
        raise ValueError('No hay tres pepazos disponibles para retirar el premio sin saldo negativo.')
    team['blueShells'] -= 3
    team['clipShellsEarnedTotal'] -= 3
    revoked = {**award, 'status':'REVOKED', 'shells':0, 'revokedShells':3, 'revokedAt':timestamp,
               'reason':'opening_round_ends_2026_10_25', 'originalAward':copy.deepcopy(award)}
    after['clipWeeklyRewards'][OLD_WEEK] = revoked
    saved = copy.deepcopy(recovered)
    saved['weeklyAward'] = copy.deepcopy(revoked)
    saved['archived'] = True
    archives = after.setdefault('clipArchives', {})
    if OLD_WEEK in archives and archives[OLD_WEEK].get('posts') != posts:
        raise ValueError('Ya existe un archivo diferente; no se sobrescribe.')
    archives[OLD_WEEK] = saved
    board = after.get('clips') or {}
    if (board.get('previousWeeklyAward') or {}).get('week') == OLD_WEEK:
        board.pop('previousWeeklyAward', None)
    if board.get('week') == OLD_WEEK:
        board['weeklyAward'] = copy.deepcopy(revoked)
    if summary:
        after['weeklySummaries'][OLD_WEEK]['clips']['winner'] = None
    for event in after.get('events', []):
        if event.get('id') == 'clip-week-' + OLD_WEEK:
            event.update(type='CLIP_WEEKLY_REWARD_REVOKED', status='REVOKED',
                         message='Premio de clips anulado: la primera ronda termina el 25 de octubre.')
    report = {'teamId':team['id'], 'teamName':team['teamName'], 'removedShells':3,
              'recoveredPosts':counts['posts'], 'recoveredVotes':counts['votes'], 'correctedAt':timestamp}
    repairs[REPAIR_ID] = report
    after.setdefault('events', []).insert(0, {'id':REPAIR_ID, 'type':'CLIP_WEEKLY_REWARD_CORRECTION',
        'timestamp':datetime.fromtimestamp(timestamp,timezone.utc).isoformat(), **report,
        'message':f"Se retiran 3 pepazos de {team['teamName']} por el cierre adelantado de clips."})
    return after, {'changed':True, **report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recovery', required=True, help='Private JSON backup with the old clips board')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    settings = dict(line.split('=',1) for line in (root/'neon-setup'/'render-neon.env').read_text(encoding='utf-8-sig').splitlines()
                    if '=' in line and not line.lstrip().startswith('#'))
    backend = PostgresStorage(os.environ.get('DATABASE_URL','').strip() or settings['DATABASE_URL'].strip())
    before = backend.load()
    recovered = json.loads(Path(args.recovery).read_text(encoding='utf-8'))['clips']
    after, report = prepare_repair(before, recovered)
    if args.apply and report['changed']:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = root/'backups'/f'pre-clip-calendar-repair-{stamp}.json'
        backup.parent.mkdir(exist_ok=True)
        backup.write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
        backend.save(after)
        actual = backend.fetch()[0]
        assert actual['clipCalendarRepairs'][REPAIR_ID] == after['clipCalendarRepairs'][REPAIR_ID]
        assert actual['clipArchives'][OLD_WEEK] == after['clipArchives'][OLD_WEEK]
        expected = next(d for d in after['duos'] if d['id']==report['teamId'])
        saved = next(d for d in actual['duos'] if d['id']==report['teamId'])
        assert all(saved[key]==expected[key] for key in ('blueShells','clipShellsEarnedTotal'))
        report['backup'] = str(backup)
    print(json.dumps({**report, 'applied':bool(args.apply and report['changed'])}))


if __name__ == '__main__': main()
