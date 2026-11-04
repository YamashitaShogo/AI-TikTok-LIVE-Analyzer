"""Mission safety tests (2026-10-31 autonomous quality mission).

Reproduction-first tests for the audit findings on PR #12:

M1-M4  Connection-error kinds (offline / not_found / rate_limit /
       other) never reached collector_health, the session sampler,
       the fixed-observation status or the report, so a session that
       collected nothing looked identical whether the target was
       offline, the ID did not exist, or login was required.
M5     FixedObservationController._spawn leaked the previous log
       handle and the fixed log grew without bound; start_ex's
       verify budget (2.5s) is too small for a cold PyInstaller start.
M6     fixed_lock.write_status used a fixed temp file name shared by
       every writer process.
M7     The startup license window wrote settings.json through its own
       lenient path: a temporarily unreadable file was replaced by a
       dict holding only the two license keys (all other settings
       lost), with a fixed temp name and no write retry.
M8     The AI page read/wrote ./settings.json relative to the CWD
       while the Settings page and the auto analyzer use the real
       AppData settings.json, so a prompt saved on the AI page never
       reached the analysis that uses it.
M9     Report page: no warning while a running fixed session has
       never connected (zero data), and a runtime error while stopping
       a session escaped the button handler after the collector had
       already stopped.

Run: python tests/mission_safety_test.py   (GUI parts need a display)
"""
import inspect
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_mission_')
os.environ['LOCALAPPDATA'] = _TMP  # must precede core imports (BASE)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pyaudiowpatch  # noqa: F401
except ImportError:
    sys.modules['pyaudiowpatch'] = types.ModuleType('pyaudiowpatch')

passed = failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f'PASS {name}')
    else:
        failed += 1
        print(f'FAIL {name}')


# ---------------------------------------------------------------- M1
from core.battle_monitor import classify_connection_error

check('M1a offline classification',
      classify_connection_error('UserOfflineError') == 'offline')
check('M1b not-found classification',
      classify_connection_error('UserNotFoundError') == 'not_found')
check('M1c rate-limit classification',
      classify_connection_error('SignatureRateLimitError') == 'rate_limit')
check('M1d other errors stay generic, never a specific kind',
      classify_connection_error('TimeoutError') == 'error'
      and classify_connection_error('') == '')

from core import collection_health


class _StubMonitor:
    def __init__(self, error):
        self._lock = threading.Lock()
        self._unique_id = 'ghost'
        self._connected = False
        self._connection_blocked = False
        self._error = error

    def last_connection_error(self):
        return self._error


health_dir = Path(_TMP) / 'healthcase'
health_dir.mkdir(parents=True, exist_ok=True)
collection_health.heartbeat(
    health_dir, _StubMonitor({'kind': 'not_found',
                              'name': 'UserNotFoundError',
                              'unique_id': 'ghost'}))
raw = json.loads((health_dir / 'collector_health.json').read_text('utf-8'))
check('M1e heartbeat carries the error kind for the current target',
      raw.get('error_kind') == 'not_found')
health = collection_health.read_health(health_dir)
check('M1f read_health exposes the error kind',
      health.get('error_kind') == 'not_found')
check('M1g read_health status strings are unchanged (sampler compat)',
      health.get('status') == '未接続・待機中')

collection_health.heartbeat(
    health_dir, _StubMonitor({'kind': 'not_found',
                              'name': 'UserNotFoundError',
                              'unique_id': 'someone_else'}))
raw2 = json.loads((health_dir / 'collector_health.json').read_text('utf-8'))
check('M1h an error for a previous target is not reported as current',
      not raw2.get('error_kind'))


class _LegacyMonitor:
    """A monitor without last_connection_error must not break heartbeat."""

    def __init__(self):
        self._lock = threading.Lock()
        self._unique_id = 'ghost'
        self._connected = False
        self._connection_blocked = False


collection_health.heartbeat(health_dir, _LegacyMonitor())
check('M1i heartbeat tolerates a monitor without error reporting',
      (health_dir / 'collector_health.json').exists())

# ---------------------------------------------------------------- M2
import core.fixed_observation as fx

nf = fx.status_from_health(
    True, {'status': '未接続・待機中', 'unique_id': 'ghost',
           'error_kind': 'not_found'})
check('M2a not_found is its own state, not plain waiting',
      nf['state'] == 'not_found' and '見つかりません' in nf['label'])
off = fx.status_from_health(
    True, {'status': '未接続・待機中', 'unique_id': 'alice',
           'error_kind': 'offline'})
