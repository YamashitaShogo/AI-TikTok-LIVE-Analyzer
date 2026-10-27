"""Isolated, bounded Top battle discovery; credentials travel only over stdin."""
import atexit
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def candidate(state, uid, now):
    if not state.get('active') or state.get('unique_id') != uid:
        return False
    try:
        end = float(state['start_time_ms']) / 1000 + float(state['duration_seconds'])
        return float(state['start_time_ms']) / 1000 <= now < end
    except (KeyError, ValueError, TypeError):
        return False


class TopWatch:
    def __init__(self, base):
        self.base = Path(base)
        self.work = self.base / 'top_watch'
        self.children = {}
        self.cursor = 0
        self.paused = False
        self.next_start = 0
        self.last_move = 0
        self.seen = set()
        self.offline_until = {}
        self.subscription_until = read_json(self.base / 'top_subscription_cooldowns.json')
        self.gate_host = ''
        self.gate_since = None
        self.message = '待機中'
        atexit.register(self.close)

    def close(self):
        for uid in list(self.children):
            self.remove(uid)

    def remove(self, uid):
        child, _, log, _ = self.children.pop(uid)
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        log.close()

    def tick(self, url, current, monitor, subscription_gate=False, log=None):
        config = read_json(self.base / 'top_watchlist.json')
        ids = list(dict.fromkeys(x for x in config.get('ids', [])
                                if isinstance(x, str) and re.fullmatch(r'[A-Za-z0-9_.]{1,64}', x)))[:100]
        now = time.time()
        match = re.search(r'tiktok\.com/@([^/]+)/live', url or '')
        host = match.group(1) if match else ''
        # Only a visible playback gate can override the current battle lock.
        mono = time.monotonic()
        if subscription_gate and host:
            if self.gate_host != host or self.gate_since is None:
                self.gate_host, self.gate_since = host, mono
        else:
            self.gate_host, self.gate_since = '', None
        gated = bool(subscription_gate and host and self.gate_since is not None
                     and mono - self.gate_since >= 10)
        self.subscription_until = {
            uid: until for uid, until in self.subscription_until.items()
            if uid in ids and isinstance(until, (int, float)) and until > now}
        target = None
        offline_host = getattr(monitor, 'offline_unique_id', lambda: None)() == host and bool(host)
        if offline_host:
            self.offline_until[host] = now + 300
        self.offline_until = {uid: until for uid, until in self.offline_until.items()
                              if uid in ids and until > now}
        with monitor._lock:
            auth = [monitor._session_id, monitor._tt_target_idc]
        if monitor.is_connection_blocked():
            self.paused = True
        for uid, (proc, started, log, folder) in list(self.children.items()):
            health = read_json(folder / 'watch_health.json')
            if health.get('offline') and now - health.get('at', 0) < 15:
                self.offline_until[uid] = now + 300
            if health.get('blocked'):
                self.paused = True
            state = read_json(folder / 'latest_battle.json')
            key = (uid, state.get('battle_id'))
            fresh = now - health.get('at', 0) < 15
            if uid in ids and uid not in self.subscription_until and fresh and candidate(state, uid, now) and key not in self.seen and uid != host:
                if target is None or ids.index(uid) < ids.index(target[0]):
                    target = (uid, key)
            if uid not in ids or uid == host or uid in self.offline_until or uid in self.subscription_until or proc.poll() is not None or now - started >= 180:
                self.remove(uid)
        if self.paused or not config.get('enabled'):
            self.close()
            self.message = '接続制限：監視停止。制限解消後にViewerを再起動' if self.paused else '監視停止中'
            target = None
        elif not all(auth):
            self.message = '固定ViewerでTikTokにログインしてください'
            target = None
        else:
            slots = max(1, min(3, int(config.get('slots', 2))))
            while len(self.children) > slots:
                self.remove(next(reversed(self.children)))
            if len(self.children) < slots and now >= self.next_start and ids:
                for _ in ids:
                    uid = ids[self.cursor % len(ids)]
                    self.cursor += 1
                    if uid == host or uid in self.children or uid in self.offline_until or uid in self.subscription_until:
                        continue
                    self.spawn(uid, auth, now)
                    self.next_start = now + 30
                    break
            self.message = 'バトル観測中：移動しません' if current.get('active') else '登録枠のバトルを探索中'
            if offline_host and not current.get('active'):
                if target is None:
                    # Continue down the list, wrapping only after reaching its end.
                    start = ids.index(host) + 1 if host in ids else 0
                    ordered = ids[start:] + ids[:start]
                    next_uid = next((uid for uid in ordered if uid != host and uid not in self.offline_until and uid not in self.subscription_until), None)
                    if next_uid:
                        target = (next_uid, None)
                self.message = '配信なし：次の枠を確認（接続間隔30秒）' if target else '全候補が配信なし：5分後に再確認'

        subscription_target = None
        if gated and config.get('enabled') and not self.paused and all(auth):
            if host not in self.subscription_until:
                self.subscription_until[host] = now + 1800
                write_json(self.base / 'top_subscription_cooldowns.json', self.subscription_until)
                message = f'TOP SUBSCRIPTION: @{host} playback gated for 10s; cooldown=1800s'
                (log or print)(message)
            # Follow registration order; do not select this room's stale battle.
            start = ids.index(host) + 1 if host in ids else 0
            subscription_target = next(
                (uid for uid in ids[start:] + ids[:start]
                 if uid != host and uid not in self.subscription_until
                 and uid not in self.offline_until), None)
            self.message = ('サブスク限定：次の登録枠へ移動' if subscription_target
                            else 'サブスク限定：移動可能な登録枠なし（待機中）')
            target = None

        write_json(self.base / 'top_watch_status.json', {
            'at': now, 'message': self.message, 'watching': list(self.children),
            'waiting': [uid for uid in ids if uid not in self.children and uid != host], 'viewer': host, 'offline': list(self.offline_until),
            'subscription_cooldowns': self.subscription_until})
        if subscription_target:
            self.last_move = now
            return f'https://www.tiktok.com/@{subscription_target}/live'
        # Current receiver owns battle lock; never navigate away from an active battle.
        if target and not current.get('active') and now - self.last_move >= (30 if offline_host else 45) and not self.paused:
            uid, key = target
            if key is not None:
                self.seen.add(key)
            self.last_move = now
            return f'https://www.tiktok.com/@{uid}/live'
        return None

    def spawn(self, uid, auth, now):
        sandbox = self.work / uid
        folder = sandbox / 'AI-TikTok-LIVE-Analyzer' / 'capture_fixed'
        folder.mkdir(parents=True, exist_ok=True)
        for name in ('latest_battle.json', 'watch_health.json'):
            (folder / name).unlink(missing_ok=True)
        env = os.environ.copy()
        env.update(LOCALAPPDATA=str(sandbox), LIVEMETRY_OBSERVATION_MODE='fixed', PYTHONIOENCODING='utf-8')
        env.pop('LIVEMETRY_TOP_WATCH', None)
        log = (sandbox / 'watch.log').open('w', encoding='utf-8')
        child = subprocess.Popen([sys.executable, '-u', str(Path(__file__).resolve()), '--worker', uid],
                                 env=env, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                                 text=True, encoding='utf-8')
        try:
            child.stdin.write(json.dumps(auth) + '\n')
            child.stdin.close()
        except Exception:
            child.terminate()
            child.wait(timeout=3)
            log.close()
            raise
        self.children[uid] = child, now, log, folder


def worker(uid):
    auth = json.loads(sys.stdin.readline())
    from observation_profile import CAPTURE
    from battle_monitor import BattleMonitor
    monitor = BattleMonitor()
    monitor.set_auth_cookies(*auth)
    # Discovery only: suppress database/debug writes and expose battle state to parent.
    monitor._write_payload = lambda payload: write_json(CAPTURE / 'latest_battle.json', payload)
    monitor.start(uid)
    try:
        deadline = time.monotonic() + 185
        while monitor.is_running() and time.monotonic() < deadline:
            write_json(CAPTURE / 'watch_health.json', {'at': time.time(), 'blocked': monitor.is_connection_blocked(),
                    'offline': monitor.offline_unique_id() == uid})
            time.sleep(2)
        write_json(CAPTURE / 'watch_health.json', {'at': time.time(), 'blocked': monitor.is_connection_blocked(),
                    'offline': monitor.offline_unique_id() == uid})
    finally:
        monitor.stop()


if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--worker':
    worker(sys.argv[2])
