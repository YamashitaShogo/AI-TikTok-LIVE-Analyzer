"""Offline investigator for the battle "first challenge" question.

Reads ChallengeProbe v2 JSONL exports (challenge_probe.jsonl plus its
.1/.2/.3 rotations) as a stream and produces structural, correlation and
classification evidence about candidate signals - most notably the
SDK-unregistered method ``WebcastBattleGameplayMessage``.

Verdict discipline (hard rule)
------------------------------
Assessments produced by this tool are limited to ``CANDIDATE`` and
``UNKNOWN``.  Confirming a first challenge requires external screen
evidence (what TikTok actually displayed), which this tool does not
ingest, so NO code path in this module can emit a confirmed verdict
from log data alone.  A score increase ratio is never treated as
evidence of a specific multiplier source.

Privacy
-------
Outputs never contain payload_base64, nicknames, unique_ids, user
names, or numeric user/anchor ids.  Only battle ids, method names,
timestamps (rendered in JST, Asia/Tokyo) and structural facts are
emitted.  String fields inside payloads are represented by length and
a short hash, never by content, except TikTok prompt keys matching
``pm_*`` (system template identifiers, not personal data).

Battle attribution
------------------
A record is attributed to a battle only when its own payload carries a
battle_id (WebcastLinkMicBattle field 2, WebcastLinkmicBattleTaskMessage
field 20, WebcastLinkMicBattleItemCard field 2,
WebcastLinkMicOpponentGifts field 2).  Everything else is associated
by time window only and labelled ``time_window_association``.

Dependencies: Python standard library only.  If TikTokLiveProto is
importable it is used opportunistically to decode task/gift payloads
by schema field name; the tool runs fully structurally without it.
"""

import argparse
import base64
import binascii
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9), 'JST')

GAMEPLAY_METHOD = 'WebcastBattleGameplayMessage'
TASK_METHOD = 'WebcastLinkmicBattleTaskMessage'
GIFT_METHOD = 'WebcastGiftMessage'
LINKMIC_BATTLE_METHOD = 'WebcastLinkMicBattle'
ITEM_CARD_METHOD = 'WebcastLinkMicBattleItemCard'
OPPONENT_GIFTS_METHOD = 'WebcastLinkMicOpponentGifts'

ASSESSMENT_CANDIDATE = 'CANDIDATE'
ASSESSMENT_UNKNOWN = 'UNKNOWN'

MAX_DEPTH = 6
MAX_FIELDS = 10000
EPOCH_MIN = 1577836800      # 2020-01-01 UTC
EPOCH_MAX = 4102444800      # 2100-01-01 UTC

_PROMPT_KEY_RE = re.compile(r'^pm_[a-z0-9_]+$')


# --------------------------------------------------------------------------
# Generic protobuf wire decoding (no schema assumed)
# --------------------------------------------------------------------------

def _read_varint(buf, i):
    value, shift = 0, 0
    for _ in range(10):
        if i >= len(buf):
            raise ValueError('truncated varint')
        ch = buf[i]
        i += 1
        value |= (ch & 0x7f) << shift
        if ch < 0x80:
            return value, i
        shift += 7
    raise ValueError('varint too long')


def parse_fields(buf):
    """Parse a protobuf wire buffer into [(number, wire_type, value)].

    value is int for wire type 0, bytes for wire types 1/2/5.
    Raises ValueError on malformed input.
    """
    out = []
    i = 0
    while i < len(buf):
        if len(out) >= MAX_FIELDS:
            raise ValueError('too many fields')
        tag, i = _read_varint(buf, i)
        number, wtype = tag >> 3, tag & 7
        if number <= 0:
            raise ValueError('invalid field number')
        if wtype == 0:
            value, i = _read_varint(buf, i)
        elif wtype == 2:
            size, i = _read_varint(buf, i)
            if size > len(buf) - i:
                raise ValueError('truncated length-delimited field')
            value = buf[i:i + size]
            i += size
        elif wtype in (1, 5):
            size = 8 if wtype == 1 else 4
            if size > len(buf) - i:
                raise ValueError('truncated fixed field')
            value = buf[i:i + size]
            i += size
        else:
            raise ValueError('unsupported wire type')
        out.append((number, wtype, value))
    return out


def _one(fields, number, wtype=0, default=None):
    return next((v for n, t, v in fields if n == number and t == wtype), default)


