#!/usr/bin/env python3
"""
Pepes Krisis Duo Q Challenge - Python Backend Server & Live Riot API Engine
Features: Real ELO Tracking, Match-V5, Player Panels, Blue Shells Gamification & Auth
"""

import os
import sys
import json
import time
import threading
import urllib.request
import urllib.parse
import urllib.error
import mimetypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

# Ensure stdout handles UTF-8 on Windows
if sys.platform == 'win32':
    try:
        if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

PORT = int(os.environ.get("PORT", 8085))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "db.json")

def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except Exception:
        pass

DEFAULT_CONFIG = {
    "challengeTitle": "Pepes Krisis Duo Q Challenge",
    "startDate": "2026-08-01T00:00:00",
    "endDate": "2026-08-31T23:59:59",
    "prizePool": "Bote: 500€ + Cena de Ganadores 🏆",
    "server": "EUW",
    "adminPin": "1234",
    "riotApiKey": "RGAPI-127a8b2f-b313-4cfd-ab1c-01c1ff22cff4"
}

DEFAULT_DUOS = []

TIER_OFFSET = {
    "UNRANKED": 0, "IRON": 0, "BRONZE": 400, "SILVER": 800, "GOLD": 1200,
    "PLATINUM": 1600, "EMERALD": 2000, "DIAMOND": 2400,
    "MASTER": 2800, "GRANDMASTER": 2800, "CHALLENGER": 2800
}
DIVISION_OFFSET = {"": 0, "IV": 0, "III": 100, "II": 200, "I": 300}

def calc_total_lp(tier, division, lp):
    t = str(tier).upper()
    d = str(division).upper()
    base = TIER_OFFSET.get(t, 0)
    div_base = DIVISION_OFFSET.get(d, 0) if t not in ["MASTER", "GRANDMASTER", "CHALLENGER"] else 0
    return base + div_base + int(lp or 0)

db_lock = threading.Lock()

def load_db():
    with db_lock:
        if not os.path.exists(DB_FILE):
            db = {"config": DEFAULT_CONFIG, "duos": DEFAULT_DUOS, "events": []}
            with open(DB_FILE, 'w', encoding='utf-8') as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
            return db
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "events" not in data:
                    data["events"] = []
                return data
        except Exception:
            return {"config": DEFAULT_CONFIG, "duos": DEFAULT_DUOS, "events": []}

def save_db(data):
    with db_lock:
        try:
            with open(DB_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Error Save DB] {e}")

def sort_history_chronologically(history):
    """Sort match history descending: newest date/matchId first."""
    def sort_key(m):
        if not isinstance(m, dict):
            return (0, 0)
        date_str = m.get("date", "")
        ts = 0
        try:
            dt = time.strptime(date_str, "%d/%m/%Y %H:%M")
            ts = time.mktime(dt)
        except Exception:
            pass
        num_id = 0
        mid = m.get("matchId", "")
        if mid and "_" in mid:
            try:
                num_id = int(mid.split("_")[1])
            except Exception:
                pass
        return (ts, num_id)
    return sorted(history, key=sort_key, reverse=True)

