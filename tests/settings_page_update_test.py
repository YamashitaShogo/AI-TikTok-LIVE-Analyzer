"""Regression tests: the Settings page's last two bespoke write
paths (save_settings and _save_license_result) now save through
Settings.update() like every other writer (PR #12 review).

Scenario under test (lost update): the page loads its form values
at open time; afterwards ANOTHER writer (here: a separate thread,
as happens with background license checks / other pages) updates
the registered TikTok ID and the workspace mode. When the user
then presses 保存 on the stale form, those concurrent changes must
survive — only the form's own keys may be written. The legacy
cleanup (removing a plaintext openai_api_key stored by old
versions) must still happen, and a corrupt settings file must
still abort the save. The fixed-name .json.tmp temp file is gone
from these paths.

GUI parts need a display.
"""
import json
import os
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_settings_page_update_')
os.environ['LOCALAPPDATA'] = _TMP  # must precede core imports (BASE)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pyaudiowpatch  # noqa: F401
except ImportError:
    sys.modules['pyaudiowpatch'] = types.ModuleType('pyaudiowpatch')

from core.settings import Settings

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

# --- core: update(remove=...) -----------------------------------------------------
path.write_text(json.dumps({'license_key': 'K', 'openai_api_key': 'LEGACY'}),
                encoding='utf-8')
Settings.update({'theme_x': 1}, remove=('openai_api_key',))
data = Settings.load_strict()
check('U1 update(remove=...) deletes the legacy key and keeps the rest',
      'openai_api_key' not in data and data['license_key'] == 'K'
      and data['theme_x'] == 1)
before = path.read_bytes()
check('U2 a remove of an absent key alone does not rewrite the file',
      Settings.update({}, remove=('openai_api_key',)) is False
      and path.read_bytes() == before)

# --- GUI: stale form vs concurrent writers -----------------------------------------
import customtkinter as ctk

from core import fixed_observation as fx
from ui.pages import settings as settings_page_module

dialogs = []
settings_page_module.messagebox.showerror = (
    lambda title, message, **k: dialogs.append(('error', title, message)))
settings_page_module.messagebox.showwarning = (
    lambda title, message, **k: dialogs.append(('warning', title, message)))
settings_page_module.messagebox.showinfo = (
    lambda title, message, **k: dialogs.append(('info', title, message)))
settings_page_module.messagebox.askyesno = lambda *a, **k: False

path.write_text(json.dumps({
    'license_key': 'OLDKEY',
    'license_status': '未認証',
    'openai_api_key': 'LEGACY-PLAINTEXT',
}), encoding='utf-8')

root = ctk.CTk()
root.withdraw()
page = settings_page_module.SettingsPage(root)
page.pack(fill='both', expand=True)
root.update()

# Another writer updates the registered ID and workspace mode AFTER
# the page loaded its (now stale) form values.
errors = []


def concurrent_writer():
    try:
        fx.set_pro_tiktok_id('alice')
        Settings.update({'workspace_mode': 'developer'})
    except Exception as exc:  # noqa: BLE001
        errors.append(exc)


thread = threading.Thread(target=concurrent_writer)
thread.start()
thread.join()
check('U3 the concurrent writer succeeded', not errors)

# The user edits one form field and saves from the stale form.
page.license_key_entry.delete(0, 'end')
page.license_key_entry.insert(0, 'NEWKEY')
dialogs.clear()
page.save_settings()
root.update()
saved = Settings.load_strict()
check('U4 the form value was saved', saved.get('license_key') == 'NEWKEY')
check('U5 the concurrent TikTok ID update survived the form save',
      saved.get('pro_tiktok_id') == 'alice')
check('U6 the concurrent workspace update survived the form save',
      saved.get('workspace_mode') == 'developer')
check('U7 the legacy plaintext API key was removed by the form save',
      'openai_api_key' not in saved)
check('U8 no fixed-name temp file remains',
      not Path(Settings.get_settings_dir(), 'settings.json.tmp').exists())

# License result path: same lost-update protection.
thread = threading.Thread(
    target=lambda: fx.set_pro_tiktok_id('bob'))
thread.start()
thread.join()
result = page._save_license_result('LK2', '✅ 認証済み')
saved = Settings.load_strict()
check('U9 the license result was saved', result is True
      and saved.get('license_key') == 'LK2')
check('U10 the concurrent ID update survived the license save',
      saved.get('pro_tiktok_id') == 'bob')

# Corrupt file: the unified path still aborts instead of overwriting.
path.write_text('corrupted!!', encoding='utf-8')
guard = path.read_bytes()
dialogs.clear()
page.save_settings()
check('U11 the form save aborts over an unreadable file',
      any(d[1] == '保存中止' for d in dialogs))
check('U12 the unreadable file is untouched', path.read_bytes() == guard)
check('U13 the license save also aborts over an unreadable file',
      page._save_license_result('X', 'Y') is False
      and path.read_bytes() == guard)

page.destroy()
root.destroy()
print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
