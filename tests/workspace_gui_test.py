"""GUI regression tests for the workspace settings callback (Phase 3 fix).

Verifies that flipping 「開発機能を表示」 in the Settings page updates
the sidebar IMMEDIATELY through the callback — not via the one-shot
500ms refresh timer and not via any polling:

- enabling adds 「開発者」 to the sidebar selector at once;
- disabling while in developer mode returns to the streamer
  workspace at once;
- a SettingsPage without a callback still saves safely.

Needs a display (on Windows this is the normal desktop; in the
sandbox it runs under Xvfb). Existing non-GUI tests are unaffected.
"""
import os
import sys
import tempfile
import time
import types
from pathlib import Path

os.environ['LOCALAPPDATA'] = tempfile.mkdtemp(prefix='pulse_workspace_gui_')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pyaudiowpatch  # noqa: F401  (Windows audio dependency)
except ImportError:
    sys.modules['pyaudiowpatch'] = types.ModuleType('pyaudiowpatch')

from core.workspace_config import MODE_DEVELOPER, MODE_STREAMER, nav_items
from core.workspace_manager import WorkspaceManager
from ui.main_window import MainWindow
from ui.pages.settings import SettingsPage

passed = failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f'PASS {name}')
    else:
        failed += 1
        print(f'FAIL {name}')


def pump(win, seconds=0.4):
    end = time.time() + seconds
    while time.time() < end:
        win.update()
        time.sleep(0.02)


win = MainWindow()
win.withdraw()
pump(win)

check('G1 initial mode is streamer with only ライバー selectable',
      win.workspace_mode == MODE_STREAMER
      and list(win.workspace_menu.cget('values')) == ['ライバー'])

# --- enabling reflects immediately -------------------------------------
win.show_settings()
pump(win)
page = win.current_page
check('G2 settings page received the callback',
      isinstance(page, SettingsPage)
      and page._on_developer_toggle_callback is not None)
page.developer_var.set(True)
page._on_developer_toggle()
pump(win)  # processes the deferred sync; no timer wait, no reopening
check('G3 enabling adds 開発者 to the selector immediately',
      '開発者' in list(win.workspace_menu.cget('values')))
check('G4 the settings page itself stays open after enabling',
      win.current_page is page)

# --- disabling in developer mode returns immediately ---------------------
check('G5 developer mode is selectable now',
      win.set_workspace_mode(MODE_DEVELOPER) is True)
pump(win)
win.show_settings()
pump(win)
page = win.current_page
page.developer_var.set(False)
page._on_developer_toggle()
pump(win)
check('G6 disabling in developer mode returns to streamer immediately',
      win.workspace_mode == MODE_STREAMER)
check('G7 selector is back to ライバー only',
      list(win.workspace_menu.cget('values')) == ['ライバー'])
streamer_keys = [key for key, _l, _t in nav_items(MODE_STREAMER)]
check('G8 navigation is back to the streamer items',
      all(key in win.nav_buttons for key in streamer_keys)
      and 'collection_history' not in win.nav_buttons)

# --- a callback-less settings page still saves safely ---------------------
import customtkinter as ctk

frame = ctk.CTkFrame(win)
plain_page = SettingsPage(frame)
plain_page.developer_var.set(True)
plain_page._on_developer_toggle()
check('G9 callback-less page saves the setting without error',
      WorkspaceManager().developer_enabled() is True)
plain_page.developer_var.set(False)
plain_page._on_developer_toggle()
check('G10 callback-less page can disable again',
      WorkspaceManager().developer_enabled() is False)
plain_page.destroy()
frame.destroy()

win.on_close()
print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
