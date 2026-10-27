"""Livemetry Pulse: side-effect-isolated raw battle challenge event tracker.

Reads only documented candidate message fields from incoming webcast protobuf
wire payloads. Does not invent a first-challenge multiplier. Avoids raw payload,
comments, gift-sender profiles, cookies, URLs or chat content in its output.

Output paths relative to the active observation-profile CAPTURE_DIR:
  battle_dataset/battles.sqlite3  -> lp_challenge_events_v1 table only
  latest_challenge.json           -> latest event summary (best effort)
"""

from collections import OrderedDict
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Any

MAX_PAYLOAD_BYTES = 512 * 1024
MAX_FIELDS = 10000


def _varint(buf: bytes, i: int):
    value, shift = 0, 0
    for _ in range(10):
        if i >= len(buf):
            raise ValueError('Truncated varint')
        ch = buf[i]
        i += 1
        value |= (ch & 0x7f) << shift
        if ch < 0x80:
            return value, i
        shift += 7
    raise ValueError('Varint too long')


def _fields(buf: bytes):
    out = []
    i = 0
    while i < len(buf):
        if len(out) >= MAX_FIELDS:
            raise ValueError('Too many fields')
        tag, i = _varint(buf, i)
        n, typ = tag >> 3, tag & 7
        if n <= 0:
            raise ValueError('Invalid field')
        if typ == 0:
            val, i = _varint(buf, i)
        elif typ == 2:
            size, i = _varint(buf, i)
            if size > len(buf) - i:
                raise ValueError('Truncated length-delimited field')
            val = buf[i:i + size]
            i += size
        elif typ in (1, 5):
            size = 8 if typ == 1 else 4
            if size > len(buf) - i:
                raise ValueError('Truncated fixed field')
            val = buf[i:i + size]
            i += size
        else:
            raise ValueError('Unsupported wire type')
        out.append((n, typ, val))
    return out


def _one(fs, key, typ=0, default=None):
    return next((v for n, t, v in fs if n == key and t == typ), default)


def _many(fs, key, typ=2):
    return [v for n, t, v in fs if n == key and t == typ]


def _child(fs, key):
    data = _one(fs, key, typ=2)
    return _fields(data) if data is not None else []


def _string(bs):
    if not bs:
        return ''
    return bs.decode('utf-8', 'replace')


def _valid_epoch(sec):
    return int(sec) if isinstance(sec, int) and 1577836800 < sec < 4102444800 else None


def _get_bonus(fs):
    # WebcastLinkmicBattleTaskMessage type 0/absent: 3 -> 1 -> 2 -> 2
    core = _child(_child(fs, 3), 1)
    multi = None
    for item in _many(core, 2):
        template = _child(_fields(item), 2)
        if _string(_one(template, 1, typ=2)) != 'pm_mt_match_sp_team':
            continue
        for raw in _many(template, 2):
            arg = _fields(raw)
            if _string(_one(arg, 1, typ=2)) == 'multi':
                raw_m = _string(_one(arg, 2, typ=2))
                if raw_m.isdecimal() and 2 <= int(raw_m) <= 10:
                    multi = int(raw_m)
    settings = _child(core, 3)
    effect = _child(core, 4)
    duration = _one(settings, 2)
    mission_start = _valid_epoch(_one(settings, 3))
    boost_duration = _one(effect, 2)
    return {
        'multiplier': multi,
        'mission_duration_seconds': duration if isinstance(duration, int) and 0 < duration <= 3600 else None,
        'mission_start_server': mission_start,
        'boost_duration_seconds': boost_duration if isinstance(boost_duration, int) and 0 < boost_duration <= 3600 else None,
        'owner_side_verified': False,
    }


def _get_result(fs):
    result = _child(fs, 5)
    return {
        'result_code': _one(result, 1),
        'boost_start_server': _valid_epoch(_one(result, 3)),
        'owner_side_verified': False,
    }


def _get_summary(fs):
    summary = _child(_child(fs, 6), 1)
    out = None
    for raw in _many(summary, 2):
        arg = _fields(raw)
        if _string(_one(arg, 1, typ=2)) == 'sum':
            text = _string(_one(arg, 2, typ=2))
            if text.isdecimal():
                out = text
    return {'boost_summary_points': out, 'owner_side_verified': False}


