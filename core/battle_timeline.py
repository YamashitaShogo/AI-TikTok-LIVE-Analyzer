"""Durable battle events. Unknown labels and receipt-time fallbacks remain explicit."""
import hashlib
import json
import math
from pathlib import Path
import sqlite3

SCHEMA = '''CREATE TABLE IF NOT EXISTS battle_timeline (
 unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL, event_key TEXT NOT NULL,
 received_at REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(unique_id,battle_id,event_key))'''


def record(database, uid, bid, kind, payload, received):
    if not uid or int(bid or 0) <= 0:
        return
    path = Path(database); path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    msg = str((payload.get('common') or {}).get('msgId') or '')
    key = kind + ':' + (msg if msg not in ('', '0') else hashlib.sha256(raw.encode()).hexdigest())
    with sqlite3.connect(path, timeout=5) as db:
        db.execute(SCHEMA)
        db.execute('INSERT OR IGNORE INTO battle_timeline VALUES (?,?,?,?,?,?)',
                   (uid, int(bid), key, received, kind, raw))


def epoch(value):
    try:
        n = float(value)
        if n > 1e11: n /= 1000
        return n if math.isfinite(n) and 946684800 <= n <= 4102444800 else None
    except (TypeError, ValueError): return None


def mappings(value):
    if isinstance(value, dict):
        yield value
        for v in value.values(): yield from mappings(v)
    elif isinstance(value, list):
        for v in value: yield from mappings(v)


def interval_end(start, duration):
    try:
        duration = float(duration)
        if start and math.isfinite(duration) and 0 < duration <= 3600:
            return start + duration
    except (TypeError, ValueError): pass
    return None


def hatch_segments(left, top, right, bottom, spacing=10):
    """Diagonal lines clipped exactly to the interval rectangle."""
    if right <= left or bottom <= top: return []
    height = bottom-top
    segments = []
    origin = left-height
    while origin < right:
        lo = max(0, left-origin)
        hi = min(height, right-origin)
        if hi > lo:
            segments.append((origin+lo, bottom-lo, origin+hi, bottom-hi))
        origin += max(4, spacing)
    return segments


def prompt_description(value):
    parts = []
    for d in mappings(value):
        for key in ('defaultPattern', 'text', 'content', 'promptKey'):
            v = d.get(key)
            if isinstance(v, str) and v.strip() and v not in parts:
                parts.append(v)
        if d.get('promptField') is not None and d.get('value') is not None:
            parts.append(str(d['promptField']) + '=' + str(d['value']))
    return ' / '.join(parts)[:1500]


def challenge_label(config):
    keys = {d.get('promptKey') for d in mappings(config) if isinstance(d.get('promptKey'), str)}
    if 'pm_mt_match_sp_team_gifter_target_host' in keys:
        return 'スピードチャレンジ'
    text = prompt_description(config).lower().replace('_',' ').replace('-',' ')
    if any(x in text for x in ('ファースト','ファスト','first','fast')): return 'ファーストチャレンジ'
    if 'スピード' in text or 'speed' in text: return 'スピードチャレンジ'
    return 'チャレンジ（種類未判定）'