check('M2b offline waiting says the target is offline',
      off['state'] == 'waiting' and 'オフライン' in off['label'])
err = fx.status_from_health(
    True, {'status': '未接続・待機中', 'unique_id': 'alice',
           'error_kind': 'error'})
check('M2c generic errors say retrying after a connection error',
      err['state'] == 'waiting' and '接続エラー' in err['label'])
plain = fx.status_from_health(
    True, {'status': '未接続・待機中', 'unique_id': 'alice'})
check('M2d no error info keeps the previous waiting label',
      plain['state'] == 'waiting' and '未接続' in plain['label'])
stale = fx.status_from_health(
    True, {'status': '更新停止・停止の可能性', 'unique_id': 'ghost',
           'error_kind': 'not_found'})
check('M2e a stale heartbeat still wins over a recorded error kind',
      stale['state'] == 'stalled')

# ---------------------------------------------------------------- M3
from core.observation_sessions import SessionStore, SessionSampler
import core.collection_health as ch_module

cap3 = Path(_TMP) / 'cap3'
cap3.mkdir(parents=True, exist_ok=True)
store3 = SessionStore(cap3)
sess3 = store3.start_session('固定観測', ['ghost'], profile='capture_fixed',
                             now=1_000.0)
sampler = SessionSampler(store3, sess3['session_id'], cap3)
real_read_health = ch_module.read_health
fake = {'status': '未接続・待機中', 'last_data': None,
        'error_kind': 'not_found'}
ch_module.read_health = lambda d, now=None: dict(fake)
try:
    sampler._sample_once(now=1_010.0)
    sampler._sample_once(now=1_020.0)
    events = store3.get_session(sess3['session_id'])['events']
    errs = [e for e in events if e['kind'] == 'connection_error']
    check('M3a sampler records a not_found connection_error event once',
          len(errs) == 1 and errs[0]['detail'].get('kind') == 'not_found')
    fake['error_kind'] = ''
    sampler._sample_once(now=1_030.0)
    fake['error_kind'] = 'not_found'
    sampler._sample_once(now=1_040.0)
    events = store3.get_session(sess3['session_id'])['events']
    errs = [e for e in events if e['kind'] == 'connection_error']
    check('M3b the event re-arms after the error clears', len(errs) == 2)
finally:
    ch_module.read_health = real_read_health

# ---------------------------------------------------------------- M4
from core.unattended_report import build_report

SCHEMA = """
CREATE TABLE battles (unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
    first_seen REAL NOT NULL, last_seen REAL NOT NULL, status TEXT NOT NULL,
    payload TEXT NOT NULL, PRIMARY KEY(unique_id, battle_id));
CREATE TABLE snapshots (unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
    received_at REAL NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
    UNIQUE(unique_id, battle_id, fingerprint));
CREATE TABLE comments (unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
    received_at REAL NOT NULL, username TEXT NOT NULL, comment TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE);
CREATE TABLE excluded_battles (unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
    reason TEXT NOT NULL, excluded_at REAL NOT NULL, PRIMARY KEY(unique_id, battle_id));
CREATE TABLE viewer_samples (unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
    received_at REAL NOT NULL, elapsed_seconds REAL, viewer_count INTEGER NOT NULL,
    PRIMARY KEY(unique_id, battle_id, received_at));
"""
cap4 = Path(_TMP) / 'cap4'
db_path = cap4 / 'battle_dataset' / 'battles.sqlite3'
db_path.parent.mkdir(parents=True, exist_ok=True)
_db = sqlite3.connect(db_path)
_db.executescript(SCHEMA)
_db.commit()
_db.close()
store4 = SessionStore(cap4)
T0 = 1_762_000_000.0
zero = store4.start_session('固定観測', ['ghost'], profile='capture_fixed',
                            now=T0)
for step in range(1, 49):  # sampler cadence: 10s steps up to 480s
    store4.heartbeat(zero['session_id'], False, now=T0 + step * 10)
store4.stop_session(zero['session_id'], end_kind='normal', now=T0 + 488)
rep = build_report(db_path, {'kind': 'session'},
                   session=store4.get_session(zero['session_id']),
                   profile='capture_fixed')
notes = ' '.join(rep.get('data_notes') or [])
check('M4a zero-data session report carries an explicit note',
      rep['summary']['record_count'] == 0 and '接続が確立した時間' in notes)
