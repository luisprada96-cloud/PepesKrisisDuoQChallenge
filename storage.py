"""Atomic JSON persistence. Callers serialize read/modify/write transactions."""
import json
import os
import tempfile
from pathlib import Path


class StorageError(RuntimeError):
    pass


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError("Expected an object")
        return value
    except (OSError, ValueError) as error:
        raise StorageError("No se pudo leer el almacenamiento; los datos se han conservado.") from error


def _replace_bytes(path, payload):
    path = Path(path)
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    """Replace changed data atomically; identical data must not rotate the backup."""
    try:
        payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        if os.path.exists(path):
            read_json(path)  # Never overwrite a corrupt recovery source.
            previous = Path(path).read_bytes()
            if previous == payload:
                return False
            _replace_bytes(str(path) + ".previous.bak", previous)
        _replace_bytes(path, payload)
        return True
    except (OSError, ValueError, TypeError) as error:
        raise StorageError("No se pudieron guardar los cambios. Reintenta cuando el almacenamiento esté disponible.") from error
