"""Vote totals shared by the clip board, weekly prize and summary."""
MAX_TEAM_VOTES = 2


def team_vote_count(post, team_id):
    value = post.get('teamVotes', {}).get(team_id, 0)
    if isinstance(value, list):
        return len(set(value))
    return value if type(value) is int and 0 <= value <= MAX_TEAM_VOTES else 0


def browser_liked(post, visitor):
    return bool(visitor) and (visitor in post.get('likedBy', []) or any(
        visitor in voters for voters in post.get('teamVotes', {}).values() if isinstance(voters, list)))


def vote_count(post):
    # Keep already recorded anonymous votes until their weekly board expires.
    legacy = len(set(post.get('likedBy', [])))
    return legacy + sum(team_vote_count(post, team_id) for team_id in post.get('teamVotes', {}))
