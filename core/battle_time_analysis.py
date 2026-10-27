"""Conservative phase summaries from recorded samples, without interpolation."""
from collections import defaultdict
from statistics import median
from core.collection_store import CollectionStore, safe_payload
from core.streamer_tiers import individual_score, numeric

PHASES = ('序盤', '中盤', '終盤')


def spread(values):
    if not values:
        return {'count': 0, 'min': None, 'median': None, 'max': None, 'median_absolute_deviation': None}
    middle = median(values)
    return {'count': len(values), 'min': min(values), 'median': middle, 'max': max(values),
            'median_absolute_deviation': median(abs(v-middle) for v in values)}


def phase_measure(points, begin, end, cumulative=False):
    # Unknown scores remain explicit barriers; never connect across them.
    selected = sorted((t,v) for t,v in points if begin <= t <= end)
    intervals = [(a,b) for a,b in zip(selected,selected[1:])
                 if 0 < b[0]-a[0] <= 30 and a[1] is not None and b[1] is not None]
    reset = cumulative and any(b[1] < a[1] for a,b in intervals)
    covered = sum(b[0]-a[0] for a,b in intervals)
    fraction = min(1, covered/(end-begin)) if end>begin else 0
    full = bool(intervals and selected[0][0]-begin <= 15 and end-selected[-1][0] <= 15
                and fraction >= .8 and not reset and all(v is not None for _,v in selected))
    change = sum(b[1]-a[1] for a,b in intervals) if cumulative and intervals and not reset else None
    if not cumulative and full:
        change = selected[-1][1]-selected[0][1]
    return {'change': change, 'adequate_coverage': full, 'coverage_fraction': round(fraction,3),
            'score_decrease_detected': bool(reset)}


def battle_phases(snapshots, viewers):
    timing = [(numeric(p.get('start_time_ms')), numeric(p.get('duration_seconds'))) for _,p in snapshots]
    timing = [(s/1000,d) for s,d in timing if s and d and 30 <= d <= 3600]
    if not timing:
        return None
    start,duration = timing[-1]
    if any(abs(s-start)>1 or abs(d-duration)>1 for s,d in timing):
        return None
    scores = [(t,individual_score(p)) for t,p in snapshots]
    phases = []
    for i,name in enumerate(PHASES):
        begin,end = start+duration*i/3,start+duration*(i+1)/3
        score = phase_measure(scores,begin,end,True)
        audience = phase_measure(viewers,begin,end)
        phases.append({'phase':name, 'score':score, 'viewers':audience,
                       'jointly_observed':score['adequate_coverage'] and audience['adequate_coverage']})
    return phases


def temporal_summary(database=None, now=None, days=30):
    import time
    now = time.time() if now is None else now
    cutoff = now-days*86400
    store=CollectionStore(database)
    result={'streamers':{},'latest_record_at':None,'finished_records':0,
            'method':'開始時刻と試合時間から3等分。区間端15秒以内、記録間隔30秒以内で区間80%以上を観測した場合のみ比較。補間なし。'}
    if not store.database.exists():return result
    with store._connect() as db:
        tables=store._tables(db)
        if 'battles' not in tables:return result
        batches=list(db.execute('SELECT * FROM battles WHERE first_seen BETWEEN ? AND ?', (cutoff,now)))
        result['latest_record_at']=max((r['last_seen'] for r in batches),default=None)
        series=defaultdict(list);viewers=defaultdict(list)
        for table,columns,target in [('snapshots','received_at,payload',series),('viewer_samples','received_at,viewer_count',viewers)]:
            if table not in tables:continue
            for r in db.execute(f'SELECT unique_id,battle_id,{columns} FROM {table} WHERE received_at BETWEEN ? AND ? ORDER BY received_at',(cutoff,now)):
                value=safe_payload(r['payload']) if table=='snapshots' else numeric(r['viewer_count'])
                target[(r['unique_id'],r['battle_id'])].append((r['received_at'],value))
    groups=defaultdict(lambda:{'scores':[],'viewers':[],'timing_unknown':0,'records':0,
                              'phases':[{'score':[],'viewers':[],'joint':0} for _ in PHASES]})
    for r in batches:
        if r['status']!='finished':continue
        p=safe_payload(r['payload'])
        if p.get('gameplay_option')=='MATCH_OPTION_SPECIFIC_GIFT':continue
        score=individual_score(p)
        if score is None:continue
        key=(r['unique_id'],r['battle_id'])
        finish=numeric(p.get('finished_at'))
        end=min(r['last_seen'],finish) if finish else r['last_seen']
        observed=[(t,v) for t,v in viewers[key] if r['first_seen']<=t<=end and v is not None]
        if not observed:continue
        group=groups[r['unique_id']]
        group['records']+=1;result['finished_records']+=1
        group['scores'].append(score);group['viewers'].append(median(v for _,v in observed))
        snapshots=[(t,payload) for t,payload in series[key] if r['first_seen']<=t<=end]
        phases=battle_phases(snapshots,observed)
        if phases is None:group['timing_unknown']+=1;continue
        for i,phase in enumerate(phases):
            for metric in ('score','viewers'):
                if phase[metric]['adequate_coverage']:
                    group['phases'][i][metric].append(phase[metric]['change'])
            group['phases'][i]['joint']+=int(phase['jointly_observed'])
    for uid,g in groups.items():
        result['streamers'][uid]={'records':g['records'],'timing_unknown':g['timing_unknown'],
            'final_score_spread':spread(g['scores']),'viewer_median_spread':spread(g['viewers']),
            'phases':[{'phase':name,'score_increase':spread(v['score']),
                       'viewer_change':spread(v['viewers']),'jointly_observed_records':v['joint'],
                       'score_missing_records':g['records']-len(v['score']),
                       'viewer_missing_records':g['records']-len(v['viewers'])}
                      for name,v in zip(PHASES,g['phases'])]}
    return result
