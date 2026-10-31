"""Regression tests for the settings-save safety fix (PR #12).

Background (Windows field report): Settings.save() failed at
os.replace() with WinError 5 even though the file and folder were
fully writable and no Pulse process was running at investigation
time; the occupancy at the moment of failure was never identified.
The fix therefore targets transient sharing conflicts generally:

1. os.replace is retried with backoff for transient errors
   (PermissionError / WinError 5 / 32) in core.settings, and the
   Settings page's own write paths use the same helper.
2. When saving still fails, the existing settings.json is left
   byte-identical and a SettingsSaveError is raised.
3. The Settings page surfaces the failure (dialog + status), and
   immediate-apply switches revert to the actually-saved state
   instead of showing an unsaved one.
4. A session that is 'running' while its fixed collector is stopped
   is NOT presented as healthy observation (badge, status line and
   observing-ID label all say so).

Parts 1–3a are plain tests; the GUI parts need a display.
"""
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_settings_save_')
os.environ['LOCALAPPDATA'] = _TMP  # must precede core imports (BASE)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pyaudiowpatch  # noqa: F401
except ImportError:
    sys.modules['pyaudiowpatch'] = types.ModuleType('pyaudiowpatch')

import core.settings as settings_module
from core.settings import Settings, SettingsSaveError, replace_with_retry

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


real_replace = os.replace

# --- 1: transient failures are retried ---------------------------------------
Settings.save({'theme': 'dark', 'n': 1})
attempts = {'count': 0}


def flaky_replace(src, dst):
    attempts['count'] += 1
    if attempts['count'] <= 2:
        raise PermissionError(5, 'Access is denied (simulated transient)')
    return real_replace(src, dst)


os.replace = flaky_replace
try:
    saved = Settings.save({'theme': 'light', 'n': 2})
finally:
    os.replace = real_replace
check('S1 save succeeds after transient replace failures',
      saved is True and attempts['count'] == 3)
check('S2 the new settings were actually written',
      Settings.load() == {'theme': 'light', 'n': 2})

# --- 2: persistent failure protects the existing file -------------------------
before = Path(Settings.get_file_path()).read_bytes()
attempts['count'] = 0


def always_denied(src, dst):
    attempts['count'] += 1
    raise PermissionError(5, 'Access is denied (simulated persistent)')


os.replace = always_denied
error = None
try:
    Settings.save({'theme': 'broken'})
except SettingsSaveError as exc:
    error = exc
finally:
    os.replace = real_replace
check('S3 persistent failure raises SettingsSaveError', error is not None)
check('S4 retries actually happened before giving up', attempts['count'] > 3)
check('S5 the existing settings file is byte-identical',
      Path(Settings.get_file_path()).read_bytes() == before)
check('S6 no temporary files are left behind',
      not list(Path(Settings.get_settings_dir()).glob('settings_*.tmp')))

# --- 3: non-transient errors are not retried ----------------------------------
attempts['count'] = 0


def missing(src, dst):
    attempts['count'] += 1
    raise FileNotFoundError('simulated non-transient')


os.replace = missing
raised = None
try:
    replace_with_retry('a', 'b')
except FileNotFoundError as exc:
    raised = exc
finally:
    os.replace = real_replace
check('S7 non-transient errors raise immediately',
      raised is not None and attempts['count'] == 1)

# --- 3b: Settings page failure handling (GUI) ----------------------------------
import customtkinter as ctk

from ui.pages import settings as settings_page_module

dialogs = []
settings_page_module.messagebox.showerror = (
    lambda title, message, **k: dialogs.append((title, message)))
settings_page_module.messagebox.showwarning = lambda *a, **k: None
settings_page_module.messagebox.showinfo = lambda *a, **k: None

root = ctk.CTk()
root.withdraw()
page = settings_page_module.SettingsPage(root)
page.pack(fill='both', expand=True)
root.update()

real_save = settings_page_module.AppSettings.save


def broken_save(data):
    raise SettingsSaveError('simulated save failure')


settings_page_module.AppSettings.save = staticmethod(broken_save)
page.viewer_autostart_var.set(True)
page._on_viewer_autostart_toggle()
check('S8 autostart switch reverts when the save fails',
      page.viewer_autostart_var.get() is False)
check('S9 the failure is shown to the user',
      bool(dialogs) and '変更されていません' in dialogs[-1][1])
check('S10 the status line reports the failure',
      '保存できませんでした' in page.status_label.cget('text'))
settings_page_module.AppSettings.save = real_save


class BrokenManager:
    def set_developer_enabled(self, enabled):
        raise SettingsSaveError('simulated save failure')


real_manager = settings_page_module.WorkspaceManager
settings_page_module.WorkspaceManager = BrokenManager
callback_calls = []
page._on_developer_toggle_callback = lambda enabled: callback_calls.append(enabled)
dialogs.clear()
page.developer_var.set(True)
page._on_developer_toggle()
check('S11 developer switch reverts when the save fails',
      page.developer_var.get() is False)
check('S12 the sidebar callback is NOT invoked for an unsaved setting',
      callback_calls == [] and bool(dialogs))
settings_page_module.WorkspaceManager = real_manager
page.destroy()

# --- 4: running session + stopped collector is not "observing" ------------------
from core import fixed_observation as fx
from core.observation_profile import BASE
from ui.pages import unattended_report as report_module

report_module.messagebox.showerror = lambda *a, **k: None
report_module.messagebox.showwarning = lambda *a, **k: None
report_module.messagebox.showinfo = lambda *a, **k: None

ROOT = str(Path(__file__).resolve().parent.parent)
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

page2 = report_module.UnattendedReportPage(root)
page2.pack(fill='both', expand=True)


def pump(seconds=0.5):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


pump()
page2.account_entry.delete(0, 'end')
page2.account_entry.insert(0, 'alice')
page2.start_session()
pump()
check('S13 while the collector runs, the badge says 観測中',
      '観測中' in page2.badge.cget('text'))

controller.stop()  # the collector dies while the session stays open
page2.refresh()
pump(1.0)
check('S14 with the collector stopped, the badge no longer says 観測中',
      'コレクタ停止' in page2.badge.cget('text'))
check('S15 the status line warns that nothing is being collected',
      '収集されていません' in page2.status.cget('text'))
check('S16 the observing-ID label says collection is stopped',
      '収集していません' in page2.observing_label.cget('text'))

if page2._active_session_id is not None:
    page2._runtime.stop_session(page2._active_session_id, end_kind='abnormal')
page2.destroy()
root.destroy()
print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
