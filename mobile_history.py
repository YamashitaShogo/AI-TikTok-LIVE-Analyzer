"""Read-only LAN history viewer. Run from the Pulse project directory."""
import argparse
from contextlib import closing
from datetime import datetime, timezone, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import secrets
import socket
import sqlite3
from urllib.parse import parse_qs, urlsplit

BASE = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'AI-TikTok-LIVE-Analyzer'
JST = timezone(timedelta(hours=9))

def database(source):
    return BASE / ('capture_fixed' if source == 'top' else 'capture') / 'battle_dataset' / 'battles.sqlite3'

def connect(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=3)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    db.execute('BEGIN')
    return db

def payload(raw):
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except (ValueError, TypeError):
        return {}

def number(v):
    try:
        n = float(v)
        return n if math.isfinite(n) and n >= 0 else None
    except (TypeError, ValueError):
        return None

def scores(p):
    host = str(p.get('host_user_id') or '')
    out = {}
    if p.get('mode') == 'team':
        for t in p.get('teams') or []:
            users = t.get('users') or []
            own = host and any(str(u.get('user_id')) == host for u in users)
            key = ('自チーム ' if own else 'チーム ') + str(t.get('team_id', '?'))
            out[key] = None if t.get('score_known') is False else number(t.get('score'))
            for u in users:
                if host and str(u.get('user_id')) == host:
                    out['自枠（個人）'] = None if u.get('score_known') is False else number(u.get('score'))
    else:
        for u in p.get('participants') or []:
            uid = str(u.get('anchor_id') or u.get('key') or '')
            key = '自枠' if host and uid == host else '参加者 ' + uid
            out[key] = None if u.get('score_known') is False else number(u.get('score'))
    return out

def summary(row):
    p = payload(row['payload'])
    return dict(uid=row['unique_id'], bid=str(row['battle_id']),
                name=p.get('host_nickname') or row['unique_id'],
                at=row['first_seen'], status=row['status'], scores=scores(p))

def overview(source, search='', page=0):
    path = database(source)
    if not path.exists():
        return dict(rows=[], count=0, message='この収集先にはまだデータがありません。')
    with closing(connect(path)) as db:
        term = search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        where = " WHERE unique_id LIKE ? ESCAPE '\\' OR payload LIKE ? ESCAPE '\\'" if term else ''
        args = (f'%{term}%', f'%{term}%') if term else ()
        count = db.execute('SELECT COUNT(*) FROM battles' + where, args).fetchone()[0]
        rows = db.execute('SELECT * FROM battles' + where + ' ORDER BY first_seen DESC,battle_id DESC LIMIT 30 OFFSET ?', (*args, page * 30))
        return dict(rows=[summary(r) for r in rows], count=count, message='')

