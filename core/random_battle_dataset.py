"""Durable battle collection. Standard library only; no AI API calls."""
from contextlib import contextmanager
import csv
import hashlib
import json
import logging
import os
import random
import sqlite3
import threading
import time
from pathlib import Path

if __package__:
    from .observation_profile import CAPTURE, PROFILE, FIXED
else:
    from observation_profile import CAPTURE, PROFILE, FIXED

try:
    from core.low_score_policy import exclusion_reason
except ModuleNotFoundError:
    from low_score_policy import exclusion_reason

DEFAULT_CAPTURE = CAPTURE


class RandomBattleDatasetRecorder:
    def __init__(self, sample_probability=1.0, capture_dir=None):
        self.capture_dir = Path(capture_dir or DEFAULT_CAPTURE)
        self.dataset_dir = self.capture_dir / 'battle_dataset'
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.dataset_dir / 'battles.sqlite3'
        self.sample_probability = max(0.0, min(1.0, float(sample_probability)))
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._stream = None
        self._selected = {}
        self._last_error = None
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS battles (
                    unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
                    first_seen REAL NOT NULL, last_seen REAL NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(unique_id, battle_id));
                CREATE TABLE IF NOT EXISTS snapshots (
                    unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
                    received_at REAL NOT NULL, fingerprint TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(unique_id, battle_id, fingerprint));
                CREATE TABLE IF NOT EXISTS comments (
                    unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
                    received_at REAL NOT NULL, username TEXT NOT NULL,
                    comment TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS excluded_battles (
                    unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
                    reason TEXT NOT NULL, excluded_at REAL NOT NULL,
                    PRIMARY KEY(unique_id, battle_id));
                CREATE TABLE IF NOT EXISTS viewer_samples (
                    unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
                    received_at REAL NOT NULL, elapsed_seconds REAL,
                    viewer_count INTEGER NOT NULL,
                    PRIMARY KEY(unique_id, battle_id, received_at));
                CREATE INDEX IF NOT EXISTS snapshot_battle ON snapshots(unique_id, battle_id, received_at);
                CREATE INDEX IF NOT EXISTS comment_battle ON comments(unique_id, battle_id, received_at);
            ''')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA busy_timeout=10000')
            with db:
                yield db
        finally:
            db.close()

    def set_current_stream(self, unique_id):
        stream = str(unique_id or '').strip().lstrip('@') or None
        with self._lock:
            if self._stream and self._stream != stream:
                with self._connect() as db:
                    db.execute("UPDATE battles SET status='interrupted' WHERE unique_id=? AND status='active'", (self._stream,))
            self._stream = stream

    def exclude_battle(self, unique_id, battle_id, reason):
        key = (str(unique_id or '').strip().lstrip('@'), int(battle_id or 0))
        if not key[0] or key[1] <= 0:
            return
        with self._lock, self._connect() as db:
            db.execute('INSERT OR IGNORE INTO excluded_battles VALUES (?, ?, ?, ?)', (*key, reason, time.time()))
            for table in ('comments', 'viewer_samples', 'snapshots', 'battles'):
                db.execute(f'DELETE FROM {table} WHERE unique_id=? AND battle_id=?', key)

    def record_battle(self, payload):
        if not isinstance(payload, dict):
            return False
        stream = str(payload.get('unique_id') or '').strip().lstrip('@')
        battle_id = int(payload.get('battle_id') or 0)
        if not stream or battle_id <= 0:
            return False
        key = (stream, battle_id)
        with self._lock:
            reason = exclusion_reason(payload)
            if reason and not FIXED:
                self.exclude_battle(stream, battle_id, reason)
                return False
            if key not in self._selected:
                self._selected[key] = random.random() < self.sample_probability
            if not self._selected[key]:
                return False
            if FIXED:
                payload = dict(payload)
                payload['observation_mode'] = 'fixed'
                payload['exclusion_flag'] = reason or (
                    'specific_gift' if payload.get('gameplay_option') == 'MATCH_OPTION_SPECIFIC_GIFT' else None)
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            fingerprint = hashlib.sha256(raw.encode()).hexdigest()
            status = 'active' if payload.get('active') else str(payload.get('reason') or 'finished')
            now = time.time()
            with self._connect() as db:
                if db.execute('SELECT 1 FROM excluded_battles WHERE unique_id=? AND battle_id=?', key).fetchone():
                    return False
                previous = db.execute('SELECT status FROM battles WHERE unique_id=? AND battle_id=?', key).fetchone()
                # Never revive a finished battle from a late polling snapshot.
                if previous and previous[0] not in ('active', 'interrupted') and status == 'active':
                    return False
                added = db.execute('INSERT OR IGNORE INTO snapshots VALUES (?, ?, ?, ?, ?)', (*key, now, fingerprint, raw)).rowcount
                if not added:
                    return False
                db.execute('''INSERT INTO battles VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(unique_id, battle_id) DO UPDATE SET
                    last_seen=excluded.last_seen, status=excluded.status, payload=excluded.payload''',
                    (*key, now, now, status, raw))
            return True

    def record_comments(self, unique_id, battle_id, comments):
        stream = str(unique_id or '').strip().lstrip('@')
        battle_id = int(battle_id or 0)
        if not stream or battle_id <= 0:
            return
        with self._lock, self._connect() as db:
            battle = db.execute('SELECT status, payload FROM battles WHERE unique_id=? AND battle_id=?', (stream, battle_id)).fetchone()
            if not battle or battle[0] != 'active':
                return
            current = json.loads(battle[1])
            started_at = float(current.get('start_time_ms') or 0) / 1000

            for item in comments:
                message = str(item.get('comment') or '')
                if not message:
                    continue
                username = str(item.get('username') or '')
                timestamp = float(item.get('timestamp') or time.time())
                if started_at and timestamp < started_at:
                    continue
                raw = json.dumps([stream, battle_id, timestamp, username, message], ensure_ascii=False)
                fingerprint = hashlib.sha256(raw.encode()).hexdigest()
                db.execute('INSERT OR IGNORE INTO comments VALUES (?, ?, ?, ?, ?, ?)',
                           (stream, battle_id, timestamp, username, message, fingerprint))

    def record_viewers(self, unique_id, battle_id, viewer_count, received_at=None):
        stream = str(unique_id or '').strip().lstrip('@')
        battle_id = int(battle_id or 0)
        if isinstance(viewer_count, bool):
            return False
        count = int(viewer_count)
        if count < 0 or not stream or battle_id <= 0:
            return False
        now = time.time() if received_at is None else float(received_at)
        with self._lock, self._connect() as db:
            row = db.execute('SELECT status, payload FROM battles WHERE unique_id=? AND battle_id=?', (stream, battle_id)).fetchone()
            if not row or row[0] != 'active':
                return False
            payload = json.loads(row[1])
            started_at = float(payload.get('start_time_ms') or 0) / 1000
            elapsed = round(now - started_at, 3) if started_at else None
            if elapsed is not None and elapsed < 0:
                return False
            return bool(db.execute('INSERT OR IGNORE INTO viewer_samples VALUES (?, ?, ?, ?, ?)',
                        (stream, battle_id, now, elapsed, count)).rowcount)

    def export_viewers_csv(self, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as db, destination.open('w', encoding='utf-8-sig', newline='') as out:
            writer = csv.writer(out)
            writer.writerow(['unique_id', 'battle_id', 'received_at', 'elapsed_seconds', 'viewer_count'])
            for row in db.execute('SELECT * FROM viewer_samples ORDER BY received_at'):
                writer.writerow(row)
        return destination

    def poll_once(self):
        with self._lock:
            stream = self._stream
            if not stream:
                return
            path = self.capture_dir / 'latest_battle.json'
            if not path.exists():
                return
            payload = json.loads(path.read_text(encoding='utf-8'))
            if str(payload.get('unique_id') or '').lstrip('@') == stream:
                self.record_battle(payload)

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True, name='BattleDataset')
            self._thread.start()
            return True

    def _run(self):
        while not self._stop.is_set():
            try:
                self.poll_once()
                self._last_error = None
            except Exception as exc:
                self._last_error = str(exc)
                logging.exception('Battle dataset collection failed')
            self._stop.wait(1)

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=12)
        self.set_current_stream(None)

    def status(self):
        with self._lock, self._connect() as db:
            return {'database': str(self.db_path), 'stream': self._stream,
                    'battles': db.execute('SELECT count(*) FROM battles').fetchone()[0],
                    'snapshots': db.execute('SELECT count(*) FROM snapshots').fetchone()[0],
                    'comments': db.execute('SELECT count(*) FROM comments').fetchone()[0],
                    'viewer_samples': db.execute('SELECT count(*) FROM viewer_samples').fetchone()[0],
                    'excluded_battles': db.execute('SELECT count(*) FROM excluded_battles').fetchone()[0],
                    'last_error': self._last_error}

    def export_jsonl(self, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as db, destination.open('w', encoding='utf-8') as out:
            for stream, battle_id, first, last, status, raw in db.execute('SELECT * FROM battles ORDER BY first_seen'):
                comments = [{'timestamp': t, 'username': u, 'comment': c} for t, u, c in db.execute(
                    'SELECT received_at, username, comment FROM comments WHERE unique_id=? AND battle_id=? ORDER BY received_at', (stream, battle_id))]
                viewers = [{'timestamp': t, 'elapsed_seconds': elapsed, 'viewer_count': count}
                    for t, elapsed, count in db.execute('SELECT received_at, elapsed_seconds, viewer_count FROM viewer_samples WHERE unique_id=? AND battle_id=? ORDER BY received_at', (stream, battle_id))]
                result = json.loads(raw)
                finished_at = float(result.get('finished_at') or 0)
                if finished_at:
                    # Finish events have whole-second timestamps.
                    comments = [c for c in comments if c['timestamp'] < finished_at + 1]
                out.write(json.dumps({'unique_id': stream, 'battle_id': battle_id,
                    'first_seen': first, 'last_seen': last, 'status': status,
                    'result': result, 'comments': comments, 'viewer_timeline': viewers}, ensure_ascii=False) + '\n')
        return destination


_default_recorder = None
_default_lock = threading.Lock()


def record_battle_payload(payload):
    """Called at every monitor commit, so short-lived finish events are retained."""
    global _default_recorder
    with _default_lock:
        if _default_recorder is None:
            _default_recorder = RandomBattleDatasetRecorder()
        return _default_recorder.record_battle(payload)


def record_viewer_count(unique_id, battle_id, count, received_at=None):
    global _default_recorder
    with _default_lock:
        if _default_recorder is None:
            _default_recorder = RandomBattleDatasetRecorder()
        return _default_recorder.record_viewers(unique_id, battle_id, count, received_at)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Livemetry Pulse battle collection')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--export', type=Path)
    parser.add_argument('--export-viewers', type=Path)
    args = parser.parse_args()
    recorder = RandomBattleDatasetRecorder()
    if args.export_viewers:
        print(recorder.export_viewers_csv(args.export_viewers))
    elif args.export:
        print(recorder.export_jsonl(args.export))
    else:
        print(json.dumps(recorder.status(), ensure_ascii=False, indent=2))
