"""Low-score rules: unknown scores never count as zero."""
import time

def known_scores(payload):
    mode = payload.get('mode')
    entries = payload.get('teams' if mode == 'team' else 'participants') or []
    if mode not in ('team', 'individual') or len(entries) < 2:
        return None
    scores = []
    for entry in entries:
        if entry.get('score_known') is not True:
            return None
        value = entry.get('score')
        if isinstance(value, bool):
            return None
        try:
            value = int(value)
        except (ValueError, TypeError):
            return None
        if value < 0:
            return None
        scores.append(value)
    return scores

def exclusion_reason(payload, now=None):
    if not isinstance(payload, dict):
        return None
    scores = known_scores(payload)
    if scores is None:
        return None
    if not payload.get('active'):
        return 'final_all_at_most_100' if max(scores) <= 100 else None
    now = time.time() if now is None else now
    try:
        start = float(payload.get('start_time_ms') or 0) / 1000
        updated = float(payload.get('update_time') or 0) / 1000
        duration = float(payload.get('duration_seconds') or 0)
    except (ValueError, TypeError):
        return None
    elapsed = now - start
    if start > 0 and duration > 0 and 60 <= elapsed < duration and 0 <= now - updated <= 15 and max(scores) <= 40:
        return 'after_60s_all_at_most_40'
    return None
