"""Persistent OBS credentials, scoped exclusively to reading incoming alerts."""
import hashlib
import secrets


def digest(value):
    return hashlib.sha256(str(value or '').encode('utf-8')).hexdigest()


def credential(duo):
    return digest(duo.get('passwordHash') or duo.get('password', '1234'))


def team(db, token):
    if not isinstance(token, str) or not token.startswith('obs_'):
        return None
    record = db.get('overlaySessions', {}).get(digest(token))
    if not isinstance(record, dict):
        return None
    duo = next((d for d in db.get('duos', []) if d.get('id') == record.get('teamId')), None)
    if duo and secrets.compare_digest(credential(duo), str(record.get('credential', ''))):
        return duo['id']
    return None


def create(db, duo):
    sessions = db.setdefault('overlaySessions', {})
    # Discard records revoked by a removed team or a changed password.
    valid = {d['id']: credential(d) for d in db.get('duos', [])}
    for key, record in list(sessions.items()):
        if record.get('credential') != valid.get(record.get('teamId')):
            del sessions[key]
    token = 'obs_' + secrets.token_urlsafe(32)
    sessions[digest(token)] = {'teamId': duo['id'], 'credential': credential(duo)}
    return token


def revoke(db, token):
    return db.get('overlaySessions', {}).pop(digest(token), None) is not None
