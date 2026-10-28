"""Unified participant display label (presentation only, never a key).

Every surface that shows a battle participant formats the name the
same way, from the nickname / unique_id recorded on the payload entry:

    nickname + unique_id -> 'nickname（@unique_id）'
    nickname only        -> 'nickname'
    unique_id only       -> '@unique_id'
    neither              -> the caller-provided fallback

Scores are always keyed by anchor_id / user_id / team_id elsewhere;
this label is display text and may change as names arrive mid-battle.
Malformed entries never raise: anything unusable counts as absent.
"""


def _clean(value):
    if value is None:
        return ''
    try:
        return str(value).strip()
    except Exception:
        return ''


def participant_label(entry, fallback=''):
    """Display label for one participant / team-user entry dict."""
    try:
        nickname = _clean(entry.get('nickname'))
        handle = _clean(entry.get('unique_id')).lstrip('@')
    except Exception:
        return fallback
    if nickname and handle:
        return f'{nickname}（@{handle}）'
    if nickname:
        return nickname
    if handle:
        return f'@{handle}'
    return fallback


def member_labels(users):
    """One label per team member that has any name info, in order.

    Members with neither nickname nor unique_id are omitted, matching
    how the surfaces have always rendered unnamed members.
    """
    labels = []
    for user in users or []:
        label = participant_label(user)
        if label:
            labels.append(label)
    return labels
