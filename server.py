#!/usr/bin/env python3
"""
Pepes Krisis Duo Q Challenge - Python Backend Server & Live Riot API Engine
Features: Real ELO Tracking, Match-V5, Player Panels, Pepazos Gamification & Auth
"""

import os
import overlay_effects
import overlay_sessions
import remembered_sessions
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
import copy
import re
import clips_service
import weekly_summary
import discord_live
import discord_shells
import tierlists_service
import final_predictions
import betting_service
import shop_service
import pickem_service
import champions_service
import stat_progression
import player_accounts
import participant_roles
import riot_accounts_sync
import riot_match_policy
from competition_ranking import team_rank
from shell_rules import SHELL_KILLS, SHELL_ASSISTS, SHELL_PERFECT_KDA, individual_shell_criteria
from http.cookies import SimpleCookie, CookieError
from functools import wraps
from storage import read_json, write_json, StorageError
from terminology import pepazo_payload
from postgres_storage import from_environment
from elo_history import record_elo, ensure_player_elo_histories, record_player_elo
from trophies import build_trophies, deadline_timestamp
from sync_jobs import SyncJobs, utc_now
from match_details import participant_details, add_match_metadata, needs_match_details, update_match_details_backfill
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
DATA_DIR = os.environ.get("PEPES_DATA_DIR", BASE_DIR)
DB_FILE = os.path.join(DATA_DIR, "db.json")
SECRETS_FILE = os.path.join(DATA_DIR, "secrets.json")
TWITCH_SYNC_INTERVAL = 300
RIOT_MATCH_DETAIL_BATCH_PER_DUO = 40
MIN_RIOT_MATCH_DURATION_SECONDS = 600
VALID_MAIN_ROLES = {"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"}
MAX_SHELLS_INVENTORY = 5
MAX_SHELLS_PER_MATCH = 2
SHELL_WIN_STREAK = 4


def shell_reward_rules():
    return {
        "inventoryLimit": MAX_SHELLS_INVENTORY,
        "perMatchLimit": MAX_SHELLS_PER_MATCH,
        "rules": [
            {"id": "streak", "name": "Racha de victorias", "requirement": f"Ganar {SHELL_WIN_STREAK} partidas consecutivas. La racha se cuenta en bloques sin repetir victorias."},
            {"id": "penta", "name": "Pentakill", "requirement": "Uno de los integrantes consigue una pentakill."},
            {"id": "kills", "name": "Asesinatos", "requirement": f"Un integrante consigue al menos {SHELL_KILLS} kills en una partida."},
            {"id": "assists", "name": "Asistencias", "requirement": f"Un integrante consigue al menos {SHELL_ASSISTS} asistencias en una partida."},
            {"id": "perfect", "name": "KDA perfecto", "requirement": f"Un integrante termina con 0 muertes y más de {SHELL_PERFECT_KDA} kills + asistencias."},
        ]
    }

SECRET_HASH_ITERATIONS = 260000
SECRET_HASH_PREFIX = "pbkdf2_sha256"

PENALTY_CATALOG = [
    {"id": "autofill_one", "baseId": "autofill", "scope": "ONE", "name": "Polivalente · UNO", "icon": "🎲", "desc": "El integrante elegido por la ruleta (50/50) debe jugar en la posición sorteada entre las cuatro distintas de su rol principal.", "defaultWeight": 12},
    {"id": "autofill_both", "baseId": "autofill", "scope": "BOTH", "name": "Polivalente · AMBOS", "icon": "🎲", "desc": "Cada integrante debe jugar en su posición sorteada entre las cuatro distintas de su rol principal.", "defaultWeight": 5},
    {"id": "random_champion_one", "baseId": "random_champion", "scope": "ONE", "name": "Campeón aleatorio · UNO", "icon": "🎯", "desc": "El integrante elegido por la ruleta (50/50) debe jugar su campeón aleatorio asignado.", "defaultWeight": 28},
    {"id": "random_champion_both", "baseId": "random_champion", "scope": "BOTH", "name": "Campeón aleatorio · AMBOS", "icon": "🎯", "desc": "Cada integrante debe jugar su campeón aleatorio asignado.", "defaultWeight": 12},
    {"id": "no_flash_one", "baseId": "no_flash", "scope": "ONE", "name": "Sin Flash · UNO", "icon": "⚡", "desc": "El integrante elegido por la ruleta (50/50) debe jugar sin Flash.", "defaultWeight": 14},
    {"id": "no_flash_both", "baseId": "no_flash", "scope": "BOTH", "name": "Sin Flash · AMBOS", "icon": "⚡", "desc": "Los dos deben jugar sin Flash.", "defaultWeight": 6},
    {"id": "swap_flash_one", "baseId": "swap_flash", "scope": "ONE", "name": "Flash al otro lado · UNO", "icon": "🔄", "desc": "El integrante elegido por la ruleta (50/50) debe llevar Flash en la posición contraria a la registrada en su primera partida con Flash. El otro hechizo es libre.", "defaultWeight": 12},
    {"id": "swap_flash_both", "baseId": "swap_flash", "scope": "BOTH", "name": "Flash al otro lado · AMBOS", "icon": "🔄", "desc": "Ambos deben llevar Flash en la posición contraria a la registrada en su primera partida con Flash, cada uno según su propia referencia. El otro hechizo es libre.", "defaultWeight": 6},
    {"id": "return_shell", "baseId": "return_shell", "scope": "SPECIAL", "name": "Devuelve el pepazo", "icon": "↩️", "desc": "El equipo atacante recibe el pepazo en su bandeja y debe girar su ruleta.", "defaultWeight": 5}
]

player_sessions = {}
shell_notifications = threading.Condition()
shell_notification_revision = 0
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

RETIRED_PENALTY_IDS = {"no_boots", "basic_boots_15", "basic_boots_15_one", "basic_boots_15_both"}
# Remove these outcomes from future draws, without cancelling already assigned penalties.
REPLACED_PENALTY_WEIGHTS = {
    "no_main_champion_one": "random_champion_one",
    "no_main_champion_both": "random_champion_both",
}


def is_retired_penalty(penalty):
    return penalty.get("id") in RETIRED_PENALTY_IDS or penalty.get("baseId") == "basic_boots_15"


def without_retired_weights(weights):
    """Transfer removed favorite odds by scope; preserve all other available odds."""
    remaining = {key: value for key, value in weights.items()
                 if key not in RETIRED_PENALTY_IDS and key not in REPLACED_PENALTY_WEIGHTS}
    for old_id, replacement in REPLACED_PENALTY_WEIGHTS.items():
        if old_id in weights:
            remaining[replacement] = int(remaining.get(replacement, 0) or 0) + int(weights[old_id] or 0)
    if any(int(weights.get(key, 0) or 0) > 0 for key in RETIRED_PENALTY_IDS):
        if not any(int(remaining.get(item["id"], 0) or 0) > 0 for item in PENALTY_CATALOG):
            return default_penalty_weights()
    return remaining


