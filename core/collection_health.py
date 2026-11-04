"""Collector heartbeat and read-only health summaries."""
import json
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path


def heartbeat(directory, monitor, paused=False):
    temporary = None
    try:
        with monitor._lock:
            state = dict(updated_at=time.time(), pid=os.getpid(),
                         unique_id=monitor._unique_id, connected=monitor._connected,
                         blocked=monitor._connection_blocked, navigation_paused=paused)
            # Why the latest connection attempt ended, when the
            # monitor tracks it (core.battle_monitor). Reported only
            # for the CURRENT target: a previous target's error must
            # never be presented as this target's state.
            error = {}
            reporter = getattr(monitor, 'last_connection_error', None)
            if callable(reporter):
                try:
                    error = reporter() or {}
                except Exception:
                    error = {}
            if error.get('unique_id') == monitor._unique_id:
                state['error_kind'] = error.get('kind') or ''
                state['error_name'] = error.get('name') or ''
            else:
                state['error_kind'] = ''
                state['error_name'] = ''
        directory = Path(directory)
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=directory, delete=False) as f:
            temporary = f.name
            json.dump(state, f)
        os.replace(temporary, directory / 'collector_health.json')
    except Exception:
        pass  # Diagnostics must not stop collection.
    finally:
        if temporary and os.path.exists(temporary):
            try: os.unlink(temporary)
            except OSError: pass


def read_health(directory, now=None):
    directory = Path(directory)
    now = time.time() if now is None else now
    result = dict(status='稼働情報なし', unique_id='', heartbeat=None,
                  last_data=None, today=None, reason='記録なし', db_error=None,
                  error_kind='', error_name='')
    try:
        h = json.loads((directory / 'collector_health.json').read_text(encoding='utf-8-sig'))
        result.update(unique_id=h.get('unique_id') or '', heartbeat=h['updated_at'],
                      error_kind=h.get('error_kind') or '',
                      error_name=h.get('error_name') or '')
        age = now - float(h['updated_at'])
        if age < -5 or age > 30: result['status'] = '更新停止・停止の可能性'
        elif h.get('blocked'): result['status'] = '接続制限で停止'
        elif h.get('connected'): result['status'] = '接続中'
        else: result['status'] = '未接続・待機中'
        if 0 <= age <= 30 and h.get('navigation_paused'):
            result['status'] += ' ／ 自動移動一時停止'
    except (OSError, ValueError, KeyError, TypeError): pass
    db_path = directory / 'battle_dataset' / 'battles.sqlite3'
    if db_path.exists():
        try:
            db = sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0.2)
            try:
                day = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
                result['today'] = db.execute('SELECT count(*) FROM battles WHERE first_seen>=? AND first_seen<?',
                                            (day.timestamp(), (day+timedelta(days=1)).timestamp())).fetchone()[0]
                times = []
                for table in ('snapshots', 'comments', 'viewer_samples'):
                    try:
                        value = db.execute('SELECT max(received_at) FROM '+table).fetchone()[0]
                        if value is not None: times.append(float(value))
                    except sqlite3.OperationalError: pass
                result['last_data'] = max(times) if times else None
            finally: db.close()
        except (sqlite3.Error, ValueError, OSError): result['db_error'] = 'DBを読めません（使用中または形式違い）'
    try:
        with (directory / 'navigation_recovery.log').open('rb') as f:
            f.seek(0, 2); size=f.tell(); f.seek(max(0,size-32768))
            lines=f.read().decode('utf-8',errors='replace').splitlines()
        if lines: result['reason'] = lines[-1][:500]
    except OSError: pass
    return result
