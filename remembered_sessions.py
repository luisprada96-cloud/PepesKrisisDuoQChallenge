"""Revocable, persistent team sessions. Only token digests are stored."""
import hashlib
import re
import secrets
import time

COOKIE = 'pepes_team_session'
LIFETIME = 30 * 24 * 60 * 60
MAX_DEVICES = 20


def digest(value):
    return hashlib.sha256(str(value or '').encode('utf-8')).hexdigest()


def credential(duo):
    return digest(duo.get('passwordHash') or duo.get('password', '1234'))


def valid_record(db, record, now=None):
    if not isinstance(record, dict):
        return False
    expires = record.get('expiresAt')
    if not isinstance(expires, (int, float)) or expires <= (time.time() if now is None else now):
        return False
    duo = next((d for d in db.get('duos', []) if d.get('id') == record.get('teamId')), None)
    return bool(duo and secrets.compare_digest(credential(duo), str(record.get('credential', ''))))


def team(db, token, now=None):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        return None
    record = db.get('rememberedTeamSessions', {}).get(digest(token))
    return record['teamId'] if valid_record(db, record, now) else None


def create(db, duo, now=None):
    now = time.time() if now is None else now
    sessions = db.setdefault('rememberedTeamSessions', {})
    for key, record in list(sessions.items()):
        if not valid_record(db, record, now):
            del sessions[key]
    devices = sorted(((key, value) for key, value in sessions.items() if value['teamId'] == duo['id']),
                     key=lambda item: item[1].get('createdAt', 0))
    for key, _ in devices[:max(0, len(devices) - MAX_DEVICES + 1)]:
        del sessions[key]
    token = secrets.token_urlsafe(32)
    sessions[digest(token)] = {'teamId': duo['id'], 'credential': credential(duo),
                             'createdAt': now, 'expiresAt': now + LIFETIME}
    return token


def revoke(db, token):
    return db.get('rememberedTeamSessions', {}).pop(digest(token), None) is not None