def retire_removed_penalties(db):
    changed = False
    config = db.setdefault("config", {})
    wheels = [config] + [attack for attack in db.get("shellAttacks", []) if attack.get("status") == "PENDING_SPIN"]
    for owner in wheels:
        key = "penaltyWeights" if owner is config else "wheelSnapshot"
        weights = owner.get(key)
        if isinstance(weights, dict) and (RETIRED_PENALTY_IDS | REPLACED_PENALTY_WEIGHTS.keys()).intersection(weights):
            owner[key] = without_retired_weights(weights)
            changed = True
    for duo in db.get("duos", []):
        for debuff in duo.get("activeDebuffs", []):
            if not is_retired_penalty(debuff.get("penalty", {})):
                continue
            if not debuff.get("retiredPenalty"):
                debuff["retiredPenalty"] = True
                changed = True
            if not debuff.get("resolved") and debuff.get("status") in (None, "ACTIVE"):
                debuff["status"] = "CANCELLED"
                debuff["retiredAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                debuff["retirementReason"] = "El castigo de botas se ha retirado del torneo."
                changed = True
    return changed


def ensure_shell_schema(db):
    config = db.setdefault("config", {})
    configured = config.get("penaltyWeights")
    defaults = default_penalty_weights()
    if not isinstance(configured, dict):
        config["penaltyWeights"] = defaults
    else:
        configured = without_retired_weights(configured)
        config["penaltyWeights"] = {
            item["id"]: int(configured.get(item["id"], defaults[item["id"]]) or 0)
            for item in PENALTY_CATALOG
        }
    db.setdefault("shellAttacks", [])
    db.setdefault("events", [])
    return db


def migrate_flash_penalty_weights(db):
    """Introduce the new outcomes once while keeping admin percentages at 100."""
    if db.get("flashPenaltyConfigVersion") == 1:
        return False
    weights = db["config"]["penaltyWeights"]
    total = sum(weights.values())
    if total > 0 and total != 100:
        flash_ids = {"swap_flash_one", "swap_flash_both"}
        flash_total = sum(weights[key] for key in flash_ids)
        other_total = total - flash_total
        protected = flash_ids if 0 < flash_total < 100 and other_total > 0 else set()
        budget = 100 - flash_total if protected else 100
        pool = {key: max(0, value) for key, value in weights.items() if key not in protected}
        pool_total = sum(pool.values())
        if pool_total:
            allocation = {key: value * budget // pool_total for key, value in pool.items()}
            remainder = budget - sum(allocation.values())
            order = sorted(pool, key=lambda key: pool[key] * budget % pool_total, reverse=True)
            for key in order[:remainder]:
                allocation[key] += 1
            weights.update(allocation)
    db["flashPenaltyConfigVersion"] = 1
    return True

def safe_duo_for_player(duo):
    result = dict(duo)
    for key in ("player1", "player2"):
        if result.get(key):
            result[key] = copy.deepcopy(result[key])
        for account in (result.get(key) or {}).get("accounts", []):
            account.pop("matchDiscovery", None)
    result.pop("password", None)
    participant_roles.update_roles(result)
    result.pop("passwordHash", None)
    result.pop("riotMatchDiscovery", None)
    result.pop("excludedRiotMatches", None)
    result.pop("discordWebhook", None)
    result.pop("discordRoleId", None)
    return result

def safe_duo_for_admin(duo):
    result = safe_duo_for_player(duo)
    result["discordWebhook"] = duo.get("discordWebhook", "")
    result["discordRoleId"] = duo.get("discordRoleId", "")
    return result

def safe_duos(duos):
    return [safe_duo_for_player(duo) for duo in duos]

def safe_duos_for_admin(duos):
    return [safe_duo_for_admin(duo) for duo in duos]

def duo_summary(duo):
    result = safe_duo_for_player(duo)
    result["competitionRank"] = team_rank(duo)
    result["tournamentRecord"] = riot_match_policy.history_record(duo, MIN_RIOT_MATCH_DURATION_SECONDS)
    result["historyCount"] = len(result.pop("history", []))
    return result


summary_cache = {"key": None, "value": []}


def public_duo_summaries():
    with db_lock:
        stat = os.stat(DB_FILE) if os.path.exists(DB_FILE) else None
        key = (DB_FILE, stat.st_mtime_ns, stat.st_size) if stat else None
        if remote_backend is None and key is not None and summary_cache["key"] == key:
            return copy.deepcopy(summary_cache["value"])
        db = load_db()
        duos = db.get("duos", [])
        attacks = db.get("shellAttacks", [])
        for duo in duos:
            update_duo_current_streak(duo)
            calculate_player_insights(duo)
            calculate_duo_best_match(duo)
            update_stats_backfill_status(duo)
            duo["shellsLaunched"] = sum(a.get("attackerTeamId") == duo.get("id") for a in attacks)
            duo["shellsReceived"] = sum(a.get("targetTeamId") == duo.get("id") for a in attacks)
        result = [duo_summary(duo) for duo in duos]
        summary_cache.update(key=key, value=copy.deepcopy(result))
        return result


def page_args(parsed):
    query = urllib.parse.parse_qs(parsed.query)
    return max(0, int(query.get("offset", [0])[0])), min(100, max(1, int(query.get("limit", [30])[0])))


def session_team(token, db=None):
    session = player_sessions.get(str(token or ""))
    if not session or session.get("expiresAt", 0) < time.time():
        return None
    if db is not None and session.get('rememberDigest'):
        record = db.get('rememberedTeamSessions', {}).get(session['rememberDigest'])
        if not remembered_sessions.valid_record(db, record):
            return None
    return session.get("teamId")

def notify_shell_receivers():
    global shell_notification_revision
    with shell_notifications:
        shell_notification_revision += 1
        shell_notifications.notify_all()


def receiver_notification_state(token, remembered=False):
    with db_lock:
        db = load_db()
        team_id = (remembered_sessions.team(db, token) if remembered else
                   session_team(token, db) or overlay_sessions.team(db, token))
        if not team_id:
            return None
        duo = next((d for d in db.get("duos", []) if d.get("id") == team_id), None)
        if not duo:
            return None
        return {
            "team": {"id": team_id, "name": duo.get("teamName", "Equipo")},
            "attacks": [{key: a.get(key) for key in ("id", "attackerName", "launchedAt", "overlayEffect")}
                        for a in reversed(db.get("shellAttacks", []))
                        if a.get("targetTeamId") == team_id and a.get("status") == "PENDING_SPIN"]
        }


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

def create_pending_shell(db, attacker, target, wheel_snapshot=None, returned_from=None):
    """Create an inbox attack; spending inventory is handled only by a normal launch."""
    attack = {
        "id": f"shell-{uuid.uuid4().hex}",
        "attackerTeamId": attacker["id"], "attackerName": attacker["teamName"],
        "targetTeamId": target["id"], "targetName": target["teamName"],
        "status": "PENDING_SPIN",
        "overlayEffect": overlay_effects.choose(db),
        "launchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "wheelSnapshot": without_retired_weights(wheel_snapshot if wheel_snapshot is not None else db.get("config", {}).get("penaltyWeights", default_penalty_weights()))
    }
    if returned_from:
        attack.update(returnedFromAttackId=returned_from["id"],
                      rootShellId=returned_from.get("rootShellId") or returned_from["id"],
                      reflectionCount=int(returned_from.get("reflectionCount", 0)) + 1)
    db.setdefault("shellAttacks", []).insert(0, attack)
    return attack


def weighted_penalty(snapshot):
    snapshot = without_retired_weights(snapshot)
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

def fill_pending_penalty_favorites(duo):
    """Resolve empty favorite references from newly available history, once."""
    snapshot = None
    changed = []
    for debuff in duo.get("activeDebuffs", []):
        penalty = debuff.get("penalty") or {}
        if debuff.get("status") != "ACTIVE" or debuff.get("resolved"):
            continue
        if (penalty.get("baseId") or penalty.get("id")) != "no_main_champion":
            continue
        requirements = debuff.setdefault("requirements", {})
        favorites = requirements.setdefault("favoriteChampions", {})
        scope = debuff.get("scope") or penalty.get("scope") or "ONE"
        assigned = requirements.get("assignedPlayer")
        keys = (assigned,) if scope == "ONE" and assigned in ("player1", "player2") else ("player1", "player2")
        updated = False
        for key in keys:
            if favorites.get(key):
                continue  # An existing reference must not move while serving the penalty.
            if snapshot is None:
                snapshot = favorite_snapshot(duo)
            if snapshot[key]:
                favorites[key] = list(snapshot[key])
                updated = True
        if updated:
            changed.append(debuff)
    return changed


def fill_pending_penalty_roles(duo):
    """Resolve empty automatic references once; published legacy roles stay fixed."""
    changed = []
    for debuff in duo.get('activeDebuffs', []):
        req = debuff.get('requirements') or {}
        if debuff.get('status') != 'ACTIVE' or debuff.get('resolved') or debuff.get('penalty', {}).get('baseId') != 'autofill' or req.get('mainRoleMode') != 'most_played':
            continue
        scope = debuff.get('scope') or debuff.get('penalty', {}).get('scope')
        assigned = req.get('assignedPlayer')
        keys = (assigned,) if scope == 'ONE' and assigned in ('player1','player2') else ('player1','player2')
        roles, updated = req.setdefault('mainRoles', {}), False
        for key in keys:
            if roles.get(key) not in VALID_MAIN_ROLES:
                position = participant_roles.role_summary(duo, key)['position']
                if position:
                    roles[key] = position
                    updated = True
            if 'randomPositions' in req and roles.get(key) in VALID_MAIN_ROLES and not req['randomPositions'].get(key):
                req['randomPositions'][key] = secrets.choice(tuple(role for role in participant_roles.POSITIONS if role != roles[key]))
                updated = True
        if updated:
            changed.append(debuff)
    return changed


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

def flash_account(player):
    return {field: player.get(field, "") for field in ("name", "tag", "puuid", "displayName")}


def same_flash_account(left, right):
    if left.get("puuid") and right.get("puuid"):
        return bool(player_accounts.known_puuids(left) & player_accounts.known_puuids(right))
    identity = lambda account: (str(account.get("name", "")).strip().casefold(), str(account.get("tag") or "EUW").strip().casefold())
    return bool(left.get("name")) and identity(left) == identity(right)


def player_flash_baseline(player):
    baseline = player.get("flashBaseline") or {}
    if (baseline.get("slot") in (1, 2) and baseline.get("matchId")
            and baseline.get("gameStartTimestamp", 0) > 0
            and same_flash_account(baseline.get("account", {}), player)):
        return baseline
    return None


def record_flash_baselines(duo, match):
    """First successfully imported game with Flash fixes each account's comfort slot."""
    if match.get("isTest") or not match.get("matchId") or not match.get("gameStartTimestamp"):
        return
    for key in ("player1", "player2"):
        owner = duo.get(key) or {}
        stats = match.get(f"{key}Stats") or {}
        player = player_accounts.account_for_stats(owner, stats) or owner
        if not player.get("name") or player_flash_baseline(player):
            continue
        spells = stats.get("summonerSpellIds") or []
        if not stats.get("puuid") or (player.get("puuid") and player["puuid"] != stats["puuid"]):
            continue
        if len(spells) != 2 or not all(spells) or spells.count(4) != 1:
            continue
        player["flashBaseline"] = {"slot": spells.index(4) + 1, "matchId": match["matchId"],
                                   "gameStartTimestamp": match["gameStartTimestamp"],
                                   "account": {**flash_account(player), "puuid": stats["puuid"]}}
        if owner.get("accounts") and len(owner["accounts"]) == 1:
            owner["flashBaseline"] = copy.deepcopy(player["flashBaseline"])


def fill_pending_flash_baselines(duo):
    changed = []
    for debuff in duo.get("activeDebuffs", []):
        if debuff.get("status") != "ACTIVE" or debuff.get("resolved") or debuff.get("penalty", {}).get("baseId") != "swap_flash":
            continue
        req = debuff.setdefault("requirements", {})
        baselines = req.setdefault("flashBaselines", {})
        updated = False
        for key, account in req.get("flashAccounts", {}).items():
            baseline = player_flash_baseline(duo.get(key) or {})
            if key not in baselines and baseline and same_flash_account(account, baseline["account"]):
                baselines[key] = copy.deepcopy(baseline)
                updated = True
        if updated:
            changed.append(debuff)
    return changed


def penalty_requirements(duo, penalty, duos, assign_positions=True):
    requirements = {
        "mainRoles": {key: participant_roles.role_summary(duo, key, time.time()*1000)['position'] for key in ("player1", "player2")},
        "favoriteChampions": favorite_snapshot(duo)
    }
    if penalty.get('baseId') == 'autofill':
        requirements['mainRoleMode'] = 'most_played'
    if penalty.get("scope") == "ONE":
        # Exactly one independent, uniform draw for every individual penalty.
        player_key = secrets.choice(("player1", "player2"))
        player = duo.get(player_key) or {}
        requirements.update(
            assignmentVersion=2,
            assignedPlayer=player_key,
            assignedAccount={"name": player.get("name", ""), "tag": player.get("tag", "EUW"),
                             "displayName": player.get("displayName") or player.get("name", ""),
                             "puuid": player.get("puuid", "")})
    if penalty.get("baseId") == "random_champion":
        pool = champion_pool(duos)
        keys = (requirements["assignedPlayer"],) if penalty.get("scope") == "ONE" else ("player1", "player2")
        requirements["randomChampions"] = {key: secrets.choice(pool) for key in keys}
    if penalty.get("baseId") == "autofill" and assign_positions:
        keys = (requirements["assignedPlayer"],) if penalty.get("scope") == "ONE" else ("player1", "player2")
        requirements["randomPositions"] = {
            key: secrets.choice(tuple(role for role in participant_roles.POSITIONS if role != requirements["mainRoles"][key]))
            for key in keys if requirements["mainRoles"].get(key) in VALID_MAIN_ROLES
        }
    if penalty.get("baseId") == "swap_flash":
        keys = (requirements["assignedPlayer"],) if penalty.get("scope") == "ONE" else ("player1", "player2")
        requirements["flashAccounts"] = {key: flash_account(duo.get(key) or {}) for key in keys}
        requirements["flashBaselines"] = {key: copy.deepcopy(player_flash_baseline(duo.get(key) or {}))
                                          for key in keys if player_flash_baseline(duo.get(key) or {})}
    return requirements


def penalty_player_matches(duo, match, requirements):
    """Check the selected participant's account, not just their slot in the duo."""
    key = requirements.get("assignedPlayer")
    if key not in ("player1", "player2"):
        return False
    account = requirements.get("assignedAccount")
    if not account:
        return requirements.get("assignmentVersion", 0) < 2  # Older random-champion assignments.
    stats = match.get(f"{key}Stats") or {}
    player = duo.get(key) or {}
    if len(player_accounts.accounts(player)) > 1:
        bound = any(same_flash_account(account, a) or (account.get("puuid") in player_accounts.known_puuids(a) if account.get("puuid") else False)
                    for a in player_accounts.accounts(player))
        return bound and player_accounts.account_for_stats(player, stats) is not None
    if account.get("puuid"):
        return stats.get("puuid") == account["puuid"]
    player = duo.get(key) or {}
    # Before the first Riot sync, bind to the configured Riot ID until its PUUID is known.
    identity = lambda value: (str(value.get("name", "")).strip().casefold(), str(value.get("tag") or "EUW").strip().casefold())
    if identity(player) != identity(account):
        return False
    if player.get("puuid") and stats.get("puuid") != player["puuid"]:
        return False
    return bool(account.get("name"))


def migrate_legacy_penalties(db):
    changed = False
    legacy_map = {"no_flash": "no_flash_one", "autofill": "autofill_both"}
    catalog_by_id = {item["id"]: item for item in PENALTY_CATALOG}
    for duo in db.get("duos", []):
        for debuff in duo.get("activeDebuffs", []):
            if not debuff.get("id"):
                debuff["id"] = f"penalty-{uuid.uuid4().hex}"
                changed = True
            old_penalty = debuff.get("penalty", {})
            if is_retired_penalty(old_penalty):
                continue
            mapped = catalog_by_id.get(legacy_map.get(old_penalty.get("id")))
            if mapped and not old_penalty.get("baseId"):
                debuff["penalty"] = dict(mapped)
                if mapped["scope"] == "ONE":
                    debuff["penalty"]["desc"] = "Uno de los dos integrantes debe jugar sin Flash."
                debuff["scope"] = mapped["scope"]
                changed = True
            expected_status = "COMPLETED" if debuff.get("resolved") else "ACTIVE"
            if not debuff.get("status"):
                debuff["status"] = expected_status
                changed = True
            if "requirements" not in debuff:
                # Already-open penalties keep their original scope and player assignment.
                legacy_requirements = penalty_requirements(duo, {**debuff.get("penalty", {}), "scope": "BOTH"}, db.get("duos", []), assign_positions=False)
                if (debuff.get("scope") or debuff.get("penalty", {}).get("scope")) == "ONE" and debuff.get("penalty", {}).get("baseId") == "random_champion":
                    key = secrets.choice(("player1", "player2"))
                    legacy_requirements["assignedPlayer"] = key
                    legacy_requirements["randomChampions"] = {key: legacy_requirements["randomChampions"][key]}
                debuff["requirements"] = legacy_requirements
                changed = True
    return changed

def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except Exception:
        pass

DEFAULT_CONFIG = {
    "challengeTitle": "Pepes Krisis Duo Q Challenge",
    "startDate": "2026-10-15T18:00:00+02:00",
    "endDate": "2026-11-15T23:59:00+01:00",
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

db_lock = threading.RLock()
sync_jobs = SyncJobs()
riot_sync_lock = threading.Lock()
twitch_sync_lock = threading.Lock()
secrets_lock = threading.Lock()
twitch_token_lock = threading.Lock()
twitch_token_cache = {"client_id": "", "access_token": "", "expires_at": 0}

remote_backend = from_environment()
CLIPS_PREVIEW = os.environ.get("PEPES_CLIPS_PREVIEW") == "1" and remote_backend is None


def load_db():
    with db_lock:
        if remote_backend is not None:
            remote_backend.reconcile()
            data = remote_backend.load()
        elif not os.path.exists(DB_FILE):
            seed_file = os.path.join(BASE_DIR, "seed-db.json")
            data = read_json(seed_file) if os.path.exists(seed_file) else {"config": copy.deepcopy(DEFAULT_CONFIG), "duos": [], "events": []}
            # Bootstrap a fresh container only. Existing data always wins.
            write_json(DB_FILE, data)
        else:
            data = read_json(DB_FILE)
        if not isinstance(data.get("config"), dict) or not isinstance(data.get("duos"), list):
            raise StorageError("La base de datos no tiene un formato válido; no se ha sobrescrito.")
        rewards_migrated = data.get("shellRewardsVersion") != 1
        if rewards_migrated:
            # Existing games keep their old rewards; new criteria start on new imports.
            for duo in data.get("duos", []):
                for match in duo.get("history", []):
                    match["legacyShellRewards"] = True
            data["shellRewardsVersion"] = 1
        elo_migrated = False
        roles_changed = False
        for duo in data.get("duos", []):
            roles_changed = participant_roles.update_roles(duo) or roles_changed
            player = duo.get("player1") or {}
            account = player_accounts.elo_identity(player)
            if not duo.get("eloHistory") or duo.get("eloHistoryAccount") != account:
                record_elo(duo, calc_total_lp(duo.get("tier"), duo.get("division"), duo.get("lp")), time.time(), "initial")
                elo_migrated = True
            elo_migrated = ensure_player_elo_histories(duo) or elo_migrated
            for key in ("player1", "player2"):
                participant = duo.get(key) or {}
                rank = participant.get("rank") or {}
                if not participant.get("eloHistory") and rank.get("tier") and rank.get("observedAt"):
                    record_player_elo(participant, calc_total_lp(rank.get("tier"), rank.get("division"), rank.get("lp")), rank["observedAt"])
                    elo_migrated = True
        penalties_retired = retire_removed_penalties(data)
        data = ensure_shell_schema(data)
        flash_weights_migrated = migrate_flash_penalty_weights(data)
        clips_awarded = clips_service.settle_weekly_reward(data)
        weekly_archived = weekly_summary.maintain(data)
        pickem_awarded = pickem_service.maintain(data)
        predictions_settled = final_predictions.maintain(data)
        betting_changed = betting_service.maintain(data)
        if migrate_credentials(data) or rewards_migrated or elo_migrated or roles_changed or penalties_retired or flash_weights_migrated or clips_awarded or weekly_archived or pickem_awarded or predictions_settled or betting_changed:
            save_db(data)
        return data


def save_db(data):
    with db_lock:
        for duo in data.get('duos', []):
            participant_roles.update_roles(duo)
        betting_service.maintain(data)
        if remote_backend is not None:
            summary_cache["key"] = None
            remote_backend.save(data)
            # Neon is authoritative; local writes are only a disposable cache.
            try:
                write_json(DB_FILE, data)
            except StorageError:
                safe_print("[Neon] Guardado confirmado; no se pudo actualizar la copia local.")
        else:
            write_json(DB_FILE, data)


def load_secrets():
    with secrets_lock:
        return read_json(SECRETS_FILE) if os.path.exists(SECRETS_FILE) else {}


def save_secrets(data):
    with secrets_lock:
        write_json(SECRETS_FILE, data)


def serialized_mutation(method):
    @wraps(method)
    def wrapped(self):
        with db_lock:
            return method(self)
    return wrapped


def http_errors(method):
    @wraps(method)
    def wrapped(self):
        try:
            return method(self)
        except StorageError as error:
            self._send_json({"success": False, "error": str(error)}, 503)
        except (ValueError, TypeError, KeyError, AttributeError):
            self._send_json({"success": False, "error": "Solicitud inválida."}, 400)
    return wrapped


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
        if parsed.scheme != 'https' or hostname != 'twitch.tv' or len(parts) != 1 or parsed.username or parsed.password or parsed.port:
            return ''
        channel = parts[0]
        if not re.fullmatch(r'[A-Za-z0-9_]{4,25}', channel):
            return ''
        return channel.lower()
    except Exception:
        return ''

def normalize_opgg_url(value):
    raw = str(value or '').strip()
    if not raw or len(raw) > 2048 or any(ord(char) < 32 or ord(char) == 127 or char == '\\' for char in raw):
        return ''
    try:
        url = urllib.parse.urlsplit(raw)
        host = (url.hostname or '').lower()
        if (url.scheme != 'https' or not (host == 'op.gg' or host.endswith('.op.gg'))
                or url.username or url.password or url.port not in (None, 443)):
            return ''
        return raw
    except ValueError:
        return ''


def participant_twitch_channel(duo, player_key):
    player = duo.get(player_key) or {}
    # Legacy team links belong to the first participant until explicitly edited.
    url = player.get("twitchUrl") if "twitchUrl" in player else duo.get("twitchUrl") if player_key == "player1" else ""
    return twitch_channel_from_url(url)


def participant_twitch_live(duo, player_key):
    player = duo.get(player_key) or {}
    if not participant_twitch_channel(duo, player_key):
        return False
    if "twitchIsLive" in player:
        return player["twitchIsLive"] is True
    return "twitchUrl" not in player and player_key == "player1" and duo.get("twitchIsLive") is True


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

def check_service_credentials(db):
    """Real API probes without teams; never return keys, tokens or raw errors."""
    result = {"checkedAt": utc_now()}
    api_key = get_riot_api_key()
    if not api_key:
        result["riot"] = {"success": False, "error": "Clave de Riot no configurada."}
    else:
        try:
            region = db.get("config", {}).get("server", "EUW").lower()
            platform = {"euw": "euw1", "eune": "eun1", "na": "na1", "kr": "kr"}.get(region, "euw1")
            request = urllib.request.Request(f"https://{platform}.api.riotgames.com/lol/status/v4/platform-data",
                                             headers={"X-Riot-Token": api_key, "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or not payload.get("id"):
                raise ValueError("invalid response")
            result["riot"] = {"success": True, "httpStatus": 200, "endpoint": "lol-status-v4"}
        except urllib.error.HTTPError as error:
            result["riot"] = {"success": False, "httpStatus": error.code, "error": f"Riot respondió HTTP {error.code}."}
        except Exception:
            result["riot"] = {"success": False, "error": "No se pudo confirmar la conexión con Riot."}
    client_id, client_secret = get_twitch_credentials(db)
    if not client_id or not client_secret:
        result["twitch"] = {"success": False, "error": "Credenciales de Twitch no configuradas."}
    else:
        try:
            # Obtain a fresh token to verify the currently configured client secret.
            clear_twitch_token_cache()
            token = get_twitch_app_token(client_id, client_secret)
            request = urllib.request.Request("https://api.twitch.tv/helix/streams?first=1",
                                             headers={"Authorization": f"Bearer {token}", "Client-Id": client_id})
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("invalid response")
            result["twitch"] = {"success": True, "httpStatus": 200, "endpoint": "oauth + helix/streams"}
        except urllib.error.HTTPError as error:
            clear_twitch_token_cache()
            result["twitch"] = {"success": False, "httpStatus": error.code, "error": f"Twitch respondió HTTP {error.code}."}
        except Exception:
            result["twitch"] = {"success": False, "error": "No se pudo confirmar la conexión con Twitch."}
    return result


def single_sync(lock):
    def decorate(callback):
        @wraps(callback)
        def run(*args, **kwargs):
            if not lock.acquire(blocking=False):
                return {"success": False, "error": "Ya hay una sincronización en curso."}
            try:
                return callback(*args, **kwargs)
            finally:
                lock.release()
        return run
    return decorate


def sync_discord_live_alerts(live_streams, owners):
    raw_url = os.environ.get("DISCORD_LIVE_WEBHOOK_URL", "").strip()
    if not raw_url:
        return {"configured": False, "sent": 0}
    url = discord_live.webhook_url(raw_url)
    if not url:
        return {"configured": True, "sent": 0, "error": "DISCORD_LIVE_WEBHOOK_URL no es un webhook válido de Discord."}
    try:
        with db_lock:
            current = load_db()
            if discord_live.prepare(current, live_streams, owners):
                save_db(current)
            queued = discord_live.pending(current, live_streams, owners)
            status = current.get("discordLiveStatus", {})
            if time.time() < status.get("retryAt", 0):
                return {"configured": True, "sent": 0, "pending": len(queued), "error": status.get("error")}
        sent = 0
        # Bound network work; additional live alerts wait for the next regular cycle.
        for alert in queued[:5]:
            with db_lock:
                current = load_db()
                duo = next((d for d in current.get("duos", []) if d.get("id") == alert["teamId"]), None)
                if not duo or participant_twitch_channel(duo, alert["playerKey"]) != alert["channel"]:
                    continue
            # Never hold the database lock while waiting for Discord.
            result = discord_live.send(url, alert)
            with db_lock:
                current = load_db()
                record = current.get("discordLiveNotifications", {}).get(alert["channel"], {})
                status = current.setdefault("discordLiveStatus", {})
                if result["success"]:
                    if record.get("streamId") == alert["streamId"]:
                        record.update(status="sent", messageId=result["messageId"], sentAt=utc_now())
                    status.update(lastSentAt=utc_now(), error=None, retryAt=0)
                    sent += 1
                else:
                    status.update(error=result["error"], retryAt=time.time() + result["retryAfter"])
                save_db(current)
            if not result["success"]:
                return {"configured": True, "sent": sent, "pending": len(queued) - sent, "error": result["error"]}
        return {"configured": True, "sent": sent, "pending": max(0, len(queued) - sent)}
    except StorageError:
        return {"configured": True, "error": "No se pudo guardar el estado de los avisos de Discord."}


@single_sync(twitch_sync_lock)
def sync_twitch_live_status():
    db = load_db()
    requested = {(duo["id"], key): participant_twitch_channel(duo, key)
                 for duo in db.get("duos", []) for key in ("player1", "player2")}
    channels = sorted({channel for channel in requested.values() if channel})
    live_channels = set()
    live_streams = {}
    try:
        if channels:
            client_id, client_secret = get_twitch_credentials(db)
            if not client_id or not client_secret:
                return {"success": False, "error": "Credenciales de Twitch no configuradas"}
            access_token = get_twitch_app_token(client_id, client_secret)
            # Twitch accepts up to 100 logins; request all possible live results per batch.
            for offset in range(0, len(channels), 100):
                batch = channels[offset:offset + 100]
                query = urllib.parse.urlencode([("first", 100)] + [("user_login", channel) for channel in batch])
                request = urllib.request.Request(
                    f"https://api.twitch.tv/helix/streams?{query}",
                    headers={"Authorization": f"Bearer {access_token}", "Client-Id": client_id})
                with urllib.request.urlopen(request, timeout=20) as response:
                    stream_data = json.loads(response.read().decode('utf-8'))
                if not isinstance(stream_data.get("data"), list):
                    raise ValueError("Respuesta de Twitch inválida")
                live_channels.update(str(stream.get("user_login", "")).lower()
                                     for stream in stream_data["data"]
                                     if stream.get("type") == "live" and str(stream.get("user_login", "")).lower() in batch)
                live_streams.update({str(stream.get("user_login", "")).lower(): stream
                                     for stream in stream_data["data"]
                                     if stream.get("type") == "live" and str(stream.get("user_login", "")).lower() in batch})

        with db_lock:
            current = load_db()
            changed = False
            owners = {}
            for duo in current.get("duos", []):
                for key in ("player1", "player2"):
                    channel = participant_twitch_channel(duo, key)
                    # An edit made while Twitch was responding must keep its own state.
                    if (duo["id"], key) not in requested or requested[(duo["id"], key)] != channel:
                        continue
                    player = duo.get(key)
                    if channel and isinstance(player, dict):
                        owners.setdefault(channel, {"teamId": duo["id"], "playerKey": key,
                                                   "teamName": duo.get("teamName", ""),
                                                   "name": player.get("displayName") or player.get("name") or channel})
                    if isinstance(player, dict) and player.get("twitchIsLive") is not (channel in live_channels):
                        player["twitchIsLive"] = channel in live_channels
                        changed = True
                is_live = any(participant_twitch_live(duo, key) for key in ("player1", "player2"))
                if duo.get("twitchIsLive") is not is_live:
                    duo["twitchIsLive"] = is_live
                    changed = True
            if changed:
                save_db(current)
        discord_result = sync_discord_live_alerts(live_streams, owners)
        safe_print(f"[Twitch Sync] {len(channels)} canal(es) comprobados; {len(live_channels)} en directo.")
        return {"success": True, "checked": len(channels), "live": len(live_channels), "discord": discord_result}
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
        if m.get("gameEndTimestamp"):
            return (int(m["gameEndTimestamp"]) / 1000, 0)
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

def participant_stats(participant, participants=()):
    if not participant:
        return None
    return {
        "puuid": str(participant.get("puuid") or ""),
        "championName": normalize_champion_name(participant.get("championName")),
        "kills": int(participant.get("kills", 0) or 0),
        "deaths": int(participant.get("deaths", 0) or 0),
        "assists": int(participant.get("assists", 0) or 0),
        "pentaKills": int(participant.get("pentaKills", 0) or 0),
        "largestMultiKill": int(participant.get("largestMultiKill", 0) or 0),
        "win": bool(participant.get("win", False)),
        "position": normalize_position(participant),
        "summonerSpellIds": [int(participant.get("summoner1Id", 0) or 0), int(participant.get("summoner2Id", 0) or 0)],
        "participantId": int(participant.get("participantId", 0) or 0),
        **participant_details(participant, participants)
    }

def enrich_match_record(match, info, puuid1, puuid2):
    """Add the two participants' durable stats to a new or legacy match record."""
    participants = info.get("participants", [])
    p1 = next((p for p in participants if p.get("puuid") == puuid1), None)
    p2 = next((p for p in participants if puuid2 and p.get("puuid") == puuid2), None)
    p1_stats = participant_stats(p1, participants)
    p2_stats = participant_stats(p2, participants)

    match["player1Stats"] = p1_stats
    match["player2Stats"] = p2_stats
    match["statsVersion"] = 2
    add_match_metadata(match, info, puuid1, puuid2, bool(p1))

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

def evaluate_active_penalties(duo, match):
    if match.get("isTest"):
        return 0
    if not match.get("player1Stats") or not match.get("player2Stats"):
        return 0
    game_start_ms = int(match.get("gameStartTimestamp", 0) or 0)
    completed = 0
    for debuff in duo.get("activeDebuffs", []):
        if match.get("matchId") in debuff.get("excludedMatchIds", []):
            continue
        if debuff.get("status") != "ACTIVE" or debuff.get("resolved"):
            continue
        assigned_ms = int(debuff.get("assignedAtEpochMs", 0) or 0)
        if assigned_ms and (not game_start_ms or game_start_ms < assigned_ms):
            continue
        penalty = debuff.get("penalty", {})
        base_id = penalty.get("baseId") or penalty.get("id")
        scope = debuff.get("scope") or penalty.get("scope") or "ONE"
        req = debuff.get("requirements", {})
        results = {}
        flash_evidence = {}
        for player_key in ("player1", "player2"):
            stats = match.get(f"{player_key}Stats") or {}
            if base_id == "autofill":
                actual, primary = stats.get("position"), req.get("mainRoles", {}).get(player_key)
                results[player_key] = actual in VALID_MAIN_ROLES and primary in VALID_MAIN_ROLES and actual != primary
                if "randomPositions" in req:
                    results[player_key] = results[player_key] and actual == req["randomPositions"].get(player_key)
            elif base_id == "no_main_champion":
                forbidden = req.get("favoriteChampions", {}).get(player_key, [])
                results[player_key] = bool(forbidden) and bool(stats.get("championName")) and stats.get("championName") not in forbidden
            elif base_id == "random_champion":
                assigned = req.get("randomChampions", {}).get(player_key)
                results[player_key] = bool(assigned) and stats.get("championName") == assigned
            elif base_id == "no_flash":
                spells = stats.get("summonerSpellIds") or []
                results[player_key] = len(spells) == 2 and all(spells) and 4 not in spells
            elif base_id == "swap_flash":
                baseline = req.get("flashBaselines", {}).get(player_key) or {}
                owner = duo.get(player_key) or {}
                if len(player_accounts.accounts(owner)) > 1:
                    source = player_accounts.account_for_stats(owner, stats)
                    baseline = player_flash_baseline(source or {}) or {}
                flash_evidence[player_key] = copy.deepcopy(baseline)
                slot = baseline.get("slot")
                spells = stats.get("summonerSpellIds") or []
                results[player_key] = bool(
                    slot in (1, 2) and baseline.get("account", {}).get("puuid") == stats.get("puuid")
                    and stats.get("puuid") and baseline.get("gameStartTimestamp", 0) > 0
                    and game_start_ms > baseline["gameStartTimestamp"]
                    and match.get("matchId") != baseline.get("matchId")
                    and len(spells) == 2 and all(spells) and spells.count(4) == 1 and spells[2 - slot] == 4)
        relevant = [results.get("player1") is True, results.get("player2") is True]
        if scope == "ONE" and ("assignedPlayer" in req or req.get("assignmentVersion", 0) >= 2):
            assigned_player = req.get("assignedPlayer")
            passed = penalty_player_matches(duo, match, req) and results.get(assigned_player) is True
        elif scope == "ONE":
            # Historical penalties without a selected player retain their published rule.
            passed = base_id != "random_champion" and any(relevant)
        else:
            passed = scope == "BOTH" and all(relevant)
        if passed:
            debuff["status"] = "COMPLETED"
            debuff["resolved"] = True
            debuff["resolvedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            debuff["resolvedByMatchId"] = match.get("matchId")
            debuff["evidence"] = {"players": results, "matchId": match.get("matchId"),
                                  "assignedPlayer": req.get("assignedPlayer"),
                                  "assignedAccount": copy.deepcopy(req.get("assignedAccount"))}
            if base_id == "autofill" and "randomPositions" in req:
                debuff["evidence"]["randomPositions"] = copy.deepcopy(req["randomPositions"])
            if base_id == "swap_flash":
                debuff["evidence"]["flashBaselines"] = {key: value for key, value in flash_evidence.items() if key in req.get("flashAccounts", req.get("flashBaselines", {}))}
                debuff["evidence"]["summonerSpellIds"] = {key: list((match.get(f"{key}Stats") or {}).get("summonerSpellIds") or []) for key in req.get("flashBaselines", {})}
            completed += 1
    return completed

def calculate_player_insights(duo):
    """Recalculate champion and position summaries from enriched, non-test matches."""
    participant_roles.update_roles(duo)
    insights = {}
    for player_key, stats_key in (("player1", "player1Stats"), ("player2", "player2Stats")):
        champion_totals = {}
        games_analyzed = 0
        totals = {"kills": 0, "deaths": 0, "assists": 0}
        best_match = None

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

            kills, deaths, assists = (int(stats.get(key, 0) or 0) for key in ("kills", "deaths", "assists"))
            candidate = {
                "matchId": match.get("matchId"), "date": match.get("date", ""),
                "result": ("WIN" if stats["win"] else "LOSS") if "win" in stats else match.get("result", ""),
                "championName": normalize_champion_name(stats.get("championName")),
                "position": stats.get("position", "UNKNOWN"),
                "kills": kills, "deaths": deaths, "assists": assists,
                "kda": (kills + assists) / max(1, deaths)
            }
            def best_key(item):
                return (item["kda"], item["kills"] + item["assists"], -item["deaths"], item["date"])
            if best_match is None or best_key(candidate) > best_key(best_match):
                best_match = candidate

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

        top_champion = None
        if champion_totals:
            top_champion = sorted(champion_totals.values(), key=lambda item: (-item["games"], item["name"]))[0]
            top_champion["winrate"] = round((top_champion["wins"] / top_champion["games"]) * 100)
            top_champion["kda"] = round(
                (top_champion["kills"] + top_champion["assists"]) / max(1, top_champion["deaths"]), 2
            )

        most_played_position = None
        position_summary = participant_roles.role_summary(duo, player_key)
        if position_summary['position']:
            most_played_position = {"position": position_summary['position'], "games": position_summary['games']}

        insights[player_key] = {
            "gamesAnalyzed": games_analyzed,
            "bestMatch": best_match,
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
    """Award distinct team achievements once, including across syncs and backfills."""
    history = sort_history_chronologically(duo.get("history", []))
    duo["history"] = history
    streak = 0
    for match in history:
        if match.get("result") != "WIN":
            break
        streak += 1
    duo["streak"] = streak
    pending_wins = []
    legacy_wins = 0
    for match in reversed(history):
        # Seed the ledger from the former flags without awarding them again.
        if "shellRewardIds" not in match:
            previous = []
            if match.get("processedForPenta"):
                previous.append("penta")
            if match.get("result") == "WIN" and match.get("processedForShell"):
                legacy_wins += 1
                if legacy_wins % SHELL_WIN_STREAK == 0:
                    previous.append("streak")
            else:
                legacy_wins = 0
            match["shellRewardIds"] = previous
        else:
            legacy_wins = 0
        rewards = match["shellRewardIds"]
        evaluated = match.setdefault("shellRewardsEvaluated", list(rewards))
        candidates = []
        if match.get("result") == "WIN" and not match.get("processedForShell"):
            pending_wins.append(match)
            if len(pending_wins) == SHELL_WIN_STREAK:
                for win in pending_wins:
                    win["processedForShell"] = True
                pending_wins = []
                candidates.append("streak")
        else:
            pending_wins = []
        if match.get("pentaKill"):
            candidates.append("penta")
            match["processedForPenta"] = True
        if not match.get("legacyShellRewards"):
            players = [match.get(key) for key in ("player1Stats", "player2Stats")]
            players = [p for p in players if isinstance(p, dict)]
            individual = {rule for p in players for rule in individual_shell_criteria(p)}
            candidates.extend(rule for rule in ('kills', 'assists', 'perfect') if rule in individual)
        for rule in candidates:
            if rule in evaluated:
                continue
            evaluated.append(rule)
            if len(rewards) >= MAX_SHELLS_PER_MATCH:
                continue
            rewards.append(rule)
            duo["shellsEarnedTotal"] = duo.get("shellsEarnedTotal", 0) + 1
            match.setdefault("shellRewardCredits", {})[rule] = duo.get("blueShells", 0) < MAX_SHELLS_INVENTORY
            if duo.get("blueShells", 0) < MAX_SHELLS_INVENTORY:
                duo["blueShells"] = duo.get("blueShells", 0) + 1


def merge_riot_result(original, scanned):
    """Merge only Riot-owned fields; inventory and penalties use the latest state."""
    with db_lock:
        current = load_db()
        last_api_success = scanned.get("lastRiotApiSuccessAt")
        if last_api_success and last_api_success > current.get("lastRiotApiSuccessAt", ""):
            current["lastRiotApiSuccessAt"] = last_api_success
        originals = {d["id"]: d for d in original.get("duos", [])}
        scanned_by_id = {d["id"]: d for d in scanned.get("duos", [])}
        for duo in current.get("duos", []):
            old, incoming = originals.get(duo["id"]), scanned_by_id.get(duo["id"])
            if not old or not incoming:
                continue
            # An account edited during a network request invalidates that result.
            if any((duo.get(k) or {}).get(f) != (old.get(k) or {}).get(f)
                   for k in ("player1", "player2") for f in ("name", "tag")) or any(
                   player_accounts.configuration(duo.get(k) or {}) != player_accounts.configuration(old.get(k) or {})
                   for k in ("player1", "player2")):
                continue
            for field in ("tier", "division", "lp", "wins", "losses", "initialTotalLp"):
                if field in incoming and duo.get(field) == old.get(field):
                    duo[field] = incoming[field]
            if "tier" in duo:
                duo["netLp"] = calc_total_lp(duo.get("tier"), duo.get("division"), duo.get("lp")) - duo.get("initialTotalLp", 0)
            if incoming.get("rankObservedAt", 0) > duo.get("rankObservedAt", 0) and all(duo.get(f) == incoming.get(f) for f in ("tier", "division", "lp", "wins", "losses")):
                duo["rankObservedAt"] = incoming["rankObservedAt"]
                record_elo(duo, calc_total_lp(duo.get("tier"), duo.get("division"), duo.get("lp")), incoming["rankObservedAt"])
            for key in ("player1", "player2"):
                if not duo.get(key):
                    continue
                for field in ("puuid", "avatar", "rank", "flashBaseline", "accounts"):
                    if field in (incoming.get(key) or {}) and duo[key].get(field) == (old.get(key) or {}).get(field):
                        duo[key][field] = incoming[key][field]
                rank = duo[key].get("rank") or {}
                incoming_rank = (incoming.get(key) or {}).get("rank") or {}
                if rank.get("observedAt") and rank == incoming_rank:
                    record_player_elo(duo[key], calc_total_lp(rank.get("tier"), rank.get("division"), rank.get("lp")), rank["observedAt"])
                    if len(duo[key].get("accounts", [])) == 1:
                        duo[key]["accounts"][0]["eloHistory"] = copy.deepcopy(duo[key].get("eloHistory", []))
            excluded = riot_match_policy.merge_exclusions(duo, incoming, old)
            duo["excludedRiotMatches"] = excluded
            matches = {m["matchId"]: m for m in duo.get("history", []) if m.get("matchId") and m["matchId"] not in excluded}
            unkeyed = [m for m in duo.get("history", []) if not m.get("matchId")]
            for match in incoming.get("history", []):
                mid = match.get("matchId")
                if not mid:
                    continue
                if mid in excluded:
                    continue
                existing = matches.get(mid, {})
                merged = {**existing, **copy.deepcopy(match)}
                for flag in ("processedForShell", "processedForPenta", "shellRewardIds", "shellRewardsEvaluated", "shellRewardCredits", "legacyShellRewards"):
                    if flag in existing:
                        merged[flag] = existing[flag]
                matches[mid] = merged
            duo["history"] = sort_history_chronologically(list(matches.values()) + unkeyed)
            if incoming.get("riotMatchDiscovery") and duo.get("riotMatchDiscovery") == old.get("riotMatchDiscovery"):
                duo["riotMatchDiscovery"] = copy.deepcopy(incoming["riotMatchDiscovery"])
                known_ids = {m.get("matchId") for m in duo["history"] if not m.get("isTest")} | set(excluded)
                duo["riotMatchDiscovery"]["pendingMatchIds"] = [mid for mid in duo["riotMatchDiscovery"]["pendingMatchIds"] if mid not in known_ids]
            # Apply the same date rule to stored or concurrently scanned evidence
            # before it can contribute to rewards, penalties or aggregate stats.
            riot_match_policy.prune_history(duo)
            riot_match_policy.prune_duo_history(duo)
            # History can arrive after the roulette draw. Resolve only empty
            # references before evaluating it, preserving existing player draws.
            for debuff in fill_pending_penalty_favorites(duo) + fill_pending_flash_baselines(duo) + fill_pending_penalty_roles(duo):
                source_id = debuff.get("sourceShellId")
                if source_id:
                    for attack in current.get("shellAttacks", []):
                        if attack.get("id") == source_id:
                            attack["requirements"] = copy.deepcopy(debuff["requirements"])
                    for event in current.get("events", []):
                        if event.get("type") == "SHELL_SPUN" and event.get("shellAttackId") == source_id:
                            event["requirements"] = copy.deepcopy(debuff["requirements"])
            # Oldest first makes the first qualifying match the recorded evidence.
            for match in reversed(duo["history"]):
                evaluate_active_penalties(duo, match)
            update_duo_shells(duo)
            update_duo_current_streak(duo)
            calculate_player_insights(duo)
            calculate_duo_best_match(duo)
            update_stats_backfill_status(duo, include_timestamp=True)
            update_match_details_backfill(duo)
        pickem_service.capture_rankings(current)
        weekly_summary.maintain(current, refresh=True)
        save_db(current)
        return sum(int(m.get("statsVersion", 0) or 0) < 2 or needs_match_details(m) or riot_match_policy.needs_pair_validation(d, m)
                   for d in current.get("duos", []) for m in d.get("history", []) if not m.get("isTest"))


def riot_open(request, timeout=8):
    """Retry short transient failures; long rate limits are left for the next job."""
    for attempt in range(3):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            if attempt == 2 or error.code not in (429, 500, 502, 503, 504):
                raise
            try:
                delay = float(error.headers.get("Retry-After", 1 + attempt))
            except (ValueError, TypeError, AttributeError):
                delay = 1 + attempt
            if delay > 30:
                raise
            time.sleep(max(0.2, delay))


def solo_rank_snapshot(entries):
    """A confirmed Solo/Duo rank; an empty successful response means unranked."""
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise ValueError("Invalid league response")
    entry = next((item for item in entries if item.get("queueType") == "RANKED_SOLO_5x5"), None)
    if entry is None:
        return {"tier": "Unranked", "division": "", "lp": 0, "observedAt": time.time()}
    return {"tier": str(entry["tier"]).capitalize(), "division": str(entry.get("rank", "")),
            "lp": int(entry["leaguePoints"]), "wins": int(entry.get("wins", 0)),
            "losses": int(entry.get("losses", 0)), "observedAt": time.time()}


def discover_riot_matches(duo, puuid, fetch_json, min_timestamp):
    """Discover new IDs while retaining every previously discovered import gap."""
    min_timestamp = max(min_timestamp, riot_match_policy.MIN_START_TIMESTAMP)
    player = duo.get("player1") or {}
    account = [str(player.get("name", "")).strip().casefold(),
               str(player.get("tag") or "EUW").strip().casefold()]
    previous = duo.get("riotMatchDiscovery") or {}
    if not isinstance(previous, dict) or previous.get("version") != 1 or previous.get("account") != account:
        previous = {}
    boundary = previous.get("latestMatchId")
    known = {m["matchId"] for m in duo.get("history", [])
             if isinstance(m, dict) and m.get("matchId") and not m.get("isTest")}
    known.update(duo.get("excludedRiotMatches", {}))
    discovered = []
    seen = set()
    latest = boundary
    offset = 0
    while True:
        url = (f"https://europe.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
               f"?queue=420&start={offset}&count=100&startTime={min_timestamp}")
        page = fetch_json(url)
        if not isinstance(page, list) or any(not isinstance(mid, str) or not mid for mid in page):
            raise ValueError("Riot devolvió una lista de partidas no válida.")
        if offset == 0 and page:
            latest = page[0]
        if page and not any(mid not in seen for mid in page):
            raise ValueError("Riot repitió la página de partidas; no se ha avanzado el historial.")
        seen.update(page)
        discovered.extend(page)
        # Only an earlier successful discovery is a safe boundary: existing history
        # alone may have holes from failed details or the per-sync import budget.
        if boundary in page or len(page) < 100:
            break
        offset += 100
        time.sleep(0.2)
    pending = [mid for mid in dict.fromkeys(discovered + previous.get("pendingMatchIds", [])) if mid not in known]
    return {"version": 1, "account": account, "latestMatchId": latest, "pendingMatchIds": pending}


@single_sync(riot_sync_lock)
def sync_riot_data():
    scan_started = time.time()
    db = load_db()
    original = copy.deepcopy(db)
    failures = 0
    failure_reasons = {}
    pending_imports = 0
    api_key = get_riot_api_key()
    if not api_key:
        safe_print("[Riot Sync] No API key provided.")
        return {"success": False, "error": "Clave de Riot no configurada."}

    headers = {
        "X-Riot-Token": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    updated = False
    response_cache = {}

    def record_failure(error):
        nonlocal failures
        failures += 1
        if isinstance(error, urllib.error.HTTPError):
            reason = f"HTTP {error.code}"
        elif isinstance(error, (urllib.error.URLError, TimeoutError)):
            reason = "error de conexión"
        else:
            reason = "respuesta o datos no válidos"
        failure_reasons[reason] = failure_reasons.get(reason, 0) + 1

    def fetch_json(url):
        # Shared matches/profiles are requested once per job, never across jobs.
        # Failed requests are not cached so a later request can still recover.
        if url not in response_cache:
            request = urllib.request.Request(url, headers=headers)
            with riot_open(request, timeout=8) as response:
                response_cache[url] = json.loads(response.read().decode("utf-8"))
            db["lastRiotApiSuccessAt"] = utc_now()
        return copy.deepcopy(response_cache[url])

    for duo in db.get("duos", []):
        try:
            if any(len(player_accounts.accounts(duo.get(k) or {})) > 1 for k in ("player1", "player2")):
                scanned_duo = copy.deepcopy(duo)
                pending_imports += riot_accounts_sync.sync_team(scanned_duo, fetch_json, record_failure, sys.modules[__name__])
                player_accounts.validate_ownership([d for d in db.get("duos", []) if d["id"] != duo["id"]] + [scanned_duo])
                duo.clear()
                duo.update(scanned_duo)
                updated = True
                continue
            p1_name = duo["player1"]["name"]
            p1_tag = duo["player1"].get("tag", "EUW")
            puuid1 = duo["player1"].get("puuid")
            puuid2 = duo.get("player2", {}).get("puuid") if duo.get("player2") else None
            resolved_accounts = {'player1': False, 'player2': False}

            # 1. Refresh PUUIDs on every sync. Riot can rotate encrypted PUUIDs,
            # so a permanently cached value may start returning "Exception decrypting".
            if p1_name and p1_tag:
                try:
                    url_acc1 = f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{urllib.parse.quote(p1_name)}/{urllib.parse.quote(p1_tag)}"
                    acc_data1 = fetch_json(url_acc1)
                    puuid1 = acc_data1.get("puuid")
                    if puuid1:
                        player_accounts.remember_puuid(duo['player1'], puuid1)
                        for account in duo['player1'].get('accounts', []):
                            player_accounts.remember_puuid(account, puuid1)
                        resolved_accounts['player1'] = True
                        updated = True
                except Exception as ex_p1:
                    record_failure(ex_p1)
                    safe_print(f"[Riot Sync PUUID P1 Error] {p1_name}: {ex_p1}")

            if duo.get("player2") and duo["player2"].get("name"):
                try:
                    p2_name = duo["player2"]["name"]
                    p2_tag = duo["player2"].get("tag", "EUW")
                    url_acc2 = f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{urllib.parse.quote(p2_name)}/{urllib.parse.quote(p2_tag)}"
                    acc_data2 = fetch_json(url_acc2)
                    puuid2 = acc_data2.get("puuid")
                    if puuid2:
                        player_accounts.remember_puuid(duo['player2'], puuid2)
                        for account in duo['player2'].get('accounts', []):
                            player_accounts.remember_puuid(account, puuid2)
                        resolved_accounts['player2'] = True
                        updated = True
                except Exception as ex_p2:
                    record_failure(ex_p2)
                    safe_print(f"[Riot Sync PUUID P2 Error] {ex_p2}")

            # Each participant has an independent Solo/Duo rank for the public table.
            if puuid2 and duo.get("player2") and duo["player2"].get("name"):
                try:
                    url_lea2 = f"https://euw1.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid2}"
                    entries2 = fetch_json(url_lea2)
                    duo["player2"]["rank"] = solo_rank_snapshot(entries2)
                    updated = True
                except Exception as error:
                    record_failure(error)
                    safe_print(f"[Riot Sync League P2 Error] {error}")

            if not puuid1:
                continue

            # 2. Fetch Profile Icons if default
            if puuid1 and duo.get("player1") and (not duo["player1"].get("avatar") or duo["player1"].get("avatar", "").rsplit("/", 1)[-1] == "29.png"):
                try:
                    url_m1 = f"https://europe.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid1}/ids?count=1"
                    m1_ids = fetch_json(url_m1)
                    if m1_ids:
                        url_d1 = f"https://europe.api.riotgames.com/lol/match/v5/matches/{m1_ids[0]}"
                        md1 = fetch_json(url_d1)
                        for p in md1.get("info", {}).get("participants", []):
                            if p.get("puuid") == puuid1 and p.get("profileIcon"):
                                icon_id1 = p.get("profileIcon")
                                duo["player1"]["avatar"] = f"https://ddragon.leagueoflegends.com/cdn/15.3.1/img/profileicon/{icon_id1}.png"
                                updated = True
                                break
                except Exception:
                    pass

            if puuid2 and duo.get("player2") and (not duo["player2"].get("avatar") or duo["player2"].get("avatar", "").rsplit("/", 1)[-1] == "1.png"):
                try:
                    url_m2 = f"https://europe.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid2}/ids?count=1"
                    m2_ids = fetch_json(url_m2)
                    if m2_ids:
                        url_d2 = f"https://europe.api.riotgames.com/lol/match/v5/matches/{m2_ids[0]}"
                        md2 = fetch_json(url_d2)
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
                entries = fetch_json(url_lea1)
                duo["player1"]["rank"] = solo_rank_snapshot(entries)
                updated = True
                for entry in entries:
                    if entry.get("queueType") == "RANKED_SOLO_5x5":
                        duo["tier"] = entry.get("tier", duo["tier"]).capitalize()
                        duo["division"] = entry.get("rank", duo["division"])
                        duo["lp"] = entry.get("leaguePoints", duo["lp"])
                        duo["wins"] = entry.get("wins", duo["wins"])
                        duo["losses"] = entry.get("losses", duo["losses"])

                        duo["rankObservedAt"] = duo["player1"]["rank"]["observedAt"]
                        current_total_lp = calc_total_lp(duo["tier"], duo["division"], duo["lp"])
                        initial_total = duo.get("initialTotalLp", 0)
                        duo["netLp"] = current_total_lp - initial_total
                        updated = True
            except Exception as e:
                record_failure(e)
                safe_print(f"[Riot Sync League Error] {e}")

            # 4. Incremental Match-V5 fetch + progressive legacy backfill.
            riot_match_policy.prune_duo_history(duo)
            existing_history = duo.get("history", [])
            existing_by_id = {
                match.get("matchId"): match
                for match in existing_history
                if isinstance(match, dict) and match.get("matchId")
            }
            # Keep the existing date/queue filters. First discovery scans all pages;
            # subsequent jobs stop at the saved boundary and retry their saved gaps.
            minimum_start = riot_match_policy.MIN_START_TIMESTAMP
            discovery = discover_riot_matches(duo, puuid1, fetch_json, minimum_start)
            duo["riotMatchDiscovery"] = discovery
            new_match_ids = discovery["pendingMatchIds"]
            updated = True
            legacy_ids = [
                match.get("matchId")
                for match in existing_history
                if isinstance(match, dict)
                and not match.get("isTest")
                and match.get("matchId")
                and (int(match.get("statsVersion", 0) or 0) < 2 or not match.get("gameStartTimestamp") or needs_match_details(match)
                     or riot_match_policy.needs_pair_validation(duo, match))
            ]
            for match in existing_history:
                if riot_match_policy.needs_pair_validation(duo, match):
                    match['matchDetailsVersion'] = 0
            fetch_ids = list(dict.fromkeys(new_match_ids + legacy_ids + riot_match_policy.pair_rechecks(duo)))[:RIOT_MATCH_DETAIL_BATCH_PER_DUO]
            new_matches = []
            enriched_count = 0

            for mid in fetch_ids:
                try:
                    time.sleep(0.2)
                    url_detail = f"https://europe.api.riotgames.com/lol/match/v5/matches/{mid}"
                    mdetail = fetch_json(url_detail)
                    info = mdetail.get("info", {})
                    if riot_match_policy.match_timestamp_ms(info) is None:
                        raise ValueError("La partida no tiene fecha confirmada; se reintentará.")
                    if riot_match_policy.before_cutoff(info):
                        duo.setdefault("excludedRiotMatches", {})[mid] = riot_match_policy.exclusion(info)
                        existing_by_id.pop(mid, None)
                        existing_history = [m for m in existing_history if m.get("matchId") != mid]
                        continue
                    duration_sec = int(info.get("gameDuration", 0) or 0)
                    if info.get('queueId') is None:
                        raise ValueError('La partida no confirma el tipo de cola; se reintentará.')
                    if info['queueId'] != 420:
                        duo.setdefault('excludedRiotMatches', {})[mid] = {'reason': 'wrong_queue', 'queueId': info['queueId']}
                        existing_by_id.pop(mid, None)
                        existing_history = [m for m in existing_history if m.get('matchId') != mid]
                        continue
                    if 0 < duration_sec < MIN_RIOT_MATCH_DURATION_SECONDS:
                        duo.setdefault("excludedRiotMatches", {})[mid] = {
                            "reason": "duration_below_minimum", "durationSeconds": duration_sec,
                            "minimumDurationSeconds": MIN_RIOT_MATCH_DURATION_SECONDS
                        }
                        # Keep an exclusion instead of a retry gap or a counted match.
                        existing_by_id.pop(mid, None)
                        existing_history = [m for m in existing_history if m.get("matchId") != mid]
                        continue
                    mins, secs = divmod(duration_sec, 60)
                    game_end_ms = info.get("gameEndTimestamp") or info.get("gameStartTimestamp") or 0

                    participants = info.get('participants', [])
                    if not participants or not isinstance(participants, list) or any(not isinstance(p, dict) or not p.get('puuid') for p in participants):
                        raise ValueError('La partida no confirma sus participantes; se reintentará.')
                    found = {key: next((p for p in participants if uid and p.get('puuid') == uid), None)
                             for key, uid in (('player1', puuid1), ('player2', puuid2))}
                    reason = riot_match_policy.validate_pair(duo, found, resolved_accounts)
                    if reason:
                        riot_match_policy.exclude_pair(duo, mid, reason, existing_by_id.pop(mid, None))
                        existing_history = [m for m in existing_history if m.get('matchId') != mid]
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
                        match.update(copy.deepcopy((duo.get('excludedRiotMatches', {}).get(mid) or {}).get('match') or {}))

                    match["gameStartTimestamp"] = int(info.get("gameStartTimestamp", 0) or 0)
                    match["gameEndTimestamp"] = int(game_end_ms or 0)
                    p1_detail, p2_detail = enrich_match_record(match, info, puuid1, puuid2)
                    duo.get('excludedRiotMatches', {}).pop(mid, None)
                    record_flash_baselines(duo, match)
                    if (duo.get("player2") or {}).get("name") and not puuid2:
                        # Retry details once the second account can be identified.
                        match["matchDetailsVersion"] = 0
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
                    record_failure(ex_m)
                    safe_print(f"[Riot Sync Match Detail Error] {mid}: {ex_m}")

            discovery["pendingMatchIds"] = [mid for mid in new_match_ids if mid not in existing_by_id and mid not in duo.get("excludedRiotMatches", {})]
            discovery['pendingMatchIds'] = list(dict.fromkeys(discovery['pendingMatchIds'] + riot_match_policy.pair_rechecks(duo)))
            pending_imports += len(discovery["pendingMatchIds"])
            if new_matches:
                existing_history = new_matches + existing_history
            duo["history"] = sort_history_chronologically(existing_history)
            for key in ("player1", "player2"):
                player = duo.get(key) or {}
                if player.get("accounts"):
                    account = player["accounts"][0]
                    for field in ("puuid", "rank", "avatar", "flashBaseline"):
                        if field in player:
                            account[field] = copy.deepcopy(player[field])
            backfill_status = update_stats_backfill_status(duo, include_timestamp=True)
            update_match_details_backfill(duo)
            remaining_backfill = backfill_status["remaining"]
            if fetch_ids:
                safe_print(
                    f"[Riot Stats] {p1_name}: {len(new_matches)} nuevas, {enriched_count} enriquecidas, "
                    f"{remaining_backfill} pendientes."
                )

            safe_print(f"[Riot Sync Success] Updated {p1_name}#{p1_tag}: {duo['tier']} {duo['division']} ({duo['lp']} LP), History: {len(duo.get('history',[]))} matches, Shells: {duo.get('blueShells', 0)}")

        except Exception as e:
            record_failure(e)
            safe_print(f"[Riot API Sync Error] {e}")

    confirmed_api_call = db.get("lastRiotApiSuccessAt") != original.get("lastRiotApiSuccessAt")
    pending = merge_riot_result(original, db) if updated or confirmed_api_call else 0
    pending += pending_imports
    if not failures and not pending:
        with db_lock:
            current = load_db()
            if pickem_service.record_complete_sync(current, original, scan_started):
                save_db(current)
    error = None
    if failures:
        outcome = "parcial" if confirmed_api_call else "fallida"
        reasons = "; ".join(f"{reason}: {count}" for reason, count in sorted(failure_reasons.items()))
        error = (f"Sincronización {outcome}: {failures} consulta(s) fallida(s) ({reasons}). "
                 "Se conservan los últimos datos disponibles.")
    return {"success": failures == 0, "pending": pending,
            "error": error}

def public_trophies():
    with db_lock:
        db = load_db()
        if db.get("awardedTrophies"):
            return db["awardedTrophies"]
        end_date = db.get("config", {}).get("endDate")
        result = build_trophies(db.get("duos", []), end_date)
        deadline = deadline_timestamp(end_date)
        if deadline is not None and time.time() >= deadline and result.get('standingsReady', True):
            result["status"] = "awarded"
            result["awardedAt"] = time.time()
            db["awardedTrophies"] = result
            final_predictions.maintain(db)
            save_db(db)
        return result


def schedule_trophies():
    def loop():
        while True:
            try:
                public_trophies()
            except Exception as error:
                safe_print(f"[Trophies] {error}")
            time.sleep(15)
    threading.Thread(target=loop, daemon=True).start()


def schedule_clip_rewards():
    def loop():
        while True:
            delay = 30
            try:
                with db_lock:
                    # Settles overdue awards and prunes while no publication can intervene.
                    db = load_db()
                    board, changed = clips_service.board_for(db, CLIPS_PREVIEW)
                    if changed:
                        save_db(db)
                deadline = clips_service.board_closes_at(board) + (60 if board.get('weeklyAward') else 0)
                delay = max(0.1, min(30, deadline - time.time()))
            except Exception as error:
                safe_print(f"[Clips rewards] {error}")
            time.sleep(delay)
    threading.Thread(target=loop, daemon=True).start()


def schedule_sync():
    def loop():
        while True:
            time.sleep(300)  # Sincronización automática cada 5 minutos (300 seg)
            try:
                sync_jobs.start("riot", sync_riot_data)
            except Exception as error:
                safe_print(f"[Riot scheduler] {error}")

    t = threading.Thread(target=loop, daemon=True)
    t.start()

def schedule_twitch_sync():
    def loop():
        while True:
            try:
                sync_jobs.start("twitch", sync_twitch_live_status)
            except Exception as error:
                safe_print(f"[Twitch Sync Error] {error}")
            time.sleep(TWITCH_SYNC_INTERVAL)

    t = threading.Thread(target=loop, daemon=True)
    t.start()

class ReusableServer(ThreadingHTTPServer):
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

    def _send_bytes(self, content_bytes, content_type, code=200, headers=None):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        if not headers or 'Cache-Control' not in headers:
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        if not headers or 'Cache-Control' not in headers:
            self.send_header('Pragma', 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Content-Length', str(len(content_bytes)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content_bytes)

    def _send_json(self, data_obj, code=200, headers=None):
        body_bytes = json.dumps(pepazo_payload(data_obj), ensure_ascii=False).encode('utf-8')
        self._send_bytes(body_bytes, 'application/json; charset=utf-8', code, headers)

    def clips_visitor(self, cookie_name='pepes_clips_visitor'):
        try:
            cookies = SimpleCookie()
            cookies.load(self.headers.get('Cookie', ''))
            value = cookies.get(cookie_name)
            token = value.value if value else ''
            return token if re.fullmatch(r'[A-Za-z0-9_-]{43}', token) else None
        except CookieError:
            return None

    def clips_cookie(self, token, cookie_name='pepes_clips_visitor'):
        secure = self.headers.get('X-Forwarded-Proto', '').split(',')[0].strip() == 'https'
        return f'{cookie_name}={token}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax' + ('; Secure' if secure else '')

    def clips_origin_allowed(self):
        origin = self.headers.get('Origin')
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.scheme in ('http', 'https') and parsed.netloc == self.headers.get('Host')

    def team_cookie_token(self):
        return self.clips_visitor(remembered_sessions.COOKIE)

    def team_cookie(self, token='', clear=False):
        # Production is HTTPS (including behind Render's TLS proxy). Allow HTTP
        # only for loopback development; never weaken the cookie for public HTTP.
        host = urlparse('//' + self.headers.get('Host', '')).hostname
        secure = host not in ('localhost', '127.0.0.1', '::1') or self.headers.get('X-Forwarded-Proto', '').split(',')[0].strip() == 'https'
        return (f'{remembered_sessions.COOKIE}={token}; Path=/; Max-Age={0 if clear else remembered_sessions.LIFETIME}; '
                'HttpOnly; SameSite=Lax' + ('; Secure' if secure else ''))

    def authenticated_team(self, db, body_token=None):
        # Explicit invalid credentials must never silently become another team
        # through a cookie. OBS tokens are deliberately not accepted here.
        authorization = self.headers.get('Authorization', '')
        if authorization:
            team_id = session_team(authorization[7:], db) if authorization.startswith('Bearer ') else None
        elif body_token:
            team_id = session_team(body_token, db)
        else:
            team_id = remembered_sessions.team(db, self.team_cookie_token())
        return team_id if any(duo.get('id') == team_id for duo in db.get('duos', [])) else None

    def clips_team(self, db):
        return self.authenticated_team(db)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length < 0 or length > 1024 * 1024:
            raise ValueError("Invalid body length")
        body = json.loads(self.rfile.read(length).decode("utf-8") if length else "{}")
        if not isinstance(body, dict):
            raise ValueError("Expected JSON object")
        return body

    def stream_shell_notifications(self):
        authorization = self.headers.get("Authorization", "")
        token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        remembered = not authorization
        if remembered:
            token = self.team_cookie_token()
        # Read the revision first so a concurrent launch cannot be missed.
        with shell_notifications:
            revision = shell_notification_revision
        state = receiver_notification_state(token, remembered)
        if state is None:
            self._send_json({"success": False, "error": "Sesión caducada"}, 401)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.connection.settimeout(20)
        previous = None
        try:
            while True:
                if state is None:
                    self.wfile.write(b'event: expired\ndata: {}\n\n')
                    self.wfile.flush()
                    return
                payload = json.dumps(state, ensure_ascii=False)
                if payload != previous:
                    self.wfile.write(("data: " + payload + "\n\n").encode("utf-8"))
                    previous = payload
                else:
                    self.wfile.write(b': heartbeat\n\n')
                self.wfile.flush()
                with shell_notifications:
                    shell_notifications.wait_for(lambda: shell_notification_revision != revision, timeout=15)
                    revision = shell_notification_revision
                state = receiver_notification_state(token, remembered)
        except (OSError, StorageError):
            # Disconnection and temporary storage errors reconnect on the client.
            return

    @http_errors
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/overlay/effects':
            with db_lock:
                effects = overlay_effects.library(load_db())
            self._send_json({'effects': [effect for effect in effects if effect['active']]})
            return
        if path.startswith('/api/overlay/media/'):
            digest = path.removeprefix('/api/overlay/media/')
            with db_lock:
                db = load_db()
                known = overlay_effects.library(db) + overlay_effects.removed(db)
                exists = any(effect['id'] == digest and effect['kind'] == 'video' for effect in known)
            if not exists:
                self._send_json({'error': 'Vídeo no encontrado'}, 404)
                return
            payload = overlay_effects.media_bytes(digest, DB_FILE, remote_backend)
            if payload is None:
                self._send_json({'error': 'Vídeo no encontrado'}, 404)
                return
            headers = {'Cache-Control': 'public, max-age=31536000, immutable', 'Accept-Ranges': 'bytes'}
            requested = self.headers.get('Range')
            if requested:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
                if not match or not any(match.groups()):
                    self._send_bytes(b'', 'video/webm', 416, {'Content-Range': f'bytes */{len(payload)}'})
                    return
                left, right = match.groups()
                start = int(left) if left else max(0, len(payload) - int(right))
                end = min(int(right), len(payload)-1) if right and left else len(payload)-1
                if start > end or start >= len(payload):
                    self._send_bytes(b'', 'video/webm', 416, {'Content-Range': f'bytes */{len(payload)}'})
                    return
                headers['Content-Range'] = f'bytes {start}-{end}/{len(payload)}'
                self._send_bytes(payload[start:end+1], 'video/webm', 206, headers)
            else:
                self._send_bytes(payload, 'video/webm', headers=headers)
            return
        if path == '/api/shop':
            with db_lock:
                db = load_db()
                result = shop_service.public_shop(db, self.clips_team(db))
            self._send_json(result, headers={'Vary': 'Cookie, Authorization'})
            return
        if path == '/api/bets':
            offset, limit = page_args(parsed)
            view = urllib.parse.parse_qs(parsed.query).get('view', ['open'])[0]
            if view not in ('open', 'history'):
                self._send_json({'error':'Vista inválida.'}, 400)
                return
            with db_lock:
                db = load_db()
                result = betting_service.public_board(db, self.clips_team(db), offset, min(limit,12), view)
            self._send_json(result, headers={'Vary':'Cookie, Authorization'})
            return
        if path == '/api/pickem':
            visitor_token = self.clips_visitor('pepes_pickem_visitor')
            new_token = visitor_token is None
            visitor_token = visitor_token or secrets.token_urlsafe(32)
            selected_week = urllib.parse.parse_qs(parsed.query).get('week', [None])[0]
            with db_lock:
                db = load_db()
                _, changed = pickem_service.ensure_week(db)
                if changed: save_db(db)
                try:
                    result = pickem_service.public_board(db, self.clips_team(db), clips_service.visitor_hash(visitor_token), selected_week)
                except LookupError as error:
                    self._send_json({'error': str(error)}, 404)
                    return
            headers = {'Vary': 'Cookie, Authorization'}
            if new_token: headers['Set-Cookie'] = self.clips_cookie(visitor_token, 'pepes_pickem_visitor')
            self._send_json(result, headers=headers)
            return
        if path == '/api/final-predictions':
            visitor_token = self.clips_visitor('pepes_porra_visitor')
            new_token = visitor_token is None
            visitor_token = visitor_token or secrets.token_urlsafe(32)
            offset, limit = page_args(parsed)
            with db_lock:
                db = load_db()
                changed = final_predictions.ensure_board(db)
                changed = final_predictions.maintain(db) or changed
                if changed: save_db(db)
                result = final_predictions.public_board(db, self.clips_team(db), clips_service.visitor_hash(visitor_token), offset, min(limit, 6))
            headers = {'Vary': 'Cookie, Authorization'}
            if new_token: headers['Set-Cookie'] = self.clips_cookie(visitor_token, 'pepes_porra_visitor')
            self._send_json(result, headers=headers)
            return
        if path == '/api/tierlists':
            kind = urllib.parse.parse_qs(parsed.query).get('kind', ['teams'])[0]
            visitor_token = self.clips_visitor('pepes_tierlist_visitor')
            new_token = visitor_token is None
            visitor_token = visitor_token or secrets.token_urlsafe(32)
            offset, limit = page_args(parsed)
            with db_lock:
                db = load_db()
                result = tierlists_service.public_board(db, self.clips_team(db), clips_service.visitor_hash(visitor_token), offset, min(limit, 6), kind=kind)
            headers = {'Vary': 'Cookie, Authorization'}
            if new_token:
                headers['Set-Cookie'] = self.clips_cookie(visitor_token, 'pepes_tierlist_visitor')
            self._send_json(result, headers=headers)
            return
        if path == '/api/clips/comments':
            query = urllib.parse.parse_qs(parsed.query)
            offset, limit = page_args(parsed)
            try:
                with db_lock:
                    result = clips_service.comment_page(load_db(), query.get('week', [''])[0], query.get('clipId', [''])[0], offset, min(limit, 10))
            except LookupError as error:
                self._send_json({'error':str(error)}, 404)
                return
            self._send_json(result)
            return
        if path == '/api/clips':
            token = self.clips_visitor()
            new_token = token is None
            token = token or secrets.token_urlsafe(32)
            with db_lock:
                db = load_db()
                selected_week = urllib.parse.parse_qs(parsed.query).get('week', [None])[0]
                try:
                    result, changed = clips_service.public_payload(db, self.clips_team(db), CLIPS_PREVIEW,
                                                                  clips_service.visitor_hash(token), selected_week)
                except LookupError as error:
                    self._send_json({'error': str(error)}, 404)
                    return
                if changed:
                    save_db(db)
            headers = {'Vary': 'Cookie, Authorization'}
            if new_token:
                headers['Set-Cookie'] = self.clips_cookie(token)
            self._send_json(result, headers=headers)
            return
        if path == '/api/weekly-summary':
            week = urllib.parse.parse_qs(parsed.query).get('week', [None])[0]
            with db_lock:
                db = load_db()
                try:
                    result = weekly_summary.public_payload(db, week)
                except LookupError as error:
                    self._send_json({'error': str(error)}, 404)
                    return
            self._send_json(result)
            return
        if path == '/api/player/events':
            self.stream_shell_notifications()
            return
        if path == '/api/duos':
            self._send_json(public_duo_summaries())
            return
        elif path == '/api/stats/progression':
            self._send_json(stat_progression.build_progression(load_db(), MIN_RIOT_MATCH_DURATION_SECONDS))
            return
        elif path == '/api/champions':
            self._send_json(champions_service.build_album(load_db(), MIN_RIOT_MATCH_DURATION_SECONDS))
            return
        elif path == '/api/sync/status':
            status = sync_jobs.snapshot()
            db = load_db()
            status.setdefault("riot", {})["lastApiSuccessAt"] = db.get("lastRiotApiSuccessAt")
            raw_webhook = os.environ.get("DISCORD_LIVE_WEBHOOK_URL", "").strip()
            status["discord"] = {"configured": bool(raw_webhook), **db.get("discordLiveStatus", {})}
            if raw_webhook and not discord_live.webhook_url(raw_webhook):
                status["discord"]["error"] = "DISCORD_LIVE_WEBHOOK_URL no es un webhook válido de Discord."
            self._send_json(status)
            return
        elif path.startswith('/api/duos/') and path.endswith('/history'):
            duo_id = urllib.parse.unquote(path.split('/')[3])
            duo = next((d for d in load_db().get("duos", []) if d.get("id") == duo_id), None)
            if not duo:
                self._send_json({"error": "Equipo no encontrado"}, 404)
                return
            offset, limit = page_args(parsed)
            history = sort_history_chronologically(duo.get("history", []))
            self._send_json({"matches": history[offset:offset + limit], "total": len(history), "offset": offset, "limit": limit})
            return
        elif path == '/api/trophies':
            self._send_json(public_trophies())
            return
        elif path == '/api/config':
            db = load_db()
            config = public_config(db.get("config", {}))
            config["shellRewardRules"] = shell_reward_rules()
            config["penaltyCatalog"] = [
                {key: item[key] for key in ("id", "name", "icon", "desc")}
                for item in PENALTY_CATALOG
            ]
            self._send_json(config)
            return
        elif path == '/api/events':
            db = load_db()
            offset, limit = page_args(parsed)
            events = db.get("events", [])
            event_type = urllib.parse.parse_qs(parsed.query).get("type", [None])[0]
            if event_type:
                events = [event for event in events if event.get("type") == event_type]
            self._send_json(events[offset:offset + limit])
            return

        # The repository root is never a public directory.
        public_files = {"stat-progression.js", "resumen.html", "resumen.js", "resumen.css", "roulette.html", "roulette.css", "roulette-core.js", "roulette-window.js", "roulette-popup.js", "clips.html", "clips.css", "clips.js", "torneo.html", "torneo.js", "index.html", "admin.html", "player.html", "app.js", "match-history.js", "admin.js", "player.js", "data.js", "alerts.js", "styles.css"}
        public_files.update({'tierlist.html', 'tierlist.js', 'tierlist.css', 'pickem.html', 'pickem.js', 'pickem.css', 'premios.html', 'premios.js', 'navigation.js'})
        public_files.update({'porra.html', 'porra.js', 'porra.css'})
        public_files.update({'overlay.html', 'overlay.js', 'overlay.css', 'overlay-pepazo.mp3', 'admin-overlay.js'})
        public_files.update({'campeones.html', 'campeones.js', 'campeones.css'})
        public_files.update({'favicon.svg', 'favicon.ico'})
        public_files.update({'apuestas.html', 'apuestas.js', 'apuestas.css'})
        public_files.update({'tienda.html', 'tienda.js', 'tienda.css'})
        shop_assets = {'assets/shop/pepe-shop.webp', 'assets/shop/pepazo.webp'}
        tierlist_assets = {item['image'].lstrip('/') for item in tierlists_service.ALL_ITEMS}
        filename = "index.html" if path == "/" else path.removeprefix("/")
        if filename not in public_files and filename not in tierlist_assets and filename not in shop_assets:
            self._send_json({"error": "File Not Found"}, 404)
            return
        filepath = os.path.realpath(os.path.join(BASE_DIR, filename))
        expected_directory = os.path.join(BASE_DIR, 'assets', 'tierlist') if filename in tierlist_assets else BASE_DIR
        if filename in shop_assets:
            expected_directory = os.path.join(BASE_DIR, 'assets', 'shop')
        if os.path.dirname(filepath) != expected_directory or not os.path.isfile(filepath):
            self._send_json({"error": "File Not Found"}, 404)
            return
        with open(filepath, "rb") as handle:
            content = handle.read()
        self._send_bytes(content, mimetypes.guess_type(filename)[0] or "application/octet-stream")

    def send_discord_test(self, path, data):
        # Authenticate and capture only the delivery inputs while holding the lock.
        # Sending never saves this snapshot, so concurrent edits cannot be overwritten.
        with db_lock:
            db = load_db()
            if not verify_admin_pin(db, data.get("authPin", "")):
                self._send_json({"success": False, "error": "PIN incorrecto"}, 401)
                return
            url = discord_live.webhook_url(os.environ.get("DISCORD_LIVE_WEBHOOK_URL", ""))
            if not url:
                self._send_json({"success": False, "error": "Configura un webhook válido en DISCORD_LIVE_WEBHOOK_URL."}, 400)
                return
            payload = {
                "content": "🔔 **Mensaje de prueba · Pepes Krisis Duo Q**\nLa conexión de la web con este canal de Discord funciona.\nEsto es una prueba; no anuncia ningún directo real.",
                "allowed_mentions": {"parse": []}
            }

        # Discord can take up to ten seconds; unrelated reads/writes remain available.
        result = discord_live.send_payload(url, payload)
        if result.get("success"):
            self._send_json({"success": True})
        else:
            fallback = "Error al enviar el mensaje de prueba a Discord."
            self._send_json({"success": False, "error": result.get("error", fallback)}, 502)

    def upload_overlay(self):
        if not self.clips_origin_allowed():
            self._send_json({'error': 'Origen no permitido'}, 403)
            return
        pin = self.headers.get('X-Admin-Pin', '')
        with db_lock:
            valid = verify_admin_pin(load_db(), pin)
        if not valid:
            self._send_json({'error': 'PIN incorrecto'}, 401)
            return
        length = int(self.headers.get('Content-Length', '0'))
        if not 32 <= length <= overlay_effects.MAX_BYTES:
            self._send_json({'error': 'El vídeo debe ocupar como máximo 12 MiB'}, 413)
            return
        if self.headers.get('Content-Type', '').split(';')[0] != 'video/webm':
            self._send_json({'error': 'Selecciona un vídeo WebM'}, 400)
            return
        self.connection.settimeout(30)
        blob = self.rfile.read(length)  # Never hold the tournament lock while receiving a file.
        try:
            if len(blob) != length:
                raise ValueError('El vídeo no se recibió completo.')
            effect = overlay_effects.validate_upload(urllib.parse.unquote(self.headers.get('X-Overlay-Name', '')),
                                                     self.headers.get('X-Overlay-Duration'), blob)
            with db_lock:
                db = load_db()
                if not verify_admin_pin(db, pin):
                    self._send_json({'error': 'PIN incorrecto'}, 401)
                    return
                overlay_effects.add(db, effect)
                # Store immutable bytes first; a later catalogue save failure leaves only an unreferenced blob.
                overlay_effects.media_bytes(effect['id'], DB_FILE, remote_backend, blob)
                save_db(db)
                effects = overlay_effects.library(db)
        except ValueError as error:
            self._send_json({'error': str(error)}, 400)
            return
        self._send_json({'success': True, 'effects': effects})

    @http_errors
    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith('/api/player/') or self.team_cookie_token():
            if not self.clips_origin_allowed() or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                self._send_json({'success': False, 'error': 'Origen no permitido.'}, 403)
                return
            if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json' and path != '/api/admin/overlay/upload':
                self._send_json({'success': False, 'error': 'Se requiere JSON.'}, 415)
                return
        if path == '/api/admin/overlay/upload':
            self.upload_overlay()
            return
        if path == '/api/discord/test':
            self.send_discord_test(path, self.read_body())
            return
        self._handle_serialized_post()

    @serialized_mutation
    def _handle_serialized_post(self):
        parsed = urlparse(self.path)
        data = self.read_body()
        db = load_db()

        if parsed.path == '/api/shop':
            if not self.clips_origin_allowed():
                self._send_json({'error': 'Origen no permitido.'}, 403)
                return
            team_id = self.clips_team(db)
            if not team_id:
                self._send_json({'error': 'Inicia sesión con tu equipo para comprar.'}, 401)
                return
            try:
                receipt = shop_service.purchase(db, team_id, data)
            except FileExistsError as error:
                self._send_json({'error': str(error)}, 409)
                return
            except ValueError as error:
                self._send_json({'error': str(error)}, 400)
                return
            save_db(db)
            self._send_json({'success': True, 'purchase': receipt, **shop_service.public_shop(db, team_id)},
                            headers={'Vary': 'Cookie, Authorization'})
            return

        if parsed.path == '/api/bets':
            if not self.clips_origin_allowed():
                self._send_json({'error':'Origen no permitido.'},403)
                return
            team_id = self.clips_team(db)
            if not team_id:
                self._send_json({'error':'Inicia sesión con tu equipo para apostar.'},401)
                return
            try:
                bet_id = betting_service.participate(db, team_id, data)
            except FileExistsError as error:
                self._send_json({'error':str(error)},409)
                return
            except ValueError as error:
                self._send_json({'error':str(error)},400)
                return
            save_db(db)
            self._send_json({'success':True,'betId':bet_id,**betting_service.public_board(db,team_id)},
                            headers={'Vary':'Cookie, Authorization'})
            return

        if parsed.path == '/api/admin/overlay':
            if not self.clips_origin_allowed():
                self._send_json({'error': 'Origen no permitido'}, 403)
                return
            if not verify_admin_pin(db, str(data.get('authPin', '')).strip()):
                self._send_json({'error': 'PIN incorrecto'}, 401)
                return
            if data.get('action') == 'toggle':
                try:
                    overlay_effects.set_active(db, data.get('id'), data.get('active'))
                except ValueError as error:
                    self._send_json({'error': str(error)}, 400)
                    return
                save_db(db)
            elif data.get('action') in ('remove', 'restore'):
                try:
                    operation = overlay_effects.remove if data['action'] == 'remove' else overlay_effects.restore
                    operation(db, data.get('id'))
                except ValueError as error:
                    self._send_json({'error': str(error)}, 400)
                    return
                save_db(db)
            elif data.get('action', 'list') != 'list':
                self._send_json({'error': 'Acción inválida'}, 400)
                return
            self._send_json({'success': True, 'effects': overlay_effects.library(db),
                             'removedEffects': overlay_effects.removed(db)})
            return

        if parsed.path == '/api/admin/pickem':
            if not verify_admin_pin(db, str(data.get('authPin', '')).strip()):
                self._send_json({'success': False, 'error': 'PIN incorrecto'}, 401)
                return
            _, changed = pickem_service.ensure_week(db)
            if changed:
                save_db(db)
            try:
                board = pickem_service.admin_board(db, data.get('week') or None)
            except LookupError as error:
                self._send_json({'success': False, 'error': str(error)}, 404)
                return
            self._send_json({'success': True, **board})
            return

        if parsed.path == '/api/pickem':
            if not self.clips_origin_allowed():
                self._send_json({'error':'Origen no permitido.'}, 403)
                return
            team_id = self.clips_team(db)
            if not team_id:
                self._send_json({'error':'Inicia sesión con tu equipo para rellenar la quiniela.'}, 401)
                return
            visitor_token = self.clips_visitor('pepes_pickem_visitor')
            if not visitor_token:
                self._send_json({'error':'Activa las cookies y vuelve a cargar la página.'}, 400)
                return
            week, _ = pickem_service.ensure_week(db)
            if data.get('week') != week:
                self._send_json({'error':'La semana ha cambiado. Actualiza la quiniela.'}, 409)
                return
            try:
                _, changed = pickem_service.submit(db, team_id, clips_service.visitor_hash(visitor_token), data.get('categoryId'), data.get('optionId'), data.get('author',''))
            except FileExistsError as error:
                self._send_json({'error':str(error)}, 409)
                return
            except (ValueError,PermissionError) as error:
                self._send_json({'error':str(error)}, 400)
                return
            if changed: save_db(db)
            self._send_json({'success':True, **pickem_service.public_board(db, team_id, clips_service.visitor_hash(visitor_token))}, headers={'Vary':'Cookie, Authorization'})
            return

        if parsed.path == '/api/final-predictions':
            if not self.clips_origin_allowed():
                self._send_json({'error': 'Origen no permitido.'}, 403)
                return
            team_id = self.clips_team(db)
            if not team_id:
                self._send_json({'error': 'Inicia sesión con tu equipo para publicar.'}, 401)
                return
            visitor_token = self.clips_visitor('pepes_porra_visitor')
            if not visitor_token:
                self._send_json({'error': 'Activa las cookies y vuelve a cargar la página.'}, 400)
                return
            try:
                post, changed = final_predictions.publish(db, team_id, clips_service.visitor_hash(visitor_token), data.get('author', ''), data.get('order'))
            except FileExistsError as error:
                self._send_json({'error': str(error)}, 409)
                return
            if changed: save_db(db)
            self._send_json({'success': True, 'postId': post['id'], **final_predictions.public_board(db, team_id, clips_service.visitor_hash(visitor_token))}, headers={'Vary': 'Cookie, Authorization'})
            return
        if parsed.path == '/api/tierlists':
            if not self.clips_origin_allowed():
                self._send_json({'error': 'Origen no permitido.'}, 403)
                return
            team_id = self.clips_team(db)
            if not team_id:
                self._send_json({'error': 'Inicia sesión con tu equipo para publicar.'}, 401)
                return
            visitor_token = self.clips_visitor('pepes_tierlist_visitor')
            if not visitor_token:
                self._send_json({'error': 'Activa las cookies y vuelve a cargar la página.'}, 400)
                return
            try:
                post = tierlists_service.publish(db, team_id, clips_service.visitor_hash(visitor_token), data.get('author', ''), data.get('tiers'), kind=data.get('kind', 'teams'))
            except FileExistsError as error:
                self._send_json({'error': str(error)}, 409)
                return
            except ValueError as error:
                self._send_json({'error': str(error)}, 400)
                return
            save_db(db)
            self._send_json({'success': True, 'postId': post['id'], **tierlists_service.public_board(db, team_id, clips_service.visitor_hash(visitor_token), kind=post['kind'])})
            return

        if parsed.path in ('/api/clips/delete', '/api/clips/moderate'):
            if (not self.clips_origin_allowed() or self.headers.get('Sec-Fetch-Site') == 'cross-site'
                    or self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json'):
                self._send_json({'error': 'Solicitud no permitida. Usa JSON desde esta web.'}, 403)
                return
            admin = False
            if parsed.path == '/api/clips/moderate' or 'authPin' in data:
                admin = verify_admin_pin(db, str(data.get('authPin', '')).strip())
                if not admin:
                    self._send_json({'error': 'PIN de administrador incorrecto.'}, 401)
                    return
            token = self.clips_visitor()
            if not token and not admin:
                self._send_json({'error': 'Activa las cookies y recarga la página.'}, 401)
                return
            visitor = clips_service.visitor_hash(token) if token else None
            team_id = self.clips_team(db)
            try:
                if parsed.path == '/api/clips/delete':
                    changed = clips_service.remove_clip(db, data.get('week'), data.get('clipId'), visitor, team_id, admin)
                    if changed:
                        save_db(db)
                result, changed = clips_service.public_payload(db, team_id, CLIPS_PREVIEW, visitor, data.get('week'), admin=admin)
                if changed:
                    save_db(db)
            except PermissionError as error:
                self._send_json({'error': str(error)}, 403)
                return
            except LookupError as error:
                self._send_json({'error': str(error)}, 404)
                return
            self._send_json({'success': True, **result}, headers={'Vary': 'Cookie, Authorization'})
            return

        if parsed.path == '/api/clips/comments':
            if not self.clips_origin_allowed():
                self._send_json({'error':'Origen no permitido.'}, 403)
                return
            token = self.clips_visitor()
            if not token:
                self._send_json({'error':'Activa las cookies y recarga la página para comentar.'}, 401)
                return
            try:
                comment, changed = clips_service.add_comment(db, data.get('week'), data.get('clipId'), clips_service.visitor_hash(token),
                    data.get('name',''), data.get('text'), data.get('requestId'))
            except LookupError as error:
                self._send_json({'error':str(error)}, 404)
                return
            except clips_service.CommentRateLimit as error:
                self._send_json({'error':str(error)}, 429, headers={'Retry-After':str(error.retry_after)})
                return
            except ValueError as error:
                self._send_json({'error':str(error)}, 400)
                return
            except OverflowError as error:
                self._send_json({'error':str(error)}, 409)
                return
            if changed:
                save_db(db)
            self._send_json({'success':True, 'comment':clips_service.public_comment(comment),
                **clips_service.comment_page(db, data.get('week'), data.get('clipId'))})
            return

        if parsed.path in ('/api/clips', '/api/clips/like'):
            if not self.clips_origin_allowed():
                self._send_json({'error': 'Origen no permitido.'}, 403)
                return
            team_id = self.clips_team(db)
            if parsed.path == '/api/clips/like' and not team_id:
                self._send_json({'error': 'Inicia sesión con tu equipo para votar.'}, 401)
                return
            visitor_token = self.clips_visitor()
            if not visitor_token:
                self._send_json({'error': 'Activa las cookies y recarga la página para participar.'}, 401)
                return
            board, changed = clips_service.board_for(db, CLIPS_PREVIEW)
            requested_week = data.get('week') or urllib.parse.parse_qs(parsed.query).get('week', [None])[0]
            if requested_week and requested_week != board['week']:
                if changed: save_db(db)
                self._send_json({'error': 'Esta semana está archivada. No se puede publicar ni cambiar likes.'}, 409)
                return
            try:
                if parsed.path == '/api/clips/like':
                    changed = clips_service.set_like(board, data.get('clipId'), team_id, clips_service.visitor_hash(visitor_token), data.get('liked')) or changed
                else:
                    team = next((duo for duo in db.get('duos', []) if duo['id'] == data.get('teamId')), None)
                    clips_service.publish(board, data.get('title'), data.get('url'), team=team,
                                          visitor=clips_service.visitor_hash(visitor_token), uploader_team_id=team_id)
                    changed = True
            except LookupError as error:
                if changed:
                    save_db(db)
                self._send_json({'error': str(error)}, 404)
                return
            except (FileExistsError, OverflowError) as error:
                self._send_json({'error': str(error)}, 409)
                return
            if changed:
                save_db(db)
            result, _ = clips_service.public_payload(db, team_id, CLIPS_PREVIEW, clips_service.visitor_hash(visitor_token))
            self._send_json(result, headers={'Vary': 'Cookie, Authorization'})
            return

        if parsed.path == '/api/admin/login':
            entered_pin = str(data.get("pin", "")).strip()
            if not verify_admin_pin(db, entered_pin):
                self._send_json({"success": False, "error": "PIN incorrecto"}, 401)
                return

            self._send_json({"success": True, "config": admin_config_response(db), "penaltyCatalog": PENALTY_CATALOG, "duos": safe_duos_for_admin(db.get("duos", []))})

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
            if existing_duo:
                editable = {"teamName", "twitchUrl", "password", "discordWebhook", "discordRoleId"}
                submitted = data
                data = copy.deepcopy(existing_duo)
                data.update({key: submitted[key] for key in editable if key in submitted})
                for player_key in ("player1", "player2"):
                    if player_key in submitted:
                        data[player_key] = {**data.get(player_key, {}), **{key: value for key, value in submitted[player_key].items() if key in {"name", "tag", "displayName", "twitchUrl", "opggUrl"}}}
                        if any((data.get(player_key) or {}).get(field) != (existing_duo.get(player_key) or {}).get(field) for field in ("name", "tag")):
                            if (existing_duo.get(player_key) or {}).get("accounts"):
                                raise ValueError("Conserva la identidad del integrante y añade su nueva cuenta en Cuentas de LoL.")
                            data[player_key]["rank"] = None
                            data[player_key].pop("flashBaseline", None)
                            data[player_key].pop("puuid", None)
                            data[player_key]["eloHistory"] = []
                            data[player_key]["eloHistoryAccount"] = [str(data[player_key].get("name", "")).lower(), str(data[player_key].get("tag", "")).lower()]
            if not str(data.get("teamName", "")).strip():
                raise ValueError("Team name is required")

            if "discordWebhook" in data:
                raw_webhook = str(data.get("discordWebhook") or "").strip()
                if raw_webhook:
                    valid_wh = discord_shells.webhook_url(raw_webhook)
                    if not valid_wh:
                        self._send_json({"success": False, "error": "El webhook de Discord no es válido (debe empezar por https://discord.com/api/webhooks/...)"}, 400)
                        return
                    data["discordWebhook"] = valid_wh
                else:
                    data["discordWebhook"] = ""

            if "discordRoleId" in (submitted if existing_duo else data):
                role_id = str(data.get("discordRoleId") or "").strip()
                if role_id and not re.fullmatch(r"[0-9]{17,20}", role_id):
                    self._send_json({"success": False, "error": "Pega el ID numérico del rol de Discord (entre 17 y 20 dígitos), no su nombre."}, 400)
                    return
                data["discordRoleId"] = role_id

            for key in ("player1", "player2"):
                edits = copy.deepcopy((submitted if existing_duo else data).get(key) or {})
                if "accounts" in edits or "eloAccountId" in edits:
                    if not existing_duo:
                        data[key].pop("accounts", None)
                        data[key].pop("eloAccountId", None)
                    player_accounts.update_accounts(data.setdefault(key, {}), edits)
                    if key == "player1" and existing_duo and "initialTotalLp" in existing_duo:
                        data[key]["accounts"][0].setdefault("initialTotalLp", existing_duo["initialTotalLp"])
            player_accounts.validate_ownership([d for d in duos if d.get("id") != new_id] + [data])
            if existing_duo and player_accounts.configuration(data.get("player1") or {})[1] != player_accounts.configuration(existing_duo.get("player1") or {})[1]:
                selected = player_accounts.elo_account(data["player1"])
                rank = selected.get("rank") or {}
                data.update(tier=rank.get("tier", "Unranked"), division=rank.get("division", ""), lp=rank.get("lp",0),
                            wins=rank.get("wins",0), losses=rank.get("losses",0), rankObservedAt=rank.get("observedAt",0))
                data["eloHistory"] = copy.deepcopy(selected.get("eloHistory", []))
                data["eloHistoryAccount"] = player_accounts.identity(selected)
                data["initialTotalLp"] = selected.get("initialTotalLp", (selected.get("eloHistory") or [{}])[0].get("totalLp", calc_total_lp(data["tier"],data["division"],data["lp"])))
                data["netLp"] = calc_total_lp(data["tier"],data["division"],data["lp"]) - data["initialTotalLp"]

            player1 = data.get("player1") or {}
            player2 = data.get("player2") or {}
            for player_key, player in (("player1", player1), ("player2", player2)):
                display_name = str(player.get("displayName", player.get("name", ""))).strip()
                if not display_name or len(display_name) > 60:
                    self._send_json({"success": False, "error": "Indica un nombre de entre 1 y 60 caracteres para cada integrante."}, 400)
                    return
                player["displayName"] = display_name
                if "opggUrl" in player:
                    raw_opgg = str(player.get("opggUrl") or '').strip()
                    opgg_url = normalize_opgg_url(raw_opgg)
                    if raw_opgg and not opgg_url:
                        self._send_json({"success": False, "error": "El enlace de OP.GG debe ser una URL HTTPS válida de op.gg."}, 400)
                        return
                    player["opggUrl"] = opgg_url
                if "twitchUrl" in player:
                    raw_url = str(player.get("twitchUrl") or "").strip()
                    channel = twitch_channel_from_url(raw_url)
                    if raw_url and not channel:
                        self._send_json({"success": False, "error": "El enlace de Twitch debe ser la URL HTTPS de un canal válido."}, 400)
                        return
                    player["twitchUrl"] = f"https://www.twitch.tv/{channel}" if channel else ""
                # Live status comes only from Twitch, never from an admin form.
                player["twitchIsLive"] = participant_twitch_live(existing_duo, player_key) if existing_duo else False
                if participant_twitch_channel({player_key: player, "twitchUrl": data.get("twitchUrl")}, player_key) != participant_twitch_channel(existing_duo, player_key):
                    player["twitchIsLive"] = False
            data["player1"], data["player2"] = player1, player2
            data["twitchIsLive"] = any(participant_twitch_live(data, key) for key in ("player1", "player2"))
            
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
            self._send_json({"success": True, "duo": safe_duo_for_admin(data)})

        elif parsed.path in ('/api/overlay/login', '/api/overlay/session', '/api/overlay/state', '/api/overlay/logout'):
            if not self.clips_origin_allowed():
                self._send_json({'success': False, 'error': 'Origen no permitido'}, 403)
                return
            token = data.get('sessionToken')
            if parsed.path == '/api/overlay/logout':
                if overlay_sessions.revoke(db, token):
                    save_db(db)
                notify_shell_receivers()
                self._send_json({'success': True})
                return
            if parsed.path == '/api/overlay/login':
                duo = next((d for d in db.get('duos', []) if d.get('id') == data.get('teamId')), None)
                if not duo or not verify_secret(str(data.get('password', '')).strip(), duo.get('passwordHash') or duo.get('password', '1234')):
                    self._send_json({'success': False, 'error': 'Contraseña o equipo incorrecto'}, 401)
                    return
            else:
                team_id = self.authenticated_team(db, token) if parsed.path == '/api/overlay/session' else overlay_sessions.team(db, token)
                duo = next((d for d in db.get('duos', []) if d.get('id') == team_id), None)
                if not duo:
                    self._send_json({'success': False, 'error': 'Sesión caducada'}, 401)
                    return
            if parsed.path != '/api/overlay/state':
                token = overlay_sessions.create(db, duo)
                save_db(db)
            attacks = [{'id': a.get('id')} for a in db.get('shellAttacks', [])
                       if a.get('targetTeamId') == duo['id'] and a.get('status') == 'PENDING_SPIN']
            self._send_json({'success': True, 'sessionToken': token,
                             'duo': {'id': duo['id'], 'teamName': duo.get('teamName'), 'pendingShellAttacks': attacks}})

        elif parsed.path == '/api/player/login':
            team_id = data.get("teamId")
            pwd = data.get("password", "").strip()
            duos = db.get("duos", [])
            duo = next((d for d in duos if d["id"] == team_id or d["teamName"].lower() == str(team_id).lower()), None)
            
            stored_password = (duo or {}).get("passwordHash") or (duo or {}).get("password", "1234")
            if duo and verify_secret(pwd, stored_password):
                previous = self.team_cookie_token()
                remembered_sessions.revoke(db, previous)
                remember_token = remembered_sessions.create(db, duo)
                save_db(db)
                token = create_player_session(duo["id"])
                player_sessions[token]['rememberDigest'] = remembered_sessions.digest(remember_token)
                self._send_json({"success": True, "duo": player_state(db, duo), "sessionToken": token, 'remembered': True},
                                headers={'Set-Cookie': self.team_cookie(remember_token)})
                notify_shell_receivers()
            else:
                self._send_json({"success": False, "error": "Contraseña o equipo incorrecto"}, 401)

        elif parsed.path == '/api/player/logout':
            legacy = player_sessions.get(str(data.get('sessionToken', '')), {})
            keys = {remembered_sessions.digest(self.team_cookie_token()), legacy.get('rememberDigest')} - {None}
            sessions = db.get('rememberedTeamSessions', {})
            changed = False
            for key in keys:
                if sessions.pop(key, None) is not None:
                    changed = True
            if changed:
                save_db(db)
            for token, record in list(player_sessions.items()):
                if record.get('rememberDigest') in keys or token == data.get('sessionToken'):
                    player_sessions.pop(token, None)
            notify_shell_receivers()
            self._send_json({'success': True}, headers={'Set-Cookie': self.team_cookie(clear=True)})

        elif parsed.path == '/api/player/state':
            team_id = self.authenticated_team(db, data.get("sessionToken"))
            duo = next((d for d in db.get("duos", []) if d.get("id") == team_id), None)
            if not duo:
                self._send_json({"success": False, "error": "Sesión caducada"}, 401)
                return
            self._send_json({"success": True, "duo": player_state(db, duo)})

        elif parsed.path == '/api/player/launch-shell':
            attacker_id = self.authenticated_team(db, data.get("sessionToken"))
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
                self._send_json({"success": False, "error": "No puedes lanzarte un pepazo a ti mismo"}, 400)
                return

            if attacker.get("blueShells", 0) <= 0:
                self._send_json({"success": False, "error": "No tienes Pepazos disponibles en tu inventario"}, 400)
                return

            attacker["blueShells"] -= 1
            attacker["shellsUsed"] = attacker.get("shellsUsed", 0) + 1

            attack = create_pending_shell(db, attacker, target)

            # Log Event
            event = {
                "id": f"event-{int(time.time()*1000)}",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "attacker": attacker["teamName"],
                "target": target["teamName"],
                "type": "SHELL_LAUNCHED",
                "shellAttackId": attack["id"],
                "message": f"🐢⚡ ¡{attacker['teamName']} ha lanzado un Pepazo contra {target['teamName']}! El equipo receptor debe girar la ruleta."
            }
            events = db.get("events", [])
            events.insert(0, event)
            db["events"] = events

            save_db(db)
            notify_shell_receivers()
            target_webhook = target.get("discordWebhook")
            if target_webhook:
                discord_shells.notify_shell_received_async(target_webhook, attacker.get("teamName", "Rival"), target.get("teamName", "Objetivo"), target.get("discordRoleId"))
            self._send_json({"success": True, "attacker": player_state(db, attacker), "attack": attack, "event": event})

        elif parsed.path == '/api/player/spin-shell':
            team_id = self.authenticated_team(db, data.get("sessionToken"))
            attack_id = str(data.get("attackId", ""))
            if not team_id:
                self._send_json({"success": False, "error": "Sesión caducada"}, 401)
                return
            target = next((d for d in db.get("duos", []) if d.get("id") == team_id), None)
            attack = next((a for a in db.get("shellAttacks", []) if a.get("id") == attack_id), None)
            if not target or not attack or attack.get("targetTeamId") != team_id:
                self._send_json({"success": False, "error": "Pepazo no encontrado"}, 404)
                return
            if attack.get("status") != "PENDING_SPIN":
                self._send_json({"success": False, "error": "Este pepazo ya ha sido girado"}, 409)
                return

            try:
                selected_penalty = weighted_penalty(attack.get("wheelSnapshot", {}))
            except ValueError as error:
                self._send_json({"success": False, "error": str(error)}, 400)
                return

            return_target = None
            if selected_penalty["baseId"] == "return_shell":
                return_target = next((d for d in db.get("duos", []) if d.get("id") == attack.get("attackerTeamId")), None)
                if not return_target or return_target["id"] == target["id"]:
                    self._send_json({"success": False, "error": "No se puede devolver el pepazo: el equipo atacante ya no está disponible."}, 409)
                    return
                selected_penalty["desc"] = f"El pepazo vuelve a {return_target['teamName']}, que debe girarlo desde su bandeja."

            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            attack["spunAt"] = now_iso
            attack["result"] = selected_penalty
            penalty_instance = None
            returned_attack = None
            if return_target:
                returned_attack = create_pending_shell(db, target, return_target, attack.get("wheelSnapshot", {}), attack)
                attack["status"] = "RETURNED"
                attack["returnedAttackId"] = returned_attack["id"]
                db.setdefault("events", []).insert(0, {
                    "id": f"event-{uuid.uuid4().hex}", "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "type": "SHELL_RETURNED", "shellAttackId": returned_attack["id"],
                    "sourceShellAttackId": attack["id"], "attacker": target["teamName"], "target": return_target["teamName"],
                    "message": f"↩️ {target['teamName']} ha devuelto el pepazo a {return_target['teamName']}. Debe girar su ruleta."
                })
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
                attack["requirements"] = copy.deepcopy(penalty_instance["requirements"])
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
                "scope": selected_penalty["scope"],
                "requirements": copy.deepcopy(penalty_instance["requirements"]) if penalty_instance else {},
                "message": f"🎰 {attack.get('targetName')} ha girado la ruleta: {selected_penalty['icon']} {selected_penalty['name']} — {selected_penalty['desc']}"
            }
            db.setdefault("events", []).insert(0, event)
            save_db(db)
            notify_shell_receivers()
            if return_target:
                target_webhook = target.get("discordWebhook")
                if target_webhook:
                    discord_shells.notify_shell_returned_async(target_webhook, target.get("teamName", "Defensor"), return_target.get("teamName", "Atacante"))
                return_target_webhook = return_target.get("discordWebhook")
                if return_target_webhook:
                    discord_shells.notify_shell_bounced_back_async(return_target_webhook, target.get("teamName", "Defensor"), return_target.get("teamName", "Atacante"), return_target.get("discordRoleId"))
            else:
                target_webhook = target.get("discordWebhook")
                if target_webhook:
                    discord_shells.notify_shell_spun_async(target_webhook, target.get("teamName", "Equipo"), attack.get("attackerName", "Rival"), selected_penalty)
            self._send_json({"success": True, "penalty": selected_penalty, "penaltyInstance": penalty_instance, "duo": player_state(db, target), "attack": attack, "returnedAttack": returned_attack})

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
                # An admin tab opened before deployment may still submit the old catalog.
                submitted_weights = without_retired_weights(submitted_weights)
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
            if is_retired_penalty(found.get("penalty", {})):
                self._send_json({"success": False, "error": "Este castigo se ha retirado del torneo y no se puede modificar."}, 409)
                return
            if action == "REOPEN":
                if found.get("resolvedByMatchId"):
                    found.setdefault("excludedMatchIds", []).append(found["resolvedByMatchId"])
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
            found.setdefault("resolutionHistory", []).append({"action": action, "note": note, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "by": "ADMIN"})
            db.setdefault("events", []).insert(0, {
                "id": f"event-{uuid.uuid4().hex}", "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "penaltyInstanceId": instance_id, "action": action, "note": note,
                "type": "PENALTY_ADMIN_CORRECTION", "target": owner.get("teamName"),
                "penalty": found.get("penalty"), "message": f"🛡️ Administración ha actualizado {found.get('penalty', {}).get('name', 'un castigo')} de {owner.get('teamName')}: {action}. Motivo: {note}"
            })
            weekly_summary.maintain(db, refresh=True)
            save_db(db)
            self._send_json({"success": True, "duos": safe_duos_for_admin(db.get("duos", []))})

        elif parsed.path == '/api/calculate-shells':
            if not verify_admin_pin(db, data.get('authPin', '')):
                self._send_json({'success': False, 'error': 'PIN incorrecto'}, 401)
                return
            db = load_db()
            duos = db.get("duos", [])
            total_new_shells = 0
            for duo in duos:
                before = duo.get("blueShells", 0)
                update_duo_shells(duo)
                after = duo.get("blueShells", 0)
                safe_print(f"[CalcShells] {duo['teamName']}: before={before}, after={after}")
                total_new_shells += max(0, after - before)
            weekly_summary.maintain(db, refresh=True)
            save_db(db)
            self._send_json({"success": True, "newShells": total_new_shells, "duos": safe_duos_for_admin(duos)})

        elif parsed.path == '/api/admin/check-apis':
            if not verify_admin_pin(db, data.get("authPin", "")):
                self._send_json({"success": False, "error": "PIN incorrecto"}, 401)
                return
            checks = check_service_credentials(db)
            if checks["riot"]["success"]:
                db["lastRiotApiSuccessAt"] = utc_now()
                save_db(db)
            self._send_json({"success": True, **checks})

        elif parsed.path in ('/api/sync', '/api/twitch/sync'):
            if not verify_admin_pin(db, data.get("authPin", "")):
                self._send_json({"success": False, "error": "PIN incorrecto"}, 401)
                return
            name = "riot" if parsed.path == '/api/sync' else "twitch"
            callback = sync_riot_data if name == "riot" else sync_twitch_live_status
            self._send_json(sync_jobs.start(name, callback), 202)

        else:
            self._send_json({"error": "Endpoint Not Found"}, 404)

    @http_errors
    @serialized_mutation
    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/duos/'):
            data = self.read_body()
            duo_id = urllib.parse.unquote(parsed.path.split('/')[-1])
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

    schedule_trophies()
    schedule_clip_rewards()
    schedule_sync()
    schedule_twitch_sync()
    server = ReusableServer(('', PORT), CustomHandler)
    server.serve_forever()
