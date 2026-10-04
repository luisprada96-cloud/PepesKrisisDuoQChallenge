"""Daily observations, never reconstructed from match wins/losses."""
from datetime import datetime
import copy


def record_elo(duo, total_lp, timestamp, source="riot"):
    player = duo.get("player1") or {}
    account = [str(player.get("name", "")).lower(), str(player.get("tag", "")).lower()]
    if duo.get("eloHistoryAccount") != account:
        duo["eloHistory"] = []
        duo["eloHistoryAccount"] = account
    history = duo.setdefault("eloHistory", [])
    day = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
    point = {"date":day,"observedAt":timestamp,"totalLp":total_lp,"tier":duo.get("tier","Unranked"),"division":duo.get("division",""),"lp":duo.get("lp",0),"wins":duo.get("wins",0),"losses":duo.get("losses",0),"source":source}
    if history and history[-1]["date"] == day:
        if timestamp >= history[-1]["observedAt"]:
            history[-1] = point
    elif not history or timestamp > history[-1]["observedAt"]:
        history.append(point)


def ensure_player_elo_histories(duo):
    """Preserve the legacy first-player history; never reuse another account's data."""
    changed = False
    for key in ("player1", "player2"):
        player = duo.get(key)
        if not player or not player.get("name"):
            continue
        account = [str(player.get("name", "")).lower(), str(player.get("tag", "")).lower()]
        if player.get("eloHistoryAccount") != account:
            player["eloHistory"] = []
            player["eloHistoryAccount"] = account
            changed = True
            if (key == "player1" and duo.get("eloHistoryAccount") == account
                    and not ("rank" in player and player["rank"] is None)):
                player["eloHistory"] = copy.deepcopy(duo.get("eloHistory", []))
    return changed


def record_player_elo(player, total_lp, timestamp, source="riot"):
    """Record only an observed participant rank, keeping the latest value per day."""
    rank = player.get("rank") or {}
    day = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
    point = {"date": day, "observedAt": timestamp, "totalLp": total_lp,
             "tier": rank.get("tier", "Unranked"), "division": rank.get("division", ""),
             "lp": rank.get("lp", 0), "wins": rank.get("wins"), "losses": rank.get("losses"),
             "source": source}
    history = player.setdefault("eloHistory", [])
    if history and history[-1]["date"] == day:
        if timestamp >= history[-1]["observedAt"]:
            history[-1] = point
    elif not history or timestamp > history[-1]["observedAt"]:
        history.append(point)
