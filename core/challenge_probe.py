"""Bounded diagnostics for battle notifications, including unknown proto fields.

Only individual selected message payloads are saved, never the fetch envelope
(which may contain connection parameters). No inferred challenge intervals.
"""
import base64
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
from collections import OrderedDict, Counter
from pathlib import Path
import time


class ChallengeProbe:
    def __init__(self, directory, unique_id):
        self.unique_id = unique_id
        self.seen = OrderedDict()
        self.envelope = None
        self.counts = Counter()
        self.last_summary = 0
        path = Path(directory) / 'challenge_probe.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handler = RotatingFileHandler(path, maxBytes=8*1024*1024,
                                          backupCount=3, encoding='utf-8')
        self.handler.setFormatter(logging.Formatter('%(message)s'))
        self.write(dict(kind='probe_version', version=2, unique_id=self.unique_id, received_at=time.time()))
        print('[Challenge Probe] v2 gift/panel/tray capture enabled', flush=True)

    def write(self, data):
        record = logging.LogRecord('challenge_probe', logging.INFO, '', 0,
                                   json.dumps(data, ensure_ascii=False), (), None)
        self.handler.emit(record)

    def capture(self, event, battle_id=None):
        raw = getattr(event, 'raw', event)
        # SDK emits the same envelope once per contained message.
        if raw is self.envelope:
            return
        self.envelope = raw
        now = time.time()
        for message in getattr(raw, 'messages', ()):
            method = str(getattr(message, 'method', ''))
            payload = bytes(getattr(message, 'payload', b''))
            msg_id = str(getattr(message, 'msg_id', '') or '')
            key = (method, msg_id, hashlib.sha256(payload).hexdigest())
            if key in self.seen:
                continue
            self.seen[key] = None
            if len(self.seen) > 4096:
                self.seen.popitem(last=False)
            self.counts[method] += 1
            selected = any(word in method.lower() for word in (
                'battle', 'linkmic', 'linklayer', 'system', 'notify', 'notification',
                'banner', 'guide', 'commontext', 'toast', 'notice', 'capsule',
                'giftprompt', 'boost', 'bonus', 'challenge',
                'giftmessage', 'giftpanel', 'giftdynamic', 'barrage',
                'commenttray', 'roommessage', 'goalupdate', 'anchortool'))
            if not selected:
                continue
            data = dict(kind='raw_notification', received_at=now,
                        unique_id=self.unique_id, method=method, msg_id=msg_id,
                        observed_battle_id=str(battle_id or ''),
                        association='context only; may precede battle detection',
                        is_history=bool(getattr(message, 'is_history', False)),
                        payload_bytes=len(payload))
            if len(payload) <= 512*1024:
                data['payload_base64'] = base64.b64encode(payload).decode('ascii')
            else:
                data['omitted'] = 'payload exceeds 512 KiB limit'
            self.write(data)
        if now - self.last_summary >= 30:
            self.summary(now)

    def summary(self, now):
        self.write(dict(kind='method_counts', received_at=now,
                        unique_id=self.unique_id, counts=dict(self.counts)))
        self.last_summary = now

    def close(self):
        self.envelope = None
        self.summary(time.time())
        self.handler.close()
