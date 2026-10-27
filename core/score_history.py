"""Score extraction without treating missing values as zero."""
import math

try:
    from core.score_known import known_score
except ModuleNotFoundError:
    from score_known import known_score

def number(value):
    if isinstance(value, bool): return None
    try: value = float(value)
    except (TypeError, ValueError): return None
    return value if math.isfinite(value) and value >= 0 else None

def scores(payload):
    result = {}
    host = str(payload.get('host_user_id') or '')
    if payload.get('mode') == 'team':
        for team in payload.get('teams') or []:
            key = str(team.get('team_id') or '')
            if not key: continue
            result['チーム '+key] = known_score(team)
            for user in team.get('users') or []:
                if host and str(user.get('user_id')) == host:
                    result['自枠（個人）'] = known_score(user)
    else:
        for user in payload.get('participants') or []:
            key = str(user.get('anchor_id') or user.get('key') or '')
            if key:
                result['自枠' if key == host else '相手 '+key] = known_score(user)
    return result

