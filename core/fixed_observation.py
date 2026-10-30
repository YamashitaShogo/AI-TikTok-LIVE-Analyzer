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
    """Validate and persist the registered @ID; returns the bare ID."""
    tiktok_id = normalize_tiktok_id(raw)
    data = Settings.load()
    if not isinstance(data, dict):
        data = {}
    data[SETTINGS_KEY] = tiktok_id
    Settings.save(data)
    return tiktok_id


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
    if not running:
        state, label = 'stopped', '停止中'
    elif raw.startswith('接続中'):
        state, label = 'observing', '観測中（接続中）'
    elif raw.startswith('接続制限'):
        state, label = 'blocked', '接続制限で停止'
    elif raw.startswith('更新停止'):
        state, label = 'stalled', '接続切れの可能性（ハートビート更新停止）'
    elif raw.startswith('未接続'):
        state, label = 'waiting', '待機中（配信オフライン／未接続）'
    else:
        state, label = 'waiting', '待機中（起動直後／稼働情報なし）'
    return {'state': state, 'label': label, 'health_status': raw,
            'unique_id': health.get('unique_id') or '',
            'last_data': health.get('last_data')}


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
        """Start the fixed collector for the ID. False if already running."""
        tiktok_id = normalize_tiktok_id(tiktok_id)
        if self.is_running():
            return False
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        if getattr(sys, 'frozen', False):
            command = [sys.executable, '--viewer-collector']
            working_directory = str(Path(sys.executable).resolve().parent)
        else:
            if not self._script.exists():
                raise FileNotFoundError(f'固定観測コレクタが見つかりません: {self._script}')
            command = [sys.executable, '-u', str(self._script)]
            working_directory = str(self._script.parent.parent)
        self._log_handle = open(self.capture_dir / 'viewer_fixed.log', 'a',
                                encoding='utf-8', buffering=1)
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
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None

    def status(self, now=None):
        health = {}
        try:
            health = read_health(self.capture_dir, now=now)
        except Exception:
            health = {}
        result = status_from_health(self.is_running(), health)
        result['target_id'] = self.target_id
        result['running'] = self.is_running()
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
