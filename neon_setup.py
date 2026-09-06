"""Explicit import to an EMPTY Neon database; never overwrite production."""
import argparse
import os
from pathlib import Path
from postgres_storage import PostgresStorage
from storage import read_json, StorageError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default="neon-setup/render-neon.env")
    parser.add_argument("--import-file", help="Validated production snapshot. Omit for a read-only check.")
    args = parser.parse_args()
    values = dict(line.split("=", 1) for line in Path(args.env_file).read_text().splitlines() if "=" in line and not line.startswith("#"))
    store = PostgresStorage(values.get("DATABASE_URL", "").strip())
    try:
        data = store.import_initial(read_json(args.import_file)) if args.import_file else store.load()
        print("Conexión verificada. Equipos:", len(data["duos"]))
        print("La cadena de conexión no se muestra ni se guarda en GitHub.")
    except Exception:
        print("No se pudo completar la operación. Comprueba la conexión y que Neon esté vacío para una primera importación.")
        raise SystemExit(1)


if __name__ == "__main__": main()
