"""Recorded battle timing; missing timing never becomes a guessed five minutes."""
import math

class BattleClock:
    def __init__(self, detail):
        self.start = self.end = None
        timings = []
        candidates = [detail.get('result') or {}] + [p.get('result') or {} for p in detail.get('score_snapshots', [])]
        for data in candidates:
            try:
                start = float(data.get('start_time_ms', 0))/1000
                duration = float(data.get('duration_seconds', 0))
                if math.isfinite(start) and math.isfinite(duration) and start > 946684800 and 0 < duration <= 3600:
                    timings.append((start, start+duration))
            except (TypeError, ValueError):
                pass
        if timings and all(abs(a-timings[0][0]) <= 1 and abs(b-timings[0][1]) <= 1 for a,b in timings):
            self.start, self.end = timings[0]

    def label(self, ts, fallback):
        if self.end is None: return fallback(ts)
        if ts < self.start: seconds, prefix = round(self.start-ts), '開始前 '
        elif ts > self.end: seconds, prefix = round(ts-self.end), '終了後 +'
        else: seconds, prefix = round(self.end-ts), ''
        return f'{prefix}{seconds//60}:{seconds%60:02d}'

    def bounds(self, times):
        values = list(times)
        if self.end is not None: values += [self.start, self.end]
        if not values: return 0,1
        return min(values), max(min(values)+1, max(values))

    def ticks(self, lo, hi):
        if self.end is None: return [lo+(hi-lo)*i/5 for i in range(6)]
        step = 60 if hi-lo>180 else 30 if hi-lo>90 else 10 if hi-lo>30 else 5 if hi-lo>10 else 1
        ticks = [self.end-n*step for n in range(math.ceil((self.end-hi)/step), math.floor((self.end-lo)/step)+1)]
        return sorted([lo]+[t for t in ticks if t-lo>=step*.35 and hi-t>=step*.35]+[hi])

    @property
    def caption(self):
        return 'バトル残り時間（通知の制限時間基準）' if self.end is not None else '開始・制限時間未取得：記録時刻で表示'
