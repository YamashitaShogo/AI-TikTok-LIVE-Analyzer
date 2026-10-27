"""Score extraction without treating missing values as zero."""
import math

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
            result['チーム '+key] = None if team.get('score_known') is False else number(team.get('score'))
            for user in team.get('users') or []:
                if host and str(user.get('user_id')) == host:
                    result['自枠（個人）'] = None if user.get('score_known') is False else number(user.get('score'))
    else:
        for user in payload.get('participants') or []:
            key = str(user.get('anchor_id') or user.get('key') or '')
            if key:
                result['自枠' if key == host else '相手 '+key] = None if user.get('score_known') is False else number(user.get('score'))
    return result

