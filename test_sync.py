"""Manual live diagnostic. Not executed when unittest discovers this module."""
import argparse


def main():
    parser = argparse.ArgumentParser(description="Sincronizar Riot usando los datos reales.")
    parser.add_argument("--live", action="store_true", help="Autoriza llamadas reales y escritura en db.json")
    args = parser.parse_args()
    if not args.live:
        parser.error("Esta comprobación escribe datos reales. Usa --live para ejecutarla.")
    import server
    result = server.sync_riot_data()
    print(result)


if __name__ == "__main__":
    main()
