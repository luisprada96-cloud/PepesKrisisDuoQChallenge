"""Immutable overlay media and an equally weighted, persistent per-attack draw."""
import copy
import hashlib
import math
import os
from pathlib import Path
import re
import secrets
import tempfile

from storage import StorageError

MAX_BYTES = 12 * 1024 * 1024
MAX_LIBRARY_BYTES = 100 * 1024 * 1024
MAX_EFFECTS = 30
# Immutable uploaded Bulo asset: names are rendered by OBS, never burned into it.
BULO_VIDEO_ID = 'f11b638d2d42fbf4914d8cd041b6cad8181fe3d33cc8bfced3e9649b3d76dad4'
BUILTIN = {'id': 'pepo-nuclear-v1', 'name': 'Misil Pepo · alarma nuclear',
           'kind': 'builtin', 'durationMs': 10000, 'active': True}


def library(db):
    items = copy.deepcopy(db.get('overlayEffects', [BUILTIN]))
    for item in items:
        if item.get('id') == BULO_VIDEO_ID:
            item['senderRevealMs'] = 6500
    return items


def removed(db):
    return copy.deepcopy(db.get('removedOverlayEffects', []))


def remove(db, effect_id):
    items = library(db)
    target = next((item for item in items if item['id'] == effect_id), None)
    if not target or target.get('kind') != 'video':
        raise ValueError('Solo se pueden retirar vídeos de la biblioteca.')
    remaining = [item for item in items if item['id'] != effect_id]
    if not any(item.get('active') for item in remaining):
        raise ValueError('Debe quedar al menos una animación activa.')
    # Keep immutable bytes and attack snapshots intact; this action is reversible.
    db['removedOverlayEffects'] = removed(db) + [{**target, 'active': False}]
    db['overlayEffects'] = remaining


def restore(db, effect_id):
    items = removed(db)
    target = next((item for item in items if item['id'] == effect_id), None)
    if not target:
        raise ValueError('La animación retirada no existe.')
    add(db, {**target, 'active': False})
    db['removedOverlayEffects'] = [item for item in items if item['id'] != effect_id]


def snapshot(effect):
    return {k: copy.deepcopy(v) for k, v in effect.items() if k != 'active'}


def choose(db):
    active = [effect for effect in library(db) if effect.get('active')]
    return snapshot(secrets.choice(active or [BUILTIN]))


def validate_upload(name, duration, blob):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError('El nombre debe tener entre 1 y 80 caracteres.')
    try:
        duration = float(duration)
    except (ValueError, TypeError):
        raise ValueError('La duración del vídeo no es válida.') from None
    if not math.isfinite(duration) or not 500 <= duration <= 30000:
        raise ValueError('El vídeo debe durar entre 0,5 y 30 segundos.')
    if not 32 <= len(blob) <= MAX_BYTES:
        raise ValueError('El vídeo debe ocupar como máximo 12 MiB.')
    if not blob.startswith(b'\x1aE\xdf\xa3') or b'webm' not in blob[:4096]:
        raise ValueError('Selecciona un vídeo WebM válido, con el audio incorporado.')
    digest = hashlib.sha256(blob).hexdigest()
    return {'id': digest, 'name': name.strip(), 'kind': 'video', 'active': True,
            'url': '/api/overlay/media/' + digest, 'durationMs': round(duration),
            'bytes': len(blob)}


def add(db, effect):
    effects = library(db)
    if any(item['id'] == effect['id'] for item in effects):
        raise ValueError('Ese vídeo ya está en la biblioteca.')
    if len(effects) >= MAX_EFFECTS or sum(e.get('bytes', 0) for e in effects) + effect['bytes'] > MAX_LIBRARY_BYTES:
        raise ValueError('La biblioteca admite 30 efectos y 100 MiB en total.')
    effects.append(copy.deepcopy(effect))
    db['overlayEffects'] = effects


def set_active(db, effect_id, active):
    if not isinstance(active, bool):
        raise ValueError('Estado de animación inválido.')
    effects = library(db)
    target = next((effect for effect in effects if effect['id'] == effect_id), None)
    if target is None:
        raise ValueError('La animación ya no existe.')
    target['active'] = active
    if not any(effect['active'] for effect in effects):
        raise ValueError('Debe quedar al menos una animación activa.')
    db['overlayEffects'] = effects


def media_bytes(digest, db_file, backend, blob=None):
    """Videos live outside the tournament JSON: files locally, BYTEA in Neon."""
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise ValueError('Identificador de vídeo inválido.')
    try:
        if backend is not None:
            with backend.connect() as conn:
                with conn.cursor() as cursor:
                    if blob is not None:
                        cursor.execute('CREATE TABLE IF NOT EXISTS overlay_media (sha256 text PRIMARY KEY, payload bytea NOT NULL)')
                        cursor.execute('INSERT INTO overlay_media (sha256, payload) VALUES (%s, %s) ON CONFLICT (sha256) DO NOTHING', (digest, blob))
                        return
                    cursor.execute('SELECT payload FROM overlay_media WHERE sha256 = %s', (digest,))
                    row = cursor.fetchone()
                    return bytes(row[0]) if row else None
        folder = Path(db_file).parent / 'overlay-media'
        target = folder / (digest + '.webm')
        if blob is None:
            return target.read_bytes() if target.is_file() else None
        folder.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=folder, delete=False) as handle:
                temporary = handle.name
                handle.write(blob); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
    except Exception as error:
        raise StorageError('No se pudo guardar o leer el vídeo del overlay. Se conservan los datos del torneo.') from error