def _many(fields, number, wtype=2):
    return [v for n, t, v in fields if n == number and t == wtype]


def _child(fields, number):
    data = _one(fields, number, wtype=2)
    if data is None:
        return []
    try:
        return parse_fields(data)
    except ValueError:
        return []


def _string(raw):
    if not raw:
        return ''
    return raw.decode('utf-8', 'replace')


def _valid_epoch(sec):
    return int(sec) if isinstance(sec, int) and EPOCH_MIN < sec < EPOCH_MAX else None


def _is_text_like(raw):
    if not raw:
        return False
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return False
    printable = sum(1 for ch in text if ch.isprintable() or ch in '\r\n\t')
    return printable >= 0.9 * len(text)


def fingerprint(buf, prefix='', depth=0, out=None):
    """Structural fingerprint: {field_path: set(tokens)} for one payload.

    Tokens are structural only: 'v:<int>' for varints, 'f32:<hex>' /
    'f64:<hex>' for fixed fields, 'len:<n>' for opaque segments and
    'str:<len>:<sha256-8>' for text-like segments (content never kept).
    """
    if out is None:
        out = defaultdict(set)
    try:
        fields = parse_fields(buf)
    except ValueError:
        out[prefix + '<unparseable>'].add('len:%d' % len(buf))
        return out
    for number, wtype, value in fields:
        path = '%s%d' % (prefix, number)
        if wtype == 0:
            out[path].add('v:%d' % value)
        elif wtype == 1:
            out[path].add('f64:%s' % value.hex())
        elif wtype == 5:
            out[path].add('f32:%s' % value.hex())
        elif wtype == 2:
            if _is_text_like(value):
                digest = hashlib.sha256(value).hexdigest()[:8]
                out[path].add('str:%d:%s' % (len(value), digest))
            elif depth < MAX_DEPTH and value:
                before = set(out.keys())
                fingerprint(value, path + '.', depth + 1, out)
                if set(out.keys()) == before:
                    out[path].add('len:%d' % len(value))
            else:
                out[path].add('len:%d' % len(value))
    return out


def compare_fingerprints(fps):
    """Common vs differing structure across a list of fingerprints."""
    if not fps:
        return {'occurrences': 0, 'common_fields': [], 'differing_fields': []}
    all_paths = set()
    for fp in fps:
        all_paths.update(fp.keys())
    common, differing = [], []
    for path in sorted(all_paths):
        present = [path in fp for fp in fps]
        value_sets = [fp.get(path, set()) for fp in fps]
        identical = all(v == value_sets[0] for v in value_sets)
        if all(present) and identical:
            common.append({'path': path,
                           'values': sorted(value_sets[0])})
        else:
            differing.append({
                'path': path,
                'present_in': sum(present),
                'values_by_occurrence': [sorted(v) for v in value_sets],
            })
    return {'occurrences': len(fps), 'common_fields': common,
            'differing_fields': differing}


# --------------------------------------------------------------------------
# Payload-embedded battle ids and battle start (payload-confirmed only)
# --------------------------------------------------------------------------

_BATTLE_ID_FIELDS = {
    LINKMIC_BATTLE_METHOD: 2,
    TASK_METHOD: 20,
    ITEM_CARD_METHOD: 2,
    OPPONENT_GIFTS_METHOD: 2,
}


def payload_battle_id(method, fields):
    """Battle id carried inside the payload itself, or None."""
    number = _BATTLE_ID_FIELDS.get(method)
    if number is None or fields is None:
        return None
    value = _one(fields, number)
    return int(value) if isinstance(value, int) and value > 0 else None


