"""Small, durable Match-V5 details for the duo's match-history viewer."""

MATCH_DETAILS_VERSION = 1


def optional_int(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return None


def participant_details(participant, participants):
    """Keep IDs and numbers, never the full Riot response or static item data."""
    team_id = optional_int(participant.get("teamId"))
    teammates = [p for p in participants if team_id is not None and optional_int(p.get("teamId")) == team_id]
    team_kills = [optional_int(p.get("kills")) for p in teammates]
    lane_cs = optional_int(participant.get("totalMinionsKilled"))
    jungle_cs = optional_int(participant.get("neutralMinionsKilled"))
    return {
        "riotIdGameName": str(participant.get("riotIdGameName") or ""),
        "riotIdTagline": str(participant.get("riotIdTagline") or ""),
        "champLevel": optional_int(participant.get("champLevel")),
        "teamId": team_id,
        "teamKills": sum(team_kills) if team_kills and all(k is not None for k in team_kills) else None,
        "totalMinionsKilled": lane_cs,
        "neutralMinionsKilled": jungle_cs,
        "cs": lane_cs + jungle_cs if lane_cs is not None and jungle_cs is not None else None,
        "goldEarned": optional_int(participant.get("goldEarned")),
        "visionScore": optional_int(participant.get("visionScore")),
        "itemIds": [optional_int(participant.get(f"item{i}")) for i in range(7)],
    }


def add_match_metadata(match, info, puuid1, puuid2, player1_present):
    duration = optional_int(info.get("gameDuration"))
    match["durationSeconds"] = duration
    if duration is not None:
        minutes, seconds = divmod(duration, 60)
        match["duration"] = f"{minutes}m {seconds:02d}s"
    match["gameVersion"] = str(info.get("gameVersion") or "")
    match["queueId"] = optional_int(info.get("queueId"))
    # A resolved account absent from participants really did not play this game.
    match["participantsChecked"] = {"player1": bool(puuid1), "player2": bool(puuid2)}
    match["matchDetailsVersion"] = MATCH_DETAILS_VERSION if player1_present else 0


def needs_match_details(match):
    return bool(not match.get("isTest") and match.get("matchId")
                and (optional_int(match.get("matchDetailsVersion")) or 0) < MATCH_DETAILS_VERSION)


def update_match_details_backfill(duo):
    remaining = sum(needs_match_details(m) for m in duo.get("history", []) if isinstance(m, dict))
    duo["matchDetailsBackfill"] = {"remaining": remaining, "complete": remaining == 0}
    return duo["matchDetailsBackfill"]
