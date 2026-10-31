"""Safety tests for fixed observation (Phase 4).

Cross-process profile exclusion, target-ID identity between the
collector and the session, safe start/stop outcomes, and strict
report scoping. The real collector cannot run here (WebView2), so a
dummy collector reproduces its exact lock behaviour through
core.fixed_lock — the same module the real collector uses. Windows
msvcrt locking itself can only be verified on Windows.
"""
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_fixed_safety_')
os.environ['LOCALAPPDATA'] = _TMP  # must precede core imports (BASE)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import fixed_lock
from core.fixed_observation import (FixedObservationController,
                                    get_pro_tiktok_id, set_pro_tiktok_id)
from core.observation_profile import BASE
from core.unattended_report import build_report

CAPTURE_FIXED = BASE / 'capture_fixed'
CAPTURE_FIXED.mkdir(parents=True, exist_ok=True)

passed = failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f'PASS {name}')
    else:
        failed += 1
        print(f'FAIL {name}')


def wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


# A dummy collector with the real collector's lock behaviour.
DUMMY = Path(_TMP) / 'dummy_locking_collector.py'
DUMMY.write_text(
    "import os, sys, time, atexit\n"
    "sys.path.insert(0, r'" + str(Path(__file__).resolve().parent.parent) + "')\n"
    "from core import fixed_lock\n"
    "target = fixed_lock.target_id_from_url(os.environ.get('LIVEMETRY_FIXED_URL', ''))\n"
    "lock = fixed_lock.ProfileLock()\n"
    "if not lock.acquire():\n"
    "    fixed_lock.write_status('conflict', target_id=target)\n"
    "    sys.exit(3)\n"
    "fixed_lock.write_status('held', target_id=target)\n"
    "atexit.register(lock.release)\n"
    "print('READY', flush=True)\n"
    "time.sleep(120)\n", encoding='utf-8')

# A helper that simply holds the profile lock (another process).
HOLDER = Path(_TMP) / 'lock_holder.py'
HOLDER.write_text(
    "import sys, time\n"
    "sys.path.insert(0, r'" + str(Path(__file__).resolve().parent.parent) + "')\n"
    "from core import fixed_lock\n"
    "lock = fixed_lock.ProfileLock()\n"
    "assert lock.acquire()\n"
    "print('HELD', flush=True)\n"
    "time.sleep(120)\n", encoding='utf-8')

# A dummy collector that never takes the lock (broken build).
NO_LOCK = Path(_TMP) / 'dummy_no_lock_collector.py'
NO_LOCK.write_text("import time\ntime.sleep(120)\n", encoding='utf-8')

# --- lock primitives ------------------------------------------------------
lock = fixed_lock.ProfileLock()
check('K1 lock acquires and releases', lock.acquire() and lock.held
      and (lock.release() or not lock.held))
check('K2 profile is free after release', fixed_lock.probe_locked() is False)
fixed_lock.write_status('held', target_id='someone')
status = fixed_lock.read_status()
check('K3 status roundtrip carries the target',
      status['state'] == 'held' and status['target_id'] == 'someone')
check('K4 target is parsed from the LIVE URL',
      fixed_lock.target_id_from_url('https://www.tiktok.com/@abc.def/live') == 'abc.def')

