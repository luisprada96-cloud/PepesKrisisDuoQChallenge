"""Public trophy standings, built only from tournament data already stored."""
from datetime import datetime
from fractions import Fraction
from competition_ranking import team_rank, team_rank_key

ROLES = {"TOP": "Top", "JUNGLE": "Jungla", "MIDDLE": "Mid", "BOTTOM": "ADC", "UTILITY": "Support"}


def deadline_timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def build_trophies(duos, end_date):
    ranked = sorted(duos, key=lambda d: tuple(-x for x in team_rank_key(d)) + (str(d.get("id", "")),))
    def team_entry(duo):
        rank = team_rank(duo)
        return {"name": duo.get("teamName", "Equipo"), "teamName": duo.get("teamName", ""), "id": duo.get("id"), "value": rank['label'], "rankReady": rank['ready']}
    cards = [{"id": "champion", "title": "Campeón del torneo", "icon": "🏆", "description": "Mayor media de ELO de las cuentas seleccionadas de ambos integrantes. Desempate por winrate conjunto de esas cuentas.", "entries": [team_entry(d) for d in ranked]}]
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
        if len(ordered) > 1 and team_rank_key(ordered[0]) == team_rank_key(ordered[1]):
            for entry, duo in zip(card["entries"], ordered):
                entry["tied"] = team_rank_key(duo) == team_rank_key(ordered[0])
    cards.append({"id": "dishonor", "title": "Pin de la deshonra", "icon": "📌", "description": "Dúo que termina más abajo en la clasificación.", "entries": [team_entry(d) for d in reversed(ranked)]})
    if len(ranked) > 1 and team_rank_key(ranked[-1]) == team_rank_key(ranked[-2]):
        for entry, duo in zip(cards[-1]["entries"], reversed(ranked)):
            entry["tied"] = team_rank_key(duo) == team_rank_key(ranked[-1])
    ready = bool(duos) and all(team_rank(d)['ready'] for d in duos)
    for card in (cards[0], cards[-1]):
        card['rankPending'] = not ready
    return {"status": "provisional", "endDate": end_date, "roleMode": "main_role_matches", "standingsReady": ready, "cards": cards}
