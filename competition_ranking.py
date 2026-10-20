"""Team standings are the arithmetic mean of the two selected Solo/Duo accounts.

Legacy team rank fields still describe player one's source account. Never persist
the average over those fields: imports and individual ELO histories need them.
"""
from fractions import Fraction
import math

import player_accounts

TIER_OFFSETS = {'IRON': 0, 'BRONZE': 400, 'SILVER': 800, 'GOLD': 1200,
                'PLATINUM': 1600, 'EMERALD': 2000, 'DIAMOND': 2400,
                'MASTER': 2800, 'GRANDMASTER': 2800, 'CHALLENGER': 2800}
DIVISIONS = {'IV': 0, 'III': 100, 'II': 200, 'I': 300}


def rank_points(rank):
    if not isinstance(rank, dict):
        return None
    tier = str(rank.get('tier') or '').upper()
    if tier not in TIER_OFFSETS:
        return None  # Unranked is not a confirmed Iron IV rank.
    division = str(rank.get('division') or '').upper()
    if tier not in ('MASTER', 'GRANDMASTER', 'CHALLENGER') and division not in DIVISIONS:
        return None
    try:
        lp = float(rank.get('lp', 0) or 0)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lp) or lp < 0:
        return None
    return TIER_OFFSETS[tier] + (DIVISIONS.get(division, 0) if TIER_OFFSETS[tier] < 2800 else 0) + lp


def selected_rank(duo, key):
    player = duo.get(key) or {}
    if not player.get('name'):
        return None
    if player.get('accounts'):
        return player_accounts.elo_account(player).get('rank')
    if 'rank' in player:
        return player['rank']
    return duo if key == 'player1' else None


def rank_label(points):
    if points is None:
        return 'Media de ELO pendiente'
    tier, offset = next((t, base) for t, base in reversed(list(TIER_OFFSETS.items())[:8]) if points >= base)
    remaining = points - offset
    if offset >= 2800:
        return f'Master · {remaining:g} LP'
    division = ('IV', 'III', 'II', 'I')[min(3, int(remaining // 100))]
    return f'{tier.title()} {division} · {remaining % 100:g} LP'


def average_rank(first, second):
    points = [rank_points(first), rank_points(second)]
    ready = all(p is not None for p in points)
    total = sum(points) / 2 if ready else None
    wins = sum(max(0, int((r or {}).get('wins', 0) or 0)) for r in (first, second))
    losses = sum(max(0, int((r or {}).get('losses', 0) or 0)) for r in (first, second))
    return {'version': 2, 'ready': ready, 'totalLp': total, 'label': rank_label(total),
            'wins': wins, 'losses': losses}


def team_rank(duo):
    return average_rank(*(selected_rank(duo, key) for key in ('player1', 'player2')))


def team_rank_key(duo):
    rank = team_rank(duo)
    return average_rank_key(rank)


def average_rank_key(rank):
    return (bool(rank.get('ready')), rank.get('totalLp') if rank.get('ready') else -1,
            Fraction(rank.get('wins', 0), max(1, rank.get('wins', 0) + rank.get('losses', 0))) if rank.get('ready') else Fraction(0))
