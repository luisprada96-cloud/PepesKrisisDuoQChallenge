"""Daily observations, never reconstructed from match wins/losses."""
from datetime import datetime


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