check('M4b the note names the indistinguishable causes honestly',
      '存在しない' in notes and 'ログイン' in notes)

live = store4.start_session('固定観測', ['alice'], profile='capture_fixed',
                            now=T0)
store4.heartbeat(live['session_id'], True, now=T0 + 60)
store4.stop_session(live['session_id'], end_kind='normal', now=T0 + 120)
rep2 = build_report(db_path, {'kind': 'session'},
                    session=store4.get_session(live['session_id']),
                    profile='capture_fixed')
check('M4c a session that did connect gets no zero-data note',
      '接続が確立した時間' not in ' '.join(rep2.get('data_notes') or []))

# ---------------------------------------------------------------- M5
check('M5a start_ex verify budget fits a cold packaged start',
      inspect.signature(fx.FixedObservationController.start_ex)
      .parameters['verify_timeout'].default >= 10.0)

cap5 = Path(_TMP) / 'cap5'
cap5.mkdir(parents=True, exist_ok=True)
quick = cap5 / 'quick_collector.py'
quick.write_text("import time\ntime.sleep(0.2)\n", encoding='utf-8')
ctrl = fx.FixedObservationController(cap5, script_path=quick)

log_file = cap5 / 'viewer_fixed.log'
with open(log_file, 'wb') as f:
    f.seek(getattr(fx, 'LOG_ROTATE_BYTES', 20 * 1024 * 1024))
    f.write(b'x')
ctrl.start('alice')
for _ in range(100):
    if not ctrl.is_running():
        break
    time.sleep(0.05)
check('M5b an oversized fixed log is rotated at spawn',
      (cap5 / 'viewer_fixed.log.1').exists())
first_handle = ctrl._log_handle
ctrl.start('alice')
check('M5c respawn closes the previous log handle',
      first_handle is not None and first_handle.closed)
ctrl.stop()

# ---------------------------------------------------------------- M6
from core import fixed_lock

cap6 = Path(_TMP) / 'cap6'
cap6.mkdir(parents=True, exist_ok=True)
seen_temps = []
real_replace = os.replace


def recording_replace(src, dst):
    seen_temps.append(str(src))
    return real_replace(src, dst)


os.replace = recording_replace
try:
    fixed_lock.write_status('held', target_id='alice', base=cap6, pid=111)
    fixed_lock.write_status('held', target_id='alice', base=cap6, pid=111)
finally:
    os.replace = real_replace
check('M6 write_status uses a unique temp file per write',
      len(seen_temps) == 2 and seen_temps[0] != seen_temps[1])

# ---------------------------------------------------------------- M7
# LicenseWindow is its own CTk root: exercise it before creating ours.
import customtkinter as ctk

from ui.license_window import LicenseWindow
from core.settings import Settings