def detail(source, uid, bid):
    path = database(source)
    with closing(connect(path)) as db:
        key = (uid, int(bid))
        row = db.execute('SELECT * FROM battles WHERE unique_id=? AND battle_id=?', key).fetchone()
        if row is None:
            raise LookupError('バトルが見つかりません。')
        out = summary(row)
        p = payload(row['payload'])
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        out['points'] = []
        if 'snapshots' in tables:
            for r in db.execute('SELECT received_at,payload FROM snapshots WHERE unique_id=? AND battle_id=? ORDER BY received_at', key):
                state = payload(r['payload'])
                if not state.get('host_user_id'):
                    state['host_user_id'] = p.get('host_user_id')
                out['points'].append(dict(at=r['received_at'], values=scores(state)))
        out['viewers'] = [dict(at=r[0], values={'視聴者数':number(r[1])}) for r in db.execute('SELECT received_at,viewer_count FROM viewer_samples WHERE unique_id=? AND battle_id=? ORDER BY received_at', key)] if 'viewer_samples' in tables else []
        cutoff = number(p.get('finished_at')) or 1e99
        out['comments'] = [dict(at=r[0], name=r[1], text=r[2]) for r in db.execute('SELECT received_at,username,comment FROM comments WHERE unique_id=? AND battle_id=? AND received_at<? ORDER BY received_at DESC LIMIT 300', (*key, cutoff + 1))] if 'comments' in tables else []
        out['events'] = []
        out['event_warning'] = ''
        try:
            from core.battle_timeline import load
            from core.timeline_display import describe_event
            fmt = lambda t: datetime.fromtimestamp(float(t), JST).strftime('%H:%M:%S')
            for e in load(db, tables, *key, legacy_path=path.parent.parent / 'battle_items.json'):
                out['events'].append(dict(at=e['at'], end=e.get('end'), text=describe_event(e, p, fmt)))
        except (ImportError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            out['event_warning'] = 'イベント表示を読み込めません: ' + type(exc).__name__
        if 'battle_timeline' in tables:
            out['raw_event_counts'] = {r[0]:r[1] for r in db.execute('SELECT kind,COUNT(*) FROM battle_timeline WHERE unique_id=? AND battle_id=? GROUP BY kind', key)}
        else:
            out['raw_event_counts'] = {}
    out['note'] = ''
    notes = path.with_name('battle_notes.sqlite3')
    if notes.exists():
        try:
            with closing(connect(notes)) as db:
                r = db.execute('SELECT note FROM battle_notes WHERE unique_id=? AND battle_id=?', key).fetchone()
                if r: out['note'] = r[0]
        except sqlite3.Error:
            out['note'] = 'メモを読み込めませんでした。'
    return out

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Access URLs contain the temporary pairing token.

    def send(self, status, body, mime='application/json; charset=utf-8', cookie=None, location=None):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        if cookie: self.send_header('Set-Cookie', cookie)
        if location: self.send_header('Location', location)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlsplit(self.path)
        q = parse_qs(u.query)
        token = q.get('token', [''])[0]
        if u.path == '/' and token and secrets.compare_digest(token, self.server.token):
            self.send(303, '', cookie='pulse_mobile=' + self.server.token + '; HttpOnly; SameSite=Strict; Path=/', location='/')
            return
        cookies = SimpleCookie()
        try: cookies.load(self.headers.get('Cookie', ''))
        except Exception: pass
        cookie = cookies.get('pulse_mobile')
        if not cookie or not secrets.compare_digest(cookie.value, self.server.token):
            self.send(401, 'PCに表示された接続URLから開いてください。', 'text/plain; charset=utf-8')
            return
        try:
            source = q.get('source', ['normal'])[0]
            if source not in ('normal', 'top'): raise ValueError('収集先が不正です')
            if u.path == '/':
                self.send(200, Path(__file__).with_suffix('.html').read_bytes(), 'text/html; charset=utf-8')
            elif u.path == '/api/list':
                data = overview(source, q.get('q', [''])[0][:200], max(0, min(100000, int(q.get('page', ['0'])[0]))))
                self.send(200, json.dumps(data, ensure_ascii=False, allow_nan=False))
            elif u.path == '/api/detail':
                data = detail(source, q.get('uid', [''])[0], q.get('bid', [''])[0])
                self.send(200, json.dumps(data, ensure_ascii=False, allow_nan=False))
            else: self.send(404, '{}')
        except (ValueError, LookupError):
            self.send(400, json.dumps({'error':'指定したバトルを読み込めません。履歴を更新してください。'}, ensure_ascii=False))
        except (sqlite3.Error, OSError):
            self.send(503, json.dumps({'error':'データを読み込めません。収集先・DBの存在を確認して再試行してください。'}, ensure_ascii=False))

def main():
    parser = argparse.ArgumentParser(description='スマホで収集履歴を閲覧（同じWi-Fi内）')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('0.0.0.0', args.port), Handler)
    server.daemon_threads = True
    server.token = secrets.token_urlsafe(24)
    ips = sorted({a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET) if not a[4][0].startswith('127.')})
    print('スマホをPCと同じWi-Fiにつなぎ、次のURLをSafari/Chromeで開いてください。', flush=True)
    for ip in ips or ['127.0.0.1']:
        print(f'http://{ip}:{args.port}/?token={server.token}', flush=True)
    print(f'PC確認用: http://127.0.0.1:{args.port}/?token={server.token}', flush=True)
    print('このPowerShellは開いたまま。終了は Ctrl+C。再起動すると接続URLは変わります。', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__ == '__main__':
    main()
