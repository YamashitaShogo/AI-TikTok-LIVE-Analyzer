"""Regression tests for the Phase 4 final safety review (PR #12).

1. The fixed collector's lock gate is fail-closed
   (core.fixed_lock.acquire_profile_lock_or_exit): contention exits
   3, initialization/verification failure exits 4, and the collector
   never collects unguarded. A source pin keeps
   core/viewer_collector.py routed through that gate.
2. A competing process that failed to acquire cannot overwrite the
   owner's status information; its conflict note goes to a separate
   file. Exclusion itself never depends on these files.
3. Page stop ordering: the collector is confirmed stopped BEFORE
   the session is closed as a normal end and its final JSON is
   generated; when the collector cannot be confirmed stopped, the
   session is NOT ended (it stays running).

Parts 1–2 are plain subprocess tests. Part 3 needs a display
(Windows desktop / Xvfb), like tests/workspace_gui_test.py.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_fixed_review_')
os.environ['LOCALAPPDATA'] = _TMP  # must precede core imports (BASE)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pyaudiowpatch  # noqa: F401
except ImportError:
    sys.modules['pyaudiowpatch'] = types.ModuleType('pyaudiowpatch')

from core import fixed_lock
from core.observation_profile import BASE

passed = failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f'PASS {name}')
    else:
        failed += 1
        print(f'FAIL {name}')


def wait_for(predicate, timeout=6.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


ROOT = str(Path(__file__).resolve().parent.parent)

HOLDER = Path(_TMP) / 'holder.py'
HOLDER.write_text(
    "import sys, time\n"
    f"sys.path.insert(0, r'{ROOT}')\n"
    "from core import fixed_lock\n"
    "lock = fixed_lock.acquire_profile_lock_or_exit('owner')\n"
    "print('HELD', flush=True)\n"
    "time.sleep(120)\n", encoding='utf-8')

CONTENDER = Path(_TMP) / 'contender.py'
CONTENDER.write_text(
    "import sys, json\n"
    f"sys.path.insert(0, r'{ROOT}')\n"
    "from core import fixed_lock\n"
    "lock = fixed_lock.ProfileLock()\n"
    "acquired = lock.acquire()\n"
    "held_write = fixed_lock.write_status('held', target_id='attacker')\n"
    "released_write = fixed_lock.write_status('released', target_id='attacker')\n"
    "conflict_write = fixed_lock.write_status('conflict', target_id='contender')\n"
    "print(json.dumps({'acquired': acquired,\n"
    "                  'held_refused': held_write is None,\n"
    "                  'released_refused': released_write is None,\n"
    "                  'conflict_recorded': conflict_write is not None}))\n",
    encoding='utf-8')

GATE = Path(_TMP) / 'gate.py'
GATE.write_text(
    "import sys\n"
    f"sys.path.insert(0, r'{ROOT}')\n"
    "from core import fixed_lock\n"
    "fixed_lock.acquire_profile_lock_or_exit('gateuser')\n"
    "print('ACQUIRED', flush=True)\n", encoding='utf-8')

# --- 1+2: owner protection and the fail-closed gate -------------------------
holder = subprocess.Popen([sys.executable, str(HOLDER)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
holder.stdout.readline()
owner_status = fixed_lock.read_status()
check('V1 gate holder owns the status with its target',
      owner_status and owner_status['state'] == 'held'
      and owner_status['target_id'] == 'owner'
      and owner_status['pid'] == holder.pid)

out = subprocess.run([sys.executable, str(CONTENDER)], capture_output=True,
                     text=True, timeout=30).stdout.strip()
result = json.loads(out)
check('V2 contender cannot acquire while held', result['acquired'] is False)
check('V3 contender held/released writes are refused',
      result['held_refused'] and result['released_refused'])
check('V4 contender conflict note is recorded separately',
      result['conflict_recorded']
      and (fixed_lock.read_conflict() or {}).get('target_id') == 'contender')
after = fixed_lock.read_status()
check('V5 owner status is NOT clobbered by the contender',
      after and after['target_id'] == 'owner' and after['pid'] == holder.pid)

gate = subprocess.run([sys.executable, str(GATE)], capture_output=True,
                      text=True, timeout=30)
check('V6 gate under contention exits 3 (fail-closed, no collection)',
      gate.returncode == 3)
after_gate = fixed_lock.read_status()
check('V7 owner status still intact after the gate conflict',
      after_gate and after_gate['pid'] == holder.pid)
holder.kill()
holder.wait(timeout=5)
check('V8 profile frees after the holder dies',
      wait_for(lambda: fixed_lock.probe_locked() is False))

# Gate verification failure (acquire raising) exits 4, in-process.
original_acquire = fixed_lock.ProfileLock.acquire


def boom(self):
    raise RuntimeError('simulated lock infra failure')


fixed_lock.ProfileLock.acquire = boom
try:
    fixed_lock.acquire_profile_lock_or_exit('anyone')
    check('V9 gate infra failure exits 4', False)
except SystemExit as exc:
    check('V9 gate infra failure exits 4', exc.code == 4)
finally:
    fixed_lock.ProfileLock.acquire = original_acquire

# Source pin: the real collector routes through the fail-closed gate.
source = (Path(ROOT) / 'core' / 'viewer_collector.py').read_text(encoding='utf-8')
check('V10 collector uses the fail-closed gate with no fall-through',
      'acquire_profile_lock_or_exit' in source
      and 'sys.exit(4)' in source
      and '排他ロックを初期化できませんでした' not in source)

# --- 3: stop ordering on the report page (GUI) -------------------------------
import customtkinter as ctk

from core import fixed_observation as fx
from ui.pages import unattended_report as page_module

page_module.messagebox.showerror = lambda *a, **k: None
page_module.messagebox.showwarning = lambda *a, **k: None
page_module.messagebox.showinfo = lambda *a, **k: None

DUMMY = Path(_TMP) / 'dummy_locking_collector.py'
DUMMY.write_text(
    "import os, sys, time\n"
    f"sys.path.insert(0, r'{ROOT}')\n"
    "from core import fixed_lock\n"
    "target = fixed_lock.target_id_from_url(os.environ.get('LIVEMETRY_FIXED_URL', ''))\n"
    "lock = fixed_lock.ProfileLock()\n"
    "if not lock.acquire():\n"
    "    fixed_lock.write_status('conflict', target_id=target)\n"
    "    sys.exit(3)\n"
    "fixed_lock.write_status('held', target_id=target)\n"
    "time.sleep(120)\n", encoding='utf-8')

capture_fixed = BASE / 'capture_fixed'
controller = fx.get_fixed_controller(capture_fixed)
controller._script = DUMMY

root = ctk.CTk()
root.withdraw()
page = page_module.UnattendedReportPage(root)
page.pack(fill='both', expand=True)


def pump(seconds=0.5):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


pump()
page.account_entry.delete(0, 'end')
page.account_entry.insert(0, 'alice')
page.start_session()
pump()
sessions = page._runtime.store.list_sessions(limit=3)
check('W1 session started for the ordering test',
      len(sessions) == 1 and sessions[0]['end_kind'] == 'running')

order = []
real_controller_stop = controller.stop
real_session_stop = page._runtime.stop_session


def recording_controller_stop():
    order.append('collector')
    return real_controller_stop()


def recording_session_stop(session_id, end_kind='normal'):
    order.append('session')
    return real_session_stop(session_id, end_kind=end_kind)


controller.stop = recording_controller_stop
page._runtime.stop_session = recording_session_stop
page.stop_session()
pump()
check('W2 collector stops BEFORE the session is closed',
      order == ['collector', 'session'])
ended = page._runtime.store.list_sessions(limit=3)[0]
check('W3 session then records a normal end', ended['end_kind'] == 'normal')
reports_dir = capture_fixed / 'observation_report' / 'reports'
check('W4 final JSON is generated after the ordered stop',
      wait_for(lambda: reports_dir.exists()
               and any(reports_dir.glob('report_*.json')), timeout=8)
      and (pump(0.2) or True))

# Stop failure: the session must NOT be ended.
controller.stop = real_controller_stop
page._runtime.stop_session = real_session_stop
page.start_session()
pump()
controller.stop = lambda: False  # collector cannot be confirmed stopped
page.stop_session()
pump()
latest = page._runtime.store.list_sessions(limit=3)[0]
check('W5 failed collector stop leaves the session running (no normal end)',
      latest['end_kind'] == 'running')
check('W6 the page says the stop was not confirmed',
      '停止を確認できなかったため' in page.status.cget('text'))
controller.stop = real_controller_stop
page.stop_session()
pump()
latest = page._runtime.store.list_sessions(limit=3)[0]
check('W7 retrying after recovery ends the session normally',
      latest['end_kind'] == 'normal')

page.destroy()
root.destroy()
print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