def linkmic_battle_timing(fields):
    """(action, start_server_sec, finish_server_sec) for LinkMicBattle.

    Mirrors core/challenge_tracker.py: action is field 4; the settings
    child (field 3) carries start_time_ms at its field 2 (the schema
    name in TikTokLiveProto v3 BattleSetting) and the end ms at its
    field 10.
    """
    if fields is None:
        return None, None, None
    action = _one(fields, 4)
    settings = _child(fields, 3)
    start_ms = _one(settings, 2)
    finish_ms = _one(settings, 10)
    start = _valid_epoch(start_ms // 1000) if isinstance(start_ms, int) else None
    finish = _valid_epoch(finish_ms // 1000) if isinstance(finish_ms, int) else None
    return action, start, finish


# --------------------------------------------------------------------------
# Tracker-mirror task classification (core/challenge_tracker.py logic)
# --------------------------------------------------------------------------

def _tracker_bonus(fields):
    """Mirror of challenge_tracker._get_bonus (template-arg evidence)."""
    core = _child(_child(fields, 3), 1)
    multi = None
    for item in _many(core, 2):
        try:
            template = _child(parse_fields(item), 2)
        except ValueError:
            continue
        if _string(_one(template, 1, wtype=2)) != 'pm_mt_match_sp_team':
            continue
        for raw in _many(template, 2):
            try:
                arg = parse_fields(raw)
            except ValueError:
                continue
            if _string(_one(arg, 1, wtype=2)) == 'multi':
                raw_m = _string(_one(arg, 2, wtype=2))
                if raw_m.isdecimal() and 2 <= int(raw_m) <= 10:
                    multi = int(raw_m)
    settings = _child(core, 3)
    effect = _child(core, 4)
    duration = _one(settings, 2)
    return {
        'multiplier': multi,
        'mission_duration_seconds':
            duration if isinstance(duration, int) and 0 < duration <= 3600 else None,
        'mission_start_server': _valid_epoch(_one(settings, 3)),
        'boost_duration_seconds':
            _one(effect, 2) if isinstance(_one(effect, 2), int) and 0 < _one(effect, 2) <= 3600 else None,
        'target_type': _one(settings, 24),
        'reward_multiple': _one(effect, 3),
    }


def classify_task(fields):
    """Mirror challenge_tracker.decode_notification for task messages.

    Returns (classification_or_None, reason, info).  The classification
    names are the tracker's own event names; a None classification is
    what the tracker leaves unclassified, with the concrete reason.
    """
    if fields is None:
        return None, 'unparseable_payload', {}
    bid = _one(fields, 20)
    if not bid:
        return None, 'missing_battle_id_field_20', {}
    subtype = _one(fields, 2, default=0)
    if subtype == 0:
        bonus = _tracker_bonus(fields)
        if bonus['multiplier'] is None:
            return None, 'start_without_evidenced_bonus_multiplier', bonus
        return 'bonus_announced', 'start_with_sp_team_prompt_multi_arg', bonus
    if subtype == 1:
        return None, 'task_update_subtype_1_not_classified_by_tracker', {}
    if subtype == 2:
        result = _child(fields, 5)
        result_code = _one(result, 1)
        boost_start = _valid_epoch(_one(result, 3))
        if result_code != 2 or not boost_start:
            return None, 'settle_without_both_succeed_or_boost_start', {
                'result_code': result_code}
        return 'bonus_succeeded', 'settle_result_code_2_with_boost_start', {
            'boost_start_server': boost_start}
    if subtype == 3:
        return 'bonus_boost_ended', 'reward_settle_subtype_3', {}
    return None, 'subtype_value_%s_unknown' % subtype, {}


# --------------------------------------------------------------------------
# Optional schema decoding (TikTokLiveProto, guarded)
# --------------------------------------------------------------------------

_SCHEMA = {'available': False, 'task': None, 'gift': None}


def _load_schema():
    if _SCHEMA['task'] is not None or _SCHEMA['available']:
        return _SCHEMA['available']
    try:
        from TikTokLiveProto.v3.webcast.model import message as _m
        _SCHEMA['task'] = _m.WebcastLinkmicBattleTaskMessage
        _SCHEMA['gift'] = _m.WebcastGiftMessage
        _SCHEMA['available'] = True
    except Exception:
        _SCHEMA['available'] = False
    return _SCHEMA['available']


def _schema_parse(cls, payload):
    try:
        return cls().parse(payload)
    except Exception:
        pass
    try:
        return cls.FromString(payload)
    except Exception:
        return None


def schema_task_info(payload):
    """Schema-named field presence/values for a task payload, or None.

    Only values whose schema names are structural (enum names, field
    presence, pm_* prompt keys, config numbers) are returned.
    """
    if not _load_schema():
        return None
    obj = _schema_parse(_SCHEMA['task'], payload)
    if obj is None:
        return {'decode': 'failed'}
    info = {'decode': 'ok'}
    try:
        info['task_message_type'] = str(obj.task_message_type).split('.')[-1]
    except Exception:
        info['task_message_type'] = None
    info['present'] = [name for name in ('start', 'task_update', 'task_settle', 'reward')
                       if getattr(obj, name, None) is not None]
    update = getattr(obj, 'task_update', None)
    if update is not None:
        key = getattr(update, 'prompt_key', '') or ''
        info['update_prompt_key'] = key if _PROMPT_KEY_RE.match(key) else None
    return info


def schema_gift_diamonds(payload):
    """Diamond total for one gift payload via schema field names.

    Uses the schema fields literally named diamond_count (on the gift
    struct) and repeat_count.  Returns None when unavailable.
    """
    if not _load_schema():
        return None
    obj = _schema_parse(_SCHEMA['gift'], payload)
    if obj is None:
        return None
    gift = getattr(obj, 'gift', None)
    if gift is None or not hasattr(gift, 'diamond_count'):
        return None
    repeat = getattr(obj, 'repeat_count', 1) or 1
    try:
        return int(gift.diamond_count) * int(repeat)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Streaming probe reader
# --------------------------------------------------------------------------

class Record:
    __slots__ = ('method', 'msg_id', 'received_at', 'battle_id',
                 'task_class', 'task_reason', 'task_info', 'gift_diamonds')

    def __init__(self, method, msg_id, received_at):
        self.method = method
        self.msg_id = msg_id
        self.received_at = received_at
        self.battle_id = None          # payload-embedded only
        self.task_class = None
        self.task_reason = None
        self.task_info = {}
        self.gift_diamonds = None


def jst(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(JST).isoformat()


class Investigation:
    def __init__(self, window=90):
        self.window = window
        self.seen = set()
        self.method_counts = Counter()
        self.method_payload_bytes = Counter()
        self.omitted_counts = Counter()
        self.duplicate_lines = 0
        self.bad_lines = 0
        self.probe_versions = []
        self.method_count_rows = []      # (basename, counts dict)
        self.records = []                # Record, in arrival order
        self.gameplay = []               # (Record, payload bytes)
        self.battles = {}                # battle_id -> dict
        self.envelopes = defaultdict(list)  # received_at -> [Record]

    # -- ingestion ------------------------------------------------------
    def ingest_file(self, path):
        base = Path(path).name
        last_counts = None
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    self.bad_lines += 1
                    continue
                if not isinstance(row, dict):
                    self.bad_lines += 1
                    continue
                kind = row.get('kind')
                if kind == 'probe_version':
                    self.probe_versions.append({
                        'file': base,
                        'version': row.get('version'),
                        'received_at': row.get('received_at'),
                        'received_at_jst': jst(row.get('received_at')),
                    })
                    continue
                if kind == 'method_counts':
                    counts = row.get('counts')
                    if isinstance(counts, dict):
                        last_counts = counts
                    continue
                if kind != 'raw_notification':
                    continue
                self._ingest_notification(row)
        if last_counts is not None:
            self.method_count_rows.append((base, last_counts))

    def _ingest_notification(self, row):
        method = str(row.get('method') or '')
        msg_id = str(row.get('msg_id') or '')
        received_at = row.get('received_at')
        if not isinstance(received_at, (int, float)) or isinstance(received_at, bool):
            self.bad_lines += 1
            return
        payload = None
        omitted = 'omitted' in row
        if not omitted:
            encoded = row.get('payload_base64')
            if isinstance(encoded, str):
                try:
                    payload = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError):
                    payload = None
                    omitted = True
        if omitted:
            key = (method, msg_id, 'omitted', row.get('payload_bytes'))
            if key in self.seen:
                self.duplicate_lines += 1
                return
            self.seen.add(key)
            self.omitted_counts[method] += 1
            self.method_counts[method] += 1
            return
        if payload is None:
            payload = b''
        key = (method, msg_id, hashlib.sha256(payload).hexdigest())
        if key in self.seen:
            self.duplicate_lines += 1
            return
        self.seen.add(key)
        self.method_counts[method] += 1
        self.method_payload_bytes[method] += len(payload)

        record = Record(method, msg_id, float(received_at))
        fields = None
        if payload:
            try:
                fields = parse_fields(payload)
            except ValueError:
                fields = None
        record.battle_id = payload_battle_id(method, fields)
        if method == TASK_METHOD:
            record.task_class, record.task_reason, record.task_info = \
                classify_task(fields)
            record.task_info['schema'] = schema_task_info(payload)
        elif method == GIFT_METHOD:
            record.gift_diamonds = schema_gift_diamonds(payload)
        elif method == GAMEPLAY_METHOD:
            self.gameplay.append((record, payload))
        if method == LINKMIC_BATTLE_METHOD:
            self._note_battle_timing(record, fields)
        if record.battle_id is not None:
            battle = self._battle(record.battle_id)
            battle['methods'][method] += 1
            battle['first_seen'] = min(battle['first_seen'] or record.received_at,
                                       record.received_at)
            battle['last_seen'] = max(battle['last_seen'] or record.received_at,
                                      record.received_at)
        self.records.append(record)
        self.envelopes[record.received_at].append(record)

    def _battle(self, battle_id):
        return self.battles.setdefault(battle_id, {
            'battle_id': battle_id,
            'start_server': None, 'start_source': None,
            'finish_server': None,
            'first_seen': None, 'last_seen': None,
            'methods': Counter(),
        })

    def _note_battle_timing(self, record, fields):
        if record.battle_id is None:
            return
        action, start, finish = linkmic_battle_timing(fields)
        battle = self._battle(record.battle_id)
        if action == 4 and start is not None:
            battle['start_server'] = start
            battle['start_source'] = 'linkmic_battle_setting_start_time_ms'
        if action == 5 and finish is not None:
            battle['finish_server'] = finish

    # -- battle association for time-window-only records -----------------
    def associate_battle(self, record):
        """Return (battle_id_or_None, association_label)."""
        envelope_ids = {r.battle_id for r in self.envelopes.get(record.received_at, [])
                        if r.battle_id is not None}
        if len(envelope_ids) == 1:
            return envelope_ids.pop(), 'same_envelope_payload_battle_id'
        t = record.received_at
        windowed = []
        for battle in self.battles.values():
            start = battle['start_server'] or battle['first_seen']
            end = battle['finish_server'] or battle['last_seen']
            if start is not None and end is not None and start - 5 <= t <= end + 300:
                windowed.append(battle)
        if windowed:
            windowed.sort(key=lambda b: (b['start_server'] or b['first_seen'] or 0),
                          reverse=True)
            return windowed[0]['battle_id'], 'time_window_association'
        return None, 'none'

    def battle_start(self, battle_id):
        battle = self.battles.get(battle_id)
        if battle is None:
            return None, None
        if battle['start_server'] is not None:
            return battle['start_server'], battle['start_source']
        if battle['first_seen'] is not None:
            return battle['first_seen'], 'first_seen_received_at'
        return None, None

    # -- gameplay correlation --------------------------------------------
    def gameplay_report(self):
        fps = [fingerprint(payload) for _, payload in self.gameplay]
        occurrences = []
        for idx, ((record, payload), fp) in enumerate(zip(self.gameplay, fps)):
            battle_id, association = self.associate_battle(record)
            start, start_source = self.battle_start(battle_id)
            elapsed = None
            if start is not None:
                elapsed = round(record.received_at - start, 3)
            co_received = [
                {'method': r.method,
                 'battle_id': str(r.battle_id) if r.battle_id is not None else None,
                 'battle_id_source': 'payload' if r.battle_id is not None else None}
                for r in self.envelopes.get(record.received_at, [])
                if r is not record
            ]
            near_tasks = [r for r in self.records
                          if r.method == TASK_METHOD
                          and abs(r.received_at - record.received_at) <= 5]
            near_gifts = [r for r in self.records
                          if r.method == GIFT_METHOD
                          and abs(r.received_at - record.received_at) <= self.window]
            diamonds = [r.gift_diamonds for r in near_gifts]
            diamond_total = (sum(diamonds)
                             if diamonds and all(d is not None for d in diamonds)
                             else None)
            top_varints = {}
            try:
                for number, wtype, value in parse_fields(payload):
                    if wtype == 0:
                        top_varints.setdefault(str(number), []).append(value)
            except ValueError:
                pass
            coincidence = []
            if battle_id is not None:
                for number, values in top_varints.items():
                    if battle_id in values:
                        coincidence.append(number)
            battle_records = [r for r in self.records
                              if battle_id is not None and r.battle_id == battle_id]
            known = {
                'bonus_announced_tasks_in_battle':
                    sum(1 for r in battle_records if r.task_class == 'bonus_announced'),
                'unclassified_tasks_in_battle':
                    sum(1 for r in battle_records
                        if r.method == TASK_METHOD and r.task_class is None),
                'item_cards_in_battle':
                    sum(1 for r in battle_records if r.method == ITEM_CARD_METHOD),
                'bonus_config_observations': [
                    {'multiplier_from_prompt_args': r.task_info.get('multiplier'),
                     'target_type': r.task_info.get('target_type'),
                     'reward_multiple': r.task_info.get('reward_multiple')}
                    for r in battle_records
                    if r.method == TASK_METHOD and r.task_info.get('multiplier') is not None
                ],
            }
            if near_tasks:
                assessment = ASSESSMENT_CANDIDATE
                reasons = ['unregistered_method_name_contains_gameplay',
                           'task_message_within_5s_present',
                           'meaning_not_established_no_schema_no_screen_evidence']
            else:
                assessment = ASSESSMENT_UNKNOWN
                reasons = ['unregistered_method_name_contains_gameplay',
                           'no_correlating_task_message_within_5s',
                           'meaning_not_established_no_schema_no_screen_evidence']
            occurrences.append({
                'index': idx,
                'received_at': record.received_at,
                'received_at_jst': jst(record.received_at),
                'payload_bytes': len(payload),
                'associated_battle_id': str(battle_id) if battle_id is not None else None,
                'battle_association': association,
                'elapsed_from_battle_start_seconds': elapsed,
                'battle_start_source': start_source,
                'co_received': co_received,
                'tasks_within_5s': [{
                    'received_at_jst': jst(r.received_at),
                    'delta_seconds': round(r.received_at - record.received_at, 3),
                    'battle_id': str(r.battle_id) if r.battle_id is not None else None,
                    'tracker_classification': r.task_class,
                    'tracker_reason': r.task_reason,
                } for r in near_tasks],
                'gifts_within_window': {
                    'window_seconds': self.window,
                    'count': len(near_gifts),
                    'diamond_total_schema': diamond_total,
                },
                'top_level_varint_battle_id_value_coincidence_fields': coincidence,
                'known_event_contrast_in_battle': known,
                'assessment': assessment,
                'assessment_reasons': reasons,
            })
        return {
            'occurrences': occurrences,
            'structural_comparison': compare_fingerprints([
                {path: set(tokens) for path, tokens in fp.items()} for fp in fps]),
            'schema_decode': 'unavailable_no_schema_definition_in_tiktokliveproto_v3',
        }

    # -- full report -------------------------------------------------------
    def report(self, battle_filter=None):
        gameplay = self.gameplay_report()
        battles_out = []
        for battle in sorted(self.battles.values(),
                             key=lambda b: b['first_seen'] or 0):
            if battle_filter and str(battle['battle_id']) not in battle_filter:
                continue
            battles_out.append({
                'battle_id': str(battle['battle_id']),
                'start_server_jst': jst(battle['start_server']),
                'start_source': battle['start_source'],
                'finish_server_jst': jst(battle['finish_server']),
                'first_seen_jst': jst(battle['first_seen']),
                'last_seen_jst': jst(battle['last_seen']),
                'payload_confirmed_record_counts': dict(battle['methods']),
            })
        if battle_filter:
            wanted = set(battle_filter)
            gameplay['occurrences'] = [
                o for o in gameplay['occurrences']
                if o['associated_battle_id'] in wanted]
        tasks = [{
            'received_at_jst': jst(r.received_at),
            'battle_id': str(r.battle_id) if r.battle_id is not None else None,
            'tracker_classification': r.task_class,
            'tracker_reason': r.task_reason,
            'bonus_multiplier_from_prompt_args': r.task_info.get('multiplier'),
            'target_type': r.task_info.get('target_type'),
            'reward_multiple': r.task_info.get('reward_multiple'),
            'schema': r.task_info.get('schema'),
        } for r in self.records if r.method == TASK_METHOD]
        if battle_filter:
            tasks = [t for t in tasks if t['battle_id'] in battle_filter]
        return {
            'tool': 'first_challenge_investigator',
            'verdict_policy':
                'log_only_investigation; assessments limited to CANDIDATE/UNKNOWN; '
                'screen evidence is required for any stronger verdict and is not ingested',
            'schema_available': _SCHEMA['available'],
            'inputs': {
                'probe_version_rows': self.probe_versions,
                'method_counts_final_snapshots': [
                    {'file': base, 'counts': counts}
                    for base, counts in self.method_count_rows],
                'duplicate_lines_skipped': self.duplicate_lines,
                'unparseable_lines_skipped': self.bad_lines,
            },
            'method_counts': dict(self.method_counts),
            'method_payload_bytes': dict(self.method_payload_bytes),
            'omitted_payload_counts': dict(self.omitted_counts),
            'battles': battles_out,
            'task_messages': tasks,
            'gameplay': gameplay,
            'first_challenge_assessment': {
                'status': ASSESSMENT_UNKNOWN,
                'reasons': [
                    'no_schema_definition_for_gameplay_method_in_tiktokliveproto_v3',
                    'no_field_directly_evidences_a_first_gift_multiplier',
                    'no_screen_ground_truth_in_input',
                ],
            },
        }


# --------------------------------------------------------------------------
# Output writers
# --------------------------------------------------------------------------

def write_outputs(report, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / 'report.json', 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    with open(out / 'method_counts.csv', 'w', encoding='utf-8', newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow(['method', 'records', 'payload_bytes', 'omitted_payloads'])
        for method in sorted(report['method_counts']):
            writer.writerow([method, report['method_counts'][method],
                             report['method_payload_bytes'].get(method, 0),
                             report['omitted_payload_counts'].get(method, 0)])
    with open(out / 'battles.csv', 'w', encoding='utf-8', newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow(['battle_id', 'start_server_jst', 'start_source',
                         'finish_server_jst', 'first_seen_jst', 'last_seen_jst'])
        for battle in report['battles']:
            writer.writerow([battle['battle_id'], battle['start_server_jst'],
                             battle['start_source'], battle['finish_server_jst'],
                             battle['first_seen_jst'], battle['last_seen_jst']])
    with open(out / 'task_messages.csv', 'w', encoding='utf-8', newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow(['received_at_jst', 'battle_id', 'tracker_classification',
                         'tracker_reason', 'bonus_multiplier_from_prompt_args',
                         'target_type', 'reward_multiple'])
        for task in report['task_messages']:
            writer.writerow([task['received_at_jst'], task['battle_id'] or '',
                             task['tracker_classification'] or '',
                             task['tracker_reason'],
                             task['bonus_multiplier_from_prompt_args'] or '',
                             task['target_type'] or '',
                             task['reward_multiple'] or ''])
    with open(out / 'gameplay_occurrences.csv', 'w', encoding='utf-8',
              newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow(['index', 'received_at_jst', 'payload_bytes',
                         'associated_battle_id', 'battle_association',
                         'elapsed_from_battle_start_seconds', 'battle_start_source',
                         'tasks_within_5s', 'gifts_in_window', 'assessment'])
        for occ in report['gameplay']['occurrences']:
            writer.writerow([occ['index'], occ['received_at_jst'],
                             occ['payload_bytes'],
                             occ['associated_battle_id'] or '',
                             occ['battle_association'],
                             occ['elapsed_from_battle_start_seconds'] or '',
                             occ['battle_start_source'] or '',
                             len(occ['tasks_within_5s']),
                             occ['gifts_within_window']['count'],
                             occ['assessment']])


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Offline structural investigation of ChallengeProbe logs '
                    'for first-challenge candidate signals.')
    parser.add_argument('jsonl', nargs='+',
                        help='ChallengeProbe JSONL files (rotations included)')
    parser.add_argument('--battle', action='append', default=None,
                        help='restrict battle/task/gameplay detail to this '
                             'battle_id (repeatable)')
    parser.add_argument('--window', type=int, default=90,
                        help='gift correlation window in seconds (default 90)')
    parser.add_argument('--out', default='./investigator_out',
                        help='output directory (default ./investigator_out)')
    args = parser.parse_args(argv)

    investigation = Investigation(window=args.window)
    for path in args.jsonl:
        investigation.ingest_file(path)
    report = investigation.report(battle_filter=set(args.battle) if args.battle else None)
    write_outputs(report, args.out)

    print('records by method:', dict(investigation.method_counts))
    print('gameplay occurrences:', len(investigation.gameplay))
    print('battles (payload-confirmed):', len(investigation.battles))
    print('first challenge assessment:',
          report['first_challenge_assessment']['status'])
    print('outputs written to', args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
