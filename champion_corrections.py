"""Narrow, participant-confirmed repairs for the old Locke -> Vex import bug."""

CONFIRMED_LOCKE_MATCHES = {'EUW1_8014333109', 'EUW1_8017228945'}


def repair_confirmed_locke(duo):
    changed = False
    for match in duo.get('history', []):
        if match.get('matchId') not in CONFIRMED_LOCKE_MATCHES or match.get('isTest'):
            continue
        for key, legacy in (('player1','championP1'), ('player2','championP2')):
            stats = match.get(key+'Stats')
            if not isinstance(stats, dict) or stats.get('championName') != 'Vex' or stats.get('championId'):
                continue
            name, tag = stats.get('riotIdGameName'), stats.get('riotIdTagline')
            if (str(name or '').casefold(), str(tag or '').casefold()) != ('jagenau','joyas'):
                continue
            stats['championName'] = 'Locke'
            match[legacy] = 'Locke'
            stats['championCorrection'] = {
                'from':'Vex', 'to':'Locke', 'source':'participant_confirmed',
                'riotId':'JaGenau#JOYAS', 'reason':'legacy_locke_alias'
            }
            changed = True
    return changed