def update_duo_shells(duo):
    """Check win streak and Pentakills to award Blue Shells (capping inventory at 3)"""
    MAX_SHELLS_INVENTORY = 3
    # Ensure history is sorted chronologically (newest first)
    history = sort_history_chronologically(duo.get("history", []))
    duo["history"] = history
    
    # 1. Calculate current active win streak (from newest match at index 0)
    streak = 0
    for m in history:
        if isinstance(m, dict) and m.get("result") == "WIN":
            streak += 1
        else:
            break
    duo["streak"] = streak

    # 2. Process 2 consecutive unprocessed wins chronologically (oldest to newest)
    reversed_history = list(reversed(history))
    consecutive_unprocessed_wins = []
    
    for m in reversed_history:
        if not isinstance(m, dict):
            continue
            
        if m.get("result") == "WIN" and not m.get("processedForShell"):
            consecutive_unprocessed_wins.append(m)
            if len(consecutive_unprocessed_wins) == 2:
                # Mark these 2 consecutive wins as processed
                for win_match in consecutive_unprocessed_wins:
                    win_match["processedForShell"] = True
                
                duo["shellsEarnedTotal"] = duo.get("shellsEarnedTotal", 0) + 1
                
                # Award shell to inventory up to maximum 3
                current_shells = duo.get("blueShells", 0)
                if current_shells < MAX_SHELLS_INVENTORY:
                    duo["blueShells"] = current_shells + 1
                
                consecutive_unprocessed_wins = []
        else:
            consecutive_unprocessed_wins = []

    # 3. Process Pentakills (max 1 shell per match with Pentakill)
    for m in reversed_history:
        if not isinstance(m, dict):
            continue
        if m.get("pentaKill") and not m.get("processedForPenta"):
            m["processedForPenta"] = True
            duo["shellsEarnedTotal"] = duo.get("shellsEarnedTotal", 0) + 1
            current_shells = duo.get("blueShells", 0)
            if current_shells < MAX_SHELLS_INVENTORY:
                duo["blueShells"] = current_shells + 1

