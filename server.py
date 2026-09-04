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
import secrets
import uuid
import hashlib
import hmac
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
SECRETS_FILE = os.path.join(BASE_DIR, "secrets.json")
TWITCH_SYNC_INTERVAL = 300
RIOT_MATCH_DETAIL_BATCH_PER_DUO = 40
VALID_MAIN_ROLES = {"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"}
MAX_SHELLS_INVENTORY = 3
SECRET_HASH_ITERATIONS = 260000
SECRET_HASH_PREFIX = "pbkdf2_sha256"

PENALTY_CATALOG = [
    {"id": "autofill_one", "baseId": "autofill", "scope": "ONE", "name": "Polivalente · UNO", "icon": "🎲", "desc": "Al menos uno debe jugar fuera de su rol principal.", "defaultWeight": 12},
    {"id": "autofill_both", "baseId": "autofill", "scope": "BOTH", "name": "Polivalente · AMBOS", "icon": "🎲", "desc": "Los dos deben jugar fuera de sus roles principales.", "defaultWeight": 5},
    {"id": "no_main_champion_one", "baseId": "no_main_champion", "scope": "ONE", "name": "Sin campeón favorito · UNO", "icon": "🚫", "desc": "Al menos uno debe evitar su campeón más jugado.", "defaultWeight": 16},
    {"id": "no_main_champion_both", "baseId": "no_main_champion", "scope": "BOTH", "name": "Sin campeón favorito · AMBOS", "icon": "🚫", "desc": "Los dos deben evitar sus campeones más jugados.", "defaultWeight": 7},
    {"id": "random_champion_one", "baseId": "random_champion", "scope": "ONE", "name": "Campeón aleatorio · UNO", "icon": "🎯", "desc": "Un integrante debe jugar el campeón que indique la ruleta.", "defaultWeight": 12},
    {"id": "random_champion_both", "baseId": "random_champion", "scope": "BOTH", "name": "Campeón aleatorio · AMBOS", "icon": "🎯", "desc": "Cada integrante debe jugar su campeón aleatorio asignado.", "defaultWeight": 5},
    {"id": "no_flash_one", "baseId": "no_flash", "scope": "ONE", "name": "Sin Flash · UNO", "icon": "⚡", "desc": "Al menos uno debe jugar sin Flash.", "defaultWeight": 14},
    {"id": "no_flash_both", "baseId": "no_flash", "scope": "BOTH", "name": "Sin Flash · AMBOS", "icon": "⚡", "desc": "Los dos deben jugar sin Flash.", "defaultWeight": 6},
    {"id": "basic_boots_15_one", "baseId": "basic_boots_15", "scope": "ONE", "name": "Botas básicas hasta 15 · UNO", "icon": "👢", "desc": "Al menos uno no puede mejorar sus botas antes del minuto 15.", "defaultWeight": 12},
    {"id": "basic_boots_15_both", "baseId": "basic_boots_15", "scope": "BOTH", "name": "Botas básicas hasta 15 · AMBOS", "icon": "👢", "desc": "Los dos deben mantener botas básicas o ninguna hasta el minuto 15.", "defaultWeight": 6},
    {"id": "return_shell", "baseId": "return_shell", "scope": "SPECIAL", "name": "Devuelve el caparazón", "icon": "↩️", "desc": "El caparazón vuelve inmediatamente al equipo atacante.", "defaultWeight": 5}
]

player_sessions = {}
ddragon_champion_cache = []

def hash_secret(value):
    value = str(value or "")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), bytes.fromhex(salt), SECRET_HASH_ITERATIONS)
    return f"{SECRET_HASH_PREFIX}${SECRET_HASH_ITERATIONS}${salt}${digest.hex()}"

def is_secret_hash(value):
    return str(value or "").startswith(f"{SECRET_HASH_PREFIX}$")

def normalize_secret_hash(value):
    value = str(value or "")
    malformed_prefix = f"$" + SECRET_HASH_PREFIX + "$$"
    if value.startswith(malformed_prefix):
        return value[1:].replace("$$", "$")
    return value