def decode_notification(method: str, raw: bytes):
    """Return (battle_id, event_type, server_timestamp_seconds, multiplier, info).

    Only direct explicitly matched fields produce confirmed events.
    An item-card saying 'boosting glove' is NOT treated as first x3.
    """
    if len(raw) > MAX_PAYLOAD_BYTES:
        return None
    fs = _fields(raw)
    if method == 'WebcastLinkMicBattle':
        battle_id = _one(fs, 2)
        action = _one(fs, 4)
        if not battle_id:
            return None
        settings = _child(fs, 3)
        if action == 4:
            start = _one(settings, 2)
            server = _valid_epoch(start // 1000) if isinstance(start, int) else None
            return str(battle_id), 'battle_started', server, None, {'first_challenge_status': 'unverified'}
        if action == 5:
            ended = _one(settings, 10)
            server = _valid_epoch(ended // 1000) if isinstance(ended, int) else None
            return str(battle_id), 'battle_finished', server, None, {}
        return None
    if method == 'WebcastLinkmicBattleTaskMessage':
        bid = _one(fs, 20)
        if not bid:
            return None
        subtype = _one(fs, 2, default=0)
        if subtype == 0:
            bonus = _get_bonus(fs)
            # Do not call an unrelated/unknown task a bonus without an
            # evidence-bearing multiplier in the localized template args.
            if bonus['multiplier'] is None:
                return None
            return str(bid), 'bonus_announced', bonus['mission_start_server'], bonus['multiplier'], bonus
        if subtype == 2:
            result = _get_result(fs)
            if result['result_code'] != 2 or not result['boost_start_server']:
                return None
            return str(bid), 'bonus_succeeded', result['boost_start_server'], None, result
        if subtype == 3:
            return str(bid), 'bonus_boost_ended', None, None, _get_summary(fs)
        return None
    if method == 'WebcastLinkMicBattleItemCard':
        bid = _one(fs, 2)
        if not bid:
            return None
        data = _child(fs, 5)
        item_text = _string(_one(_child(data, 3), 2, typ=2))
        if 'boosting glove' in item_text.lower():
            return str(bid), 'item_boosting_glove', None, None, {'item': 'boosting_glove', 'owner_side_verified': False}
        return None
    return None


class ChallengeTracker:
    def __init__(self, capture_dir, unique_id: str):
        self.dir = Path(capture_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.unique_id = unique_id
        self._seen = OrderedDict()
        self._last_envelope = None
        self._latest = {}
        db_path = self.dir / 'battle_dataset' / 'battles.sqlite3'
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # Independent connection, short insert transactions; no change to
        # existing battle/score or participant tables.
        self.db = sqlite3.connect(str(db_path), timeout=3.0)
        self.db.execute('PRAGMA busy_timeout = 3000')
        self.db.execute('''CREATE TABLE IF NOT EXISTS lp_challenge_events_v1 (
            event_key TEXT PRIMARY KEY,
            unique_id TEXT NOT NULL,
            battle_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            received_at REAL NOT NULL,
            server_at REAL,
            multiplier INTEGER,
            details_json TEXT NOT NULL
        )''')
        self.db.execute('''CREATE INDEX IF NOT EXISTS lp_challenge_events_v1_by_battle
                           ON lp_challenge_events_v1 (unique_id, battle_id, received_at)''')
        self.db.commit()

    def capture(self, event, received_at=None):
        # received_at is only overridden by the bundled *offline* replay tool.
        observed_at = float(received_at) if received_at is not None else time.time()
        raw_response = getattr(event, 'raw', event)
        if raw_response is self._last_envelope:
            return
        self._last_envelope = raw_response
        for msg in getattr(raw_response, 'messages', ()):
            method = str(getattr(msg, 'method', ''))
            if method not in (
                'WebcastLinkMicBattle',
                'WebcastLinkmicBattleTaskMessage',
                'WebcastLinkMicBattleItemCard',
            ):
                continue
            raw = bytes(getattr(msg, 'payload', b''))
            msg_id = str(getattr(msg, 'msg_id', '') or '')
            sig = hashlib.sha256(method.encode('ascii') + b'\0' + msg_id.encode('ascii') + b'\0' + raw).hexdigest()
            if sig in self._seen:
                continue
            self._seen[sig] = None
            if len(self._seen) > 4096:
                self._seen.popitem(last=False)
            try:
                decoded = decode_notification(method, raw)
                if decoded is None:
                    continue
                bid, kind, server_at, multiplier, info = decoded
                received_at = observed_at
                key = hashlib.sha256((self.unique_id + ':' + sig + ':' + kind).encode('utf-8')).hexdigest()
                cur = self.db.execute('''INSERT OR IGNORE INTO lp_challenge_events_v1
                    (event_key,unique_id,battle_id,event_type,received_at,server_at,multiplier,details_json)
                    VALUES (?,?,?,?,?,?,?,?)''',
                    (key, self.unique_id, bid, kind, received_at, server_at,
                     multiplier, json.dumps(info, ensure_ascii=False, separators=(',', ':'))))
                self.db.commit()
                if cur.rowcount:
                    self._update_latest(bid, kind, received_at, server_at, multiplier, info)
            except (ValueError, TypeError, UnicodeError, sqlite3.Error, OSError) as exc:
                logging.warning('[Challenge Tracker] %s: %s', type(exc).__name__, exc)

    def _update_latest(self, battle_id, kind, received_at, server_at, multiplier, details):
        if self._latest.get('battle_id') != battle_id:
            self._latest = {
                'unique_id': self.unique_id,
                'battle_id': battle_id,
                'first_challenge': {'status': 'unverified', 'multiplier': None,
                                    'evidence': 'no dedicated first-challenge field identified'},
                'bonus_missions': [], 'recent_events': []}
        doc = self._latest
        if kind == 'bonus_announced':
            doc['bonus_missions'].append({
                'multiplier': multiplier,
                'announced_at': received_at,
                'mission_start_server': details.get('mission_start_server'),
                'mission_duration_seconds': details.get('mission_duration_seconds'),
                'boost_duration_seconds': details.get('boost_duration_seconds'),
                'boost_start_server': None,
                'boost_end_server_estimated': None,
                'owner_side_verified': False,
            })
            doc['bonus_missions'] = doc['bonus_missions'][-12:]
        elif kind == 'bonus_succeeded':
            waiting = next((m for m in reversed(doc['bonus_missions']) if m.get('boost_start_server') is None), None)
            if waiting is not None:
                waiting['boost_start_server'] = server_at
                if server_at is not None and waiting.get('boost_duration_seconds'):
                    waiting['boost_end_server_estimated'] = server_at + waiting['boost_duration_seconds']
        elif kind == 'bonus_boost_ended':
            waiting = next((m for m in reversed(doc['bonus_missions']) if m.get('boost_ended_at') is None), None)
            if waiting is not None:
                waiting['boost_ended_at'] = received_at
                waiting['boost_summary_points'] = details.get('boost_summary_points')
        event_info = {'type': kind, 'received_at': received_at, 'server_at': server_at,
                      'multiplier': multiplier}
        doc['recent_events'].append(event_info)
        doc['recent_events'] = doc['recent_events'][-30:]
        doc['updated_at'] = received_at
        self._write_snapshot(doc)

    def _write_snapshot(self, doc):
        path = self.dir / 'latest_challenge.json'
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.dir,
                                             prefix='latest_challenge_', suffix='.tmp', delete=False) as f:
                temporary = Path(f.name)
                json.dump(doc, f, ensure_ascii=False, indent=2)
            for k in range(5):
                try:
                    os.replace(temporary, path)
                    temporary = None
                    break
                except PermissionError:
                    if k == 4: raise
                    time.sleep(.015 * (2 ** k))
        except OSError as exc:
            logging.warning('[Challenge Tracker] snapshot failed: %s', exc)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def close(self):
        self._last_envelope = None
        self.db.close()
