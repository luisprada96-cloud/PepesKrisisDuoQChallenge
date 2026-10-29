"""PostgreSQL persistence for the existing JSON model, with optimistic locking."""
import copy
import os
import time
import uuid
from storage import StorageError

SCHEMA = """
CREATE TABLE IF NOT EXISTS tournament_state (
    id smallint PRIMARY KEY CHECK (id = 1),
    revision bigint NOT NULL DEFAULT 1,
    payload jsonb NOT NULL,
    previous_payload jsonb,
    last_write_id text,
    updated_at timestamptz NOT NULL DEFAULT now()
)
"""


def validate(data):
    if not isinstance(data, dict) or not isinstance(data.get("config"), dict) or not isinstance(data.get("duos"), list):
        raise StorageError("La base de datos no contiene un torneo válido.")


class PostgresStorage:
    def __init__(self, url):
        if not url.startswith(("postgresql://", "postgres://")):
            raise StorageError("Configura DATABASE_URL con la conexión privada de Neon.")
        self.url = url
        self.cached = None
        self.revision = None
        self.checked_at = 0
        self.pending = None

    def connect(self):
        try:
            import psycopg
            return psycopg.connect(self.url, connect_timeout=10, sslmode="require")
        except Exception:
            raise StorageError("No se pudo conectar con Neon. Se conservan los datos y no se usará la copia inicial.") from None

    def fetch(self):
        try:
            # One atomic query: an unchanged revision returns metadata, not the
            # potentially large histories, clips, ledgers and weekly archives.
            known_revision = self.revision if self.cached is not None else None
            with self.connect() as conn:
                row = conn.execute("""
                    SELECT CASE WHEN revision = %s THEN NULL ELSE payload END,
                           revision, last_write_id
                    FROM tournament_state WHERE id = 1
                """, (known_revision,)).fetchone()
            if row is None:
                raise StorageError("Neon está vacío. Importa la copia validada del torneo antes de activar el servicio.")
            payload, revision, write_id = row
            if payload is None:
                if self.cached is None or revision != known_revision:
                    raise StorageError("No se pudo validar la revisión del torneo de Neon.")
                # Preserve fetch()'s complete, detached snapshot for maintenance
                # callers, even though no document crossed the network.
                payload = copy.deepcopy(self.cached)
            else:
                validate(payload)
                self.cached = copy.deepcopy(payload)
            self.revision = revision
            self.checked_at = time.monotonic()
            return payload, revision, write_id
        except StorageError:
            raise
        except Exception:
            raise StorageError("No se pudo leer el torneo de Neon. Comprueba la conexión y la importación inicial.") from None

    def load(self):
        if self.cached is None or time.monotonic() - self.checked_at >= 60:
            self.fetch()
        value = copy.deepcopy(self.cached)
        value["_storageRevision"] = self.revision
        return value

    def reconcile(self):
        if self.pending is not None:
            self.fetch()
            self.pending = None

    def update(self, clean, revision, write_id):
        from psycopg.types.json import Jsonb
        with self.connect() as conn:
            row = conn.execute("""
                UPDATE tournament_state
                SET previous_payload = payload, payload = %s,
                    revision = revision + 1, last_write_id = %s, updated_at = now()
                WHERE id = 1 AND revision = %s RETURNING revision
            """, (Jsonb(clean), write_id, revision)).fetchone()
        return row[0] if row else None

    def save(self, data):
        """Return whether a write was confirmed; identical snapshots do no I/O."""
        validate(data)
        if self.pending is not None:
            raise StorageError("Hay un guardado pendiente de comprobar. Actualiza antes de repetir la operación.")
        expected = data.get("_storageRevision")
        if expected is None or expected != self.revision:
            self.cached = None
            raise StorageError("Los datos han cambiado. Actualiza el panel antes de reintentar.")
        clean = copy.deepcopy(data)
        clean.pop("_storageRevision", None)
        if clean == self.cached:
            return False
        write_id = str(uuid.uuid4())
        self.pending = write_id
        try:
            revision = self.update(clean, expected, write_id)
            if revision is None:
                self.cached = None
                raise StorageError("Otra operación ha actualizado el torneo. Actualiza el panel antes de reintentar.")
            self.cached, self.revision = clean, revision
            self.checked_at = time.monotonic()
            data["_storageRevision"] = revision
            return True
        except Exception:
            self.cached = None
            try:
                row = self.fetch()
            except StorageError:
                raise StorageError("No se pudo confirmar el guardado en Neon. Actualiza antes de repetir la operación.") from None
            if row[2] == write_id:
                data["_storageRevision"] = row[1]
                return True
            raise StorageError("No se guardó esta versión. Actualiza el panel: puede haber cambios de otra operación.") from None
        finally:
            if self.cached is not None:
                self.pending = None

    def import_initial(self, data):
        validate(data)
        clean = copy.deepcopy(data)
        clean.pop("_storageRevision", None)
        clean.pop("_driveRevision", None)
        from psycopg.types.json import Jsonb
        with self.connect() as conn:
            conn.execute(SCHEMA)
            inserted = conn.execute("INSERT INTO tournament_state (id, payload) VALUES (1, %s) ON CONFLICT (id) DO NOTHING RETURNING id", (Jsonb(clean),)).fetchone()
        if not inserted:
            raise StorageError("Neon ya contiene datos. No se ha sobrescrito nada.")
        self.cached = None
        return self.load()


def from_environment():
    mode = os.environ.get("PEPES_STORAGE", "local")
    if mode == "local": return None
    if mode != "neon": raise StorageError("PEPES_STORAGE debe ser local o neon.")
    return PostgresStorage(os.environ.get("DATABASE_URL", ""))
