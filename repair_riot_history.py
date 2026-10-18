"""Remove only a named team's pre-15-October games; default is a dry run."""
import argparse
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from postgres_storage import PostgresStorage
from storage import read_json, write_json
import riot_match_policy as policy


def prepare_repair(before, team_id):
    import server
    after = copy.deepcopy(before)
    candidates = [d for d in after.get('duos', []) if d.get('id') == team_id]
    if len(candidates) != 1:
        raise ValueError('El identificador debe corresponder a un único equipo existente.')
    duo = candidates[0]
    removed = policy.prune_history(duo)
    mids = {m.get('matchId') for m in removed if m.get('matchId')}
    if any(m.get('shellRewardIds') or any(m.get('shellRewardCredits', {}).values()) for m in removed):
        raise ValueError('Hay premios registrados en partidas antiguas. No se cambia el inventario automáticamente.')
    if any(d.get('resolvedByMatchId') in mids and d.get('status') == 'COMPLETED' for d in duo.get('activeDebuffs', [])):
        raise ValueError('Una partida antigua resolvió un castigo. Requiere revisión; no se ha guardado nada.')
    if removed:
        server.update_duo_current_streak(duo)
        duo['streak'] = duo['currentStreakCount'] if duo['currentStreakType'] == 'WIN' else 0
        server.calculate_player_insights(duo)
        server.calculate_duo_best_match(duo)
        server.update_stats_backfill_status(duo)
        server.update_match_details_backfill(duo)
        for match in reversed(duo['history']):
            server.record_flash_baselines(duo, match)
    return after, {'teamId': team_id, 'teamName': duo.get('teamName'), 'cutoff': policy.MIN_START_ISO,
                   'removedCount': len(removed), 'keptCount': len(duo.get('history', [])),
                   'removedMatchIds': sorted(mids)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=('local', 'neon'), required=True)
    parser.add_argument('--team-id', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    backend = None
    if args.target == 'neon':
        url = os.environ.get('DATABASE_URL', '').strip()
        if not url:
            settings = dict(line.split('=', 1) for line in (root/'neon-setup'/'render-neon.env').read_text(encoding='utf-8-sig').splitlines()
                            if '=' in line and not line.lstrip().startswith('#'))
            url = settings.get('DATABASE_URL', '').strip()
        backend = PostgresStorage(url)
        before = backend.load()
    else:
        before = read_json(root/'db.json')
    after, report = prepare_repair(before, args.team_id)
    if not args.apply or not report['removedCount']:
        print(json.dumps({**report, 'changed': False}, ensure_ascii=False))
        return
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = root/'backups'/f'pre-riot-date-cleanup-{args.target}-{stamp}.json'
    backup.parent.mkdir(exist_ok=True)
    backup.write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding='utf-8')
    if backend:
        backend.save(after)  # revision checked atomically; concurrent writes cannot be overwritten.
        verified = backend.fetch()[0]
    else:
        write_json(root/'db.json', after)
        verified = read_json(root/'db.json')
    actual = next(d for d in verified['duos'] if d['id'] == args.team_id)
    expected = next(d for d in after['duos'] if d['id'] == args.team_id)
    assert actual['history'] == expected['history'], 'El historial guardado no coincide con la reparación.'
    assert set(report['removedMatchIds']) <= set(actual.get('excludedRiotMatches', {}))
    assert not any(not m.get('isTest') and policy.before_cutoff(m) for m in actual['history'])
    print(json.dumps({**report, 'changed': True, 'backup': str(backup)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
