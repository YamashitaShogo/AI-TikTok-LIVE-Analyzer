"""Relative streamer tiers from retained, completed battles; never mutates DB."""
import csv
import math
import time
from collections import defaultdict
from statistics import median
from core.collection_store import CollectionStore, safe_payload
from core.score_known import known_score


def numeric(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def individual_score(payload):
    host = str(payload.get('host_user_id') or '')
    if not host:
        return None
    if payload.get('mode') == 'team':
        candidates = [u for t in payload.get('teams', []) if isinstance(t, dict)
                      for u in (t.get('users') or []) if isinstance(u, dict)
                      and str(u.get('user_id') or '') == host]
    elif payload.get('mode') == 'individual':
        candidates = [u for u in (payload.get('participants') or []) if isinstance(u, dict)
                      and str(u.get('anchor_id') or u.get('key') or '') == host]
    else:
        return None
    if len(candidates) != 1:
        return None
    value = known_score(candidates[0])
    return numeric(value) if value is not None else None


def rank_top(value, population):
    # Midrank: tied values always receive the same classification.
    return 100 * (sum(v > value for v in population) + .5 * sum(v == value for v in population)) / len(population)


def classify(score_top, viewers_top):
    if score_top <= 20 and viewers_top <= 20:
        return 'Top層'
    if score_top <= 20:
        return '高スコア型'
    if viewers_top <= 20:
        return '集客型'
    if score_top <= 60 and viewers_top <= 60:
        return '中堅層'
    return 'その他'


def tier_summary(database=None, now=None, days=30):
    now = time.time() if now is None else now
    cutoff = now - days * 86400
    output = {'rows': [], 'days': days, 'cohort': 0, 'generated_at': now}
    store = CollectionStore(database)
    if not store.database.exists():
        return output
    with store._connect() as db:
        tables = store._tables(db)
        if 'battles' not in tables:
            return output
        samples = defaultdict(list)
        if 'viewer_samples' in tables:
            for r in db.execute('SELECT unique_id,battle_id,received_at,viewer_count FROM viewer_samples WHERE received_at BETWEEN ? AND ? ORDER BY received_at', (cutoff, now)):
                value = numeric(r['viewer_count'])
                if value is not None:
                    samples[(r['unique_id'], r['battle_id'])].append((r['received_at'], value))
        groups = {}
        for r in db.execute('SELECT * FROM battles WHERE first_seen BETWEEN ? AND ? ORDER BY first_seen DESC', (cutoff, now)):
            p = safe_payload(r['payload'])
            uid = r['unique_id']
            g = groups.setdefault(uid, {'unique_id': uid, 'nickname': p.get('host_nickname') or uid,
                'total': 0, 'unfinished': 0, 'restricted': 0, 'missing_score': 0,
                'missing_viewers': 0, 'excluded': 0, 'scores': [], 'viewers': [], 'paired': [], 'viewer_changes': []})
            g['total'] += 1
            if r['status'] != 'finished':
                g['unfinished'] += 1
                continue
            if p.get('gameplay_option') == 'MATCH_OPTION_SPECIFIC_GIFT':
                g['restricted'] += 1
                continue
            score = individual_score(p)
            if score is None:
                g['missing_score'] += 1
            else:
                g['scores'].append(score)
            # Exclude post-battle result-screen viewer notifications.
            start = numeric(p.get('start_time_ms'))
            start = max(r['first_seen'], start / 1000) if start else r['first_seen']
            finish = numeric(p.get('finished_at'))
            end = min(r['last_seen'], finish) if finish else r['last_seen']
            observed = [(t, v) for t, v in samples.get((uid, r['battle_id']), []) if start <= t <= end]
            if not observed:
                g['missing_viewers'] += 1
                continue
            audience = median(v for _, v in observed)
            g['viewers'].append(audience)
            if score is not None:
                g['paired'].append((score, audience))
            if len(observed) >= 2 and end > start:
                early = [v for t, v in observed if t <= start + (end-start)*.25]
                late = [v for t, v in observed if t >= start + (end-start)*.75]
                if early and late:
                    g['viewer_changes'].append(median(late)-median(early))
        if 'excluded_battles' in tables:
            for r in db.execute('SELECT unique_id,count(*) n FROM excluded_battles WHERE excluded_at BETWEEN ? AND ? GROUP BY unique_id', (cutoff, now)):
                if r['unique_id'] in groups:
                    groups[r['unique_id']]['excluded'] = r['n']
    for g in groups.values():
        paired = g.pop('paired')
        scores, viewers, changes = g.pop('scores'), g.pop('viewers'), g.pop('viewer_changes')
        g.update(valid_battles=len(paired), score_battles=len(scores), viewer_battles=len(viewers),
            median_score=median([s for s,v in paired]) if paired else (median(scores) if scores else None),
            median_viewers=median([v for s,v in paired]) if paired else (median(viewers) if viewers else None),
            median_viewer_change=median(changes) if changes else None,
            change_battles=len(changes), tier='判定待ち', confidence='判定待ち', score_top=None, viewers_top=None)
    cohort = [g for g in groups.values() if g['valid_battles'] > 0]
    output['cohort'] = len(cohort)
    for g in cohort:
        if len(cohort) < 5:
            g['confidence'] = '比較対象不足（5人必要）'
            continue
        g['score_top'] = rank_top(g['median_score'], [r['median_score'] for r in cohort])
        g['viewers_top'] = rank_top(g['median_viewers'], [r['median_viewers'] for r in cohort])
        g['tier'] = classify(g['score_top'], g['viewers_top'])
        g['confidence'] = '確定（現集計）' if g['valid_battles'] >= 10 else '暫定（10件未満）'
    output['rows'] = sorted(groups.values(), key=lambda g: (g['tier'] == '判定待ち', -(g['median_score'] or 0), g['unique_id']))
    return output


def export_tiers(rows, destination):
    fields = ['nickname','unique_id','tier','confidence','median_score','median_viewers','valid_battles',
              'score_top','viewers_top','median_viewer_change','change_battles','total','unfinished',
              'missing_score','missing_viewers','restricted','excluded']
    with open(destination, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