def normalize(kind, payload, received):
    result = []
    if kind == 'item':
        # Award/obtain notifications are not item use.
        for key, body in payload.items():
            if not key.startswith('use') or not isinstance(body, dict): continue
            card = body.get('cardInfo') or {}
            pattern = (body.get('displayContent') or {}).get('defaultPattern', '')
            label = pattern.split(' sent 1 ', 1)[-1] if ' sent 1 ' in pattern else card.get('cardNameKey')
            label = str(label or key)
            if label.lower() == 'boosting glove': label = 'グローブ'
            effect = epoch(card.get('effectTimeSec'))
            ts = effect or epoch(card.get('sendTimeSec'))
            result.append({'kind':'item', 'label':label, 'at':ts or received,
                           'basis':'効果開始時刻' if effect else '送信時刻（効果開始未取得）' if ts else '受信時刻（効果開始未取得）',
                           'end':interval_end(effect, card.get('effectLastDuration')),
                           'end_basis':'効果開始＋通知内の効果秒数',
                           'target':str(card.get('toAnchorIdStr') or card.get('toAnchorId') or '')})
    elif kind == 'challenge':
        start = payload.get('start')
        if isinstance(start, dict):
            config = start.get('config') or {}
            label = challenge_label(config)
            target = config.get('targetConfig') or {}
            reward = config.get('rewardConfig') or {}
            begin = epoch(target.get('targetStartTimestamp')) or epoch(target.get('targetStartTime'))
            mission = prompt_description(target) or 'ミッション文未取得'
            known_gifter = any(d.get('promptKey') == 'pm_mt_match_sp_team_gifter_target_host' for d in mappings(target))
            if known_gifter and target.get('progressTarget') is not None:
                mission = f"{target.get('duration', '不明')}秒以内にギフト送信者{target['progressTarget']}人を達成（チーム条件／通知キーから解釈）"
            elif target.get('progressTarget') is not None:
                mission += ' / 目標値=' + str(target['progressTarget']) + '（単位は通知文で確認）'
            result.append({'kind':'challenge', 'phase':'mission', 'label':label+'・ミッション',
                           'at':begin or received, 'end':interval_end(begin,target.get('duration')),
                           'basis':'通知内のミッション開始予定' if begin else '受信時刻（開始未取得）',
                           'end_basis':'ミッション制限時間（予定）', 'mission':mission, 'target':'',
                           'challenge_name':label, 'reward_config':reward})
        settle = payload.get('taskSettle')
        if isinstance(settle, dict):
            # Proto default SUCCEED=0 can be omitted by to_dict().
            outcome = settle.get('result', 'SUCCEED')
            succeeded = outcome in ('SUCCEED','BOTH_SUCCEED',0,2,'0','2')
            result.append({'kind':'challenge','phase':'settle',
                           'label':'ミッション達成通知' if succeeded else 'ミッション判定通知',
                           'at':received, 'end':None, 'basis':'通知受信時刻（正確な達成時刻ではありません）',
                           'target':'','outcome':str(outcome), 'succeeded':succeeded,
                           'reward_begin':epoch(settle.get('rewardStartTimestamp')) or epoch(settle.get('rewardStartTime'))})
    message_id = str((payload.get('common') or {}).get('msgId') or '')
    for e in result: e['message_id'] = message_id
    return result


def load(db, tables, uid, bid, legacy_path=None):
    events = []
    if 'battle_timeline' in tables:
        for row in db.execute('SELECT kind,payload,received_at FROM battle_timeline WHERE unique_id=? AND battle_id=? ORDER BY received_at',(uid,bid)):
            try: events.extend(normalize(row[0],json.loads(row[1]),row[2]))
            except (ValueError, TypeError, AttributeError): continue
    if legacy_path and Path(legacy_path).exists():
        try:
            history = json.loads(Path(legacy_path).read_text(encoding='utf-8-sig'))
            for row in history if isinstance(history,list) else []:
                if row.get('unique_id') == uid and int(row.get('battle_id') or 0) == bid:
                    events.extend(normalize('item',row.get('event') or {},float(row['received_at'])))
        except (OSError, ValueError, TypeError, KeyError): pass
    # Associate rewards only with a unique config, or an exact reward-start match.
    configs = {}
    for e in events:
        if e.get('phase') == 'mission':
            key = (e['at'],json.dumps(e.get('reward_config',{}),sort_keys=True))
            configs[key] = e
    rewards = []
    for e in events:
        if e.get('phase') != 'settle' or not e.get('succeeded') or not e.get('reward_begin'): continue
        begin = e['reward_begin']
        matching = [c for c in configs.values() if
            (epoch(c['reward_config'].get('rewardStartTimestamp')) or epoch(c['reward_config'].get('rewardStartTime'))) == begin]
        if not matching and len(configs) == 1:
            c = next(iter(configs.values()))
            if c['at'] <= e['at'] and (not c.get('end') or e['at'] <= c['end']+30): matching = [c]
        config = matching[0] if len(matching)==1 else None
        reward = config.get('reward_config',{}) if config else {}
        label = config['challenge_name'] if config else 'チャレンジ（種類未判定）'
        multiple = reward.get('rewardMultiple')
        rewards.append({'kind':'challenge','phase':'reward','label':label+'・倍率アップ',
                        'at':begin,'end':interval_end(begin,reward.get('duration')),
                        'basis':'達成通知内の効果開始時刻', 'end_basis':'効果開始＋通知内の効果秒数（予定）',
                        'mission':config.get('mission','') if config else '',
                        'reward_text':prompt_description(reward), 'multiple_raw':multiple,
                        'target':'','message_id':e.get('message_id','')})
    events.extend(rewards)
    # Same event may be present in both durable storage and the legacy cache.
    distinct = {}
    for e in events:
        if epoch(e['at']) is not None:
            distinct[(e['kind'],e['label'],int(e['at']),e['target'],e.get('message_id',''))] = e
    return sorted(distinct.values(),key=lambda e:e['at'])
