"""Pulse Pro fixed observation: one registered TikTok account.

Standardises the existing fixed-observation mechanism (the one
``top_viewer.py`` has always used) for personal streamers:

- the streamer's own TikTok @ID is stored once in settings.json
  (``pro_tiktok_id``) and restored on the next launch;
- starting analysis spawns the existing collector
  (``core/viewer_collector.py``) as a child process with
  ``LIVEMETRY_OBSERVATION_MODE=fixed`` and ``LIVEMETRY_FIXED_URL``
  pointing at that account's LIVE page — the exact mechanism the
  standalone fixed viewer uses. In fixed mode the collector disables
  Battle Hunter auto-scrolling by itself and writes to the separate
  ``capture_fixed`` profile/database, never mixing with ``capture``;
- the target is also recorded in ``fixed_target.json`` in the same
  format ``top_viewer.py`` writes, so both entry points agree.

Ownership honesty: registering an ID is an observation-target
setting. There is NO account-ownership verification behind it, and
nothing in this module may present the registered ID as a verified
identity. Agency sharing is out of scope here (it needs separate
identity verification, consent and access control).

The controller is a process-wide singleton, like SessionRuntime:
leaving a UI page never stops the fixed collector.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    from .collection_health import read_health
    from .observation_profile import BASE, live_url
    from .settings import Settings
except ImportError:  # direct-script import style
    from collection_health import read_health
    from observation_profile import BASE, live_url
    from settings import Settings

SETTINGS_KEY = 'pro_tiktok_id'

# The fixed collector's stdout log (viewer_fixed.log) is append-only
# and the collector prints status lines on a 5-second cadence, so an
# unattended install grows it without bound. At spawn time (when no
# child of ours is running) an oversized log is rotated to a single
# .1 generation; collection behaviour itself is untouched.
LOG_ROTATE_BYTES = 20 * 1024 * 1024
FIXED_PROFILE = 'capture_fixed'


def normalize_tiktok_id(raw):
    """Normalize '@id', 'id' or a LIVE URL to the bare unique ID.

    Raises ValueError with the shared Japanese message from
    observation_profile.live_url for anything else.
    """
    url = live_url(str(raw or ''))
    return url.split('@', 1)[1].split('/', 1)[0]


def get_pro_tiktok_id():
    data = Settings.load()
    if not isinstance(data, dict):
        return ''
    return str(data.get(SETTINGS_KEY, '') or '').strip().lstrip('@')


def set_pro_tiktok_id(raw):
    """Validate and persist the registered @ID; returns the bare ID.

    Uses Settings.update(): the stored settings are re-read strictly
    (an existing-but-unreadable file raises SettingsLoadError instead
    of being overwritten), merged under a lock, and — when the ID is
    unchanged — the file is not rewritten at all. Save failures raise
    SettingsSaveError; callers must handle both.
    """
    tiktok_id = normalize_tiktok_id(raw)
    Settings.update({SETTINGS_KEY: tiktok_id})
    return tiktok_id


def _status_ts(status):
    """updated_at of a lock status/conflict dict as a float (0 when
    absent or unreadable, so a corrupt value never looks fresh)."""
    try:
        return float((status or {}).get('updated_at') or 0)
    except (TypeError, ValueError):
        return 0.0


def build_fixed_env(tiktok_id, base_env=None):
    """Environment for the fixed collector child process."""
    env = dict(os.environ if base_env is None else base_env)
    env.update(LIVEMETRY_OBSERVATION_MODE='fixed',
               LIVEMETRY_FIXED_URL=live_url(tiktok_id),
               PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    return env


def save_fixed_target(tiktok_id, base=None):
    """Record the target exactly like top_viewer.py does."""
    base = Path(base) if base is not None else BASE
    base.mkdir(parents=True, exist_ok=True)
    path = base / 'fixed_target.json'
    path.write_text(json.dumps({'url': live_url(tiktok_id)}), encoding='utf-8')
    return path


def status_from_health(running, health):
    """Map (process running?, collector_health.read_health) to a state.

    Returns dict(state, label, health_status, unique_id, last_data).
    'waiting' covers both 'collector starting' and 'streamer offline /
    not connected yet' — the two are not distinguishable from health
    data alone and are never presented as connected.
    """
    health = health or {}
    raw = str(health.get('status') or '')
    error_kind = str(health.get('error_kind') or '')
    if not running:
        state, label = 'stopped', '停止中'
    elif raw.startswith('接続中'):
        state, label = 'observing', '観測中（接続中）'
    elif raw.startswith('接続制限'):
        state, label = 'blocked', '接続制限で停止'
    elif raw.startswith('更新停止'):
        # A stale heartbeat wins over any recorded error kind: the
        # error may belong to an attempt the collector has since
        # stopped reporting on.
        state, label = 'stalled', '接続切れの可能性（ハートビート更新停止）'
    elif error_kind == 'not_found':
        state, label = 'not_found', '対象ユーザーが見つかりません（IDをご確認ください）'
    elif raw.startswith('未接続'):
        if error_kind == 'offline':
            state, label = 'waiting', '待機中（対象はオフラインです）'
        elif error_kind:
            state, label = 'waiting', '待機中（接続エラーのため再試行中）'
        else:
            state, label = 'waiting', '待機中（配信オフライン／未接続）'
    else:
        state, label = 'waiting', '待機中（起動直後／稼働情報なし）'
    return {'state': state, 'label': label, 'health_status': raw,
            'unique_id': health.get('unique_id') or '',
            'last_data': health.get('last_data'),
            'error_kind': error_kind}


class FixedObservationController:
    """Owns the fixed-mode collector child process (one per capture dir)."""

    def __init__(self, capture_dir=None, script_path=None):
        self.capture_dir = Path(capture_dir) if capture_dir is not None \
            else BASE / FIXED_PROFILE
        self._script = Path(script_path) if script_path is not None else \
            Path(__file__).resolve().parent / 'viewer_collector.py'
        self._process = None
        self._log_handle = None
        self.target_id = ''

    def is_running(self):
        return self._process is not None and self._process.poll() is None

    def start(self, tiktok_id):
        """Low-level spawn. False if already running.

        Kept for compatibility; product code should use start_ex(),
        which verifies target identity and profile exclusion before
        any session is bound to the collector.
        """
        tiktok_id = normalize_tiktok_id(tiktok_id)
        if self.is_running():
            return False
        return self._spawn(tiktok_id)

    def start_ex(self, tiktok_id, verify_timeout=10.0):
        """Safe start used by the product UI (Phase 4).

        Returns {'outcome': ..., 'target_id': ...} where outcome is:
        - 'started':      our collector started AND holds the profile
                          lock for exactly this ID;
        - 'already_same': our collector already observes this ID
                          (reuse it; the target provably matches);
        - 'already_other': our collector observes a DIFFERENT ID —
                          the caller must not bind a session;
        - 'conflict':     another process's fixed collector holds the
                          profile (target_id says whose, when known);
        - 'error':        spawn or lock verification failed (the
                          child, if any, has been stopped again).

        A session may only ever be bound on 'started'/'already_same',
        which is what guarantees the collector's actual target and
        the session's targets are identical.
        """
        try:
            from .fixed_lock import probe_locked, read_conflict, read_status
        except ImportError:
            from fixed_lock import probe_locked, read_conflict, read_status
        tiktok_id = normalize_tiktok_id(tiktok_id)
        if self.is_running():
            outcome = 'already_same' if self.target_id == tiktok_id else 'already_other'
            return {'outcome': outcome, 'target_id': self.target_id}
        if probe_locked():
            held = read_status() or {}
            return {'outcome': 'conflict',
                    'target_id': str(held.get('target_id') or '')}
        spawned_at = time.time()
        try:
            spawned = self._spawn(tiktok_id)
        except Exception as exc:
            return {'outcome': 'error', 'target_id': '',
                    'message': f'コレクタを起動できませんでした: {exc}'}
        if not spawned:
            return {'outcome': 'error', 'target_id': '',
                    'message': 'コレクタを起動できませんでした'}
        deadline = time.time() + verify_timeout
        while time.time() < deadline:
            if self._process.poll() is not None:
                break
            held = read_status() or {}
            # Corroborate the child's self-report WITHOUT comparing
            # pids: under a launcher-shim python (e.g. the Python
            # Install Manager), Popen.pid is the shim's pid and never
            # equals the interpreter's os.getpid() that the child
            # writes into the status. A held status for exactly this
            # target, written after our spawn, while the OS lock is
            # actually held, proves our collector owns the profile.
            if (held.get('state') == 'held'
                    and str(held.get('target_id') or '') == tiktok_id
                    and _status_ts(held) >= spawned_at
                    and probe_locked()):
                return {'outcome': 'started', 'target_id': tiktok_id}
            time.sleep(0.05)
        # A child that lost the lock race records its conflict in the
        # separate conflict file (it may not touch owner status). The
        # note is attributed by freshness, not pid (same shim reason).
        conf = read_conflict() or {}
        conflict = _status_ts(conf) >= spawned_at
        self.stop()
        if conflict:
            return {'outcome': 'conflict',
                    'target_id': str(conf.get('target_id') or '')}
        return {'outcome': 'error', 'target_id': '',
                'message': 'コレクタの起動（排他ロック取得）を確認できませんでした'}

    def _spawn(self, tiktok_id):
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        if getattr(sys, 'frozen', False):
            command = [sys.executable, '--viewer-collector']
            working_directory = str(Path(sys.executable).resolve().parent)
        else:
            if not self._script.exists():
                raise FileNotFoundError(f'固定観測コレクタが見つかりません: {self._script}')
            command = [sys.executable, '-u', str(self._script)]
            working_directory = str(self._script.parent.parent)
        # A previous child may have died without stop() running:
        # never overwrite its log handle without closing it first
        # (each respawn otherwise leaks one descriptor for the life
        # of the app process).
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None
        log_path = self.capture_dir / 'viewer_fixed.log'
        try:
            if log_path.exists() and log_path.stat().st_size > LOG_ROTATE_BYTES:
                os.replace(log_path, log_path.with_name(log_path.name + '.1'))
        except OSError:
            pass  # rotation is housekeeping; never block a start
        self._log_handle = open(log_path, 'a', encoding='utf-8', buffering=1)
        creationflags = 0
        if os.name == 'nt':
            creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self._process = subprocess.Popen(
            command, cwd=working_directory, stdout=self._log_handle,
            stderr=subprocess.STDOUT, creationflags=creationflags,
            env=build_fixed_env(tiktok_id))
        self.target_id = tiktok_id
        try:
            save_fixed_target(tiktok_id)
        except OSError:
            pass  # the env var is the operative setting; the file is a compat record
        return True

    def stop(self):
        """Stop OUR collector child only (never anyone else's process).

        Returns True only when no child of ours remains running, so
        the UI never claims 停止中 while a collector still writes.
        """
        process = self._process
        stopped = True
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=3)
                except Exception:
                    pass
            stopped = process.poll() is not None
        if stopped:
            self._process = None
            self.target_id = ''
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None
        return stopped

    def status(self, now=None):
        health = {}
        try:
            health = read_health(self.capture_dir, now=now)
        except Exception:
            health = {}
        result = status_from_health(self.is_running(), health)
        result['target_id'] = self.target_id
        result['running'] = self.is_running()
        if not self.is_running():
            # Another launcher's collector may hold this profile.
            try:
                from .fixed_lock import probe_locked, read_status
            except ImportError:
                from fixed_lock import probe_locked, read_status
            try:
                if probe_locked():
                    held = read_status() or {}
                    external = str(held.get('target_id')
                                   or health.get('unique_id') or '')
                    result['state'] = 'conflict'
                    result['external_target'] = external
                    result['label'] = ('別の固定観測が動作中です'
                                       + (f'（対象 @{external}）' if external else '')
                                       + '。この画面からは停止できません')
            except Exception:
                pass
        return result


_CONTROLLERS = {}


def get_fixed_controller(capture_dir=None):
    """Process-wide controller per capture dir (survives page changes)."""
    key = str(Path(capture_dir)) if capture_dir is not None else str(BASE / FIXED_PROFILE)
    controller = _CONTROLLERS.get(key)
    if controller is None:
        controller = FixedObservationController(capture_dir)
        _CONTROLLERS[key] = controller
    return controller


def stop_all_fixed_controllers():
    for controller in list(_CONTROLLERS.values()):
        try:
            controller.stop()
        except Exception:
            pass
