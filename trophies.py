"""Public trophy standings, built only from tournament data already stored."""
from datetime import datetime
from fractions import Fraction

ROLES = {"TOP": "Top", "JUNGLE": "Jungla", "MIDDLE": "Mid", "BOTTOM": "ADC", "UTILITY": "Support"}
TIERS = ["UNRANKED", "IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"]


def rank_key(duo):
    name = str(duo.get("tier", "")).upper()
    tier = TIERS.index(name) if name in TIERS else 0
    division = {"IV": 0, "III": 1, "II": 2, "I": 3}.get(str(duo.get("division", "")).upper(), 0) if 0 < tier < 8 else 0
    lp = int(duo.get("lp", 0) or 0) if tier else 0
    wins, losses = int(duo.get("wins", 0) or 0), int(duo.get("losses", 0) or 0)
    return (tier, division, lp, Fraction(wins, max(1, wins + losses)))


def deadline_timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def build_trophies(duos, end_date):
    ranked = sorted(duos, key=lambda d: tuple(-x for x in rank_key(d)) + (str(d.get("id", "")),))
    def team_entry(duo):
        return {"name": duo.get("teamName", "Equipo"), "teamName": duo.get("teamName", ""), "id": duo.get("id"), "value": " ".join(str(duo.get(k, "")) for k in ("tier", "division")) + f" · {duo.get('lp', 0)} LP"}
    cards = [{"id": "champion", "title": "Campeón del torneo", "icon": "🏆", "description": "Mayor rango, división y LP. Desempate por winrate.", "entries": [team_entry(d) for d in ranked]}]
    for role, label in ROLES.items():
        candidates = []
        for duo in duos:
            for key in ("player1", "player2"):
                player = duo.get(key) or {}
                if not player.get("name"):
                    continue
                if str(player.get("mainRole", "")).upper() != role:
                    continue
                totals = {"kills": 0, "deaths": 0, "assists": 0}
                games = 0
                for match in duo.get("history", []):
                    stats = match.get(key + "Stats")
                    if match.get("isTest") or not isinstance(stats, dict):
                        continue
                    if str(stats.get("position", "")).upper() != role:
                        continue
                    games += 1
                    for stat in totals:
                        totals[stat] += int(stats.get(stat, 0) or 0)
                if not games:
                    continue
                ratio = Fraction(totals["kills"] + totals["assists"], max(1, totals["deaths"]))
                candidates.append({"id": f"{duo.get('id')}:{key}", "name": player["name"] + ("#" + player["tag"] if player.get("tag") else ""), "teamName": duo.get("teamName", ""), "games": games, "kda": float(ratio), "value": f"{float(ratio):.2f} KDA", "_ratio": ratio})
        candidates.sort(key=lambda p: (-p["_ratio"], -p["games"], p["id"]))
        # Exact ties remain explicit instead of inventing a winner from an ID.
        for candidate in candidates:
            candidate["tied"] = bool(len(candidates) > 1 and candidate["_ratio"] == candidates[0]["_ratio"] and candidate["games"] == candidates[0]["games"] and candidates[1]["_ratio"] == candidates[0]["_ratio"] and candidates[1]["games"] == candidates[0]["games"])
        for candidate in candidates:
            candidate.pop("_ratio")
        cards.append({"id": role, "title": f"Mejor {label}", "icon": "🏅", "description": "Mayor KDA acumulado. Desempate por partidas disputadas; si persiste, premio pendiente de desempate.", "entries": candidates})
    for card, ordered in ((cards[0], ranked),):
        if len(ordered) > 1 and rank_key(ordered[0]) == rank_key(ordered[1]):
            for entry, duo in zip(card["entries"], ordered):
                entry["tied"] = rank_key(duo) == rank_key(ordered[0])
    cards.append({"id": "dishonor", "title": "Pin de la deshonra", "icon": "📌", "description": "Dúo que termina más abajo en la clasificación.", "entries": [team_entry(d) for d in reversed(ranked)]})
    if len(ranked) > 1 and rank_key(ranked[-1]) == rank_key(ranked[-2]):
        for entry, duo in zip(cards[-1]["entries"], reversed(ranked)):
            entry["tied"] = rank_key(duo) == rank_key(ranked[-1])
    return {"status": "provisional", "endDate": end_date, "roleMode": "main_role_matches", "cards": cards}
