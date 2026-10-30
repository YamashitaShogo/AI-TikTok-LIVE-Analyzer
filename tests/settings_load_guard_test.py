"""Regression tests for the load-failure overwrite guard (PR #12).

Review findings addressed:
1. The report page caught only ValueError from set_pro_tiktok_id();
   the new SettingsSaveError (and SettingsLoadError) escaped as
   unhandled exceptions. Both are now shown as Japanese settings
   errors, and on failure neither the collector nor a session starts.
   An unchanged registered ID no longer rewrites settings.json.
2. Settings.load() returned {} for ANY failure, so a temporarily
   unreadable or corrupt settings.json could be overwritten with
   defaults/empty content (losing the license key, registered ID,
   workspace settings). Now: missing file (first run) is distinct
   from existing-but-unreadable; strict reads raise
   SettingsLoadError; save() refuses to overwrite an unreadable
   file; read-modify-write goes through Settings.update() (strict,
   locked merge) so concurrent writers cannot lose keys.

Core parts are plain tests; GUI parts need a display.
"""
import json
import os
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_settings_guard_')
os.environ['LOCALAPPDATA'] = _TMP  # must precede core imports (BASE)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pyaudiowpatch  # noqa: F401
except ImportError:
    sys.modules['pyaudiowpatch'] = types.ModuleType('pyaudiowpatch')

from core.settings import (Settings, SettingsLoadError, SettingsSaveError)

passed = failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f'PASS {name}')
    else:
        failed += 1
        print(f'FAIL {name}')


path = Path(Settings.get_file_path())

# --- missing vs unreadable -----------------------------------------------------
check('T1 a missing file is a first run, not an error',
      Settings.file_state() == 'missing' and Settings.load_strict() == {})
Settings.save({'license_key': 'KEY-1', 'workspace_mode': 'streamer'})
check('T2 first-run save works', Settings.load_strict()['license_key'] == 'KEY-1')

path.write_text('{ this is not json', encoding='utf-8')
corrupt_bytes = path.read_bytes()
check('T3 a corrupt file is reported unreadable, not missing',
      Settings.file_state() == 'unreadable')
try:
    Settings.load_strict()
    check('T4 strict load raises on a corrupt file', False)
except SettingsLoadError:
    check('T4 strict load raises on a corrupt file', True)
try:
    Settings.save({'license_key': 'WIPED'})
    check('T5 save refuses to overwrite an unreadable file', False)
except SettingsSaveError:
    check('T5 save refuses to overwrite an unreadable file', True)
check('T6 the corrupt file is left byte-identical (nothing wiped)',
      path.read_bytes() == corrupt_bytes)
try:
    Settings.update({'pro_tiktok_id': 'alice'})
    check('T7 update aborts on an unreadable file', False)
except SettingsLoadError:
    check('T7 update aborts on an unreadable file', True)
check('T8 lenient load stays available for display purposes',
      Settings.load() == {})

# --- strict merge: no lost keys --------------------------------------------------
path.write_text(json.dumps({'license_key': 'KEY-1',
                            'workspace_mode': 'streamer'}), encoding='utf-8')
Settings.update({'pro_tiktok_id': 'alice'})
merged = Settings.load_strict()
check('T9 update preserves unrelated keys',
      merged['license_key'] == 'KEY-1'
      and merged['workspace_mode'] == 'streamer'
      and merged['pro_tiktok_id'] == 'alice')
before = path.read_bytes()
written = Settings.update({'pro_tiktok_id': 'alice'})
check('T10 an unchanged update does not rewrite the file',
      written is False and path.read_bytes() == before)

stale = Settings.load()  # a writer holding an old snapshot...
Settings.update({'workspace_mode': 'developer'})
Settings.update({'license_status': 'ok'})
final = Settings.load_strict()
check('T11 sequential updates from stale snapshots lose nothing',
      final['workspace_mode'] == 'developer'
      and final['license_status'] == 'ok'
      and final['pro_tiktok_id'] == 'alice')

