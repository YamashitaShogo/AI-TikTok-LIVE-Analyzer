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
    """Series values keyed by STABLE identity, never by display name.

    Keys stay identical for a whole battle even when nicknames only
    become known partway through (e.g. at FINISH): individual mode
    uses '自枠' / '相手 <anchor_id>'; a one-person team is that person
    ('自枠' for the host, '相手 <user_id>' otherwise); a multi-person
    team uses 'チーム <team_id>' plus '自枠（個人）' for the host's own
    score inside it. Display names live in series_labels() instead.
    """
    result = {}
    host = str(payload.get('host_user_id') or '')
    if payload.get('mode') == 'team':
        for team in payload.get('teams') or []:
            key = str(team.get('team_id') or '')
            if not key: continue
            users = team.get('users') or []
            if len(users) == 1:
                uid = str(users[0].get('user_id') or '')
                if uid:
                    result['自枠' if uid == host else '相手 '+uid] = known_score(team)
                    continue
            result['チーム '+key] = known_score(team)
            for user in users:
                if host and str(user.get('user_id')) == host:
                    result['自枠（個人）'] = known_score(user)
    else:
        for user in payload.get('participants') or []:
            key = str(user.get('anchor_id') or user.get('key') or '')
            if key:
                result['自枠' if key == host else '相手 '+key] = known_score(user)
    return result

def series_labels(payload):
    """Display labels for the stable series keys, from one payload.

    Only labels backed by a recorded nickname are returned; series
    without a name keep their stable key as the legend text.
    """
    labels = {}
    host = str(payload.get('host_user_id') or '')
    if payload.get('mode') == 'team':
        for team in payload.get('teams') or []:
            key = str(team.get('team_id') or '')
            if not key: continue
            users = team.get('users') or []
            if len(users) == 1:
                uid = str(users[0].get('user_id') or '')
                nickname = str(users[0].get('nickname') or '').strip()
                if uid and uid != host and nickname:
                    labels['相手 '+uid] = nickname
                continue
            names = [str(u.get('nickname') or '').strip() for u in users]
            names = [name for name in names if name]
            if names:
                labels['チーム '+key] = '・'.join(names)
    else:
        for user in payload.get('participants') or []:
            key = str(user.get('anchor_id') or user.get('key') or '')
            nickname = str(user.get('nickname') or '').strip()
            if key and key != host and nickname:
                labels['相手 '+key] = nickname
    return labels

def resolve_labels(payloads):
    """Merge series_labels over a battle's payloads; a name, once
    known in any snapshot, labels the series for the whole battle."""
    labels = {}
    for payload in payloads or []:
        for key, label in series_labels(payload).items():
            if key not in labels:
                labels[key] = label
    return labels

