"""Individual shell triggers shared by match rewards and tournament predictions."""

SHELL_KILLS = 20
SHELL_ASSISTS = 30
SHELL_PERFECT_KDA = 20


def individual_shell_criteria(stats):
    criteria = []
    if (stats.get('pentaKills', 0) or 0)>0 or (stats.get('largestMultiKill', 0) or 0)>=5:
        criteria.append('penta')
    if stats.get('kills', 0)>=SHELL_KILLS:
        criteria.append('kills')
    if stats.get('assists', 0)>=SHELL_ASSISTS:
        criteria.append('assists')
    if stats.get('deaths')==0 and stats.get('kills', 0)+stats.get('assists', 0)>SHELL_PERFECT_KDA:
        criteria.append('perfect')
    return criteria