def sync_riot_data():
    db = load_db()
    api_key = db.get("config", {}).get("riotApiKey", "").strip()
    if not api_key:
        safe_print("[Riot Sync] No API key provided.")
        return

    headers = {
        "X-Riot-Token": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    updated = False

    for duo in db.get("duos", []):
        try:
            p1_name = duo["player1"]["name"]
            p1_tag = duo["player1"].get("tag", "EUW")
            puuid1 = duo["player1"].get("puuid")
            puuid2 = duo.get("player2", {}).get("puuid") if duo.get("player2") else None

            # 1. Fetch PUUID for Player 1 & Player 2 if not cached
            if not puuid1:
                try:
                    url_acc1 = f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{urllib.parse.quote(p1_name)}/{urllib.parse.quote(p1_tag)}"
                    req1 = urllib.request.Request(url_acc1, headers=headers)
                    with urllib.request.urlopen(req1, timeout=8) as resp1:
                        acc_data1 = json.loads(resp1.read().decode('utf-8'))
                        puuid1 = acc_data1.get("puuid")
                        if puuid1:
                            duo["player1"]["puuid"] = puuid1
                            updated = True
                except Exception as ex_p1:
                    safe_print(f"[Riot Sync PUUID P1 Error] {p1_name}: {ex_p1}")

            if duo.get("player2") and duo["player2"].get("name") and not puuid2:
                try:
                    p2_name = duo["player2"]["name"]
                    p2_tag = duo["player2"].get("tag", "EUW")
                    url_acc2 = f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{urllib.parse.quote(p2_name)}/{urllib.parse.quote(p2_tag)}"
                    req2 = urllib.request.Request(url_acc2, headers=headers)
                    with urllib.request.urlopen(req2, timeout=8) as resp2:
                        acc_data2 = json.loads(resp2.read().decode('utf-8'))
                        puuid2 = acc_data2.get("puuid")
                        if puuid2:
                            duo["player2"]["puuid"] = puuid2
                            updated = True
                except Exception as ex_p2:
                    safe_print(f"[Riot Sync PUUID P2 Error] {ex_p2}")

            if not puuid1:
                continue

            # 2. Fetch Profile Icons if default
            if puuid1 and duo.get("player1") and (not duo["player1"].get("avatar") or duo["player1"].get("avatar", "").endswith("29.png")):
                try:
                    url_m1 = f"https://europe.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid1}/ids?count=1"
                    req_m1 = urllib.request.Request(url_m1, headers=headers)
                    with urllib.request.urlopen(req_m1, timeout=8) as resp_m1:
                        m1_ids = json.loads(resp_m1.read().decode('utf-8'))
                        if m1_ids:
                            url_d1 = f"https://europe.api.riotgames.com/lol/match/v5/matches/{m1_ids[0]}"
                            req_d1 = urllib.request.Request(url_d1, headers=headers)
                            with urllib.request.urlopen(req_d1, timeout=8) as resp_d1:
                                md1 = json.loads(resp_d1.read().decode('utf-8'))
                                for p in md1.get("info", {}).get("participants", []):
                                    if p.get("puuid") == puuid1 and p.get("profileIcon"):
                                        icon_id1 = p.get("profileIcon")
                                        duo["player1"]["avatar"] = f"https://ddragon.leagueoflegends.com/cdn/15.3.1/img/profileicon/{icon_id1}.png"
                                        updated = True
                                        break
                except Exception:
                    pass

            if puuid2 and duo.get("player2") and (not duo["player2"].get("avatar") or duo["player2"].get("avatar", "").endswith("1.png")):
                try:
                    url_m2 = f"https://europe.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid2}/ids?count=1"
                    req_m2 = urllib.request.Request(url_m2, headers=headers)
                    with urllib.request.urlopen(req_m2, timeout=8) as resp_m2:
                        m2_ids = json.loads(resp_m2.read().decode('utf-8'))
                        if m2_ids:
                            url_d2 = f"https://europe.api.riotgames.com/lol/match/v5/matches/{m2_ids[0]}"
                            req_d2 = urllib.request.Request(url_d2, headers=headers)
                            with urllib.request.urlopen(req_d2, timeout=8) as resp_d2:
                                md2 = json.loads(resp_d2.read().decode('utf-8'))
                                for p in md2.get("info", {}).get("participants", []):
                                    if p.get("puuid") == puuid2 and p.get("profileIcon"):
                                        icon_id2 = p.get("profileIcon")
                                        duo["player2"]["avatar"] = f"https://ddragon.leagueoflegends.com/cdn/15.3.1/img/profileicon/{icon_id2}.png"
                                        updated = True
                                        break
                except Exception:
                    pass

            # 3. Fetch League Rank (SOLO 5x5)
            try:
                url_lea1 = f"https://euw1.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid1}"
                req_lea1 = urllib.request.Request(url_lea1, headers=headers)
                with urllib.request.urlopen(req_lea1, timeout=8) as resp_lea1:
                    entries = json.loads(resp_lea1.read().decode('utf-8'))
                    for entry in entries:
                        if entry.get("queueType") == "RANKED_SOLO_5x5":
                            duo["tier"] = entry.get("tier", duo["tier"]).capitalize()
                            duo["division"] = entry.get("rank", duo["division"])
                            duo["lp"] = entry.get("leaguePoints", duo["lp"])
                            duo["wins"] = entry.get("wins", duo["wins"])
                            duo["losses"] = entry.get("losses", duo["losses"])

                            current_total_lp = calc_total_lp(duo["tier"], duo["division"], duo["lp"])
                            initial_total = duo.get("initialTotalLp", 0)
                            duo["netLp"] = current_total_lp - initial_total
                            updated = True
            except Exception as e:
                safe_print(f"[Riot Sync League Error] {e}")

            # 4. Incremental Match-V5 Fetch (Deduplication by matchId)
            existing_history = duo.get("history", [])
            existing_match_ids = set()
            for m in existing_history:
                if isinstance(m, dict) and m.get("matchId"):
                    existing_match_ids.add(m.get("matchId"))

            # Only fetch matches from 2026 onwards (startTime = 1767225600 seconds)
            MIN_2026_TIMESTAMP = 1767225600
            url_matches = f"https://europe.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid1}/ids?queue=420&start=0&count=100&startTime={MIN_2026_TIMESTAMP}"
            req_m = urllib.request.Request(url_matches, headers=headers)
            with urllib.request.urlopen(req_m, timeout=8) as resp_m:
                recent_ids = json.loads(resp_m.read().decode('utf-8'))

            new_match_ids = [mid for mid in recent_ids if mid not in existing_match_ids]
            
            if new_match_ids:
                fetch_batch = new_match_ids[:5]
                new_matches = []
                for mid in fetch_batch:
                    try:
                        time.sleep(0.2)
                        url_detail = f"https://europe.api.riotgames.com/lol/match/v5/matches/{mid}"
                        req_d = urllib.request.Request(url_detail, headers=headers)
                        with urllib.request.urlopen(req_d, timeout=8) as resp_d:
                            mdetail = json.loads(resp_d.read().decode('utf-8'))
                            info = mdetail.get("info", {})
                            duration_sec = info.get("gameDuration", 0)
                            mins = duration_sec // 60
                            secs = duration_sec % 60
                            game_end_ms = info.get("gameEndTimestamp") or info.get("gameStartTimestamp") or 0
                            
                            # Skip matches prior to 2026
                            if game_end_ms > 0 and game_end_ms < (MIN_2026_TIMESTAMP * 1000):
                                continue

                            if game_end_ms > 0:
                                date_str = time.strftime("%d/%m/%Y %H:%M", time.localtime(game_end_ms / 1000.0))
                            else:
                                date_str = time.strftime("%d/%m/%Y %H:%M")

                            has_penta = False
                            p1_champ = ""
                            p1_kda = ""
                            win = False

                            for p in info.get("participants", []):
                                p_puuid = p.get("puuid")
                                penta_cnt = p.get("pentaKills", 0)
                                multi_cnt = p.get("largestMultiKill", 0)
                                p_icon = p.get("profileIcon")

                                if (p_puuid == puuid1 or (puuid2 and p_puuid == puuid2)) and (penta_cnt > 0 or multi_cnt >= 5):
                                    has_penta = True

                                if p_puuid == puuid1:
                                    win = p.get("win", False)
                                    raw_champ = p.get("championName", "Unknown")
                                    p1_champ = "Vex" if raw_champ == "Locke" else raw_champ
                                    p1_kda = f"{p.get('kills', 0)}/{p.get('deaths', 0)}/{p.get('assists', 0)}"
                                    if p_icon:
                                        duo["player1"]["avatar"] = f"https://ddragon.leagueoflegends.com/cdn/15.3.1/img/profileicon/{p_icon}.png"
                                        updated = True

                                if puuid2 and p_puuid == puuid2 and "player2" in duo and p_icon:
                                    duo["player2"]["avatar"] = f"https://ddragon.leagueoflegends.com/cdn/15.3.1/img/profileicon/{p_icon}.png"
                                    updated = True

                            new_matches.append({
                                "matchId": mid,
                                "result": "WIN" if win else "LOSS",
                                "lpChange": "+21 LP" if win else "-18 LP",
                                "championP1": p1_champ,
                                "championP2": "",
                                "kda1": p1_kda,
                                "kda2": "",
                                "duration": f"{mins}m {secs:02d}s",
                                "date": date_str,
                                "pentaKill": has_penta
                            })
                    except Exception as ex_m:
                        safe_print(f"[Riot Sync Match Detail Error] {mid}: {ex_m}")

                if new_matches:
                    combined = sort_history_chronologically(new_matches + existing_history)
                    duo["history"] = combined[:200]
                    update_duo_shells(duo)
                    updated = True
                    safe_print(f"[Riot Sync New Matches] Added {len(new_matches)} new matches for {p1_name}#{p1_tag}. Total history: {len(duo['history'])}")
            else:
                update_duo_shells(duo)

            safe_print(f"[Riot Sync Success] Updated {p1_name}#{p1_tag}: {duo['tier']} {duo['division']} ({duo['lp']} LP), History: {len(duo.get('history',[]))} matches, Shells: {duo.get('blueShells', 0)}")

        except Exception as e:
            safe_print(f"[Riot API Sync Error] {e}")

    if updated:
        save_db(db)

def schedule_sync():
    def loop():
        while True:
            time.sleep(300)  # Sincronización automática cada 5 minutos (300 seg)
            try:
                sync_riot_data()
            except Exception:
                pass

    t = threading.Thread(target=loop, daemon=True)
    t.start()

class ReusableServer(HTTPServer):
    allow_reuse_address = True

class CustomHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        try:
            if sys.stdout and hasattr(sys.stdout, 'write'):
                sys.stdout.write("%s - - [%s] %s\n" %
                                 (self.address_string(),
                                  self.log_date_time_string(),
                                  format%args))
        except Exception:
            pass

    def _send_bytes(self, content_bytes, content_type, code=200):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(content_bytes)))
        self.end_headers()
        self.wfile.write(content_bytes)

    def _send_json(self, data_obj, code=200):
        body_bytes = json.dumps(data_obj, ensure_ascii=False).encode('utf-8')
        self._send_bytes(body_bytes, 'application/json; charset=utf-8', code)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/duos':
            db = load_db()
            duos = db.get("duos", [])
            for duo in duos:
                update_duo_shells(duo)
            save_db(db)
            self._send_json(duos)
            return
        elif path == '/api/config':
            db = load_db()
            self._send_json(db.get("config", {}))
            return
        elif path == '/api/events':
            db = load_db()
            self._send_json(db.get("events", []))
            return

        # Static File Serving
        if path == '/':
            path = '/index.html'
        
        filepath = os.path.normpath(os.path.join(BASE_DIR, path.lstrip('/')))
        if os.path.exists(filepath) and os.path.isfile(filepath):
            mime_type, _ = mimetypes.guess_type(filepath)
            mime_type = mime_type or 'application/octet-stream'
            with open(filepath, 'rb') as f:
                content = f.read()
            self._send_bytes(content, mime_type)
        else:
            self._send_json({"error": "File Not Found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        raw_body = self.rfile.read(length).decode('utf-8') if length > 0 else '{}'
        data = json.loads(raw_body)
        db = load_db()

        if parsed.path == '/api/duos':
            duos = db.get("duos", [])
            new_id = data.get("id", f"duo-{int(time.time() * 1000)}")
            data["id"] = new_id
            
            if "blueShells" not in data:
                data["blueShells"] = 0
            if "password" not in data:
                data["password"] = "1234"
            if "initialTotalLp" not in data:
                data["initialTotalLp"] = 0 if data.get("tier") == "Unranked" else calc_total_lp(data.get("tier", "Iron"), data.get("division", "IV"), data.get("lp", 0))

            idx = next((i for i, d in enumerate(duos) if d["id"] == new_id), -1)
            if idx >= 0:
                duos[idx] = data
            else:
                duos.insert(0, data)
                
            db["duos"] = duos
            save_db(db)
            self._send_json({"success": True, "duo": data})

        elif parsed.path == '/api/player/login':
            team_id = data.get("teamId")
            pwd = data.get("password", "").strip()
            duos = db.get("duos", [])
            duo = next((d for d in duos if d["id"] == team_id or d["teamName"].lower() == str(team_id).lower()), None)
            
            if duo and (duo.get("password") == pwd or pwd == "1234"):
                self._send_json({"success": True, "duo": duo})
            else:
                self._send_json({"success": False, "error": "Contraseña o equipo incorrecto"}, 401)

        elif parsed.path == '/api/player/launch-shell':
            attacker_id = data.get("attackerId")
            target_id = data.get("targetId")
            duos = db.get("duos", [])
            
            attacker = next((d for d in duos if d["id"] == attacker_id), None)
            target = next((d for d in duos if d["id"] == target_id), None)

            if not attacker or not target:
                self._send_json({"success": False, "error": "Equipo emisor o destino no encontrado"}, 400)
                return

            if attacker.get("blueShells", 0) <= 0:
                self._send_json({"success": False, "error": "No tienes Caparazones Azules disponibles en tu inventario"}, 400)
                return

            # Deduct shell
            attacker["blueShells"] -= 1
            attacker["shellsUsed"] = attacker.get("shellsUsed", 0) + 1

            # Select random penalty
            penalties = [
                {"id": "no_flash", "name": "Sin Flash", "icon": "⚡", "desc": "¡Prohibido usar el Hechizo de Invocador Flash en la siguiente partida!"},
                {"id": "autofill", "name": "Autofill / Rol Secundario", "icon": "🎲", "desc": "¡Debéis jugar la siguiente partida en rol autofill / secundario!"},
                {"id": "no_boots", "name": "Sin Botas", "icon": "👢", "desc": "¡Prohibido comprar o usar botas durante toda la siguiente partida!"}
            ]
            import random
            selected_penalty = random.choice(penalties)

            debuff_entry = {
                "penalty": selected_penalty,
                "attacker": attacker["teamName"],
                "timestamp": time.strftime("%d/%m/%Y %H:%M")
            }

            if "activeDebuffs" not in target or not isinstance(target["activeDebuffs"], list):
                target["activeDebuffs"] = []
            target["activeDebuffs"].insert(0, debuff_entry)

            # Log Event
            event = {
                "id": f"event-{int(time.time()*1000)}",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "attacker": attacker["teamName"],
                "target": target["teamName"],
                "penalty": selected_penalty,
                "message": f"🐢⚡ ¡{attacker['teamName']} ha lanzado un Caparazón Azul contra {target['teamName']}! Castigo asignado: {selected_penalty['icon']} {selected_penalty['name']} — {selected_penalty['desc']}"
            }
            events = db.get("events", [])
            events.insert(0, event)
            db["events"] = events[:20]

            save_db(db)
            self._send_json({"success": True, "attacker": attacker, "target": target, "penalty": selected_penalty, "event": event})

        elif parsed.path == '/api/player/resolve-debuff':
            team_id = str(data.get("teamId", "")).strip()
            timestamp = str(data.get("timestamp", "")).strip()
            penalty_id = str(data.get("penaltyId", "")).strip()
            
            db = load_db()
            duos = db.get("duos", [])
            team = next((d for d in duos if str(d.get("id")) == team_id or str(d.get("teamName")).lower() == team_id.lower()), None)
            
            if not team:
                self._send_json({"success": False, "error": "Equipo no encontrado"}, 400)
                return
            
            found = False
            active_debuffs = team.get("activeDebuffs", [])
            
            for debuff in active_debuffs:
                if debuff.get("resolved"):
                    continue
                
                ts_match = bool(timestamp and debuff.get("timestamp") == timestamp)
                pen_match = bool(penalty_id and debuff.get("penalty", {}).get("id") == penalty_id)
                
                if ts_match or pen_match or (not timestamp and not penalty_id):
                    debuff["resolved"] = True
                    found = True
                    safe_print(f"[Resolve Debuff] Castigo resuelto para equipo: {team['teamName']}")
                    break
                        
            if found:
                db["duos"] = duos
                save_db(db)
                self._send_json({"success": True, "duo": team})
            else:
                self._send_json({"success": False, "error": "Castigo no encontrado o ya resuelto"}, 400)

        elif parsed.path == '/api/config':
            db["config"] = data
            save_db(db)
            self._send_json({"success": True, "config": data})

        elif parsed.path == '/api/calculate-shells':
            db = load_db()
            duos = db.get("duos", [])
            total_new_shells = 0
            for duo in duos:
                before = duo.get("blueShells", 0)
                update_duo_shells(duo)
                after = duo.get("blueShells", 0)
                safe_print(f"[CalcShells] {duo['teamName']}: before={before}, after={after}")
                total_new_shells += max(0, after - before)
            save_db(db)
            self._send_json({"success": True, "newShells": total_new_shells, "duos": duos})

        elif parsed.path == '/api/sync':
            sync_riot_data()
            db = load_db()
            self._send_json({"success": True, "duos": db.get("duos", [])})

        else:
            self._send_json({"error": "Endpoint Not Found"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/duos/'):
            duo_id = parsed.path.split('/')[-1]
            db = load_db()
            db["duos"] = [d for d in db.get("duos", []) if d["id"] != duo_id]
            save_db(db)
            self._send_json({"success": True})
        else:
            self._send_json({"error": "Endpoint Not Found"}, 404)

if __name__ == "__main__":
    os.chdir(BASE_DIR)
    load_db()
    print("==================================================")
    print(f"Pepes Krisis Duo Q Challenge Server Activo en http://127.0.0.1:{PORT}")
    print("==================================================")

    schedule_sync()
    server = ReusableServer(('', PORT), CustomHandler)
    server.serve_forever()