errors = []


def worker(i):
    try:
        Settings.update({f'key_{i}': i})
    except Exception as exc:  # noqa: BLE001
        errors.append(exc)


threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
for t in threads:
    t.start()
for t in threads:
    t.join()
final = Settings.load_strict()
check('T12 concurrent in-process updates lose no keys',
      not errors and all(final.get(f'key_{i}') == i for i in range(10)))

# --- set_pro_tiktok_id ------------------------------------------------------------
from core import fixed_observation as fx

path.write_text(json.dumps({'license_key': 'KEY-1'}), encoding='utf-8')
fx.set_pro_tiktok_id('@alice')
once = path.read_bytes()
fx.set_pro_tiktok_id('alice')
check('T13 re-saving the same ID does not rewrite settings.json',
      path.read_bytes() == once
      and Settings.load_strict()['pro_tiktok_id'] == 'alice')

path.write_text('not json at all', encoding='utf-8')
try:
    fx.set_pro_tiktok_id('bob')
    check('T14 set_pro_tiktok_id aborts on an unreadable file', False)
except SettingsLoadError:
    check('T14 set_pro_tiktok_id aborts on an unreadable file', True)
check('T15 the unreadable file survives the aborted ID save',
      path.read_text(encoding='utf-8') == 'not json at all')
path.write_text(json.dumps({'license_key': 'KEY-1'}), encoding='utf-8')

# --- GUI: report page surfaces save errors and starts nothing ----------------------
import customtkinter as ctk

from core.observation_profile import BASE
from ui.pages import unattended_report as report_module

dialogs = []
report_module.messagebox.showerror = (
    lambda title, message, **k: dialogs.append((title, message)))
report_module.messagebox.showwarning = lambda *a, **k: None
report_module.messagebox.showinfo = lambda *a, **k: None

root = ctk.CTk()
root.withdraw()
page = report_module.UnattendedReportPage(root)
page.pack(fill='both', expand=True)


def pump(seconds=0.5):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


pump()

real_save = Settings.save


def broken_save(data):
    raise SettingsSaveError('simulated save failure')


Settings.save = staticmethod(broken_save)
dialogs.clear()
page.account_entry.delete(0, 'end')
page.account_entry.insert(0, 'alice')
page.save_account_id()
check('T16 the ID save error is shown in Japanese, not raised',
      bool(dialogs) and dialogs[-1][0] == '設定保存エラー')

dialogs.clear()
page.start_session()
pump()
check('T17 on save failure a start error dialog is shown',
      bool(dialogs) and dialogs[-1][0] == '設定保存エラー')
check('T18 on save failure no session is created',
      page._runtime.store.list_sessions(limit=5) == [])
controller = fx.get_fixed_controller(BASE / 'capture_fixed')
check('T19 on save failure the collector is not started',
      controller.is_running() is False)
Settings.save = real_save
page.destroy()

# --- GUI: settings page aborts a full save over an unreadable file ------------------
from ui.pages import settings as settings_page_module

sp_dialogs = []
settings_page_module.messagebox.showerror = (
    lambda title, message, **k: sp_dialogs.append((title, message)))
settings_page_module.messagebox.showwarning = lambda *a, **k: None
settings_page_module.messagebox.showinfo = lambda *a, **k: None
settings_page_module.messagebox.askyesno = lambda *a, **k: False

spage = settings_page_module.SettingsPage(root)
spage.pack(fill='both', expand=True)
root.update()
path.write_text('corrupted!!', encoding='utf-8')
guard_bytes = path.read_bytes()
sp_dialogs.clear()
spage.save_settings()
check('T20 the full settings save aborts over an unreadable file',
      bool(sp_dialogs) and sp_dialogs[-1][0] == '保存中止')
check('T21 the unreadable file is not overwritten with defaults',
      path.read_bytes() == guard_bytes)
spage.destroy()
root.destroy()
print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