def verify_secret(candidate, stored):
    candidate = str(candidate or "")
    stored = str(stored or "")
    if not is_secret_hash(stored):
        return hmac.compare_digest(candidate, stored)
    try:
        _, iterations, salt, expected = stored.split("$", 3)
        digest = hashlib.pbkdf2_hmac("sha256", candidate.encode("utf-8"), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (TypeError, ValueError):
        return False

def migrate_credentials(db):
    changed = False
    config = db.setdefault("config", {})
    local_secrets = load_secrets()

    riot_key = str(config.pop("riotApiKey", "") or "").strip()
    if riot_key:
        local_secrets["riotApiKey"] = riot_key
        changed = True

    legacy_pin = str(config.pop("adminPin", "") or "")
    if legacy_pin:
        config["adminPinHash"] = legacy_pin if is_secret_hash(legacy_pin) else hash_secret(legacy_pin)
        changed = True
    elif config.get("adminPinHash"):
        normalized_pin = normalize_secret_hash(config["adminPinHash"])
        if normalized_pin != config["adminPinHash"]:
            config["adminPinHash"] = normalized_pin
            changed = True
    elif not config.get("adminPinHash"):
        config["adminPinHash"] = hash_secret("1234")
        changed = True

    for duo in db.get("duos", []):
        legacy_password = str(duo.pop("password", "") or "")
        if legacy_password:
            duo["passwordHash"] = legacy_password if is_secret_hash(legacy_password) else hash_secret(legacy_password)
            changed = True
        elif duo.get("passwordHash"):
            normalized_password = normalize_secret_hash(duo["passwordHash"])
            if normalized_password != duo["passwordHash"]:
                duo["passwordHash"] = normalized_password
                changed = True
        elif not duo.get("passwordHash"):
            duo["passwordHash"] = hash_secret("1234")
            changed = True

    if riot_key:
        save_secrets(local_secrets)
    return changed

def verify_admin_pin(db, candidate):
    stored = db.get("config", {}).get("adminPinHash") or db.get("config", {}).get("adminPin", "1234")
    return verify_secret(candidate, stored)

def default_penalty_weights():
    return {item["id"]: item["defaultWeight"] for item in PENALTY_CATALOG}

def ensure_shell_schema(db):
    config = db.setdefault("config", {})
    configured = config.get("penaltyWeights")
    defaults = default_penalty_weights()
    if not isinstance(configured, dict):
        config["penaltyWeights"] = defaults
    else:
        config["penaltyWeights"] = {
            item["id"]: int(configured.get(item["id"], defaults[item["id"]]) or 0)
            for item in PENALTY_CATALOG
        }
    db.setdefault("shellAttacks", [])
    db.setdefault("events", [])
    return db

def safe_duo_for_player(duo):
    result = dict(duo)
    result.pop("password", None)
    result.pop("passwordHash", None)
    return result

def safe_duos(duos):
    return [safe_duo_for_player(duo) for duo in duos]

def session_team(token):
    session = player_sessions.get(str(token or ""))
    if not session or session.get("expiresAt", 0) < time.time():
        return None
    return session.get("teamId")

def create_player_session(team_id):
    token = secrets.token_urlsafe(32)
    player_sessions[token] = {"teamId": team_id, "expiresAt": time.time() + 86400}
    return token

def player_state(db, duo):
    state = safe_duo_for_player(duo)
    attacks = db.get("shellAttacks", [])
    state["pendingShellAttacks"] = [a for a in attacks if a.get("targetTeamId") == duo.get("id") and a.get("status") == "PENDING_SPIN"]
    state["outgoingShellAttacks"] = [a for a in attacks if a.get("attackerTeamId") == duo.get("id")][:20]
    return state

def weighted_penalty(snapshot):
    available = [(item, max(0, int(snapshot.get(item["id"], 0) or 0))) for item in PENALTY_CATALOG]
    total = sum(weight for _, weight in available)
    if total <= 0:
        raise ValueError("La ruleta no tiene porcentajes activos")
    pick = secrets.randbelow(total) + 1
    cumulative = 0
    for item, weight in available:
        cumulative += weight
        if pick <= cumulative:
            return dict(item)
    return dict(available[-1][0])

def favorite_snapshot(duo):
    result = {}
    for player_key in ("player1", "player2"):
        stats_key = f"{player_key}Stats"
        counts = {}
        for match in duo.get("history", []):
            if not isinstance(match, dict) or match.get("isTest"):
                continue
            name = (match.get(stats_key) or {}).get("championName")
            if name and name != "Unknown":
                counts[name] = counts.get(name, 0) + 1
        maximum = max(counts.values(), default=0)
        result[player_key] = sorted(name for name, count in counts.items() if count == maximum) if maximum else []
    return result

def champion_pool(duos):
    global ddragon_champion_cache
    if ddragon_champion_cache:
        return list(ddragon_champion_cache)
    try:
        with urllib.request.urlopen("https://ddragon.leagueoflegends.com/api/versions.json", timeout=5) as response:
            version = json.loads(response.read().decode("utf-8"))[0]
        url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/es_ES/champion.json"
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        ddragon_champion_cache = sorted(payload.get("data", {}).keys())
        if ddragon_champion_cache:
            return list(ddragon_champion_cache)
    except Exception as error:
        safe_print(f"[Data Dragon] No se pudo cargar el catálogo completo: {error}")
    champions = set()
    for duo in duos:
        for match in duo.get("history", []):
            for stats_key in ("player1Stats", "player2Stats"):
                name = (match.get(stats_key) or {}).get("championName")
                if name and name != "Unknown":
                    champions.add(name)
    fallback = {"Ahri", "Ashe", "Caitlyn", "Darius", "Ezreal", "Garen", "Jinx", "LeeSin", "Lux", "Morgana", "Nami", "Orianna", "Thresh", "Vi", "Yasuo"}
    return sorted(champions | fallback)

def penalty_requirements(duo, penalty, duos):
    requirements = {
        "mainRoles": {
            "player1": duo.get("player1", {}).get("mainRole"),
            "player2": duo.get("player2", {}).get("mainRole")
        },
        "favoriteChampions": favorite_snapshot(duo)
    }
    if penalty["baseId"] == "random_champion":
        pool = champion_pool(duos)
        if penalty["scope"] == "ONE":
            player_key = secrets.choice(["player1", "player2"])
            requirements["randomChampions"] = {player_key: secrets.choice(pool)}
            requirements["assignedPlayer"] = player_key
        else:
            requirements["randomChampions"] = {"player1": secrets.choice(pool), "player2": secrets.choice(pool)}
    return requirements

def migrate_legacy_penalties(db):
    changed = False
    legacy_map = {"no_flash": "no_flash_one", "autofill": "autofill_both", "no_boots": "basic_boots_15_both"}
    catalog_by_id = {item["id"]: item for item in PENALTY_CATALOG}
    for duo in db.get("duos", []):
        for debuff in duo.get("activeDebuffs", []):
            if not debuff.get("id"):
                debuff["id"] = f"penalty-{uuid.uuid4().hex}"
                changed = True
            old_penalty = debuff.get("penalty", {})
            mapped = catalog_by_id.get(legacy_map.get(old_penalty.get("id")))
            if mapped and not old_penalty.get("baseId"):
                debuff["penalty"] = dict(mapped)
                debuff["scope"] = mapped["scope"]
                changed = True
            expected_status = "COMPLETED" if debuff.get("resolved") else "ACTIVE"
            if not debuff.get("status"):
                debuff["status"] = expected_status
                changed = True
            debuff.setdefault("requirements", penalty_requirements(duo, debuff.get("penalty", {}), db.get("duos", [])))
    return changed

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
    "twitchClientId": ""
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
secrets_lock = threading.Lock()
twitch_token_lock = threading.Lock()
twitch_token_cache = {"client_id": "", "access_token": "", "expires_at": 0}

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
                data = ensure_shell_schema(data)
                if migrate_credentials(data):
                    with open(DB_FILE, 'w', encoding='utf-8') as migrated_file:
                        json.dump(data, migrated_file, ensure_ascii=False, indent=2)
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

def load_secrets():
    with secrets_lock:
        if not os.path.exists(SECRETS_FILE):
            return {}
        try:
            with open(SECRETS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

def save_secrets(data):
    with secrets_lock:
        with open(SECRETS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

def public_config(config):
    hidden_keys = {"adminPin", "adminPinHash", "riotApiKey", "twitchClientSecret"}
    return {key: value for key, value in config.items() if key not in hidden_keys}

def admin_config_response(db):
    config = public_config(db.get("config", {}))
    local_secrets = load_secrets()
    config["adminPinConfigured"] = bool(db.get("config", {}).get("adminPinHash"))
    config["riotApiKeyConfigured"] = bool(os.environ.get("RIOT_API_KEY", "").strip() or local_secrets.get("riotApiKey", "").strip())
    _, twitch_client_secret = get_twitch_credentials(db)
    config["twitchClientSecretConfigured"] = bool(twitch_client_secret)
    return config

def twitch_channel_from_url(value):
    try:
        parsed = urllib.parse.urlparse(str(value or '').strip())
        hostname = (parsed.hostname or '').lower()
        if hostname.startswith('www.'):
            hostname = hostname[4:]
        parts = [part for part in parsed.path.split('/') if part]
        if parsed.scheme != 'https' or hostname != 'twitch.tv' or len(parts) != 1:
            return ''
        channel = parts[0]
        if not 4 <= len(channel) <= 25 or not all(ch.isalnum() or ch == '_' for ch in channel):
            return ''
        return channel.lower()
    except Exception:
        return ''

def get_twitch_credentials(db):
    config = db.get("config", {})
    secrets = load_secrets()
    client_id = os.environ.get("TWITCH_CLIENT_ID", config.get("twitchClientId", "")).strip()
    client_secret = os.environ.get("TWITCH_CLIENT_SECRET", secrets.get("twitchClientSecret", "")).strip()
    return client_id, client_secret

def get_riot_api_key():
    return os.environ.get("RIOT_API_KEY", "").strip() or str(load_secrets().get("riotApiKey", "")).strip()

def clear_twitch_token_cache():
    global twitch_token_cache
    with twitch_token_lock:
        twitch_token_cache = {"client_id": "", "access_token": "", "expires_at": 0}

def get_twitch_app_token(client_id, client_secret):
    global twitch_token_cache
    with twitch_token_lock:
        now = time.time()
        if (twitch_token_cache.get("client_id") == client_id and
                twitch_token_cache.get("access_token") and
                twitch_token_cache.get("expires_at", 0) > now + 60):
            return twitch_token_cache["access_token"]

        body = urllib.parse.urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials"
        }).encode('utf-8')
        request = urllib.request.Request(
            "https://id.twitch.tv/oauth2/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST"
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            token_data = json.loads(response.read().decode('utf-8'))

        access_token = token_data.get("access_token", "")
        if not access_token:
            raise RuntimeError("Twitch no devolvió un access token")

        twitch_token_cache = {
            "client_id": client_id,
            "access_token": access_token,
            "expires_at": now + int(token_data.get("expires_in", 3600))
        }
        return access_token

def sync_twitch_live_status():
    db = load_db()
    duos = db.get("duos", [])
    channel_to_duos = {}

    for duo in duos:
        channel = twitch_channel_from_url(duo.get("twitchUrl"))
        if channel:
            channel_to_duos.setdefault(channel, []).append(duo)

    if not channel_to_duos:
        return {"success": True, "checked": 0, "live": 0}

    client_id, client_secret = get_twitch_credentials(db)
    if not client_id or not client_secret:
        safe_print("[Twitch Sync] Client ID o Client Secret no configurados.")
        return {"success": False, "error": "Credenciales de Twitch no configuradas"}

    try:
        access_token = get_twitch_app_token(client_id, client_secret)
        query = urllib.parse.urlencode(
            [("user_login", channel) for channel in channel_to_duos.keys()]
        )
        request = urllib.request.Request(
            f"https://api.twitch.tv/helix/streams?{query}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Client-Id": client_id
            }
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            stream_data = json.loads(response.read().decode('utf-8'))

        live_channels = {
            str(stream.get("user_login", "")).lower()
            for stream in stream_data.get("data", [])
            if stream.get("type") == "live"
        }

        changed = False
        for channel, channel_duos in channel_to_duos.items():
            is_live = channel in live_channels
            for duo in channel_duos:
                if duo.get("twitchIsLive") is not is_live:
                    duo["twitchIsLive"] = is_live
                    changed = True

        if changed:
            save_db(db)

        safe_print(f"[Twitch Sync] {len(channel_to_duos)} canal(es) comprobados; {len(live_channels)} en directo.")
        return {
            "success": True,
            "checked": len(channel_to_duos),
            "live": len(live_channels),
            "duos": safe_duos(duos)
        }
    except urllib.error.HTTPError as error:
        if error.code == 401:
            clear_twitch_token_cache()
        safe_print(f"[Twitch Sync Error] HTTP {error.code}")
        return {"success": False, "error": f"Twitch respondió HTTP {error.code}"}
    except Exception as error:
        safe_print(f"[Twitch Sync Error] {error}")
        return {"success": False, "error": "No se pudo consultar Twitch"}

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

def update_duo_current_streak(duo):
    """Calculate the current consecutive result streak without affecting shell rewards."""
    history = sort_history_chronologically(duo.get("history", []))
    duo["history"] = history

    if not history:
        duo["currentStreakType"] = None
        duo["currentStreakCount"] = 0
        return

    latest_result = history[0].get("result")
    if latest_result not in ("WIN", "LOSS"):
        duo["currentStreakType"] = None
        duo["currentStreakCount"] = 0
        return

    count = 0
    for match in history:
        if isinstance(match, dict) and match.get("result") == latest_result:
            count += 1
        else:
            break

    duo["currentStreakType"] = latest_result
    duo["currentStreakCount"] = count

def normalize_champion_name(value):
    champion = str(value or "Unknown")
    return "Vex" if champion == "Locke" else champion

def normalize_position(participant):
    position = str(participant.get("teamPosition") or participant.get("individualPosition") or "UNKNOWN").upper()
    return position if position in {"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"} else "UNKNOWN"

def participant_stats(participant):
    if not participant:
        return None
    return {
        "championName": normalize_champion_name(participant.get("championName")),
        "kills": int(participant.get("kills", 0) or 0),
        "deaths": int(participant.get("deaths", 0) or 0),
        "assists": int(participant.get("assists", 0) or 0),
        "win": bool(participant.get("win", False)),
        "position": normalize_position(participant),
        "summonerSpellIds": [int(participant.get("summoner1Id", 0) or 0), int(participant.get("summoner2Id", 0) or 0)],
        "participantId": int(participant.get("participantId", 0) or 0)
    }

def enrich_match_record(match, info, puuid1, puuid2):
    """Add the two participants' durable stats to a new or legacy match record."""
    participants = info.get("participants", [])
    p1 = next((p for p in participants if p.get("puuid") == puuid1), None)
    p2 = next((p for p in participants if puuid2 and p.get("puuid") == puuid2), None)
    p1_stats = participant_stats(p1)
    p2_stats = participant_stats(p2)

    match["player1Stats"] = p1_stats
    match["player2Stats"] = p2_stats
    match["statsVersion"] = 2

    if p1_stats:
        match["result"] = "WIN" if p1_stats["win"] else "LOSS"
        match["championP1"] = p1_stats["championName"]
        match["kda1"] = f'{p1_stats["kills"]}/{p1_stats["deaths"]}/{p1_stats["assists"]}'
    if p2_stats:
        match["championP2"] = p2_stats["championName"]
        match["kda2"] = f'{p2_stats["kills"]}/{p2_stats["deaths"]}/{p2_stats["assists"]}'

    duo_participants = [p for p in (p1, p2) if p]
    match["pentaKill"] = any(
        int(p.get("pentaKills", 0) or 0) > 0 or int(p.get("largestMultiKill", 0) or 0) >= 5
        for p in duo_participants
    )
    return p1, p2

UPGRADED_BOOT_IDS = {3006, 3009, 3020, 3047, 3111, 3117, 3158, 3172, 3173, 3174, 3175, 3176, 3177, 3178, 3179}

def boots_compliance_from_timeline(timeline_info, match):
    purchased_before_15 = {"player1": False, "player2": False}
    participant_keys = {
        (match.get("player1Stats") or {}).get("participantId"): "player1",
        (match.get("player2Stats") or {}).get("participantId"): "player2"
    }
    for frame in timeline_info.get("frames", []):
        for event in frame.get("events", []):
            if event.get("type") != "ITEM_PURCHASED" or int(event.get("timestamp", 0) or 0) >= 900000:
                continue
            key = participant_keys.get(event.get("participantId"))
            if key and int(event.get("itemId", 0) or 0) in UPGRADED_BOOT_IDS:
                purchased_before_15[key] = True
    return {key: not upgraded for key, upgraded in purchased_before_15.items()}

def evaluate_active_penalties(duo, match, timeline_info=None):
    if not match.get("player1Stats") or not match.get("player2Stats"):
        return 0
    game_end_ms = int(match.get("gameEndTimestamp", 0) or 0)
    completed = 0
    for debuff in duo.get("activeDebuffs", []):
        if debuff.get("status") != "ACTIVE" or debuff.get("resolved"):
            continue
        assigned_ms = int(debuff.get("assignedAtEpochMs", 0) or 0)
        if assigned_ms and game_end_ms and game_end_ms <= assigned_ms:
            continue
        penalty = debuff.get("penalty", {})
        base_id = penalty.get("baseId") or penalty.get("id")
        scope = debuff.get("scope") or penalty.get("scope") or "ONE"
        req = debuff.get("requirements", {})
        results = {}
        for player_key in ("player1", "player2"):
            stats = match.get(f"{player_key}Stats") or {}
            if base_id == "autofill":
                actual, primary = stats.get("position"), req.get("mainRoles", {}).get(player_key)
                results[player_key] = actual in VALID_MAIN_ROLES and primary in VALID_MAIN_ROLES and actual != primary
            elif base_id == "no_main_champion":
                forbidden = req.get("favoriteChampions", {}).get(player_key, [])
                results[player_key] = bool(forbidden) and stats.get("championName") not in forbidden
            elif base_id == "random_champion":
                assigned = req.get("randomChampions", {}).get(player_key)
                results[player_key] = bool(assigned) and stats.get("championName") == assigned
            elif base_id == "no_flash":
                results[player_key] = 4 not in stats.get("summonerSpellIds", [])
            elif base_id == "basic_boots_15" and timeline_info is not None:
                results = boots_compliance_from_timeline(timeline_info, match)
                break
        relevant = list(results.values())
        if base_id == "random_champion" and scope == "ONE":
            assigned_player = req.get("assignedPlayer")
            passed = bool(assigned_player and results.get(assigned_player))
        else:
            passed = all(relevant) if scope == "BOTH" else any(relevant)
        if passed:
            debuff["status"] = "COMPLETED"
            debuff["resolved"] = True
            debuff["resolvedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            debuff["resolvedByMatchId"] = match.get("matchId")
            debuff["evidence"] = {"players": results, "matchId": match.get("matchId")}
            completed += 1
    return completed

def calculate_player_insights(duo):
    """Recalculate champion and position summaries from enriched, non-test matches."""
    insights = {}
    for player_key, stats_key in (("player1", "player1Stats"), ("player2", "player2Stats")):
        champion_totals = {}
        position_totals = {}
        games_analyzed = 0
        totals = {"kills": 0, "deaths": 0, "assists": 0}

        for match in duo.get("history", []):
            if not isinstance(match, dict) or match.get("isTest"):
                continue
            stats = match.get(stats_key)
            # Legacy records already contain real P1 champion/KDA data. Use it as
            # a provisional source while the full two-player backfill is pending.
            if not isinstance(stats, dict) and player_key == "player1" and match.get("championP1"):
                try:
                    kills, deaths, assists = [int(value) for value in str(match.get("kda1", "0/0/0")).split("/")]
                    stats = {
                        "championName": match.get("championP1"),
                        "kills": kills,
                        "deaths": deaths,
                        "assists": assists,
                        "win": match.get("result") == "WIN",
                        "position": "UNKNOWN"
                    }
                except (TypeError, ValueError):
                    stats = None
            if not isinstance(stats, dict):
                continue

            games_analyzed += 1
            totals["kills"] += int(stats.get("kills", 0) or 0)
            totals["deaths"] += int(stats.get("deaths", 0) or 0)
            totals["assists"] += int(stats.get("assists", 0) or 0)
            champion = normalize_champion_name(stats.get("championName"))
            champion_stats = champion_totals.setdefault(champion, {
                "name": champion, "games": 0, "wins": 0, "kills": 0, "deaths": 0, "assists": 0
            })
            champion_stats["games"] += 1
            champion_stats["wins"] += 1 if stats.get("win") else 0
            champion_stats["kills"] += int(stats.get("kills", 0) or 0)
            champion_stats["deaths"] += int(stats.get("deaths", 0) or 0)
            champion_stats["assists"] += int(stats.get("assists", 0) or 0)

            position = str(stats.get("position") or "UNKNOWN").upper()
            if position != "UNKNOWN":
                position_totals[position] = position_totals.get(position, 0) + 1

        top_champion = None
        if champion_totals:
            top_champion = sorted(champion_totals.values(), key=lambda item: (-item["games"], item["name"]))[0]
            top_champion["winrate"] = round((top_champion["wins"] / top_champion["games"]) * 100)
            top_champion["kda"] = round(
                (top_champion["kills"] + top_champion["assists"]) / max(1, top_champion["deaths"]), 2
            )

        most_played_position = None
        if position_totals:
            position, games = sorted(position_totals.items(), key=lambda item: (-item[1], item[0]))[0]
            most_played_position = {"position": position, "games": games}

        insights[player_key] = {
            "gamesAnalyzed": games_analyzed,
            "totals": totals,
            "topChampion": top_champion,
            "mostPlayedPosition": most_played_position
        }

    duo["playerInsights"] = insights
    return insights

def calculate_duo_best_match(duo):
    """Select the duo's best real match by combined KDA."""
    candidates = []
    for match in duo.get("history", []):
        if not isinstance(match, dict) or match.get("isTest"):
            continue
        p1 = match.get("player1Stats")
        p2 = match.get("player2Stats")
        if not isinstance(p1, dict) or not isinstance(p2, dict):
            continue

        kills = int(p1.get("kills", 0) or 0) + int(p2.get("kills", 0) or 0)
        deaths = int(p1.get("deaths", 0) or 0) + int(p2.get("deaths", 0) or 0)
        assists = int(p1.get("assists", 0) or 0) + int(p2.get("assists", 0) or 0)
        combined_kda = round((kills + assists) / max(1, deaths), 2)
        candidates.append({
            "matchId": match.get("matchId"),
            "date": match.get("date", ""),
            "result": match.get("result", ""),
            "duration": match.get("duration", ""),
            "combinedKda": combined_kda,
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "player1": {
                "championName": p1.get("championName", "Unknown"),
                "position": p1.get("position", "UNKNOWN"),
                "kda": f'{int(p1.get("kills", 0) or 0)}/{int(p1.get("deaths", 0) or 0)}/{int(p1.get("assists", 0) or 0)}'
            },
            "player2": {
                "championName": p2.get("championName", "Unknown"),
                "position": p2.get("position", "UNKNOWN"),
                "kda": f'{int(p2.get("kills", 0) or 0)}/{int(p2.get("deaths", 0) or 0)}/{int(p2.get("assists", 0) or 0)}'
            }
        })

    duo["bestCombinedKdaMatch"] = max(
        candidates,
        key=lambda item: (item["combinedKda"], item["kills"] + item["assists"], -item["deaths"], item["date"])
    ) if candidates else None
    return duo["bestCombinedKdaMatch"]

def update_stats_backfill_status(duo, include_timestamp=False):
    remaining = sum(
        1 for match in duo.get("history", [])
        if isinstance(match, dict)
        and not match.get("isTest")
        and match.get("matchId")
        and int(match.get("statsVersion", 0) or 0) < 2
    )
    previous = duo.get("statsBackfill", {})
    status = {
        "remaining": remaining,
        "complete": remaining == 0
    }
    if include_timestamp:
        status["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    elif previous.get("updatedAt"):
        status["updatedAt"] = previous["updatedAt"]
    duo["statsBackfill"] = status
    return status

def update_duo_shells(duo):
    """Check win streak and Pentakills to award Blue Shells (capping inventory at 3)."""
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

    # 2. Process 3 consecutive unprocessed wins chronologically (oldest to newest)
    reversed_history = list(reversed(history))
    consecutive_unprocessed_wins = []
    
    for m in reversed_history:
        if not isinstance(m, dict):
            continue
            
        if m.get("result") == "WIN" and not m.get("processedForShell"):
            consecutive_unprocessed_wins.append(m)
            if len(consecutive_unprocessed_wins) == 3:
                # Mark these 3 consecutive wins as processed
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
    api_key = get_riot_api_key()
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

            # 1. Refresh PUUIDs on every sync. Riot can rotate encrypted PUUIDs,
            # so a permanently cached value may start returning "Exception decrypting".
            if p1_name and p1_tag:
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

            if duo.get("player2") and duo["player2"].get("name"):
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

            # 4. Incremental Match-V5 fetch + progressive legacy backfill.
            existing_history = duo.get("history", [])
            existing_by_id = {
                match.get("matchId"): match
                for match in existing_history
                if isinstance(match, dict) and match.get("matchId")
            }
            existing_match_ids = set(existing_by_id)

            # Only fetch matches from 2026 onwards (startTime = 1767225600 seconds)
            MIN_2026_TIMESTAMP = 1767225600
            url_matches = f"https://europe.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid1}/ids?queue=420&start=0&count=100&startTime={MIN_2026_TIMESTAMP}"
            req_m = urllib.request.Request(url_matches, headers=headers)
            with urllib.request.urlopen(req_m, timeout=8) as resp_m:
                recent_ids = json.loads(resp_m.read().decode('utf-8'))

            new_match_ids = [mid for mid in recent_ids if mid not in existing_match_ids]
            legacy_ids = [
                match.get("matchId")
                for match in existing_history
                if isinstance(match, dict)
                and not match.get("isTest")
                and match.get("matchId")
                and int(match.get("statsVersion", 0) or 0) < 2
            ]
            fetch_ids = list(dict.fromkeys(new_match_ids + legacy_ids))[:RIOT_MATCH_DETAIL_BATCH_PER_DUO]
            new_matches = []
            enriched_count = 0

            for mid in fetch_ids:
                try:
                    time.sleep(0.2)
                    url_detail = f"https://europe.api.riotgames.com/lol/match/v5/matches/{mid}"
                    req_d = urllib.request.Request(url_detail, headers=headers)
                    with urllib.request.urlopen(req_d, timeout=8) as resp_d:
                        mdetail = json.loads(resp_d.read().decode('utf-8'))
                    info = mdetail.get("info", {})
                    duration_sec = int(info.get("gameDuration", 0) or 0)
                    mins, secs = divmod(duration_sec, 60)
                    game_end_ms = info.get("gameEndTimestamp") or info.get("gameStartTimestamp") or 0

                    if game_end_ms > 0 and game_end_ms < (MIN_2026_TIMESTAMP * 1000):
                        continue

                    if mid in existing_by_id:
                        match = existing_by_id[mid]
                    else:
                        date_str = (
                            time.strftime("%d/%m/%Y %H:%M", time.localtime(game_end_ms / 1000.0))
                            if game_end_ms > 0 else time.strftime("%d/%m/%Y %H:%M")
                        )
                        match = {
                            "matchId": mid,
                            "lpChange": "",
                            "championP1": "",
                            "championP2": "",
                            "kda1": "",
                            "kda2": "",
                            "duration": f"{mins}m {secs:02d}s",
                            "date": date_str,
                            "pentaKill": False
                        }

                    match["gameStartTimestamp"] = int(info.get("gameStartTimestamp", 0) or 0)
                    match["gameEndTimestamp"] = int(game_end_ms or 0)
                    p1_detail, p2_detail = enrich_match_record(match, info, puuid1, puuid2)
                    timeline_info = None
                    needs_timeline = any(
                        d.get("status") == "ACTIVE" and (d.get("penalty", {}).get("baseId") or d.get("penalty", {}).get("id")) == "basic_boots_15"
                        for d in duo.get("activeDebuffs", [])
                    )
                    if needs_timeline and p1_detail and p2_detail:
                        try:
                            time.sleep(0.2)
                            timeline_url = f"https://europe.api.riotgames.com/lol/match/v5/matches/{mid}/timeline"
                            timeline_request = urllib.request.Request(timeline_url, headers=headers)
                            with urllib.request.urlopen(timeline_request, timeout=8) as timeline_response:
                                timeline_info = json.loads(timeline_response.read().decode('utf-8')).get("info", {})
                        except Exception as timeline_error:
                            safe_print(f"[Riot Timeline Error] {mid}: {timeline_error}")
                    resolved_count = evaluate_active_penalties(duo, match, timeline_info)
                    if resolved_count:
                        safe_print(f"[Penalty Sync] {duo['teamName']}: {resolved_count} castigo(s) cumplido(s) en {mid}")
                    if p1_detail and p1_detail.get("profileIcon"):
                        duo["player1"]["avatar"] = f'https://ddragon.leagueoflegends.com/cdn/15.3.1/img/profileicon/{p1_detail["profileIcon"]}.png'
                    if p2_detail and duo.get("player2") and p2_detail.get("profileIcon"):
                        duo["player2"]["avatar"] = f'https://ddragon.leagueoflegends.com/cdn/15.3.1/img/profileicon/{p2_detail["profileIcon"]}.png'

                    if mid not in existing_by_id:
                        new_matches.append(match)
                        existing_by_id[mid] = match
                    else:
                        enriched_count += 1
                    updated = True
                except Exception as ex_m:
                    safe_print(f"[Riot Sync Match Detail Error] {mid}: {ex_m}")

            if new_matches:
                existing_history = new_matches + existing_history
            duo["history"] = sort_history_chronologically(existing_history)[:200]
            update_duo_shells(duo)
            update_duo_current_streak(duo)
            calculate_player_insights(duo)
            calculate_duo_best_match(duo)

            backfill_status = update_stats_backfill_status(duo, include_timestamp=True)
            remaining_backfill = backfill_status["remaining"]
            if fetch_ids:
                safe_print(
                    f"[Riot Stats] {p1_name}: {len(new_matches)} nuevas, {enriched_count} enriquecidas, "
                    f"{remaining_backfill} pendientes."
                )

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

def schedule_twitch_sync():
    def loop():
        while True:
            try:
                sync_twitch_live_status()
            except Exception as error:
                safe_print(f"[Twitch Sync Error] {error}")
            time.sleep(TWITCH_SYNC_INTERVAL)

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
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
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
            shell_attacks = db.get("shellAttacks", [])
            for duo in duos:
                update_duo_shells(duo)
                update_duo_current_streak(duo)
                calculate_player_insights(duo)
                calculate_duo_best_match(duo)
                update_stats_backfill_status(duo)
                duo["shellsLaunched"] = sum(
                    1 for attack in shell_attacks
                    if attack.get("attackerTeamId") == duo.get("id")
                )
                duo["shellsReceived"] = sum(
                    1 for attack in shell_attacks
                    if attack.get("targetTeamId") == duo.get("id")
                )
            self._send_json([safe_duo_for_player(duo) for duo in duos])
            return
        elif path == '/api/config':
            db = load_db()
            self._send_json(public_config(db.get("config", {})))
            return
        elif path == '/api/events':
            db = load_db()
            self._send_json(db.get("events", []))
            return

        # Static File Serving
        if path == '/':
            path = '/index.html'

        if path == '/db.json' or path == '/secrets.json':
            self._send_json({"error": "File Not Found"}, 404)
            return
        
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

        if parsed.path == '/api/admin/login':
            entered_pin = str(data.get("pin", "")).strip()
            if not verify_admin_pin(db, entered_pin):
                self._send_json({"success": False, "error": "PIN incorrecto"}, 401)
                return

            self._send_json({"success": True, "config": admin_config_response(db), "penaltyCatalog": PENALTY_CATALOG, "duos": safe_duos(db.get("duos", []))})

        elif parsed.path == '/api/duos':
            auth_pin = str(data.get("authPin", "")).strip()
            if not verify_admin_pin(db, auth_pin):
                self._send_json({"success": False, "error": "PIN incorrecto"}, 401)
                return
            data = data.get("duo", {})
            duos = db.get("duos", [])
            new_id = data.get("id", f"duo-{int(time.time() * 1000)}")
            data["id"] = new_id
            idx = next((i for i, d in enumerate(duos) if d["id"] == new_id), -1)
            existing_duo = duos[idx] if idx >= 0 else {}

            player1 = data.get("player1") or {}
            player2 = data.get("player2") or {}
            roles = (str(player1.get("mainRole", "")).upper(), str(player2.get("mainRole", "")).upper())
            if any(role not in VALID_MAIN_ROLES for role in roles):
                self._send_json({"success": False, "error": "Debes seleccionar un rol principal válido para ambos integrantes."}, 400)
                return
            player1["mainRole"], player2["mainRole"] = roles
            data["player1"], data["player2"] = player1, player2
            
            if "blueShells" not in data:
                data["blueShells"] = 0
            submitted_password = str(data.pop("password", "") or "")
            data.pop("passwordHash", None)
            if submitted_password:
                data["passwordHash"] = hash_secret(submitted_password)
            elif existing_duo.get("passwordHash"):
                data["passwordHash"] = existing_duo["passwordHash"]
            else:
                data["passwordHash"] = hash_secret("1234")
            if "initialTotalLp" not in data:
                data["initialTotalLp"] = 0 if data.get("tier") == "Unranked" else calc_total_lp(data.get("tier", "Iron"), data.get("division", "IV"), data.get("lp", 0))

            if idx >= 0:
                duos[idx] = data
            else:
                duos.insert(0, data)
                
            db["duos"] = duos
            save_db(db)
            self._send_json({"success": True, "duo": safe_duo_for_player(data)})

        elif parsed.path == '/api/player/login':
            team_id = data.get("teamId")
            pwd = data.get("password", "").strip()
            duos = db.get("duos", [])
            duo = next((d for d in duos if d["id"] == team_id or d["teamName"].lower() == str(team_id).lower()), None)
            
            stored_password = (duo or {}).get("passwordHash") or (duo or {}).get("password", "1234")
            if duo and verify_secret(pwd, stored_password):
                token = create_player_session(duo["id"])
                self._send_json({"success": True, "duo": player_state(db, duo), "sessionToken": token})
            else:
                self._send_json({"success": False, "error": "Contraseña o equipo incorrecto"}, 401)

        elif parsed.path == '/api/player/state':
            team_id = session_team(data.get("sessionToken"))
            duo = next((d for d in db.get("duos", []) if d.get("id") == team_id), None)
            if not duo:
                self._send_json({"success": False, "error": "Sesión caducada"}, 401)
                return
            self._send_json({"success": True, "duo": player_state(db, duo)})

        elif parsed.path == '/api/player/launch-shell':
            attacker_id = session_team(data.get("sessionToken"))
            target_id = data.get("targetId")
            duos = db.get("duos", [])

            if not attacker_id:
                self._send_json({"success": False, "error": "Sesión caducada"}, 401)
                return
            
            attacker = next((d for d in duos if d["id"] == attacker_id), None)
            target = next((d for d in duos if d["id"] == target_id), None)

            if not attacker or not target:
                self._send_json({"success": False, "error": "Equipo emisor o destino no encontrado"}, 400)
                return

            if attacker_id == target_id:
                self._send_json({"success": False, "error": "No puedes lanzarte un caparazón a ti mismo"}, 400)
                return

            if attacker.get("blueShells", 0) <= 0:
                self._send_json({"success": False, "error": "No tienes Caparazones Azules disponibles en tu inventario"}, 400)
                return

            attacker["blueShells"] -= 1
            attacker["shellsUsed"] = attacker.get("shellsUsed", 0) + 1

            attack = {
                "id": f"shell-{uuid.uuid4().hex}",
                "attackerTeamId": attacker["id"],
                "attackerName": attacker["teamName"],
                "targetTeamId": target["id"],
                "targetName": target["teamName"],
                "status": "PENDING_SPIN",
                "launchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "wheelSnapshot": dict(db.get("config", {}).get("penaltyWeights", default_penalty_weights()))
            }
            db.setdefault("shellAttacks", []).insert(0, attack)

            # Log Event
            event = {
                "id": f"event-{int(time.time()*1000)}",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "attacker": attacker["teamName"],
                "target": target["teamName"],
                "type": "SHELL_LAUNCHED",
                "shellAttackId": attack["id"],
                "message": f"🐢⚡ ¡{attacker['teamName']} ha lanzado un Caparazón Azul contra {target['teamName']}! El equipo receptor debe girar la ruleta."
            }
            events = db.get("events", [])
            events.insert(0, event)
            db["events"] = events[:20]

            save_db(db)
            self._send_json({"success": True, "attacker": player_state(db, attacker), "attack": attack, "event": event})

        elif parsed.path == '/api/player/spin-shell':
            team_id = session_team(data.get("sessionToken"))
            attack_id = str(data.get("attackId", ""))
            if not team_id:
                self._send_json({"success": False, "error": "Sesión caducada"}, 401)
                return
            target = next((d for d in db.get("duos", []) if d.get("id") == team_id), None)
            attack = next((a for a in db.get("shellAttacks", []) if a.get("id") == attack_id), None)
            if not target or not attack or attack.get("targetTeamId") != team_id:
                self._send_json({"success": False, "error": "Caparazón no encontrado"}, 404)
                return
            if attack.get("status") != "PENDING_SPIN":
                self._send_json({"success": False, "error": "Este caparazón ya ha sido girado"}, 409)
                return

            try:
                selected_penalty = weighted_penalty(attack.get("wheelSnapshot", {}))
            except ValueError as error:
                self._send_json({"success": False, "error": str(error)}, 400)
                return

            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            attack["spunAt"] = now_iso
            attack["result"] = selected_penalty
            if selected_penalty["baseId"] == "return_shell":
                attacker = next((d for d in db.get("duos", []) if d.get("id") == attack.get("attackerTeamId")), None)
                if attacker:
                    attacker["blueShells"] = int(attacker.get("blueShells", 0) or 0) + 1
                attack["status"] = "RETURNED"
            else:
                penalty_instance = {
                    "id": f"penalty-{uuid.uuid4().hex}",
                    "sourceShellId": attack["id"],
                    "penalty": selected_penalty,
                    "scope": selected_penalty["scope"],
                    "status": "ACTIVE",
                    "attacker": attack.get("attackerName"),
                    "attackerTeamId": attack.get("attackerTeamId"),
                    "assignedAt": now_iso,
                    "assignedAtEpochMs": int(time.time() * 1000),
                    "timestamp": time.strftime("%d/%m/%Y %H:%M"),
                    "requirements": penalty_requirements(target, selected_penalty, db.get("duos", [])),
                    "resolved": False
                }
                target.setdefault("activeDebuffs", []).insert(0, penalty_instance)
                attack["status"] = "PENALTY_ASSIGNED"
                attack["penaltyInstanceId"] = penalty_instance["id"]

            event = {
                "id": f"event-{int(time.time()*1000)}",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "type": "SHELL_SPUN",
                "shellAttackId": attack["id"],
                "attacker": attack.get("attackerName"),
                "target": attack.get("targetName"),
                "penalty": selected_penalty,
                "message": f"🎰 {attack.get('targetName')} ha girado la ruleta: {selected_penalty['icon']} {selected_penalty['name']} — {selected_penalty['desc']}"
            }
            db.setdefault("events", []).insert(0, event)
            db["events"] = db["events"][:50]
            save_db(db)
            self._send_json({"success": True, "penalty": selected_penalty, "duo": player_state(db, target), "attack": attack})

        elif parsed.path == '/api/config':
            auth_pin = str(data.get("authPin", "")).strip()
            current_config = db.get("config", {})
            if not verify_admin_pin(db, auth_pin):
                self._send_json({"success": False, "error": "PIN incorrecto"}, 401)
                return

            new_config = data.get("config", {})
            new_admin_pin = str(new_config.pop("adminPin", "") or "").strip()
            new_config.pop("adminPinHash", None)
            new_config.pop("adminPinConfigured", None)
            riot_api_key = str(new_config.pop("riotApiKey", "") or "").strip()
            new_config.pop("riotApiKeyConfigured", None)
            twitch_secret = str(new_config.pop("twitchClientSecret", "")).strip()
            new_config.pop("twitchClientSecretConfigured", None)
            submitted_weights = new_config.get("penaltyWeights", {})
            try:
                normalized_weights = {item["id"]: max(0, int(submitted_weights.get(item["id"], 0))) for item in PENALTY_CATALOG}
            except (TypeError, ValueError):
                self._send_json({"success": False, "error": "Los porcentajes de la ruleta deben ser números enteros."}, 400)
                return
            if sum(normalized_weights.values()) != 100:
                self._send_json({"success": False, "error": "Los porcentajes de la ruleta deben sumar exactamente 100%."}, 400)
                return
            new_config["penaltyWeights"] = normalized_weights
            new_config["adminPinHash"] = hash_secret(new_admin_pin) if new_admin_pin else current_config.get("adminPinHash")
            db["config"] = new_config
            save_db(db)

            if twitch_secret or riot_api_key:
                stored_secrets = load_secrets()
                if twitch_secret:
                    stored_secrets["twitchClientSecret"] = twitch_secret
                if riot_api_key:
                    stored_secrets["riotApiKey"] = riot_api_key
                save_secrets(stored_secrets)
                clear_twitch_token_cache()

            self._send_json({"success": True, "config": admin_config_response(db)})

        elif parsed.path == '/api/admin/resolve-penalty':
            auth_pin = str(data.get("authPin", "")).strip()
            if not verify_admin_pin(db, auth_pin):
                self._send_json({"success": False, "error": "PIN incorrecto"}, 401)
                return
            instance_id = str(data.get("penaltyInstanceId", "")).strip()
            action = str(data.get("action", "COMPLETE")).upper()
            note = str(data.get("note", "Corrección manual del administrador")).strip()[:300]
            found = None
            owner = None
            for duo in db.get("duos", []):
                for debuff in duo.get("activeDebuffs", []):
                    if debuff.get("id") == instance_id:
                        found, owner = debuff, duo
                        break
                if found:
                    break
            if not found:
                self._send_json({"success": False, "error": "Castigo no encontrado"}, 404)
                return
            if action == "REOPEN":
                found["status"] = "ACTIVE"
                found["resolved"] = False
                found.pop("resolvedAt", None)
                found.pop("manualResolution", None)
            elif action == "COMPLETE":
                found["status"] = "COMPLETED"
                found["resolved"] = True
                found["resolvedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                found["manualResolution"] = {"by": "ADMIN", "note": note}
            else:
                self._send_json({"success": False, "error": "Acción administrativa no válida"}, 400)
                return
            db.setdefault("events", []).insert(0, {
                "id": f"event-{int(time.time()*1000)}", "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "type": "PENALTY_ADMIN_CORRECTION", "target": owner.get("teamName"),
                "penalty": found.get("penalty"), "message": f"🛡️ Administración ha actualizado {found.get('penalty', {}).get('name', 'un castigo')} de {owner.get('teamName')}: {action}. Motivo: {note}"
            })
            db["events"] = db["events"][:50]
            save_db(db)
            self._send_json({"success": True, "duos": safe_duos(db.get("duos", []))})

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
            self._send_json({"success": True, "newShells": total_new_shells, "duos": safe_duos(duos)})

        elif parsed.path == '/api/sync':
            sync_riot_data()
            db = load_db()
            self._send_json({"success": True, "duos": safe_duos(db.get("duos", []))})

        elif parsed.path == '/api/twitch/sync':
            auth_pin = str(data.get("authPin", "")).strip()
            if not verify_admin_pin(db, auth_pin):
                self._send_json({"success": False, "error": "PIN incorrecto"}, 401)
                return
            result = sync_twitch_live_status()
            self._send_json(result, 200 if result.get("success") else 400)

        else:
            self._send_json({"error": "Endpoint Not Found"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/duos/'):
            length = int(self.headers.get('Content-Length', 0))
            raw_body = self.rfile.read(length).decode('utf-8') if length > 0 else '{}'
            data = json.loads(raw_body)
            duo_id = parsed.path.split('/')[-1]
            db = load_db()
            if not verify_admin_pin(db, str(data.get("authPin", "")).strip()):
                self._send_json({"success": False, "error": "PIN incorrecto"}, 401)
                return
            db["duos"] = [d for d in db.get("duos", []) if d["id"] != duo_id]
            save_db(db)
            self._send_json({"success": True})
        else:
            self._send_json({"error": "Endpoint Not Found"}, 404)

if __name__ == "__main__":
    os.chdir(BASE_DIR)
    startup_db = load_db()
    migrate_legacy_penalties(startup_db)
    save_db(startup_db)
    print("==================================================")
    print(f"Pepes Krisis Duo Q Challenge Server Activo en http://127.0.0.1:{PORT}")
    print("==================================================")

    schedule_sync()
    schedule_twitch_sync()
    server = ReusableServer(('', PORT), CustomHandler)
    server.serve_forever()