holder = subprocess.Popen([sys.executable, str(HOLDER)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
holder.stdout.readline()
check('K5 another process holding the lock is detected',
      fixed_lock.probe_locked() is True)
check('K6 a second acquire is refused while held',
      fixed_lock.ProfileLock().acquire() is False)
holder.kill()  # force-kill: no cleanup runs in the holder
holder.wait(timeout=5)
check('K7 force-killed holder frees the profile (no permanent block)',
      wait_for(lambda: fixed_lock.probe_locked() is False))

# --- controller outcomes ----------------------------------------------------
controller = FixedObservationController(capture_dir=CAPTURE_FIXED, script_path=DUMMY)
result = controller.start_ex('alice')
check('K8 start_ex succeeds with lock verification',
      result['outcome'] == 'started' and result['target_id'] == 'alice')
check('K9 the child holds the profile while running',
      fixed_lock.probe_locked() is True)
check('K10 same ID is reused, never duplicated',
      controller.start_ex('alice')['outcome'] == 'already_same')
other = controller.start_ex('bob')
check('K11 a different ID is refused with the running target reported',
      other['outcome'] == 'already_other' and other['target_id'] == 'alice')
set_pro_tiktok_id('bob')
check('K12 changing the registered ID mid-run does not change the target',
      controller.target_id == 'alice' and get_pro_tiktok_id() == 'bob'
      and controller.status()['target_id'] == 'alice')
check('K13 stop succeeds and frees the profile',
      controller.stop() is True and not controller.is_running()
      and wait_for(lambda: fixed_lock.probe_locked() is False))
check('K14 double stop is a safe no-op', controller.stop() is True)

# External collector (e.g. launched by top_viewer.py) blocks our start.
env = dict(os.environ, LIVEMETRY_OBSERVATION_MODE='fixed',
           LIVEMETRY_FIXED_URL='https://www.tiktok.com/@carol/live')
external = subprocess.Popen([sys.executable, str(DUMMY)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
try:
    check('K15 external collector takes the profile',
          wait_for(lambda: fixed_lock.probe_locked() is True))
    result = controller.start_ex('alice')
    check('K16 conflict is reported with the external target, no spawn',
          result['outcome'] == 'conflict' and result['target_id'] == 'carol'
          and not controller.is_running())
    state = controller.status()
    check('K17 status surfaces the external observation as a conflict',
          state['state'] == 'conflict' and state.get('external_target') == 'carol')
finally:
    external.terminate()
    external.wait(timeout=5)
check('K18 we never stopped the external process ourselves',
      fixed_lock.probe_locked() is False)

# Broken collector (never locks): start_ex must fail and roll back.
broken = FixedObservationController(capture_dir=CAPTURE_FIXED, script_path=NO_LOCK)
result = broken.start_ex('alice', verify_timeout=0.8)
check('K19 unverifiable start is an error and the child is rolled back',
      result['outcome'] == 'error' and not broken.is_running())

missing = FixedObservationController(capture_dir=CAPTURE_FIXED,
                                     script_path=Path(_TMP) / 'does_not_exist.py')
result = missing.start_ex('alice')
check('K20 spawn failure is an error outcome, not an exception',
      result['outcome'] == 'error')

# --- report scoping: another streamer's records never enter -----------------
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
T0 = 1_762_000_000.0
db_path = CAPTURE_FIXED / 'battle_dataset' / 'battles.sqlite3'
db_path.parent.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(db_path)
db.executescript(SCHEMA)


def payload(uid, score):
    entry = {"anchor_id": "1", "score": score, "score_known": True,
             "nickname": uid, "unique_id": uid}
    return {"mode": "individual", "host_user_id": "1", "host_nickname": uid,
            "participants": [entry], "active": False,
            "start_time_ms": int((T0 + 10) * 1000)}


for uid, bid, score in (('alice', 101, 500), ('bob', 202, 9999)):
    db.execute("INSERT INTO battles VALUES (?,?,?,?,?,?)",
               (uid, bid, T0 + 10, T0 + 300, 'finished', json.dumps(payload(uid, score))))
db.commit()
db.close()

session = {'session_id': 's1', 'mode': '固定観測', 'targets': ['alice'],
           'profile': 'capture_fixed', 'started_at': T0, 'ended_at': T0 + 3600,
           'last_heartbeat_at': T0 + 3600, 'events': [], 'end_kind': 'normal',
           'monitored_seconds': 3600, 'disconnected_seconds': 0,
           'gap_seconds': 0, 'last_data_at': T0 + 300,
           'report_state': 'none', 'elapsed_seconds': 3600}
report = build_report(db_path, {'kind': 'session'}, session=session,
                      profile='capture_fixed', now=T0 + 3600)
hosts = {battle['unique_id'] for battle in report['battles']}
streamer_ids = {s['unique_id'] for s in report['per_streamer']}
check('K21 session report contains only the bound streamer',
      hosts == {'alice'} and streamer_ids == {'alice'})
check('K22 the other streamer\'s score never enters the summary',
      report['summary']['final_score_max'] == 500)

# --- launcher-shim robustness ------------------------------------------------
# Under a launcher-shim python (e.g. the Python Install Manager),
# Popen.pid is the shim's pid and NEVER equals the interpreter's
# os.getpid() written into the lock status. Start verification must
# corroborate (fresh held status for the target + OS lock held)
# instead of comparing pids; and a STALE held status must never
# substitute for a live lock holder.
DUMMY_SHIFTED = Path(_TMP) / 'dummy_shifted_pid_collector.py'
DUMMY_SHIFTED.write_text(
    "import os, sys, time, atexit\n"
    "sys.path.insert(0, r'" + str(Path(__file__).resolve().parent.parent) + "')\n"
    "from core import fixed_lock\n"
    "target = fixed_lock.target_id_from_url(os.environ.get('LIVEMETRY_FIXED_URL', ''))\n"
    "lock = fixed_lock.ProfileLock()\n"
    "if not lock.acquire():\n"
    "    sys.exit(3)\n"
    "fixed_lock.write_status('held', target_id=target, pid=os.getpid() + 100000)\n"
    "atexit.register(lock.release)\n"
    "print('READY', flush=True)\n"
    "time.sleep(120)\n", encoding='utf-8')

shifted = FixedObservationController(capture_dir=CAPTURE_FIXED,
                                     script_path=DUMMY_SHIFTED)
result = shifted.start_ex('alice', verify_timeout=5.0)
check('K23 start verifies despite a shim-shifted status pid',
      result['outcome'] == 'started' and shifted.is_running()
      and fixed_lock.probe_locked() is True)
check('K23b shifted-pid controller stops cleanly',
      shifted.stop() is True
      and wait_for(lambda: fixed_lock.probe_locked() is False))

fixed_lock.status_path().write_text(json.dumps(
    {'state': 'held', 'pid': 424242, 'target_id': 'alice',
     'updated_at': time.time() - 3600}), encoding='utf-8')
stale = FixedObservationController(capture_dir=CAPTURE_FIXED,
                                   script_path=NO_LOCK)
result = stale.start_ex('alice', verify_timeout=0.8)
check('K24 a stale held status never verifies a non-locking child',
      result['outcome'] == 'error' and not stale.is_running())

print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
