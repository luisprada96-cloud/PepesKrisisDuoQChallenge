import server, json
server.sync_riot_data()
db = server.load_db()
for d in db["duos"]:
    print(f"  {d['teamName']}: {len(d['history'])} partidas")
