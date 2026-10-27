"""Shared interpretation of the score_known flag on payload entries.

Phase A unification: every consumer (display, analysis, exclusion policy)
must read score_known through this module so the meaning cannot drift
between screens again.

- score_known is True:  the score field was present in the source event.
  A score of 0 is a real zero.
- score_known is False: the score field was absent in the source event
  ("not fetched"). Never render or aggregate it as 0.
- score_known missing:  legacy payload written before the flag existed
  ("unstated"). Treated as unknown, never as a confirmed score, and kept
  distinguishable from False so old data stays identifiable in history.
"""


def score_state(entry):
    """Return 'known', 'not_fetched', or 'unstated' for a payload entry."""
    if not isinstance(entry, dict):
        return "unstated"
    flag = entry.get("score_known")
    if flag is True:
        return "known"
    if flag is False:
        return "not_fetched"
    return "unstated"


def is_known(entry):
    return score_state(entry) == "known"


def known_score(entry):
    """Return the int score only when it is known, otherwise None."""
    if not is_known(entry):
        return None
    try:
        value = int(entry.get("score"))
    except (TypeError, ValueError, KeyError):
        return None
    return value if value >= 0 else None


def score_text(entry):
    """Display text: the number, '未取得' (not fetched), or '不明' (unstated)."""
    value = known_score(entry)
    if value is not None:
        return f"{value:,}"
    return "未取得" if score_state(entry) == "not_fetched" else "不明"
