"""Read-only access to the battle collection database."""
from .battle_timeline import load as load_timeline

try:
    from . import score_known as _score_known
except ImportError:
    import score_known as _score_known
import csv
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
DEFAULT_DATABASE = (Path(os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))) /
                    'AI-TikTok-LIVE-Analyzer' / 'capture' / 'battle_dataset' / 'battles.sqlite3')
STATUS_LABELS = {'finished': '終了通知あり', 'timeout_fallback': '時間で終了判定',
                 'interrupted': '途中終了', 'active': '終了未検知', 'cut_short': '打ち切り'}


def safe_payload(raw):
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def format_time(timestamp):
    try:
        return datetime.fromtimestamp(float(timestamp), JST).strftime('%m/%d %H:%M:%S')
    except (ValueError, TypeError, OverflowError, OSError):
        return '不明'


def score_text(payload):
    mode = payload.get('mode')
    entries = list(payload.get('teams' if mode == 'team' else 'participants') or [])
    host_id = str(payload.get('host_user_id') or '')
    matches = []
    if host_id:
        for index, entry in enumerate(entries):
            ids = ([str(u.get('user_id') or '') for u in entry.get('users') or []]
                   if mode == 'team' else [str(entry.get('anchor_id') or entry.get('key') or '')])
            if host_id in ids:
                matches.append(index)
    identified = len(matches) == 1
    if identified:
        entries.insert(0, entries.pop(matches[0]))
    grouped_battle = mode == 'team' and len(entries) == 2 and any(
        len(entry.get('users') or []) > 1 for entry in entries
    )
    scores = []
    for index, entry in enumerate(entries):
        text = _score_known.score_text(entry)
        if grouped_battle and identified and index == 0:
            users = [u for u in entry.get('users') or [] if str(u.get('user_id') or '') == host_id]
            own_text = '不明'
            if len(users) == 1:
                own_text = _score_known.score_text(users[0])
            text += f'（{own_text}）'
        scores.append(text)
    return ('  VS  '.join(scores) or 'スコア未取得', identified)


class CollectionStore:
    def __init__(self, database=None):
        self.database = Path(database or DEFAULT_DATABASE)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.database.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            yield db
        finally:
            db.close()

    @staticmethod
    def _tables(db):
        return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    @staticmethod
    def _count(db, tables, table):
        return db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] if table in tables else 0

    def overview(self, search='', offset=0, limit=50):
        empty = {'stats': {k: 0 for k in ('battles', 'snapshots', 'comments', 'viewer_samples', 'excluded_battles')},
                 'rows': [], 'matched': 0, 'exists': False}
        if not self.database.exists():
            return empty
        with self._connect() as db:
            tables = self._tables(db)
            if 'battles' not in tables:
                return empty
            stats = {key: self._count(db, tables, key) for key in empty['stats']}
            # Escape LIKE wildcards so IDs such as abc_def are searched literally.
            term = str(search).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            where = "WHERE unique_id LIKE ? ESCAPE '\\' OR payload LIKE ? ESCAPE '\\'" if term else ''
            args = (f'%{term}%', f'%{term}%') if term else ()
            matched = db.execute('SELECT count(*) FROM battles ' + where, args).fetchone()[0]
            rows = []
            for record in db.execute('SELECT * FROM battles ' + where + ' ORDER BY first_seen DESC, battle_id DESC LIMIT ? OFFSET ?',
                                     (*args, max(1, min(int(limit), 100)), max(0, int(offset)))):
                item = dict(record)
                payload = safe_payload(item.pop('payload'))
                item['result'] = payload
                item['nickname'] = str(payload.get('host_nickname') or item['unique_id'])
                item['score_text'], item['host_identified'] = score_text(payload)
                rows.append(item)
            return {'stats': stats, 'rows': rows, 'matched': matched, 'exists': True}

    def detail(self, unique_id, battle_id):
        if not self.database.exists():
            return None
        with self._connect() as db:
            tables = self._tables(db)
            if 'battles' not in tables:
                return None
            key = (str(unique_id), int(battle_id))
            row = db.execute('SELECT * FROM battles WHERE unique_id=? AND battle_id=?', key).fetchone()
            if not row:
                return None
            item = dict(row)
            payload = safe_payload(item.pop('payload'))
            item['result'] = payload
            item['score_text'], item['host_identified'] = score_text(payload)
            item['timeline'] = load_timeline(db, tables, *key, legacy_path=self.database.parent.parent / 'battle_items.json')
            item['score_snapshots'] = [{'received_at': r['received_at'], 'result': safe_payload(r['payload'])} for r in db.execute('SELECT received_at,payload FROM snapshots WHERE unique_id=? AND battle_id=? ORDER BY received_at', key)] if 'snapshots' in tables else []
            item['snapshot_count'] = db.execute('SELECT count(*) FROM snapshots WHERE unique_id=? AND battle_id=?', key).fetchone()[0] if 'snapshots' in tables else 0
            cutoff = float(payload.get('finished_at') or 0)
            cutoff = cutoff + 1 if cutoff else 1e99
            count_args = (*key, cutoff)
            item['comment_count'] = db.execute('SELECT count(*) FROM comments WHERE unique_id=? AND battle_id=? AND received_at<?', count_args).fetchone()[0] if 'comments' in tables else 0
            item['comments'] = [dict(r) for r in db.execute('SELECT received_at, username, comment FROM comments WHERE unique_id=? AND battle_id=? AND received_at<? ORDER BY received_at DESC LIMIT 300', count_args)] if 'comments' in tables else []
            item['comments'].reverse()
            item['viewers'] = [dict(r) for r in db.execute('SELECT received_at, elapsed_seconds, viewer_count FROM viewer_samples WHERE unique_id=? AND battle_id=? ORDER BY received_at', key)] if 'viewer_samples' in tables else []
            return item

    def export_viewers(self, unique_id, battle_id, destination):
        detail = self.detail(unique_id, battle_id)
        if detail is None:
            raise ValueError('選択したバトルは現在保存されていません。更新してください。')
        with Path(destination).open('w', encoding='utf-8-sig', newline='') as out:
            writer = csv.writer(out)
            writer.writerow(['unique_id', 'battle_id', 'captured_at_JST', 'elapsed_seconds', 'viewer_count'])
            for row in detail['viewers']:
                writer.writerow([unique_id, str(battle_id), datetime.fromtimestamp(row['received_at'], JST).isoformat(),
                                 row['elapsed_seconds'], row['viewer_count']])
        return len(detail['viewers'])
