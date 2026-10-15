"""Reset only Pick'em after deploying its calendar update; preserve all team/game data."""
import argparse
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import urllib.request

import pickem_service
from postgres_storage import PostgresStorage
from storage import read_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=('local', 'neon'), required=True)
    parser.add_argument('--apply', action='store_true', help='Apply after writing a private backup; default is read-only.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    backend = None
    if args.target == 'neon':
        if args.apply:
            for path, marker in (('/api/pickem', 'teamBallots'), ('/admin.js', 'adminPickemCsv')):
                with urllib.request.urlopen('https://duoqchallenge.luisjourney.xyz' + path, timeout=30) as response:
                    if marker not in response.read().decode('utf-8'):
                        raise SystemExit('La nueva versión aún no está desplegada; no se ha reiniciado nada.')
        url = os.environ.get('DATABASE_URL', '').strip()
        if not url:
            settings = dict(line.split('=', 1) for line in (root / 'neon-setup' / 'render-neon.env').read_text(encoding='utf-8-sig').splitlines()
                            if '=' in line and not line.startswith('#'))
            url = settings.get('DATABASE_URL', '').strip()
        backend = PostgresStorage(url)
        before = backend.load()
    else:
        before = read_json(root / 'db.json')
    state = before.get('pickem') or {}
    if before.get('config', {}).get('pickemSchedule') == pickem_service.NEW_SCHEDULE:
        raise SystemExit('El nuevo calendario ya está activado. No se borran las nuevas quinielas.')
    summary = {'target': args.target, 'weeks': len(state.get('weeks', {})),
               'ballots': sum(len(board.get('ballots', [])) for board in state.get('weeks', {}).values()),
               'awardedShells': sum(reward.get('shells', 0) for board in state.get('weeks', {}).values()
                                   for reward in board.get('ballotRewards', {}).values())}
    if not args.apply:
        print(json.dumps({**summary, 'changed': False}))
        return
    if summary['awardedShells']:
        raise SystemExit('Hay premios anteriores entregados. Revisa su inventario antes de reiniciar; no se ha cambiado nada.')
    after = copy.deepcopy(before)
    pickem_service.reset_calendar(after)
    pickem_service.ensure_week(after)
    backup = root / 'backups' / ('pre-pickem-calendar-' + args.target + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json')
    backup.parent.mkdir(exist_ok=True)
    backup.write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding='utf-8')
    if backend:
        backend.save(after)
        verified = backend.fetch()[0]
    else:
        write_json(root / 'db.json', after)
        verified = read_json(root / 'db.json')
    assert verified['config']['pickemSchedule'] == pickem_service.NEW_SCHEDULE
    assert not any(board.get('ballots') for board in verified['pickem']['weeks'].values())
    assert verified['duos'] == after['duos']
    print(json.dumps({**summary, 'changed': True, 'backup': str(backup), 'weeksNow': list(verified['pickem']['weeks'])}))


if __name__ == '__main__':
    main()