def pump_win(win, seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        win.update()
        time.sleep(0.02)


win = LicenseWindow()
pump_win(win)
spath = Path(Settings.get_file_path())
original = spath.read_bytes() if spath.exists() else None
spath.write_bytes(b'{broken json')
raised = False
try:
    win._save_license('KEY-XXXX', '✅ 認証済み')
except OSError:
    raised = True
check('M7a corrupt settings: license save aborts instead of wiping',
      raised and spath.read_bytes() == b'{broken json')
spath.write_text(json.dumps({'license_key': 'OLD',
                             'pro_tiktok_id': 'alice',
                             'workspace_mode': 'developer'}),
                 encoding='utf-8')
win._save_license('NEWKEY', '✅ 認証済み')
merged = json.loads(spath.read_text('utf-8'))
check('M7b license save merges and preserves unrelated keys',
      merged.get('license_key') == 'NEWKEY'
      and merged.get('pro_tiktok_id') == 'alice'
      and merged.get('workspace_mode') == 'developer')
Settings.update({'pro_tiktok_id': 'bob'})
win._save_license('NEWKEY2', '✅ 認証済み')
merged2 = json.loads(spath.read_text('utf-8'))
check('M7c a concurrent update is not lost by the license save',
      merged2.get('pro_tiktok_id') == 'bob'
      and merged2.get('license_key') == 'NEWKEY2')
win.destroy()
if original is not None:
    spath.write_bytes(original)

# ---------------------------------------------------------------- GUI
root = ctk.CTk()
root.withdraw()


def pump(seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


# ---------------------------------------------------------------- M8
from ui.pages.ai import AIPage

workdir = Path(_TMP) / 'cwd'
workdir.mkdir(parents=True, exist_ok=True)
os.chdir(workdir)


def bare_ai_page():
    page = object.__new__(AIPage)
    page.prompt = ctk.CTkTextbox(root, width=200, height=60)
    page.status_label = ctk.CTkLabel(root, text='')
    return page


Settings.update({'ai_prompt': '正規の保存先プロンプト'})
page8 = bare_ai_page()
page8._load_prompt()
check('M8a AI page loads the prompt from the canonical settings',
      '正規の保存先プロンプト' in page8.prompt.get('1.0', 'end'))
page8.prompt.delete('1.0', 'end')
page8.prompt.insert('1.0', 'AI画面から保存したプロンプト')
page8.save_prompt()
check('M8b AI page saves the prompt to the canonical settings',
      Settings.load_strict().get('ai_prompt')
      == 'AI画面から保存したプロンプト')
check('M8c no CWD-relative settings.json is written',
      not (workdir / 'settings.json').exists())
Settings.update({}, remove=('ai_prompt',))
(workdir / 'settings.json').write_text(
    json.dumps({'ai_prompt': '旧ファイルのプロンプト'}), encoding='utf-8')
page8b = bare_ai_page()
page8b._load_prompt()
check('M8d a legacy CWD prompt is still shown when canonical is empty',
      '旧ファイルのプロンプト' in page8b.prompt.get('1.0', 'end'))
page8.prompt.destroy()
page8.status_label.destroy()
page8b.prompt.destroy()
page8b.status_label.destroy()

# ---------------------------------------------------------------- M9
import ui.pages.unattended_report as page_module

page_module.messagebox.showerror = lambda *a, **k: None
page_module.messagebox.showwarning = lambda *a, **k: None
page_module.messagebox.showinfo = lambda *a, **k: None

page = page_module.UnattendedReportPage(root)
page.pack(fill='both', expand=True)
pump()
ROOT = str(Path(__file__).resolve().parent.parent)
dummy = Path(_TMP) / 'dummy_collector.py'
dummy.write_text(
    "import os, sys, time\n"
    f"sys.path.insert(0, r'{ROOT}')\n"
    "from core import fixed_lock\n"
    "target = fixed_lock.target_id_from_url("
    "os.environ.get('LIVEMETRY_FIXED_URL', ''))\n"
    "lock = fixed_lock.ProfileLock()\n"
    "if not lock.acquire():\n"
    "    fixed_lock.write_status('conflict', target_id=target)\n"
    "    sys.exit(3)\n"
    "fixed_lock.write_status('held', target_id=target)\n"
    "time.sleep(120)\n", encoding='utf-8')
controller = fx.get_fixed_controller(page._source['capture_dir'])
controller._script = dummy

page.account_entry.delete(0, 'end')
page.account_entry.insert(0, 'alice')
page.start_session()
pump(0.6)
sessions = page._runtime.store.list_sessions(limit=3)
check('M9a session started for the page checks',
      len(sessions) == 1 and sessions[0]['end_kind'] == 'running')

real_status = controller.status
controller.status = lambda: {
    'running': True, 'state': 'not_found',
    'label': '対象ユーザーが見つかりません（IDをご確認ください）',
    'target_id': 'alice', 'external_target': ''}
alert = page._fixed_collection_alert(sessions[0])
check('M9b not_found surfaces as a collection alert',
      '見つかりません' in alert)
controller.status = real_status

running = page._runtime.store.get_session(sessions[0]['session_id'])
note = page._no_connection_note(running, now=time.time() + 400)
check('M9c zero-connection note appears after 5 minutes',
      '接続が確立した時間' in note)
note0 = page._no_connection_note(running, now=time.time())
check('M9d no zero-connection note before the grace period', note0 == '')

real_runtime_stop = page._runtime.stop_session


def failing_stop(session_id, end_kind='normal'):
    raise RuntimeError('database is locked (synthetic)')


page._runtime.stop_session = failing_stop
try:
    page.stop_session()
    contained = True
except Exception:
    contained = False
check('M9e a runtime stop failure is contained and reported',
      contained and '失敗' in page.status.cget('text'))
still = page._runtime.store.get_session(sessions[0]['session_id'])
check('M9f the session stays running after a failed stop',
      still['end_kind'] == 'running')
page._runtime.stop_session = real_runtime_stop
page.stop_session()
pump(0.4)
done = page._runtime.store.get_session(sessions[0]['session_id'])
check('M9g retrying the stop succeeds', done['end_kind'] == 'normal')

print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
