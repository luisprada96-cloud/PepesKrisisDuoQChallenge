"""Inspect a named clip, or remove exactly one with a private recovery backup."""
import argparse
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from postgres_storage import PostgresStorage
from storage import read_json, write_json
import clips_service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=('local', 'neon'), required=True)
    parser.add_argument('--title', required=True)
    parser.add_argument('--clip-id')
    parser.add_argument('--week')
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
    matches = []
    for board in [before.get('clips') or {}, *before.get('clipArchives', {}).values()]:
        for post in board.get('posts', []):
            if (str(post.get('title', '')).strip().casefold() == args.title.strip().casefold()
                    and (not args.clip_id or post['id'] == args.clip_id)
                    and (not args.week or board['week'] == args.week)):
                matches.append((board, post))
    report = [{'week': b['week'], 'id': p['id'], 'title': p['title'], 'team': p.get('team'),
               'createdAtMadrid': datetime.fromtimestamp(p['createdAt'], clips_service.MADRID).isoformat(),
               'votes': clips_service.vote_count(p), 'comments': len(p.get('comments', []))} for b, p in matches]
    if not args.apply:
        print(json.dumps({'applied': False, 'matches': report}, ensure_ascii=False))
        return
    if len(matches) != 1 or not args.clip_id or not args.week:
        raise ValueError('Para borrar se requiere un único clip y su ID y semana exactos.')
    after = copy.deepcopy(before)
    clips_service.remove_clip(after, args.week, args.clip_id, admin=True)
    assert {k: v for k, v in after.items() if k not in ('clips', 'clipArchives', 'deletedClips')} == {
        k: v for k, v in before.items() if k not in ('clips', 'clipArchives', 'deletedClips')}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = root/'backups'/f'pre-clip-delete-{args.target}-{stamp}.json'
    write_json(backup, before)
    if backend:
        backend.save(after)  # Atomic revision check; never overwrite concurrent edits.
        verified = backend.fetch()[0]
    else:
        write_json(root/'db.json', after)
        verified = read_json(root/'db.json')
    assert args.clip_id in verified.get('deletedClips', {})
    assert not any(p['id'] == args.clip_id for b in [verified.get('clips') or {}, *verified.get('clipArchives', {}).values()] for p in b.get('posts', []))
    print(json.dumps({'applied': True, 'removed': report[0], 'backup': str(backup)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
