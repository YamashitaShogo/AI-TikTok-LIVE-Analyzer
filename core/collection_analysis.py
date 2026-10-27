"""Descriptive statistics for retained battles. No API or AI calls."""
import csv
from collections import Counter, defaultdict
from statistics import median
from core.collection_store import CollectionStore, safe_payload, format_time


def host_score(payload):
    host = str(payload.get('host_user_id') or '')
    mode = payload.get('mode')
    if not host or mode not in ('team', 'individual'):
        return None
    matches = []
    for entry in payload.get('teams' if mode == 'team' else 'participants') or []:
        ids = ([str(user.get('user_id') or '') for user in entry.get('users') or []]
               if mode == 'team' else [str(entry.get('anchor_id') or entry.get('key') or '')])
        if host in ids:
            matches.append(entry)
    if len(matches) != 1 or matches[0].get('score_known') is False:
        return None
    try:
        value = int(matches[0]['score'])
        return value if value >= 0 else None
    except (ValueError, TypeError, KeyError):
        return None


def summary(database=None):
    store = CollectionStore(database)
    empty = {'total': 0, 'statuses': {}, 'finished_rate': 0.0, 'excluded': 0,
             'groups': [], 'recent': [], 'viewer_samples': 0, 'comments': 0, 'invalid_payloads': 0}
    if not store.database.exists():
        return empty
    with store._connect() as db:
        tables = store._tables(db)
        if 'battles' not in tables:
            return empty
        viewers = ({(r['unique_id'], r['battle_id']): dict(r) for r in db.execute(
            'SELECT unique_id, battle_id, count(*) samples, max(viewer_count) peak FROM viewer_samples GROUP BY unique_id,battle_id')}
        if 'viewer_samples' in tables else {})
        groups = defaultdict(lambda: {'total': 0, 'finished': 0, 'scores': [], 'peaks': []})
        statuses = Counter()
        recent = []
        invalid = 0
        for row in db.execute('SELECT * FROM battles ORDER BY first_seen DESC, battle_id DESC'):
            payload = safe_payload(row['payload'])
            if not payload:
                invalid += 1
            status = row['status']
            statuses[status] += 1
            mode = payload.get('mode') or 'unknown'
            key = (row['unique_id'], mode)
            group = groups[key]
            group['unique_id'] = row['unique_id']
            group['mode'] = mode
            group.setdefault('nickname', str(payload.get('host_nickname') or row['unique_id']))
            group['total'] += 1
            if status == 'finished':
                group['finished'] += 1
                score = host_score(payload)
                if score is not None:
                    group['scores'].append(score)
                peak = viewers.get((row['unique_id'], row['battle_id']), {}).get('peak')
                if peak is not None:
                    group['peaks'].append(peak)
            if len(recent) < 100:
                recent.append({'unique_id': row['unique_id'], 'battle_id': row['battle_id'],
                               'nickname': str(payload.get('host_nickname') or row['unique_id']),
                               'first_seen': row['first_seen'], 'status': status})
        results = []
        for group in groups.values():
            scores = group.pop('scores')
            peaks = group.pop('peaks')
            group.update(score_samples=len(scores), median_score=median(scores) if scores else None,
                         max_score=max(scores) if scores else None,
                         peak_samples=len(peaks), median_peak=median(peaks) if peaks else None)
            results.append(group)
        results.sort(key=lambda g: (g['mode'], -(g['median_score'] if g['median_score'] is not None else -1)))
        total = sum(statuses.values())
        return {'total': total, 'statuses': dict(statuses),
                'finished_rate': statuses.get('finished', 0) / total * 100 if total else 0,
                'excluded': store._count(db, tables, 'excluded_battles'), 'groups': results,
                'recent': recent, 'viewer_samples': store._count(db, tables, 'viewer_samples'),
                'comments': store._count(db, tables, 'comments'), 'invalid_payloads': invalid}


def timeline(unique_id, battle_id, database=None):
    store = CollectionStore(database)
    detail = store.detail(unique_id, battle_id)
    if detail is None:
        return None
    with store._connect() as db:
        tables = store._tables(db)
        rows = list(db.execute('SELECT received_at, payload FROM snapshots WHERE unique_id=? AND battle_id=? ORDER BY received_at',
                               (str(unique_id), int(battle_id)))) if 'snapshots' in tables else []
    parsed = [(row['received_at'], safe_payload(row['payload'])) for row in rows]
    starts = [float(p.get('start_time_ms') or 0) / 1000 for _, p in parsed if p.get('start_time_ms')]
    start = starts[0] if starts else None
    base = start if start else detail['first_seen']
    scores = []
    for received, payload in parsed:
        value = host_score(payload)
        if value is not None:
            scores.append({'seconds': max(0, received-base), 'value': value, 'timestamp': received})
    viewers = [{'seconds': max(0, row['received_at']-base), 'value': row['viewer_count'], 'timestamp': row['received_at']}
               for row in detail['viewers']]
    result = detail['result']
    peak_increases = []
    for previous, current in zip(scores, scores[1:]):
        if current['value'] > previous['value']:
            peak_increases.append({'from_seconds': previous['seconds'], 'to_seconds': current['seconds'],
                                   'increase': current['value']-previous['value'],
                                   'interval_seconds': current['seconds']-previous['seconds']})
    peak_increases.sort(key=lambda p: p['increase'], reverse=True)
    return {'detail': detail, 'scores': scores, 'viewers': viewers,
            'axis_label': 'バトル開始からの経過秒' if start else '記録開始からの経過秒（開始時刻不明）',
            'largest_increases': peak_increases[:3],
            'score_label': '本人チームの合計スコア' if result.get('mode') == 'team' else '本人スコア'}


def export_summary(groups, destination):
    columns = ['nickname', 'unique_id', 'mode', 'total', 'finished', 'score_samples', 'median_score', 'max_score', 'peak_samples', 'median_peak']
    with open(destination, 'w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in columns} for row in groups)
    return len(groups)
