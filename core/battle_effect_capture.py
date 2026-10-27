"""Preserve score-notification effect changes for diagnosis, without guessing labels."""
import json
from collections import OrderedDict

from core.battle_timeline import record


class BattleEffectCapture:
    def __init__(self):
        self.previous = OrderedDict()

    def capture(self, database, uid, payload, received):
        bid = int(payload.get('battleId') or 0)
        if not uid or bid <= 0:
            return
        # Absent, explicit empty, and populated fields are kept distinct.
        state = {k: payload[k] for k in payload
                 if 'effect' in k.lower() or 'buff' in k.lower()}
        signature = json.dumps(state, ensure_ascii=False, sort_keys=True)
        key = (uid, bid)
        if self.previous.get(key) == signature:
            return
        result = {
            'battleId': str(bid),
            'common': payload.get('common') or {},
            'battleSettings': payload.get('battleSettings') or {},
            'updateBattleScoreTime': payload.get('updateBattleScoreTime'),
            'effectFieldPresent': 'effectInfos' in payload,
            'effects': state,
            'captureNote': 'Observed state only; absence is not proof that an effect ended.',
        }
        record(database, uid, bid, 'battle_effect', result, received)
        self.previous[key] = signature
        self.previous.move_to_end(key)
        while len(self.previous) > 64:
            self.previous.popitem(last=False)
